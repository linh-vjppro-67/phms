"""M01: hồ sơ phạm nhân tham chiếu, đợt tiếp nhận, chuyển trại/bàn giao (WF-01, WF-07)."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..idempotency import run_idempotent
from ..db import get_db, lock_row
from ..notify import emit, person_name
from ..deps import active_grant, active_stay, current_user, ensure_clinical_access, grant_break_glass, has_facility_link, person_or_404, require
from ..models import (Alert, Appointment, CarePlan, ClinicalOrder, CustodyStay, Encounter, Facility, Handover,
                      HealthRecord, MedicationOrder, Person, Referral, User)
from ..permissions import perms_of
from ..utils import clean_name, fail, name_key, to_dict, utcnow

router = APIRouter()

TRANSFER_CLOSE_REASON = "Chuyển trại – đã bàn giao"


def _valid_dob(v):
    if v is not None and not (date(1900, 1, 1) <= v <= date.today()):
        raise ValueError("Ngày sinh không hợp lệ (phải từ 1900 đến hôm nay)")
    return v


def _valid_name(v):
    if v is None:
        return None
    v = clean_name(v)          # bỏ khoảng trắng TRƯỚC khi kiểm tra độ dài: "   " không phải họ tên
    if len(v) < 2:
        raise ValueError("Họ tên không được để trống (tối thiểu 2 ký tự)")
    return v


def _norm_source(v):
    v = (v or "").strip().upper()   # mã hệ thống nguồn: không phân biệt hoa/thường (qlpn = QLPN)
    return v or None


def _norm_ext(v):
    v = (v or "").strip()
    return v or None


def external_owner(db: Session, source_system: str, external_id: str, exclude_id: str | None = None) -> Person | None:
    """Hồ sơ đang giữ mã nguồn này – so khớp không phân biệt hoa/thường, khoảng trắng hai đầu."""
    q = select(Person).where(func.upper(func.trim(Person.source_system)) == source_system.strip().upper(),
                             func.upper(func.trim(Person.external_id)) == external_id.strip().upper())
    if exclude_id:
        q = q.where(Person.id != exclude_id)
    return db.scalars(q.limit(1)).first()


def duplicate_candidates(db: Session, full_name: str, dob: date | None, exclude_id: str | None = None) -> list[Person]:
    """Nghi trùng (BR-01) = cùng khóa họ tên (không phân biệt hoa/thường, dạng Unicode, khoảng trắng, dấu) VÀ
    cùng ngày sinh – hoặc một trong hai bên THIẾU ngày sinh (không đủ căn cứ để coi là hai người khác nhau).
    Chỉ cảnh báo (409, xác nhận bằng confirm_distinct), không bao giờ tự gộp."""
    q = select(Person).where(Person.name_key == name_key(full_name), Person.status != "merged")
    if dob:
        q = q.where(or_(Person.date_of_birth == dob, Person.date_of_birth.is_(None)))
    if exclude_id:
        q = q.where(Person.id != exclude_id)
    return list(db.scalars(q.order_by(Person.created_at).limit(10)))


def _candidates_out(cands: list[Person]) -> list[dict]:
    return [{"id": c.id, "full_name": c.full_name, "date_of_birth": str(c.date_of_birth) if c.date_of_birth else None,
             "source_system": c.source_system, "external_id": c.external_id, "status": c.status} for c in cands]


class PersonIn(BaseModel):
    full_name: str = Field(max_length=200)
    date_of_birth: date | None = None
    gender: str | None = None
    source_system: str | None = Field(default=None, max_length=64)
    external_id: str | None = Field(default=None, max_length=64)
    confirm_distinct: bool = False     # xác nhận "đây là người khác" khi API báo nghi trùng (tên + ngày sinh)
    _dob = field_validator("date_of_birth")(_valid_dob)
    _name = field_validator("full_name")(_valid_name)
    _src = field_validator("source_system")(_norm_source)
    _ext = field_validator("external_id")(_norm_ext)


@router.post("/persons", status_code=201, tags=["identity"])
def create_person(body: PersonIn, request: Request, user: User = Depends(require("person.write")),
                  db: Session = Depends(get_db)):
    def work():
        # BR-01: mã nguồn ngoài chỉ định danh khi đi kèm source_system; trùng -> không tạo mới
        if bool(body.external_id) != bool(body.source_system):
            fail(422, "IDENTITY_INCOMPLETE", "external_id và source_system phải đi cùng nhau")
        if body.external_id:
            ex = external_owner(db, body.source_system, body.external_id)
            if ex:
                fail(409, "PERSON_EXISTS", "Đã tồn tại hồ sơ cùng mã nguồn", existing_person_id=ex.id)
        cands = duplicate_candidates(db, body.full_name, body.date_of_birth)
        if cands and not body.confirm_distinct:
            # Không tự tạo trùng và cũng không tự gộp: buộc người dùng xem ứng viên rồi xác nhận rõ ràng
            fail(409, "DUPLICATE_SUSPECTED", "Đã có hồ sơ cùng họ tên và ngày sinh (hoặc thiếu ngày sinh để phân biệt) – kiểm tra trước khi tạo mới",
                 candidates=_candidates_out(cands))
        cand_ids = [c.id for c in cands]
        p = Person(full_name=body.full_name, date_of_birth=body.date_of_birth, gender=body.gender,
                   source_system=body.source_system, external_id=body.external_id, created_by=user.id,
                   # không tự gộp khi thông tin chưa đủ / nghi trùng -> chờ đối soát
                   status="verified" if (body.external_id and not cand_ids) else "pending_verification",
                   duplicate_candidates=cand_ids or None)
        db.add(p)
        audit(db, user, "person_created", "Person", p.id, person_id=p.id, request=request,
              reason=("xác nhận khác người với " + ",".join(cand_ids[:5])) if cand_ids else None)
        return 201, to_dict(p)
    return run_idempotent(db, request, user, body.model_dump(mode="json"), work)


@router.get("/persons", tags=["identity"])
def search_persons(q: str | None = None, external_id: str | None = None, status: str | None = None,
                   limit: int = 50, request: Request = None, user: User = Depends(require("person.read")),
                   db: Session = Depends(get_db)):
    stmt = select(Person).where(Person.status != "merged").order_by(Person.full_name).limit(max(1, min(limit, 200)))
    if q and name_key(q):   # tìm theo khóa họ tên: không phân biệt hoa/thường, dạng Unicode, khoảng trắng, dấu
        stmt = stmt.where(Person.name_key.contains(name_key(q), autoescape=True))
    if external_id and external_id.strip():
        stmt = stmt.where(func.upper(func.trim(Person.external_id)) == external_id.strip().upper())
    if status:
        stmt = stmt.where(Person.status == status)
    audit(db, user, "person_search", reason=(q or external_id or "")[:100], request=request)
    db.commit()
    out = []
    for p in db.scalars(stmt):
        d = to_dict(p)
        mine = active_stay(db, p.id, user.facility_id)
        d["facility_stay_status"] = mine.status if mine else None
        d["active_elsewhere"] = bool(not mine and active_stay(db, p.id))
        out.append(d)
    return out


@router.get("/persons/{person_id}", tags=["identity"])
def get_person(person_id: str, _: User = Depends(require("person.read")), db: Session = Depends(get_db)):
    return to_dict(person_or_404(db, person_id, allow_merged=True))


class VerifyIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    date_of_birth: date | None = None
    source_system: str | None = Field(default=None, max_length=64)
    external_id: str | None = Field(default=None, max_length=64)
    note: str = Field(min_length=3)
    confirm_distinct: bool = False     # họ tên/ngày sinh mới trùng hồ sơ khác: xác nhận là hai người khác nhau
    _dob = field_validator("date_of_birth")(_valid_dob)
    _name = field_validator("full_name")(_valid_name)
    _src = field_validator("source_system")(_norm_source)
    _ext = field_validator("external_id")(_norm_ext)


def may_manage_identity(db: Session, user: User, p: Person) -> bool:
    """Cơ sở đang quản lý người này (đợt tiếp nhận còn hiệu lực) được đối soát danh tính. Khi người này không còn
    đợt hiệu lực ở đâu: cơ sở từng liên quan hoặc chính người tạo hồ sơ. Cơ sở khác không được đổi danh tính."""
    if user.facility_id and active_stay(db, p.id, user.facility_id):
        return True
    if active_stay(db, p.id):
        return False
    return p.created_by == user.id or has_facility_link(db, p.id, user.facility_id)


@router.post("/persons/{person_id}/verify", tags=["identity"])
def verify_person(person_id: str, body: VerifyIn, request: Request, user: User = Depends(require("person.write")),
                  db: Session = Depends(get_db)):
    """Đối soát danh tính (thay cho auto-merge). Hồ sơ tạm (cấp cứu) được cập nhật danh tính thật tại đây."""
    lock_row(db, Person, person_id)
    p = person_or_404(db, person_id)
    if not may_manage_identity(db, user, p):
        audit(db, user, "access_denied", "Person", p.id, person_id=p.id, result="denied",
              reason="đối soát danh tính ngoài phạm vi cơ sở", request=request, commit=True)
        fail(403, "FACILITY_SCOPE", "Chỉ cơ sở đang quản lý (hoặc người tạo hồ sơ) được đối soát danh tính")
    if bool(body.external_id) != bool(body.source_system):
        fail(422, "IDENTITY_INCOMPLETE", "external_id và source_system phải đi cùng nhau")
    if body.external_id:
        ex = external_owner(db, body.source_system, body.external_id, exclude_id=p.id)
        if ex:
            fail(409, "PERSON_EXISTS", "Mã nguồn đã thuộc hồ sơ khác – cần quy trình gộp có phê duyệt",
                 existing_person_id=ex.id)
    new = {"full_name": body.full_name or p.full_name, "date_of_birth": body.date_of_birth or p.date_of_birth,
           "source_system": body.source_system or p.source_system, "external_id": body.external_id or p.external_id}
    if not (new["external_id"] and new["source_system"]):
        fail(422, "IDENTITY_INCOMPLETE", "Cần mã nguồn + source_system để xác minh")
    if name_key(new["full_name"]) != p.name_key or new["date_of_birth"] != p.date_of_birth:
        cands = duplicate_candidates(db, new["full_name"], new["date_of_birth"], exclude_id=p.id)
        if cands and not body.confirm_distinct:
            fail(409, "DUPLICATE_SUSPECTED", "Họ tên/ngày sinh mới trùng hồ sơ khác – kiểm tra (gộp có phê duyệt) hoặc xác nhận khác người",
                 candidates=_candidates_out(cands))
    # nhật ký giữ lại giá trị CŨ -> MỚI của các trường định danh (không mất dấu vết khi đổi tên/mã)
    changes = [f"{k}: {getattr(p, k) or '∅'} → {v or '∅'}" for k, v in new.items() if getattr(p, k) != v]
    if p.status != "verified":
        changes.append(f"status: {p.status} → verified")
    for k, v in new.items():
        setattr(p, k, v)
    p.status, p.is_temporary, p.duplicate_candidates = "verified", False, None
    audit(db, user, "person_verified", "Person", p.id, person_id=p.id, request=request,
          reason=body.note + (" | " + "; ".join(changes) if changes else ""))
    db.commit()
    return to_dict(p)


class BreakGlassIn(BaseModel):
    reason: str = Field(min_length=10)


@router.post("/persons/{person_id}/break-glass", tags=["identity"])
def break_glass(person_id: str, body: BreakGlassIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Truy cập khẩn cấp ngoài phạm vi cơ sở: chỉ đọc, có hạn (mặc định 30 phút), lý do bắt buộc, hậu kiểm."""
    person_or_404(db, person_id)
    if has_facility_link(db, person_id, user.facility_id):
        fail(409, "NOT_NEEDED", "Người này đã thuộc phạm vi cơ sở của bạn, không cần truy cập khẩn cấp")
    g = grant_break_glass(db, user, person_id, body.reason, request)
    db.commit()
    return {"expires_at": g.expires_at, "minutes": config.BREAK_GLASS_MINUTES, "read_only": True}


