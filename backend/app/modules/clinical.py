"""M02–M04: hồ sơ sức khỏe, lượt khám (Encounter), sinh hiệu, chẩn đoán, chỉ định XN/thủ thuật (WF-01, WF-02)."""
import unicodedata
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..db import get_db, lock_row
from ..deps import active_stay, ensure_clinical_access, person_or_404, require
from ..idempotency import idempotent, run_idempotent
from ..notify import emit, person_name
from ..models import (Alert, DispenseEvent, Allergy, Appointment, ClinicalOrder, CustodyStay, Diagnosis, Encounter, EncounterAddendum,
                      HealthProblem, HealthRecord, MedicationOrder, Observation, Referral, User)
from ..permissions import perms_of
from ..utils import bump_version, fail, norm_dt, to_dict, utcnow
from .identity import get_or_create_record
from .scheduling import complete_appointment

router = APIRouter()

ENC_TYPES = {"initial", "periodic", "ad_hoc", "emergency"}
ENC_TRANS = {
    "draft": {"in_progress", "cancelled"},
    "in_progress": {"awaiting_results", "in_treatment", "completed", "cancelled"},
    "awaiting_results": {"in_progress", "in_treatment", "completed", "cancelled"},
    "in_treatment": {"in_progress", "awaiting_results", "completed", "cancelled"},
}
EDITABLE = set(ENC_TRANS)


def load_encounter(db: Session, user: User, enc_id: str, request: Request, write: bool = False) -> Encounter:
    e = db.get(Encounter, enc_id)
    if not e:
        fail(404, "ENCOUNTER_NOT_FOUND", "Không tìm thấy lượt khám")
    ensure_clinical_access(db, user, e.person_id, request, write=write)
    if write and e.facility_id != user.facility_id:
        fail(403, "FACILITY_SCOPE", "Chỉ ghi dữ liệu lượt khám thuộc cơ sở của bạn")
    return e


def require_editable(e: Encounter):
    if e.status not in EDITABLE:
        fail(409, "ENCOUNTER_LOCKED", f"Lượt khám đang ở trạng thái '{e.status}' – dùng addendum để bổ sung/điều chỉnh")


# ----------------------------------------------------------------- tổng hợp hồ sơ
@router.get("/persons/{person_id}/health-summary", tags=["clinical"])
def health_summary(person_id: str, request: Request, user: User = Depends(require("person.read")),
                   db: Session = Depends(get_db)):
    p = person_or_404(db, person_id)
    stays = [to_dict(s) for s in db.scalars(select(CustodyStay).where(CustodyStay.person_id == p.id)
                                            .order_by(CustodyStay.recorded_at))]
    out = {"person": to_dict(p), "stays": stays, "clinical": None, "clinical_hidden": True}
    if "clinical.read" in perms_of(user):
        ensure_clinical_access(db, user, p.id, request)
        rec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == p.id)).first()
        out["clinical_hidden"] = False
        out["clinical"] = {
            "health_record_id": rec.id if rec else None,
            "allergy_status": rec.allergy_status if rec else "unknown",
            "allergies": [to_dict(a) for a in db.scalars(select(Allergy).where(
                Allergy.record_id == (rec.id if rec else ""), Allergy.active.is_(True)))],
            "problems": [to_dict(x) for x in db.scalars(select(HealthProblem).where(
                HealthProblem.person_id == p.id).order_by(HealthProblem.effective_from.desc()))],
            "active_medications": [to_dict(m) for m in db.scalars(select(MedicationOrder).where(
                MedicationOrder.person_id == p.id, MedicationOrder.status.in_(("confirmed", "active"))))],
            "recent_encounters": [to_dict(e) for e in db.scalars(select(Encounter).where(
                Encounter.person_id == p.id).order_by(Encounter.occurred_at.desc()).limit(10))],
            "open_referrals": [to_dict(r, exclude=("reason",)) for r in db.scalars(select(Referral).where(
                Referral.person_id == p.id, Referral.status.notin_(("completed", "cancelled"))))],
            "upcoming_appointments": [to_dict(a) for a in db.scalars(select(Appointment).where(
                Appointment.person_id == p.id, Appointment.status.in_(("scheduled", "due"))).order_by(
                Appointment.due_date))],
            # BR-07: không coi "chưa có dữ liệu" là "không có bệnh"
            "notice": "Mục chưa có dữ liệu được hiểu là CHƯA GHI NHẬN, không phải 'không có'.",
        }
    audit(db, user, "view_health_summary", "Person", p.id, person_id=p.id, request=request)
    db.commit()
    return out


