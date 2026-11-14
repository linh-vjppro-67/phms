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
from ..deps import identity_scope_clause, ensure_identity_visible, active_grant, active_stay, current_user, ensure_clinical_access, grant_break_glass, has_facility_link, person_or_404, require
from ..models import (Alert, Appointment, CarePlan, ClinicalOrder, CustodyStay, Encounter, Facility, Handover,
                      HealthRecord, MedicationOrder, Person, Referral, User)
from ..permissions import perms_of
from ..utils import fail, name_key, to_dict, utcnow

router = APIRouter()


def _valid_dob(v):
    if v is not None and not (date(1900, 1, 1) <= v <= date.today()):
        raise ValueError("Ngày sinh không hợp lệ (phải từ 1900 đến hôm nay)")
    return v


class PersonIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    date_of_birth: date | None = None
    gender: str | None = None
    source_system: str | None = None
    external_id: str | None = None
    confirm_distinct: bool = False     # xác nhận "đây là người khác" khi API báo nghi trùng (tên + ngày sinh)
    _dob = field_validator("date_of_birth")(_valid_dob)


@router.post("/persons", status_code=201, tags=["identity"])
def create_person(body: PersonIn, request: Request, user: User = Depends(require("person.write")),
                  db: Session = Depends(get_db)):
    def work():
        # BR-01: mã nguồn ngoài chỉ định danh khi đi kèm source_system; trùng -> không tạo mới
        if bool(body.external_id) != bool(body.source_system):
            fail(422, "IDENTITY_INCOMPLETE", "external_id và source_system phải đi cùng nhau")
        if body.external_id:
            ex = db.scalars(select(Person).where(Person.source_system == body.source_system,
                                                 Person.external_id == body.external_id)).first()
            if ex:
                fail(409, "PERSON_EXISTS", "Đã tồn tại hồ sơ cùng mã nguồn", existing_person_id=ex.id)
        cands = []
        if body.date_of_birth:
            cands = list(db.scalars(select(Person).where(
                Person.name_key == name_key(body.full_name), Person.date_of_birth == body.date_of_birth,
                Person.status != "merged")))
        if cands and not body.confirm_distinct:
            # Không tự tạo trùng và cũng không tự gộp: buộc người dùng xem ứng viên rồi xác nhận rõ ràng
            fail(409, "DUPLICATE_SUSPECTED", "Đã có hồ sơ cùng họ tên và ngày sinh – kiểm tra trước khi tạo mới",
                 candidates=[{"id": c.id, "full_name": c.full_name, "date_of_birth": str(c.date_of_birth),
                              "source_system": c.source_system, "external_id": c.external_id, "status": c.status} for c in cands[:10]])
        cand_ids = [c.id for c in cands]
        p = Person(full_name=body.full_name.strip(), date_of_birth=body.date_of_birth, gender=body.gender,
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
    scope = identity_scope_clause(user)       # REQ-02: chỉ vai trò quản lý danh tính mới tra cứu liên cơ sở
    if scope is not None:
        stmt = stmt.where(scope)
    if q:   # không phân biệt dấu/hoa/thường/khoảng trắng; cũng tìm theo mã nguồn
        stmt = stmt.where(or_(Person.name_key.like(f"%{name_key(q)}%"), Person.external_id.ilike(f"%{q.strip()}%")))
    if external_id:
        stmt = stmt.where(Person.external_id == external_id)
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
def get_person(person_id: str, request: Request, user: User = Depends(require("person.read")), db: Session = Depends(get_db)):
    p = person_or_404(db, person_id, allow_merged=True)
    ensure_identity_visible(db, user, p.id, request)
    return to_dict(p)


class VerifyIn(BaseModel):
    full_name: str | None = None
    date_of_birth: date | None = None
    source_system: str | None = None
    external_id: str | None = None
    note: str = Field(min_length=3)
    _dob = field_validator("date_of_birth")(_valid_dob)


@router.post("/persons/{person_id}/verify", tags=["identity"])
def verify_person(person_id: str, body: VerifyIn, request: Request, user: User = Depends(require("person.write")),
                  db: Session = Depends(get_db)):
    """Đối soát danh tính (thay cho auto-merge). Hồ sơ tạm (cấp cứu) được cập nhật danh tính thật tại đây."""
    p = person_or_404(db, person_id)
    creator = db.get(User, p.created_by) if p.created_by else None
    if not (has_facility_link(db, p.id, user.facility_id) or (creator and creator.facility_id == user.facility_id)):
        fail(403, "FACILITY_SCOPE", "Chỉ cơ sở đang quản lý (hoặc đã tiếp nhận) người này mới được đối soát danh tính")
    before = {"họ tên": p.full_name, "ngày sinh": str(p.date_of_birth or ""), "nguồn": f"{p.source_system or ''}/{p.external_id or ''}"}
    if body.external_id and body.source_system:
        ex = db.scalars(select(Person).where(Person.source_system == body.source_system,
                                             Person.external_id == body.external_id, Person.id != p.id)).first()
        if ex:
            fail(409, "PERSON_EXISTS", "Mã nguồn đã thuộc hồ sơ khác – cần quy trình gộp có phê duyệt",
                 existing_person_id=ex.id)
        p.source_system, p.external_id = body.source_system, body.external_id
    if body.full_name:
        p.full_name = body.full_name
    if body.date_of_birth:
        p.date_of_birth = body.date_of_birth
    if not (p.external_id and p.source_system):
        fail(422, "IDENTITY_INCOMPLETE", "Cần mã nguồn + source_system để xác minh")
    p.status, p.is_temporary, p.duplicate_candidates = "verified", False, None
    after = {"họ tên": p.full_name, "ngày sinh": str(p.date_of_birth or ""), "nguồn": f"{p.source_system or ''}/{p.external_id or ''}"}
    changes = "; ".join(f"{k}: '{before[k]}' → '{after[k]}'" for k in before if before[k] != after[k])
    audit(db, user, "person_verified", "Person", p.id, person_id=p.id,
          reason=(body.note + (f" | thay đổi: {changes}" if changes else " | không đổi thông tin định danh"))[:900], request=request)
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
    p = person_or_404(db, person_id)
    p = lock_row(db, Person, p.id)         # hai người cùng tiếp nhận một người: tuần tự hóa, không tạo trùng đợt/hồ sơ sức khỏe
    cur = active_stay(db, p.id)
    if cur and cur.provisional and cur.facility_id == user.facility_id:
        # đợt TẠM do cấp cứu: sau khi đối soát danh tính thì tiếp nhận chính thức = nhận lại đợt tạm đó (không tạo đợt thứ hai)
        if p.status != "verified":
            fail(409, "IDENTITY_NOT_VERIFIED", "Cần đối soát danh tính trước khi tiếp nhận chính thức")
        cur.provisional = False
        if body.source_ref:
            cur.source_ref = body.source_ref
        audit(db, user, "stay_adopted", "CustodyStay", cur.id, person_id=p.id, reason="Tiếp nhận chính thức đợt tạm của cấp cứu", request=request)
        rec = get_or_create_record(db, p.id)
        return 201, {**to_dict(cur), "health_record_id": rec.id}
    if cur:
        fail(409, "ACTIVE_STAY_EXISTS", "Người này đang trong một đợt tiếp nhận – cần chuyển trại/kết thúc trước",
             stay_id=cur.id, facility_id=cur.facility_id)
    stay = CustodyStay(person_id=p.id, facility_id=user.facility_id, start_date=body.start_date or date.today(),
                       source_ref=body.source_ref, created_by=user.id)
    db.add(stay)
    rec = get_or_create_record(db, p.id)  # UAT-01: dùng lại HealthRecord, không tạo trùng
    audit(db, user, "stay_created", "CustodyStay", stay.id, person_id=p.id, request=request)
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


@router.post("/stays/{stay_id}/void", tags=["identity"])
def void_stay(stay_id: str, body: VoidIn, request: Request, user: User = Depends(require("stay.write")),
              db: Session = Depends(get_db)):
    """Nhập nhầm người: hủy liên kết có nhật ký; KHÔNG xóa dữ liệu lâm sàng."""
    s = db.get(CustodyStay, stay_id)
    if not s or s.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy đợt tiếp nhận")
    if db.scalars(select(Encounter.id).where(Encounter.stay_id == s.id).limit(1)).first():
        fail(409, "HAS_CLINICAL_DATA", "Đợt tiếp nhận đã có dữ liệu lâm sàng – cần hiệu chỉnh bởi bộ phận y tế")
    s.status, s.void_reason = "voided", body.reason
    audit(db, user, "stay_voided", "CustodyStay", s.id, person_id=s.person_id, reason=body.reason, request=request)
    db.commit()
    return to_dict(s)


# ----------------------------------------------------------------- WF-07 chuyển trại / kết thúc
def open_items_for(db: Session, person_id: str) -> dict:
    return {
        "open_encounters": db.scalar(select(func.count()).select_from(Encounter).where(
            Encounter.person_id == person_id, Encounter.status.in_(
                ("draft", "in_progress", "awaiting_results", "in_treatment")))),
        "open_clinical_orders": db.scalar(select(func.count()).select_from(ClinicalOrder).where(
            ClinicalOrder.person_id == person_id, ClinicalOrder.status == "open")),
        "active_medication_orders": db.scalar(select(func.count()).select_from(MedicationOrder).where(
            MedicationOrder.person_id == person_id, MedicationOrder.status.in_(("confirmed", "active")))),
        "open_appointments": db.scalar(select(func.count()).select_from(Appointment).where(
            Appointment.person_id == person_id, Appointment.status.in_(("scheduled", "due")))),
        "open_referrals": db.scalar(select(func.count()).select_from(Referral).where(
            Referral.person_id == person_id, Referral.status.notin_(("completed", "cancelled")))),
    }


class HandoverIn(BaseModel):
    kind: str = Field(pattern="^(transfer|release)$")
    to_facility_id: str | None = None
    reason: str = Field(min_length=3)


def _handover_out(h: Handover, user: User) -> dict:
    d = to_dict(h)
    if "clinical.read" not in perms_of(user):  # cán bộ quản lý chỉ thấy trạng thái, không thấy nội dung y tế
        d["summary"] = None
        d["has_summary"] = bool(h.summary)
        d["open_items"] = None
    return d


@router.post("/stays/{stay_id}/handover", status_code=201, tags=["handover"])
def initiate_handover(stay_id: str, body: HandoverIn, request: Request,
                      user: User = Depends(require("handover.initiate")), db: Session = Depends(get_db)):
    s = db.get(CustodyStay, stay_id)
    if not s or s.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy đợt tiếp nhận tại cơ sở của bạn")
    s = lock_row(db, CustodyStay, s.id)    # chống tạo hai phiếu bàn giao cùng lúc cho một đợt
    if s.status not in ("received", "managed"):
        fail(409, "STAY_NOT_ACTIVE", "Đợt tiếp nhận không còn hiệu lực")
    if body.kind == "transfer":
        if not body.to_facility_id or not db.get(Facility, body.to_facility_id):
            fail(422, "TO_FACILITY_REQUIRED", "Chuyển trại cần cơ sở đích hợp lệ")
        if body.to_facility_id == s.facility_id:
            fail(422, "SAME_FACILITY", "Cơ sở đích trùng cơ sở hiện tại")
    if db.scalars(select(Handover.id).where(Handover.stay_id == s.id, Handover.status == "pending")).first():
        fail(409, "HANDOVER_PENDING", "Đã có phiếu bàn giao đang chờ xác nhận")
    h = Handover(stay_id=s.id, person_id=s.person_id, kind=body.kind, from_facility_id=s.facility_id,
                 to_facility_id=body.to_facility_id, reason=body.reason, initiated_by=user.id,
                 open_items=open_items_for(db, s.person_id))
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
    document_ids: list[str] | None = None


@router.put("/handovers/{handover_id}/summary", tags=["handover"])
def set_handover_summary(handover_id: str, body: SummaryIn, request: Request,
                         user: User = Depends(require("handover.summary")), db: Session = Depends(get_db)):
    h = db.get(Handover, handover_id)
    if not h or h.from_facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy phiếu bàn giao")
    if h.status != "pending":
        fail(409, "HANDOVER_CLOSED", "Phiếu bàn giao đã đóng")
    ensure_clinical_access(db, user, h.person_id, request)
    h.summary, h.document_ids, h.summary_by = body.summary, body.document_ids, user.id
    h.open_items = open_items_for(db, h.person_id)
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
def get_handover(handover_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = db.get(Handover, handover_id)
    if not h or user.facility_id not in (h.from_facility_id, h.to_facility_id):
        fail(404, "NOT_FOUND", "Không tìm thấy phiếu bàn giao")
    return _handover_out(h, user)


@router.post("/handovers/{handover_id}/confirm", tags=["handover"])
def confirm_handover(handover_id: str, body: ConfirmIn, request: Request,
                     user: User = Depends(require("handover.confirm")), db: Session = Depends(get_db)):
    h = db.get(Handover, handover_id)
    if not h or h.from_facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy phiếu bàn giao")
    h = lock_row(db, Handover, h.id)       # hai người cùng bấm xác nhận: chỉ một người thực hiện
    if h.status != "pending":
        fail(409, "HANDOVER_CLOSED", "Phiếu bàn giao đã đóng")
    if not h.summary:
        fail(409, "SUMMARY_REQUIRED", "Chưa có bản tóm tắt y tế bàn giao – duy trì trạng thái chờ")
    items = open_items_for(db, h.person_id)
    if any(items.values()) and not body.acknowledge_open_items:
        fail(409, "OPEN_ITEMS", "Còn điều trị/lịch đang mở – cần xác nhận đã bàn giao", open_items=items)
    s = db.get(CustodyStay, h.stay_id)
    s.status = "transferred" if h.kind == "transfer" else "ended"
    s.end_date = date.today()
    h.status, h.confirmed_by, h.confirmed_at, h.open_items = "confirmed", user.id, utcnow(), items
    handed = {"đơn thuốc": 0, "kế hoạch theo dõi": 0, "lịch hẹn": 0, "đơn nháp bị hủy": 0}
    open_appts = db.scalars(select(Appointment).where(Appointment.person_id == h.person_id, Appointment.facility_id == h.from_facility_id,
                                                      Appointment.status.in_(("scheduled", "due")))).all()
    if h.kind == "transfer" and h.to_facility_id:
        # BÀN GIAO sang cơ sở nhận: đơn thuốc còn hiệu lực, kế hoạch theo dõi và lịch đang mở chuyển theo người (BR-05: hồ sơ sức khỏe giữ nguyên)
        to = h.to_facility_id
        for o in db.scalars(select(MedicationOrder).where(MedicationOrder.person_id == h.person_id, MedicationOrder.facility_id == h.from_facility_id,
                                                          MedicationOrder.status.in_(("draft", "confirmed", "active")))):
            if o.status == "draft":
                o.status, o.stop_reason = "cancelled", "Chuyển trại – đơn nháp chưa xác nhận bị hủy"
                handed["đơn nháp bị hủy"] += 1
            else:
                o.facility_id = to
                handed["đơn thuốc"] += 1
        for cp in db.scalars(select(CarePlan).where(CarePlan.person_id == h.person_id, CarePlan.facility_id == h.from_facility_id, CarePlan.status == "active")):
            cp.facility_id, cp.responsible_user_id = to, None        # cơ sở nhận chỉ định người phụ trách mới
            handed["kế hoạch theo dõi"] += 1
        for a in open_appts:
            a.facility_id, a.assignee_id = to, None
            a.note = ((a.note + " · ") if a.note else "") + "Chuyển từ cơ sở cũ"
            handed["lịch hẹn"] += 1
    else:
        # kết thúc quản lý: lịch đang mở bị hoãn
        for a in open_appts:
            a.status, a.status_reason = "postponed", "Kết thúc quản lý"
    audit(db, user, "handover_confirmed", "Handover", h.id, person_id=h.person_id,
          reason=(f"{body.receiver_name or ''} | đã bàn giao: " + ", ".join(f"{v} {k}" for k, v in handed.items() if v))[:500], request=request)
    if h.kind == "transfer" and h.to_facility_id:
        emit(db, kind="handover.incoming", category="handover", severity="warning", facility_id=h.to_facility_id, actor=user, perms=("stay.write",),
             title="Có người được chuyển đến – cần xác nhận tiếp nhận mới", plain="Một phiếu chuyển trại đến cơ sở của bạn đã được bàn giao.",
             named=f"{person_name(db, h.person_id)} được chuyển đến, cần xác nhận tiếp nhận mới.", link_page="intake", link_ref=h.person_id, person_id=h.person_id, dedupe=f"ho:{h.id}:incoming")
    db.commit()
    return _handover_out(h, user)


class CancelIn(BaseModel):
    reason: str = Field(min_length=5)


@router.post("/handovers/{handover_id}/cancel", tags=["handover"])
def cancel_handover(handover_id: str, body: CancelIn, request: Request, user: User = Depends(require("handover.initiate")),
                    db: Session = Depends(get_db)):
    """Hủy phiếu bàn giao còn chờ (lập nhầm, thay đổi quyết định). Phiếu đã xác nhận không hủy được."""
    h = db.get(Handover, handover_id)
    if not h or h.from_facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy phiếu bàn giao")
    h = lock_row(db, Handover, h.id)
    if h.status != "pending":
        fail(409, "HANDOVER_CLOSED", "Chỉ hủy được phiếu đang chờ xác nhận")
    h.status, h.cancel_reason, h.cancelled_by, h.cancelled_at = "cancelled", body.reason.strip(), user.id, utcnow()
    audit(db, user, "handover_cancelled", "Handover", h.id, person_id=h.person_id, reason=body.reason.strip(), request=request)
    emit(db, kind="handover.cancelled", category="handover", facility_id=h.from_facility_id, actor=user, perms=("handover.summary",),
         title="Phiếu bàn giao đã bị hủy", plain="Một phiếu bàn giao đang chờ đã được hủy, không cần soạn tóm tắt.",
         named=f"{person_name(db, h.person_id)}: phiếu bàn giao đã bị hủy ({body.reason.strip()[:80]}).", link_page="handover", link_ref=h.id, person_id=h.person_id, dedupe=f"ho:{h.id}:cancel")
    db.commit()
    return _handover_out(h, user)