@router.get("/persons/{person_id}/break-glass", tags=["identity"])
def break_glass_status(person_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    g = active_grant(db, user.id, person_id)
    return {"active": bool(g), "expires_at": g.expires_at if g else None}


# ----------------------------------------------------------------- đợt tiếp nhận
class StayIn(BaseModel):
    start_date: date | None = None
    source_ref: str | None = None


def get_or_create_record(db: Session, person_id: str) -> HealthRecord:
    rec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == person_id)).first()
    if not rec:
        rec = HealthRecord(person_id=person_id)
        db.add(rec)
        db.flush()
    return rec


@router.post("/persons/{person_id}/stays", status_code=201, tags=["identity"])
def create_stay(person_id: str, body: StayIn, request: Request, user: User = Depends(require("stay.write")),
                db: Session = Depends(get_db)):
    def work():
        return _create_stay(person_id, body, request, user, db)
    return run_idempotent(db, request, user, {"p": person_id, **body.model_dump(mode="json")}, work)


def _create_stay(person_id: str, body: StayIn, request: Request, user: User, db: Session):
    # khóa hồ sơ người TRƯỚC khi kiểm tra "đang có đợt hiệu lực" + tạo HealthRecord: hai yêu cầu đồng thời được tuần tự hóa
    lock_row(db, Person, person_id)
    p = person_or_404(db, person_id)
    start = body.start_date or date.today()
    if start > date.today():
        fail(422, "BAD_START_DATE", "Ngày tiếp nhận không được ở tương lai")
    if p.date_of_birth and start < p.date_of_birth:
        fail(422, "BAD_START_DATE", "Ngày tiếp nhận không được trước ngày sinh")
    cur = active_stay(db, p.id)
    if cur and cur.provisional and cur.facility_id == user.facility_id:
        # C4: kỳ tạm (cấp cứu) tại chính cơ sở này -> chuyển thành đợt tiếp nhận chính thức, không tạo kỳ thứ hai
        stay = cur
        stay.provisional = False
        stay.source_ref = body.source_ref or stay.source_ref
        audit(db, user, "stay_adopted", "CustodyStay", stay.id, person_id=p.id, request=request,
              reason="Tiếp nhận chính thức kỳ tạm từ cấp cứu")
    elif cur:
        fail(409, "ACTIVE_STAY_EXISTS", "Người này đang trong một đợt tiếp nhận – cần chuyển trại/kết thúc trước",
             stay_id=cur.id, facility_id=cur.facility_id)
    else:
        stay = CustodyStay(person_id=p.id, facility_id=user.facility_id, start_date=start,
                           source_ref=body.source_ref, created_by=user.id)
        db.add(stay)
        audit(db, user, "stay_created", "CustodyStay", stay.id, person_id=p.id, request=request)
    rec = get_or_create_record(db, p.id)  # UAT-01: dùng lại HealthRecord, không tạo trùng
    # WF-07: cơ sở đích tiếp nhận kỳ mới = lập BIÊN NHẬN cho phiếu bàn giao đã xác nhận
    ho = db.scalars(select(Handover).where(Handover.person_id == p.id, Handover.kind == "transfer", Handover.status == "confirmed",
                                           Handover.to_facility_id == user.facility_id, Handover.received_at.is_(None))
                    .order_by(Handover.confirmed_at.desc())).first()
    if ho:
        ho.received_at, ho.received_by, ho.received_stay_id = utcnow(), user.id, stay.id
        audit(db, user, "handover_received", "Handover", ho.id, person_id=p.id, request=request)
        emit(db, kind="handover.received", category="handover", facility_id=ho.from_facility_id, actor=user, perms=("handover.confirm",),
             title="Cơ sở đích đã tiếp nhận người chuyển trại", plain="Phiếu bàn giao đã có biên nhận của cơ sở nhận.",
             named=f"{p.full_name}: cơ sở nhận đã tiếp nhận (biên nhận hoàn tất).", link_page="handover", link_ref=ho.id, person_id=p.id, dedupe=f"ho:{ho.id}:received")
    emit(db, kind="intake.new_person", category="intake", facility_id=user.facility_id, actor=user, perms=("encounter.write",),
         title="Người mới tiếp nhận cần khám ban đầu", plain="Có người mới được tiếp nhận, chờ khám sức khỏe ban đầu.",
         named=f"{p.full_name} vừa được tiếp nhận, chờ khám sức khỏe ban đầu.", link_page="initial", person_id=p.id, dedupe=f"stay:{stay.id}:new")
    return 201, {**to_dict(stay), "health_record_id": rec.id}