class AllergyIn(BaseModel):
    substance: str = Field(min_length=2)
    reaction: str | None = None
    severity: str | None = None
    confirmed: bool = False
    source: str | None = None


@router.post("/persons/{person_id}/allergies", status_code=201, tags=["clinical"])
@idempotent(201)
def add_allergy(person_id: str, body: AllergyIn, request: Request, user: User = Depends(require("encounter.write")),
                db: Session = Depends(get_db)):
    person_or_404(db, person_id)
    ensure_clinical_access(db, user, person_id, request, write=True)
    rec = get_or_create_record(db, person_id)
    a = Allergy(record_id=rec.id, recorded_by=user.id, **body.model_dump())
    rec.allergy_status = "recorded"
    db.add(a)
    audit(db, user, "allergy_added", "Allergy", a.id, person_id=person_id, request=request)
    return to_dict(a)


class RetractIn(BaseModel):
    reason: str = Field(min_length=5, description="Lý do gỡ (ghi nhầm, nhầm người…)")


@router.post("/allergies/{allergy_id}/retract", tags=["clinical"])
def retract_allergy(allergy_id: str, body: RetractIn, request: Request, user: User = Depends(require("encounter.write")),
                    db: Session = Depends(get_db)):
    """Gỡ dị ứng ghi nhầm. KHÔNG xóa vật lý (BR-02): bản ghi giữ lại kèm lý do/người/thời điểm; hết cảnh báo kê đơn.
    Dị ứng ĐÃ XÁC NHẬN chỉ bác sĩ (diagnosis.write) mới gỡ được – tránh vô tình bỏ cảnh báo an toàn."""
    a = db.get(Allergy, allergy_id)
    rec = db.get(HealthRecord, a.record_id) if a else None
    if not a or not rec:
        fail(404, "NOT_FOUND", "Không tìm thấy dị ứng")
    if not a.active:
        fail(409, "ALREADY_RETRACTED", "Dị ứng này đã được gỡ trước đó")
    ensure_clinical_access(db, user, rec.person_id, request, write=True)
    if a.confirmed and "diagnosis.write" not in perms_of(user):
        fail(403, "FORBIDDEN", "Dị ứng đã xác nhận chỉ bác sĩ được gỡ")
    a.active, a.inactive_reason, a.inactive_by, a.inactive_at = False, body.reason.strip(), user.id, utcnow()
    db.flush()
    if not db.scalars(select(Allergy.id).where(Allergy.record_id == rec.id, Allergy.active.is_(True))).first():
        rec.allergy_status = "unknown"      # hết dị ứng đang hiệu lực -> quay về "chưa ghi nhận" (KHÔNG tự coi là "không dị ứng")
    audit(db, user, "allergy_retracted", "Allergy", a.id, person_id=rec.person_id, reason=f"{a.substance}: {body.reason.strip()}"[:300], request=request)
    db.commit()
    return {"id": a.id, "active": False, "allergy_status": rec.allergy_status}


@router.post("/persons/{person_id}/allergy-status/none-confirmed", tags=["clinical"])
def confirm_no_allergy(person_id: str, request: Request, user: User = Depends(require("diagnosis.write")),
                       db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request, write=True)
    rec = get_or_create_record(db, person_id)
    has = db.scalars(select(Allergy.id).where(Allergy.record_id == rec.id, Allergy.active.is_(True))).first()
    if has:
        fail(409, "ALLERGY_EXISTS", "Đã có dị ứng được ghi nhận")
    rec.allergy_status = "none_confirmed"
    audit(db, user, "allergy_none_confirmed", "HealthRecord", rec.id, person_id=person_id, request=request)
    db.commit()
    return {"allergy_status": rec.allergy_status}