@router.get("/persons/{person_id}/stays", tags=["identity"])
def list_stays(person_id: str, _: User = Depends(require("person.read")), db: Session = Depends(get_db)):
    person_or_404(db, person_id)
    return [to_dict(s) for s in db.scalars(select(CustodyStay).where(CustodyStay.person_id == person_id)
                                           .order_by(CustodyStay.recorded_at))]


class VoidIn(BaseModel):
    reason: str = Field(min_length=5)


def _pending_handover(db: Session, stay_id: str) -> Handover | None:
    return db.scalars(select(Handover).where(Handover.stay_id == stay_id, Handover.status == "pending").limit(1)).first()


@router.post("/stays/{stay_id}/void", tags=["identity"])
def void_stay(stay_id: str, body: VoidIn, request: Request, user: User = Depends(require("stay.write")),
              db: Session = Depends(get_db)):
    """Nhập nhầm người: hủy liên kết có nhật ký; KHÔNG xóa dữ liệu lâm sàng."""
    s = db.get(CustodyStay, stay_id)
    if not s or s.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy đợt tiếp nhận")
    lock_row(db, Person, s.person_id)
    s = db.get(CustodyStay, stay_id, populate_existing=True)
    if s.status not in ("received", "managed"):
        fail(409, "STAY_NOT_ACTIVE", "Chỉ hủy được đợt tiếp nhận đang hiệu lực (đợt đã chuyển trại/kết thúc/hủy là lịch sử)")
    if _pending_handover(db, s.id):
        fail(409, "HANDOVER_PENDING", "Đợt tiếp nhận đang có phiếu bàn giao chờ xác nhận – hủy phiếu bàn giao trước")
    if db.scalars(select(Encounter.id).where(Encounter.stay_id == s.id).limit(1)).first():
        fail(409, "HAS_CLINICAL_DATA", "Đợt tiếp nhận đã có dữ liệu lâm sàng – cần hiệu chỉnh bởi bộ phận y tế")
    s.status, s.void_reason = "voided", body.reason
    audit(db, user, "stay_voided", "CustodyStay", s.id, person_id=s.person_id, reason=body.reason, request=request)
    db.commit()
    return to_dict(s)


# ----------------------------------------------------------------- WF-07 chuyển trại / kết thúc
OPEN_ENCOUNTER = ("draft", "in_progress", "awaiting_results", "in_treatment")


def open_items_for(db: Session, person_id: str, facility_id: str) -> dict:
    """Việc đang mở CỦA CƠ SỞ BÀN GIAO (cơ sở khác không phải xác nhận việc mà mình không thấy/không đóng được)."""
    return {
        "open_encounters": db.scalar(select(func.count()).select_from(Encounter).where(
            Encounter.person_id == person_id, Encounter.facility_id == facility_id, Encounter.status.in_(OPEN_ENCOUNTER))),
        "open_clinical_orders": db.scalar(select(func.count()).select_from(ClinicalOrder).join(
            Encounter, Encounter.id == ClinicalOrder.encounter_id).where(
            ClinicalOrder.person_id == person_id, Encounter.facility_id == facility_id, ClinicalOrder.status == "open")),
        "active_medication_orders": db.scalar(select(func.count()).select_from(MedicationOrder).where(
            MedicationOrder.person_id == person_id, MedicationOrder.facility_id == facility_id,
            MedicationOrder.status.in_(("confirmed", "active")))),
        "open_appointments": db.scalar(select(func.count()).select_from(Appointment).where(
            Appointment.person_id == person_id, Appointment.facility_id == facility_id,
            Appointment.status.in_(("scheduled", "due")))),
        "open_referrals": db.scalar(select(func.count()).select_from(Referral).where(
            Referral.person_id == person_id, Referral.facility_id == facility_id,
            Referral.status.notin_(("completed", "cancelled")))),
    }