# ----------------------------------------------------------------- Encounter
class EncounterIn(BaseModel):
    person_id: str
    type: str
    reason: str | None = None
    priority: str = Field(default="routine", pattern="^(routine|urgent|emergent)$")   # WF-02: phân loại ưu tiên khi nhận yêu cầu khám
    occurred_at: datetime | None = None
    appointment_id: str | None = None
    late_entry_reason: str | None = None


@router.post("/encounters", tags=["clinical"])
def create_encounter(body: EncounterIn, request: Request, user: User = Depends(require("encounter.write")),
                     db: Session = Depends(get_db)):
    def work():
        if body.type not in ENC_TYPES:
            fail(422, "BAD_TYPE", f"Loại lượt khám hợp lệ: {sorted(ENC_TYPES)}")
        person_or_404(db, body.person_id)
        ensure_clinical_access(db, user, body.person_id, request)
        stay = active_stay(db, body.person_id, user.facility_id)
        if not stay:
            fail(409, "NO_ACTIVE_STAY", "Người này không có đợt tiếp nhận đang hiệu lực tại cơ sở của bạn")
        now = utcnow()
        occ = norm_dt(body.occurred_at) or now
        if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
            fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
        if body.type == "emergency" and (now - occ) > timedelta(minutes=config.LATE_ENTRY_MIN) \
                and not body.late_entry_reason:
            fail(422, "LATE_ENTRY_REASON", "Ghi nhận muộn cần nêu lý do (late_entry_reason)")
        if body.type == "initial" and db.scalars(select(Encounter.id).where(
                Encounter.stay_id == stay.id, Encounter.type == "initial",
                Encounter.status != "cancelled")).first():
            fail(409, "INITIAL_EXISTS", "Đợt tiếp nhận này đã có lượt khám ban đầu")
        # BR-03: thời điểm khám không thể trước ngày bắt đầu đợt tiếp nhận hiện tại (so theo ngày giờ địa phương như start_date)
        if occ.replace(tzinfo=timezone.utc).astimezone().date() < stay.start_date:
            fail(422, "BEFORE_STAY", "occurred_at không được trước ngày bắt đầu đợt tiếp nhận hiện tại",
                 stay_start_date=str(stay.start_date))
        if body.appointment_id:
            ap = lock_row(db, Appointment, body.appointment_id)   # tuần tự hóa: hai lượt khám cùng lúc cho một lịch
            if not ap or ap.person_id != body.person_id or ap.facility_id != user.facility_id \
                    or ap.status not in ("scheduled", "due"):
                fail(409, "BAD_APPOINTMENT", "Lịch hẹn không hợp lệ hoặc đã xử lý")
            busy = db.scalars(select(Encounter.id).where(Encounter.appointment_id == ap.id,
                                                         Encounter.status.in_(tuple(EDITABLE)))).first()
            if busy:
                fail(409, "APPOINTMENT_IN_PROGRESS", "Lịch hẹn này đã có lượt khám đang mở", encounter_id=busy)
        e = Encounter(person_id=body.person_id, stay_id=stay.id, facility_id=user.facility_id, type=body.type,
                      reason=body.reason, priority="emergent" if body.type == "emergency" else body.priority, occurred_at=occ, recorded_at=now, appointment_id=body.appointment_id,
                      late_entry_reason=body.late_entry_reason, created_by=user.id)
        db.add(e)
        audit(db, user, "encounter_created", "Encounter", e.id, person_id=e.person_id, request=request)
        return 201, to_dict(e)
    return run_idempotent(db, request, user, body.model_dump(), work)


@router.get("/persons/{person_id}/encounters", tags=["clinical"])
def list_encounters(person_id: str, request: Request, user: User = Depends(require("clinical.read")),
                    db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request)
    audit(db, user, "view_encounters", "Person", person_id, person_id=person_id, request=request)
    db.commit()
    return [to_dict(e) for e in db.scalars(select(Encounter).where(Encounter.person_id == person_id)
                                           .order_by(Encounter.occurred_at.desc()))]


@router.get("/encounters/{enc_id}", tags=["clinical"])
def get_encounter(enc_id: str, request: Request, user: User = Depends(require("clinical.read")),
                  db: Session = Depends(get_db)):
    e = load_encounter(db, user, enc_id, request)
    audit(db, user, "view_encounter", "Encounter", e.id, person_id=e.person_id, request=request)
    db.commit()
    q = lambda m: [to_dict(x) for x in db.scalars(select(m).where(m.encounter_id == e.id))]  # noqa: E731
    from ..models import Person
    person = db.get(Person, e.person_id)
    rec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == e.person_id)).first()
    return {**to_dict(e), "person_name": person.full_name, "person_external_id": person.external_id,
            "allergy_status": rec.allergy_status if rec else "unknown",
            "allergies": [to_dict(a) for a in db.scalars(select(Allergy).where(
                Allergy.record_id == (rec.id if rec else ""), Allergy.active.is_(True)))],
            # WF-02 bước 3: tiền sử/dị ứng, thuốc đang dùng, vấn đề sức khỏe mở hiển thị ngay khi khám
            "context": {
                "active_medications": [{"id": m.id, "drug_name": m.drug_name, "dose": m.dose, "frequency": m.frequency, "status": m.status}
                                      for m in db.scalars(select(MedicationOrder).where(MedicationOrder.person_id == e.person_id,
                                                                                         MedicationOrder.status.in_(("confirmed", "active"))))],
                "open_problems": [{"id": x.id, "name": x.name, "code": x.code, "effective_from": x.effective_from}
                                  for x in db.scalars(select(HealthProblem).where(HealthProblem.person_id == e.person_id, HealthProblem.status == "active"))]}, "observations": q(Observation), "diagnoses": q(Diagnosis), "orders": q(ClinicalOrder),
            "medication_orders": q(MedicationOrder), "addenda": q(EncounterAddendum), "referrals": [
                to_dict(r) for r in db.scalars(select(Referral).where(Referral.encounter_id == e.id))]}


class EncounterPatch(BaseModel):
    reason: str | None = None
    summary: str | None = None
    expected_version: int | None = None


@router.patch("/encounters/{enc_id}", tags=["clinical"])
def patch_encounter(enc_id: str, body: EncounterPatch, request: Request,
                    user: User = Depends(require("encounter.write")), db: Session = Depends(get_db)):
    e = load_encounter(db, user, enc_id, request, write=True)
    require_editable(e)
    bump_version(e, body.expected_version)
    for k in ("reason", "summary"):
        if getattr(body, k) is not None:
            setattr(e, k, getattr(body, k))
    audit(db, user, "encounter_updated", "Encounter", e.id, person_id=e.person_id, request=request)
    db.commit()
    return to_dict(e)


class TransitionIn(BaseModel):
    to: str
    reason: str | None = None
    expected_version: int | None = None