def _hand_over_open_items(db: Session, h: Handover) -> None:
    """C3 – chuyển trại đã xác nhận: việc dài hạn đi theo người sang cơ sở đích; việc khám dở dang tại cơ sở cũ được đóng."""
    src, dst = h.from_facility_id, h.to_facility_id
    # đơn thuốc còn hiệu lực/nháp -> cơ sở đích cấp phát, theo dõi tiếp
    for o in db.scalars(select(MedicationOrder).where(MedicationOrder.person_id == h.person_id, MedicationOrder.facility_id == src,
                                                       MedicationOrder.status.in_(("draft", "confirmed", "active")))):
        o.facility_id = dst
    # kế hoạch theo dõi -> cơ sở đích; người phụ trách thuộc cơ sở cũ nên bỏ trống để cơ sở đích phân công
    for cp in db.scalars(select(CarePlan).where(CarePlan.person_id == h.person_id, CarePlan.facility_id == src,
                                                CarePlan.status == "active")):
        cp.facility_id, cp.responsible_user_id = dst, None
    for a in db.scalars(select(Appointment).where(Appointment.person_id == h.person_id, Appointment.facility_id == src,
                                                   Appointment.status.in_(("scheduled", "due")))):
        if a.round_id:   # đợt khám định kỳ là của cơ sở cũ -> không mang sang
            a.status, a.status_reason = "not_done", TRANSFER_CLOSE_REASON
            for al in db.scalars(select(Alert).where(Alert.dedupe_key == f"overdue:{a.id}",
                                                     Alert.status.in_(("new", "acknowledged")))):
                al.status, al.resolution, al.handled_at = "resolved", TRANSFER_CLOSE_REASON, utcnow()
        else:
            a.facility_id, a.assignee_id = dst, None
    # lượt khám dở dang + chỉ định chưa có kết quả tại cơ sở cũ: đóng (không xóa), cơ sở đích khám lại khi cần.
    # BR-05: chuyển viện có trạng thái độc lập với đợt tiếp nhận -> không đụng tới đề nghị chuyển viện.
    for e in db.scalars(select(Encounter).where(Encounter.person_id == h.person_id, Encounter.facility_id == src,
                                                Encounter.status.in_(OPEN_ENCOUNTER))):
        for c in db.scalars(select(ClinicalOrder).where(ClinicalOrder.encounter_id == e.id, ClinicalOrder.status == "open")):
            c.status, c.cancel_reason = "cancelled", TRANSFER_CLOSE_REASON
        e.status, e.cancel_reason = "cancelled", TRANSFER_CLOSE_REASON
        e.version += 1


class HandoverIn(BaseModel):
    kind: str = Field(pattern="^(transfer|release)$")
    to_facility_id: str | None = None
    reason: str = Field(min_length=3)


def _sees_content(h: Handover, user: User) -> bool:
    """Nội dung y tế của phiếu: người có clinical.read tại cơ sở bàn giao, hoặc cơ sở đích SAU KHI đã tiếp nhận."""
    if "clinical.read" not in perms_of(user):
        return False
    return user.facility_id == h.from_facility_id or (user.facility_id == h.to_facility_id and h.received_at is not None)


def _handover_out(h: Handover, user: User) -> dict:
    d = to_dict(h)
    if not _sees_content(h, user):  # cán bộ quản lý / cơ sở đích chưa tiếp nhận: chỉ thấy trạng thái, không thấy nội dung y tế
        d["summary"] = None
        d["has_summary"] = bool(h.summary)
        d["open_items"] = None
        d["document_ids"] = None
    return d


def _load_handover(db: Session, user: User, handover_id: str) -> Handover:
    """Phiếu bàn giao của cơ sở gửi; khóa hồ sơ người để tuần tự hóa với các thao tác khác trên đợt tiếp nhận."""
    h = db.get(Handover, handover_id)
    if not h or h.from_facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy phiếu bàn giao")
    lock_row(db, Person, h.person_id)
    return db.get(Handover, handover_id, populate_existing=True)