@router.post("/encounters/{enc_id}/transition", tags=["clinical"])
def transition_encounter(enc_id: str, body: TransitionIn, request: Request,
                         user: User = Depends(require("encounter.write")), db: Session = Depends(get_db)):
    e = load_encounter(db, user, enc_id, request, write=True)
    e = lock_row(db, Encounter, e.id)   # tuần tự hóa các thao tác chuyển trạng thái đồng thời trên cùng lượt khám
    if body.to not in ENC_TRANS.get(e.status, set()):
        fail(409, "BAD_TRANSITION", f"Không thể chuyển '{e.status}' -> '{body.to}'")
    perms = perms_of(user)
    if body.to == "completed":
        if "encounter.complete" not in perms:
            fail(403, "FORBIDDEN", "Chỉ bác sĩ/y sĩ có thẩm quyền được hoàn tất lượt khám")
        open_orders = db.scalars(select(ClinicalOrder).where(ClinicalOrder.encounter_id == e.id,
                                                              ClinicalOrder.status == "open")).all()
        if open_orders:
            fail(409, "OPEN_ORDERS", "Còn chỉ định chưa có kết quả – chuyển sang 'awaiting_results' để tiếp tục theo dõi",
                 open_order_ids=[o.id for o in open_orders])
        drafts = db.scalars(select(MedicationOrder).where(MedicationOrder.encounter_id == e.id, MedicationOrder.status == "draft")).all()
        if drafts:  # đơn nháp mà lượt khám đã khóa thì không thể xác nhận nữa -> phải xử lý trước khi hoàn tất
            fail(409, "DRAFT_ORDERS", "Còn đơn thuốc nháp chưa xác nhận – hãy xác nhận hoặc hủy trước khi hoàn tất lượt khám",
                 draft_order_ids=[o.id for o in drafts], drugs=[o.drug_name for o in drafts])
        e.completed_at, e.completed_by = utcnow(), user.id
        e.practitioner_id = e.practitioner_id or user.id
        if e.type == "initial" and e.stay_id:
            stay = db.get(CustodyStay, e.stay_id)
            if stay and stay.status == "received":
                stay.status, stay.initial_exam_completed_at = "managed", utcnow()
        if e.appointment_id:
            # lịch đã hoàn tất/hoãn/không thực hiện (vd đợt khám đã khóa) giữ nguyên – complete_appointment tự kiểm tra
            ap = lock_row(db, Appointment, e.appointment_id)
            if ap:
                complete_appointment(db, ap, e.id)
    if body.to == "cancelled":
        if not body.reason:
            fail(422, "REASON_REQUIRED", "Hủy lượt khám cần nêu lý do")
        live = db.scalars(select(MedicationOrder).where(MedicationOrder.encounter_id == e.id,
                                                          MedicationOrder.status.in_(("draft", "confirmed", "active")))).all()
        given = [o for o in live if db.scalars(select(DispenseEvent.id).where(DispenseEvent.order_id == o.id).limit(1)).first()]
        if given:
            fail(409, "ORDERS_DISPENSED", "Có đơn thuốc đã được cấp phát – phải ngừng đơn (kèm lý do) trước khi hủy lượt khám",
                 drugs=[o.drug_name for o in given])
        open_refs = db.scalars(select(Referral).where(Referral.encounter_id == e.id,
                                                       Referral.status.notin_(("draft", "cancelled", "completed")))).all()
        if open_refs:
            fail(409, "OPEN_REFERRALS", "Còn đề nghị chuyển viện đang xử lý – hãy hủy/hoàn thành đề nghị trước khi hủy lượt khám")
        # hủy lượt khám = hủy các chỉ định/đơn phát sinh từ nó (không xóa, ghi lý do)
        for o in live:
            o.status, o.stop_reason = "cancelled", f"Lượt khám bị hủy: {body.reason}"
        for c in db.scalars(select(ClinicalOrder).where(ClinicalOrder.encounter_id == e.id, ClinicalOrder.status == "open")):
            c.status, c.cancel_reason = "cancelled", f"Lượt khám bị hủy: {body.reason}"
        for r in db.scalars(select(Referral).where(Referral.encounter_id == e.id, Referral.status == "draft")):
            r.status = "cancelled"
        e.cancel_reason = body.reason
    if body.to == "in_progress" and "diagnosis.write" in perms:
        e.practitioner_id = e.practitioner_id or user.id
    bump_version(e, body.expected_version)
    old, e.status = e.status, body.to
    audit(db, user, f"encounter_{body.to}", "Encounter", e.id, person_id=e.person_id, reason=f"{old}->{body.to}",
          request=request)
    db.commit()
    return to_dict(e)


class AddendumIn(BaseModel):
    text: str = Field(min_length=3)
    reason: str = Field(min_length=3)