@router.post("/stays/{stay_id}/handover", status_code=201, tags=["handover"])
def initiate_handover(stay_id: str, body: HandoverIn, request: Request,
                      user: User = Depends(require("handover.initiate")), db: Session = Depends(get_db)):
    s = db.get(CustodyStay, stay_id)
    if not s or s.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy đợt tiếp nhận tại cơ sở của bạn")
    lock_row(db, Person, s.person_id)
    s = db.get(CustodyStay, stay_id, populate_existing=True)
    if s.status not in ("received", "managed"):
        fail(409, "STAY_NOT_ACTIVE", "Đợt tiếp nhận không còn hiệu lực")
    if body.kind == "transfer":
        if not body.to_facility_id or not db.get(Facility, body.to_facility_id):
            fail(422, "TO_FACILITY_REQUIRED", "Chuyển trại cần cơ sở đích hợp lệ")
        if body.to_facility_id == s.facility_id:
            fail(422, "SAME_FACILITY", "Cơ sở đích trùng cơ sở hiện tại")
    elif body.to_facility_id:
        fail(422, "RELEASE_NO_DESTINATION", "Kết thúc quản lý không có cơ sở đích (chỉ chuyển trại mới chọn cơ sở đích)")
    if _pending_handover(db, s.id):
        fail(409, "HANDOVER_PENDING", "Đã có phiếu bàn giao đang chờ xác nhận")
    h = Handover(stay_id=s.id, person_id=s.person_id, kind=body.kind, from_facility_id=s.facility_id,
                 to_facility_id=body.to_facility_id, reason=body.reason, initiated_by=user.id,
                 open_items=open_items_for(db, s.person_id, s.facility_id))
    db.add(h)
    audit(db, user, "handover_initiated", "Handover", h.id, person_id=s.person_id, reason=body.reason, request=request)
    what = "chuyển trại" if body.kind == "transfer" else "kết thúc quản lý"
    emit(db, kind="handover.initiated", category="handover", severity="warning", facility_id=s.facility_id, actor=user, perms=("handover.summary",),
         title="Cần soạn tóm tắt y tế bàn giao", plain=f"Có phiếu {what} đang chờ bộ phận y tế lập tóm tắt.",
         named=f"{person_name(db, s.person_id)}: phiếu {what} đang chờ bộ phận y tế lập tóm tắt.", link_page="handover", link_ref=h.id, person_id=s.person_id, dedupe=f"ho:{h.id}:init")
    db.commit()
    return _handover_out(h, user)


class SummaryIn(BaseModel):
    summary: str = Field(min_length=10)
    document_ids: list[str] | None = Field(default=None, max_length=30)


@router.put("/handovers/{handover_id}/summary", tags=["handover"])
def set_handover_summary(handover_id: str, body: SummaryIn, request: Request,
                         user: User = Depends(require("handover.summary")), db: Session = Depends(get_db)):
    from .referral import check_handover_docs   # tránh vòng import (referral -> clinical -> identity)
    h = _load_handover(db, user, handover_id)
    if h.status != "pending":
        fail(409, "HANDOVER_CLOSED", "Phiếu bàn giao đã đóng")
    ensure_clinical_access(db, user, h.person_id, request, write=True)
    h.summary, h.summary_by = body.summary, user.id
    h.document_ids = check_handover_docs(db, h.person_id, body.document_ids)
    h.open_items = open_items_for(db, h.person_id, h.from_facility_id)
    audit(db, user, "handover_summary", "Handover", h.id, person_id=h.person_id, request=request)
    emit(db, kind="handover.ready", category="handover", facility_id=h.from_facility_id, actor=user, perms=("handover.confirm",),
         title="Phiếu bàn giao sẵn sàng xác nhận", plain="Bộ phận y tế đã lập tóm tắt, chờ xác nhận bàn giao.",
         named=f"{person_name(db, h.person_id)}: đã có tóm tắt y tế, chờ xác nhận bàn giao.", link_page="handover", link_ref=h.id, person_id=h.person_id, dedupe=f"ho:{h.id}:ready")
    db.commit()
    return _handover_out(h, user)


class ConfirmIn(BaseModel):
    acknowledge_open_items: bool = False
    receiver_name: str | None = None