@router.post("/encounters/{enc_id}/addenda", status_code=201, tags=["clinical"])
@idempotent(201)
def add_addendum(enc_id: str, body: AddendumIn, request: Request, user: User = Depends(require("encounter.complete")),
                 db: Session = Depends(get_db)):
    """UAT-10 / BR-02: sau khi hoàn tất, chỉ điều chỉnh bằng addendum có version + audit; dữ liệu gốc giữ nguyên."""
    e = load_encounter(db, user, enc_id, request, write=True)
    if e.status != "completed":
        fail(409, "NOT_COMPLETED", "Addendum chỉ dùng cho lượt khám đã hoàn tất")
    e.version += 1
    a = EncounterAddendum(encounter_id=e.id, text=body.text, reason=body.reason, version_after=e.version,
                          author_id=user.id)
    db.add(a)
    audit(db, user, "encounter_addendum", "Encounter", e.id, person_id=e.person_id, reason=body.reason, request=request)
    return to_dict(a)


# ----------------------------------------------------------------- Observation / Diagnosis / Orders
VITAL_LIMITS = {   # (min, max, đơn vị chuẩn) – ngưỡng bất khả thi về sinh lý, dùng để chặn lỗi nhập liệu
    "Mạch": (20, 250, "lần/phút"), "Huyết áp tâm thu": (40, 300, "mmHg"), "Huyết áp tâm trương": (20, 200, "mmHg"),
    "Nhiệt độ": (30, 45, "°C"), "SpO2": (30, 100, "%"), "Nhịp thở": (4, 80, "lần/phút"),
    "Cân nặng": (2, 400, "kg"), "Chiều cao": (30, 250, "cm"), "Đường huyết": (0.5, 70, "mmol/L"),
}
BP_COMBINED = "Huyết áp"   # nhập gộp "tâm thu/tâm trương", vd 120/80 mmHg
UNIT_ALIASES = {   # đơn vị chuẩn -> cách viết tương đương được chấp nhận (danh mục đơn vị dùng "bpm", "C")
    "lần/phút": ("bpm", "l/p", "nhịp/phút"), "°C": ("C", "độ C", "oC"),
}
# Ngưỡng CẢNH BÁO lâm sàng (khác ngưỡng khả dĩ ở trên): vượt ngưỡng -> tạo cảnh báo "abnormal_result" cho bác sĩ (sơ đồ B)
ABNORMAL_RULES = {
    "SpO2": lambda v: v < 90,
    "Huyết áp tâm thu": lambda v: v < 90 or v >= 180,
    "Nhiệt độ": lambda v: v < 35 or v >= 39,
    "Mạch": lambda v: v < 40 or v > 130,
    "Đường huyết": lambda v: v < 3.9 or v >= 16.7,
}


def _norm_key(s: str) -> str:
    """Khóa so khớp tên chỉ số/đơn vị: NFC, gộp khoảng trắng, không phân biệt hoa thường, bỏ dấu tiếng Việt."""
    s = " ".join(unicodedata.normalize("NFC", s).split()).casefold().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


_VITAL_BY_KEY = {_norm_key(k): k for k in (*VITAL_LIMITS, BP_COMBINED)}
_UNIT_KEYS = {u: {_norm_key(u), *(_norm_key(a) for a in UNIT_ALIASES.get(u, ()))} for u in {x[2] for x in VITAL_LIMITS.values()}}


def _check_vital(canon: str, value: str, unit: str) -> tuple[float | None, dict[str, float]]:
    """Kiểm tra chỉ số đã biết: đúng đơn vị, là số, nằm trong ngưỡng khả dĩ. Trả (giá trị số lưu, {loại: giá trị} để xét cảnh báo)."""
    want = VITAL_LIMITS["Huyết áp tâm thu"][2] if canon == BP_COMBINED else VITAL_LIMITS[canon][2]
    if _norm_key(unit) not in _UNIT_KEYS[want]:
        fail(422, "OBS_BAD_UNIT", f"“{canon}” phải đo bằng đơn vị {want}", expected_unit=want)
    parts = {"Huyết áp tâm thu": None, "Huyết áp tâm trương": None} if canon == BP_COMBINED else {canon: None}
    raw = value.split("/") if canon == BP_COMBINED else [value]
    if len(raw) != len(parts):
        fail(422, "OBS_NOT_NUMERIC", f"“{canon}” phải nhập dạng tâm thu/tâm trương, vd 120/80")
    for k, s in zip(parts, raw):
        try:
            parts[k] = float(s.strip().replace(",", "."))
        except ValueError:
            fail(422, "OBS_NOT_NUMERIC", f"“{canon}” phải là số")
        lo, hi, u = VITAL_LIMITS[k]
        if not (lo <= parts[k] <= hi):
            fail(422, "OBS_OUT_OF_RANGE", f"“{k}” = {s.strip()} nằm ngoài ngưỡng khả dĩ ({lo}–{hi} {u}); kiểm tra lại số liệu nhập")
    if canon == BP_COMBINED and parts["Huyết áp tâm thu"] <= parts["Huyết áp tâm trương"]:
        fail(422, "OBS_OUT_OF_RANGE", "Huyết áp tâm thu phải lớn hơn tâm trương")
    return (None if canon == BP_COMBINED else parts[canon]), parts


class ObsIn(BaseModel):
    type: str = Field(min_length=1)
    value: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    occurred_at: datetime | None = None
    source: str = "manual"


@router.post("/encounters/{enc_id}/observations", status_code=201, tags=["clinical"])
@idempotent(201)
def add_observation(enc_id: str, body: ObsIn, request: Request, user: User = Depends(require("observation.write")),
                    db: Session = Depends(get_db)):
    e = load_encounter(db, user, enc_id, request, write=True)
    require_editable(e)
    now = utcnow()
    occ = norm_dt(body.occurred_at) or now
    if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
        fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
    typ, unit, checked = body.type.strip(), body.unit.strip(), {}
    canon = _VITAL_BY_KEY.get(_norm_key(typ))
    if canon:   # chỉ số đã biết (không phân biệt hoa thường/dấu/khoảng trắng): lưu tên + đơn vị chuẩn
        num, checked = _check_vital(canon, body.value, unit)
        typ, unit = canon, VITAL_LIMITS["Huyết áp tâm thu" if canon == BP_COMBINED else canon][2]
    else:
        try:
            num = float(body.value.replace(",", "."))
        except ValueError:
            num = None
    o = Observation(encounter_id=e.id, person_id=e.person_id, type=typ, value=body.value.strip(), numeric_value=num,
                    unit=unit, source=body.source, measured_by=user.id, occurred_at=occ, recorded_at=now)
    db.add(o)
    audit(db, user, "observation_added", "Observation", o.id, person_id=e.person_id, request=request)
    abnormal = [k for k, v in checked.items() if k in ABNORMAL_RULES and ABNORMAL_RULES[k](v)]
    if abnormal:
        _abnormal_alert(db, user, e, o, abnormal)
    return to_dict(o)


def _abnormal_alert(db: Session, user: User, e: Encounter, o: Observation, kinds: list[str]) -> None:
    """Sơ đồ B: cảnh báo khi kết quả bất thường – một cảnh báo cho mỗi lần đo; nội dung không nêu giá trị đo."""
    what = ", ".join(kinds)
    al = Alert(person_id=e.person_id, facility_id=e.facility_id, kind="abnormal_result", dedupe_key=f"abn:{o.id}",
               message=f"Chỉ số {what} vượt ngưỡng cảnh báo – cần bác sĩ đánh giá", owner_id=e.practitioner_id)
    db.add(al)
    emit(db, kind="clinical.abnormal", category="medication", severity="critical", facility_id=e.facility_id, actor=user,
         perms=("diagnosis.write",), user_ids=(e.practitioner_id,) if e.practitioner_id else (),
         title="Chỉ số sinh hiệu bất thường cần đánh giá", plain="Có chỉ số sinh hiệu vượt ngưỡng cảnh báo – cần bác sĩ đánh giá.",
         named=f"{person_name(db, e.person_id)}: chỉ số {what} vượt ngưỡng cảnh báo – cần đánh giá.",
         link_page="exam", link_ref=e.id, person_id=e.person_id, dedupe=f"alert:{al.id}:new")