@router.get("/handovers/{handover_id}", tags=["handover"])
def get_handover(handover_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = db.get(Handover, handover_id)
    if not h or user.facility_id not in (h.from_facility_id, h.to_facility_id):
        fail(404, "NOT_FOUND", "Không tìm thấy phiếu bàn giao")
    if _sees_content(h, user) and h.summary:
        ensure_clinical_access(db, user, h.person_id, request)
        audit(db, user, "view_handover", "Handover", h.id, person_id=h.person_id, request=request, commit=True)
    return _handover_out(h, user)


@router.post("/handovers/{handover_id}/confirm", tags=["handover"])
def confirm_handover(handover_id: str, body: ConfirmIn, request: Request,
                     user: User = Depends(require("handover.confirm")), db: Session = Depends(get_db)):
    h = _load_handover(db, user, handover_id)
    if h.status != "pending":
        fail(409, "HANDOVER_CLOSED", "Phiếu bàn giao đã đóng")
    s = db.get(CustodyStay, h.stay_id, populate_existing=True)
    if s.status not in ("received", "managed"):
        fail(409, "STAY_NOT_ACTIVE", "Đợt tiếp nhận không còn hiệu lực (đã hủy/chuyển/kết thúc) – hủy phiếu bàn giao này")
    if not h.summary:
        fail(409, "SUMMARY_REQUIRED", "Chưa có bản tóm tắt y tế bàn giao – duy trì trạng thái chờ")
    items = open_items_for(db, h.person_id, h.from_facility_id)
    if any(items.values()) and not body.acknowledge_open_items:
        fail(409, "OPEN_ITEMS", "Còn điều trị/lịch đang mở – cần xác nhận đã bàn giao", open_items=items)
    s.status = "transferred" if h.kind == "transfer" else "ended"
    s.end_date = date.today()
    h.status, h.confirmed_by, h.confirmed_at, h.open_items = "confirmed", user.id, utcnow(), items
    if h.kind == "transfer":
        _hand_over_open_items(db, h)      # C3: thuốc, kế hoạch, lịch đi theo người; lượt khám dở dang đóng lại
    else:
        # kết thúc quản lý: lịch đang mở tại đơn vị cũ -> hoãn (BR-05: HealthRecord không bị ảnh hưởng)
        for a in db.scalars(select(Appointment).where(Appointment.person_id == h.person_id,
                                                       Appointment.facility_id == h.from_facility_id,
                                                       Appointment.status.in_(("scheduled", "due")))):
            a.status, a.status_reason = "postponed", "Chuyển trại/kết thúc quản lý"
    audit(db, user, "handover_confirmed", "Handover", h.id, person_id=h.person_id,
          reason=body.receiver_name, request=request)
    if h.kind == "transfer" and h.to_facility_id:
        emit(db, kind="handover.incoming", category="handover", severity="warning", facility_id=h.to_facility_id, actor=user, perms=("stay.write",),
             title="Có người được chuyển đến – cần xác nhận tiếp nhận mới", plain="Một phiếu chuyển trại đến cơ sở của bạn đã được bàn giao.",
             named=f"{person_name(db, h.person_id)} được chuyển đến, cần xác nhận tiếp nhận mới.", link_page="intake", link_ref=h.person_id, person_id=h.person_id, dedupe=f"ho:{h.id}:incoming")
    db.commit()
    return _handover_out(h, user)


class CancelHandoverIn(BaseModel):
    reason: str = Field(min_length=5)


@router.post("/handovers/{handover_id}/cancel", tags=["handover"])
def cancel_handover(handover_id: str, body: CancelHandoverIn, request: Request,
                    user: User = Depends(require("handover.initiate")), db: Session = Depends(get_db)):
    """Hủy phiếu bàn giao lập nhầm (sai cơ sở đích/sai hình thức) khi CHƯA xác nhận; đợt tiếp nhận giữ nguyên."""
    reason = body.reason.strip()
    if len(reason) < 5:
        fail(422, "REASON_REQUIRED", "Hủy phiếu bàn giao cần nêu lý do")
    h = _load_handover(db, user, handover_id)
    if h.status != "pending":
        fail(409, "HANDOVER_CLOSED", "Chỉ hủy được phiếu bàn giao đang chờ xác nhận")
    h.status, h.cancel_reason, h.cancelled_by, h.cancelled_at = "cancelled", reason, user.id, utcnow()
    audit(db, user, "handover_cancelled", "Handover", h.id, person_id=h.person_id, reason=reason, request=request)
    db.commit()
    return _handover_out(h, user)