class DxIn(BaseModel):
    code: str | None = None
    text: str = Field(min_length=2)
    kind: str = Field(default="preliminary", pattern="^(preliminary|final)$")


@router.post("/encounters/{enc_id}/diagnoses", status_code=201, tags=["clinical"])
@idempotent(201)
def add_diagnosis(enc_id: str, body: DxIn, request: Request, user: User = Depends(require("diagnosis.write")),
                  db: Session = Depends(get_db)):
    e = load_encounter(db, user, enc_id, request, write=True)
    require_editable(e)
    d = Diagnosis(encounter_id=e.id, person_id=e.person_id, diagnosed_by=user.id, **body.model_dump())
    db.add(d)
    audit(db, user, "diagnosis_added", "Diagnosis", d.id, person_id=e.person_id, request=request)
    return to_dict(d)


class OrderIn(BaseModel):
    kind: str = Field(pattern="^(lab|procedure)$")
    description: str = Field(min_length=2)


@router.post("/encounters/{enc_id}/orders", status_code=201, tags=["clinical"])
@idempotent(201)
def add_clinical_order(enc_id: str, body: OrderIn, request: Request, user: User = Depends(require("order.write")),
                       db: Session = Depends(get_db)):
    e = load_encounter(db, user, enc_id, request, write=True)
    require_editable(e)
    o = ClinicalOrder(encounter_id=e.id, person_id=e.person_id, ordered_by=user.id, **body.model_dump())
    db.add(o)
    audit(db, user, "clinical_order_created", "ClinicalOrder", o.id, person_id=e.person_id, request=request)
    return to_dict(o)


class ResultIn(BaseModel):
    result_text: str = Field(min_length=1)


@router.post("/orders/{order_id}/result", tags=["clinical"])
def record_result(order_id: str, body: ResultIn, request: Request, user: User = Depends(require("observation.write")),
                  db: Session = Depends(get_db)):
    o = db.get(ClinicalOrder, order_id)
    if not o:
        fail(404, "NOT_FOUND", "Không tìm thấy chỉ định")
    e = load_encounter(db, user, o.encounter_id, request, write=True)
    if o.status != "open":
        fail(409, "ORDER_CLOSED", "Chỉ định đã có kết quả hoặc đã hủy")
    o.status, o.result_text, o.resulted_by, o.resulted_at = "resulted", body.result_text, user.id, utcnow()
    audit(db, user, "clinical_order_resulted", "ClinicalOrder", o.id, person_id=e.person_id, request=request)
    emit(db, kind="clinical.resulted", category="medication", facility_id=e.facility_id, actor=user, user_ids=(o.ordered_by,),
         title="Có kết quả xét nghiệm / thủ thuật", plain=f"Đã có kết quả: {o.description}.", named=f"{person_name(db, e.person_id)}: đã có kết quả {o.description}.",
         link_page="exam", link_ref=e.id, person_id=e.person_id, dedupe=f"clin:{o.id}:result")
    db.commit()
    return to_dict(o)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/orders/{order_id}/cancel", tags=["clinical"])
def cancel_clinical_order(order_id: str, body: CancelIn, request: Request, user: User = Depends(require("order.write")),
                          db: Session = Depends(get_db)):
    o = db.get(ClinicalOrder, order_id)
    if not o:
        fail(404, "NOT_FOUND", "Không tìm thấy chỉ định")
    e = load_encounter(db, user, o.encounter_id, request, write=True)
    if o.status != "open":
        fail(409, "ORDER_CLOSED", "Chỉ định không còn ở trạng thái mở")
    o.status, o.cancel_reason = "cancelled", body.reason
    audit(db, user, "clinical_order_cancelled", "ClinicalOrder", o.id, person_id=e.person_id, reason=body.reason,
          request=request)
    db.commit()
    return to_dict(o)
