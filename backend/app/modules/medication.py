"""M05/M06: kê đơn – cấp phát – xác nhận dùng thuốc (WF-03).

Bất biến cốt lõi: MedicationOrder ≠ DispenseEvent ≠ AdministrationEvent.
"""
import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..db import get_db, lock_row
from ..deps import ensure_clinical_access, require
from ..idempotency import idempotent, run_idempotent
from ..notify import emit, person_name
from ..models import (AdministrationEvent, Allergy, CatalogItem, DispenseEvent, Encounter, HealthRecord,
                      MedicationOrder, Person, User)
from ..utils import bump_version, fail, norm_dt, to_dict, utcnow
from .clinical import load_encounter, require_editable

router = APIRouter()
ACTIVE = ("confirmed", "active")
EPS = 1e-9   # sai số số thực khi so sánh số lượng


def _finite(d: dict) -> dict:
    """Số lượng tính ra từ dữ liệu cũ Infinity/NaN không mã hóa được JSON -> trả null thay vì lỗi 500."""
    return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()}


def course_order_ids(db: Session, o: MedicationOrder) -> list[str]:
    """Đơn hiện tại + mọi phiên bản trước (parent_order_id) – cùng một liệu trình."""
    ids, pid = [o.id], o.parent_order_id
    while pid and pid not in ids:
        ids.append(pid)
        pid = db.scalar(select(MedicationOrder.parent_order_id).where(MedicationOrder.id == pid))
    return ids


def dispense_totals(db: Session, order: MedicationOrder) -> dict:
    """Số lượng kê của phiên bản là TỔNG liệu trình: phần đã cấp ròng ở các phiên bản trước được trừ tiếp (không cấp lại từ đầu)."""
    evs = db.scalars(select(DispenseEvent).where(DispenseEvent.order_id.in_(course_order_ids(db, order)))).all()
    net = round(sum(e.quantity if e.kind == "dispense" else -e.quantity for e in evs), 6)
    prior = round(sum(e.quantity if e.kind == "dispense" else -e.quantity for e in evs if e.order_id != order.id), 6)
    status = "none" if net <= 0 else ("full" if net >= order.quantity_prescribed - EPS else "partial")
    return {"dispensed_net": net, "dispensed_prior_versions": prior,
            "remaining": max(round(order.quantity_prescribed - net, 6), 0), "dispense_status": status}


def order_out(db: Session, o: MedicationOrder) -> dict:
    return {**to_dict(o), **_finite(dispense_totals(db, o))}


# Nhóm thuốc để cảnh báo dị ứng chéo (tên hoạt chất/nhóm, không dấu, chữ thường). Danh sách tối thiểu – mở rộng qua danh mục khi cần.
DRUG_CLASSES = {
    "Penicillin / beta-lactam": ("penicillin", "amoxicillin", "ampicillin", "oxacillin", "cloxacillin", "piperacillin",
                                 "beta-lactam", "beta lactam", "augmentin", "amoxiclav"),
    "Cephalosporin": ("cephalosporin", "cefa", "cefu", "cefo", "cefi", "cefp", "ceftri", "cephalexin", "cefalexin"),
    "Sulfonamide": ("sulfa", "sulfonamid", "cotrimoxazol", "co-trimoxazol", "bactrim", "sulfamethoxazol"),
    "NSAID": ("nsaid", "ibuprofen", "diclofenac", "naproxen", "aspirin", "meloxicam", "ketoprofen", "indomethacin"),
    "Quinolone": ("quinolone", "floxacin"),
    "Macrolide": ("macrolid", "erythromycin", "azithromycin", "clarithromycin"),
}
# Penicillin và cephalosporin có thể dị ứng chéo thấp nhưng có thật: chỉ cảnh báo khi cùng nhóm, không tự suy rộng.


def _classes_of(text: str) -> set[str]:
    t = text.lower()
    return {c for c, keys in DRUG_CLASSES.items() if any(k in t for k in keys)}


SEVERE = ("severe", "nặng", "nang", "phản vệ", "phan ve", "anaphyla", "đe dọa", "nguy hiểm")


def allergy_warnings(db: Session, person_id: str, drug_name: str) -> list[dict]:
    warns = []
    rec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == person_id)).first()
    if not rec:
        return warns
    dn = drug_name.lower()
    drug_classes = _classes_of(dn)
    for a in db.scalars(select(Allergy).where(Allergy.record_id == rec.id, Allergy.active.is_(True))):
        s = a.substance.lower()
        tag = " (đã xác nhận)" if a.confirmed else ""
        # dị ứng đã xác nhận hoặc mức độ nặng: bắt buộc xác nhận lại khi phát sinh sau lúc kê đơn
        meta = {"allergy_id": a.id, "severe": a.confirmed or any(k in (a.severity or "").lower() for k in SEVERE)}
        if s in dn or dn in s:
            warns.append({"type": "allergy", "message": f"Dị ứng đã ghi nhận với '{a.substance}'" + tag, **meta})
        else:
            shared = drug_classes & _classes_of(s)
            if shared:
                warns.append({"type": "allergy", "message": f"Dị ứng '{a.substance}'{tag} – cùng nhóm {sorted(shared)[0]} với '{drug_name}' (nguy cơ dị ứng chéo)",
                              **meta})
    return warns


def compute_warnings(db: Session, person_id: str, drug_name: str, drug_code: str | None,
                     exclude_ids: set[str]) -> list[dict]:
    warns = allergy_warnings(db, person_id, drug_name)
    dn = drug_name.lower()
    for o in db.scalars(select(MedicationOrder).where(MedicationOrder.person_id == person_id,
                                                      MedicationOrder.status.in_(ACTIVE))):
        if o.id in exclude_ids:
            continue
        if o.drug_name.lower() == dn or (drug_code and o.drug_code == drug_code):
            warns.append({"type": "duplicate", "message": f"Đã có đơn đang hiệu lực cùng thuốc ({o.drug_name})",
                          "order_id": o.id})
    return warns


def new_allergy_warnings(db: Session, o: MedicationOrder) -> list[dict]:
    """Dị ứng ghi nhận SAU khi bác sĩ xác nhận đơn (chưa có trong cảnh báo đã xử lý của đơn) – đánh giá lại theo dị ứng hiện hành."""
    known = {w.get("allergy_id") for w in (o.warnings or []) if w.get("type") == "allergy"}
    return [{**w, "new": True} for w in allergy_warnings(db, o.person_id, o.drug_name) if w["allergy_id"] not in known]


def live_warnings(db: Session, o: MedicationOrder) -> list[dict]:
    return [*(o.warnings or []), *new_allergy_warnings(db, o)]


def require_allergy_ack(db: Session, o: MedicationOrder, ack: bool, note: str | None, user: User,
                        request: Request, action: str) -> list[dict]:
    """Trước khi cấp phát/cho dùng: dị ứng mới đã xác nhận/mức nặng -> phải xác nhận đã xem + ghi nhận xử lý (như khi bác sĩ xác nhận đơn).
    Cảnh báo đã xác nhận được lưu vào đơn để các lần sau không hỏi lại; trả về các cảnh báo mới (để hiển thị)."""
    new = new_allergy_warnings(db, o)
    if not any(w["severe"] for w in new):
        return new
    if not ack or not (note and len(note.strip()) >= 3):
        fail(409, "WARNINGS_UNACKNOWLEDGED", "Có dị ứng mới ghi nhận sau khi kê đơn – cần xác nhận đã xem và ghi nhận xử lý "
                                             "(nên trao đổi với bác sĩ điều trị)", warnings=new)
    at = utcnow().isoformat()
    o.warnings = [*(o.warnings or []), *({**w, "acknowledged_by": user.id, "ack_note": note, "acknowledged_at": at} for w in new)]
    audit(db, user, "medication_warning_acknowledged", "MedicationOrder", o.id, person_id=o.person_id,
          reason=f"{action} – {[w['message'] for w in new]}: {note}", request=request)
    return new


class OrderIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    drug_code: str | None = None
    drug_name: str = Field(min_length=2)
    strength: str | None = None
    dose: str = Field(min_length=1)
    route: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    start_date: date
    duration_days: int = Field(gt=0, le=3650)
    quantity_prescribed: float = Field(gt=0)
    instructions: str | None = None
    supervised: bool = False


def _check_catalog(db: Session, code: str | None):
    if code and not db.scalars(select(CatalogItem.id).where(CatalogItem.catalog == "drug", CatalogItem.code == code,
                                                            CatalogItem.active.is_(True))).first():
        fail(422, "UNKNOWN_DRUG_CODE", "Mã thuốc không có trong danh mục hiện hành")


@router.post("/encounters/{enc_id}/medication-orders", status_code=201, tags=["medication"])
def create_order(enc_id: str, body: OrderIn, request: Request, user: User = Depends(require("medorder.write")),
                 db: Session = Depends(get_db)):
    def work():
        e = load_encounter(db, user, enc_id, request, write=True)
        require_editable(e)
        _check_catalog(db, body.drug_code)
        o = MedicationOrder(encounter_id=e.id, person_id=e.person_id, facility_id=e.facility_id, ordered_by=user.id,
                            **body.model_dump())
        o.warnings = compute_warnings(db, e.person_id, o.drug_name, o.drug_code, set())
        db.add(o)
        audit(db, user, "medication_order_created", "MedicationOrder", o.id, person_id=e.person_id, request=request)
        return 201, order_out(db, o)
    return run_idempotent(db, request, user, {"enc": enc_id, **body.model_dump()}, work)


class OrderPatch(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    duration_days: int | None = Field(default=None, gt=0)
    quantity_prescribed: float | None = Field(default=None, gt=0)
    instructions: str | None = None
    supervised: bool | None = None
    expected_version: int | None = None


def _load_order(db: Session, user: User, order_id: str, request: Request, write: bool = False) -> MedicationOrder:
    """write=True: khóa dòng đơn đến hết giao dịch (tuần tự hóa kiểm tra số lượng/trạng thái rồi ghi) và chỉ cơ sở
    đang quản lý người bệnh được ghi (break-glass/cơ sở cũ chỉ xem)."""
    o = lock_row(db, MedicationOrder, order_id) if write else db.get(MedicationOrder, order_id)
    if not o:
        fail(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn thuốc")
    ensure_clinical_access(db, user, o.person_id, request, write=write)
    if write and o.facility_id != user.facility_id:
        fail(403, "FACILITY_SCOPE", "Đơn thuộc cơ sở khác")
    return o


@router.get("/medication-orders/{order_id}", tags=["medication"])
def get_order(order_id: str, request: Request, user: User = Depends(require("clinical.read")),
              db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request)
    audit(db, user, "view_medication_order", "MedicationOrder", o.id, person_id=o.person_id, request=request)
    db.commit()
    return {**order_out(db, o), "warnings": live_warnings(db, o),
            "dispenses": [to_dict(d) for d in db.scalars(select(DispenseEvent).where(
                DispenseEvent.order_id == o.id).order_by(DispenseEvent.occurred_at))],
            "administrations": [to_dict(a) for a in db.scalars(select(AdministrationEvent).where(
                AdministrationEvent.order_id == o.id).order_by(AdministrationEvent.occurred_at))]}


@router.get("/persons/{person_id}/medication-orders", tags=["medication"])
def list_orders(person_id: str, request: Request, user: User = Depends(require("clinical.read")),
                db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request)
    return [order_out(db, o) for o in db.scalars(select(MedicationOrder).where(
        MedicationOrder.person_id == person_id).order_by(MedicationOrder.recorded_at.desc()))]


@router.patch("/medication-orders/{order_id}", tags=["medication"])
def patch_order(order_id: str, body: OrderPatch, request: Request, user: User = Depends(require("medorder.write")),
                db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request, write=True)
    if o.status != "draft":
        fail(409, "ORDER_LOCKED", "Đơn đã xác nhận không sửa âm thầm – dùng /revise để tạo phiên bản mới")
    bump_version(o, body.expected_version)
    for k, v in body.model_dump(exclude={"expected_version"}, exclude_none=True).items():
        setattr(o, k, v)
    audit(db, user, "medication_order_updated", "MedicationOrder", o.id, person_id=o.person_id, request=request)
    db.commit()
    return order_out(db, o)


class ConfirmIn(BaseModel):
    acknowledge_warnings: bool = False
    ack_note: str | None = None


@router.post("/medication-orders/{order_id}/confirm", tags=["medication"])
def confirm_order(order_id: str, body: ConfirmIn, request: Request, user: User = Depends(require("medorder.confirm")),
                  db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request, write=True)
    if o.status != "draft":
        fail(409, "NOT_DRAFT", "Chỉ đơn nháp mới xác nhận được")
    e = db.get(Encounter, o.encounter_id)
    require_editable(e)
    parent = lock_row(db, MedicationOrder, o.parent_order_id) if o.parent_order_id else None
    if parent and parent.status not in ACTIVE:  # bản gốc đã dừng/hoàn thành -> không để bản điều chỉnh "hồi sinh" thuốc
        fail(409, "PARENT_NOT_ACTIVE", f"Đơn gốc đang ở trạng thái '{parent.status}' – không xác nhận bản điều chỉnh",
             parent_status=parent.status)
    # UAT-02: cảnh báo hỗ trợ, KHÔNG thay quyết định bác sĩ -> bác sĩ phải xác nhận đã đọc + ghi nhận xử lý
    warns = compute_warnings(db, o.person_id, o.drug_name, o.drug_code, {o.id, o.parent_order_id or ""})
    o.warnings = warns
    if warns:
        if not body.acknowledge_warnings or not (body.ack_note and len(body.ack_note.strip()) >= 3):
            fail(409, "WARNINGS_UNACKNOWLEDGED", "Có cảnh báo – bác sĩ cần xác nhận và ghi nhận xử lý", warnings=warns)
        o.warning_ack_note = body.ack_note
        audit(db, user, "medication_warning_acknowledged", "MedicationOrder", o.id, person_id=o.person_id,
              reason=f"{[w['type'] for w in warns]}: {body.ack_note}", request=request)
    o.status = "active" if o.start_date <= date.today() else "confirmed"
    o.confirmed_by, o.confirmed_at = user.id, utcnow()
    if parent:
        parent.status = "superseded"
    audit(db, user, "medication_order_confirmed", "MedicationOrder", o.id, person_id=o.person_id, request=request)
    emit(db, kind="medication.confirmed", category="medication", facility_id=o.facility_id, actor=user, perms=("dispense.write",),
         title="Đơn thuốc mới chờ cấp phát", plain=f"{o.drug_name} – số lượng kê {o.quantity_prescribed:g}.",
         named=f"{person_name(db, o.person_id)} – {o.drug_name}, số lượng kê {o.quantity_prescribed:g}.", link_page="pharmacy", link_ref=o.id,
         person_id=o.person_id, dedupe=f"rx:{o.id}:confirmed")
    db.commit()
    return order_out(db, o)


class ReviseIn(OrderPatch):
    reason: str = Field(min_length=3)
    encounter_id: str | None = None


@router.post("/medication-orders/{order_id}/revise", status_code=201, tags=["medication"])
def revise_order(order_id: str, body: ReviseIn, request: Request, user: User = Depends(require("medorder.write")),
                 db: Session = Depends(get_db)):
    """Điều chỉnh đơn đã xác nhận = tạo phiên bản mới (nháp) tham chiếu bản cũ."""
    p = _load_order(db, user, order_id, request, write=True)
    if body.expected_version is not None and p.version != body.expected_version:
        fail(409, "VERSION_CONFLICT", "Dữ liệu đã được người khác thay đổi, hãy tải lại.", current_version=p.version)
    if p.status not in ACTIVE:
        fail(409, "NOT_REVISABLE", "Chỉ đơn đã xác nhận/đang hiệu lực mới điều chỉnh")
    if db.scalars(select(MedicationOrder.id).where(MedicationOrder.parent_order_id == p.id,
                                                   MedicationOrder.status == "draft")).first():
        fail(409, "REVISION_PENDING", "Đã có bản điều chỉnh đang chờ xác nhận")
    e = load_encounter(db, user, body.encounter_id or p.encounter_id, request, write=True)
    if e.person_id != p.person_id:
        fail(422, "ENCOUNTER_PERSON_MISMATCH", "Lượt khám không thuộc người bệnh của đơn thuốc")
    require_editable(e)
    base = {c: getattr(p, c) for c in ("drug_code", "drug_name", "strength", "dose", "route", "frequency",
                                       "start_date", "duration_days", "quantity_prescribed", "instructions",
                                       "supervised")}
    base.update(body.model_dump(exclude={"expected_version", "reason", "encounter_id"}, exclude_none=True))
    n = MedicationOrder(encounter_id=e.id, person_id=p.person_id, facility_id=p.facility_id, ordered_by=user.id,
                        version=p.version + 1, parent_order_id=p.id, **base)
    n.warnings = compute_warnings(db, p.person_id, n.drug_name, n.drug_code, {p.id})
    db.add(n)
    audit(db, user, "medication_order_revised", "MedicationOrder", n.id, person_id=p.person_id,
          reason=body.reason, request=request)
    db.commit()
    return order_out(db, n)


class StopIn(BaseModel):
    outcome: str = Field(pattern="^(stopped|completed|cancelled)$")
    reason: str = Field(min_length=3)


@router.post("/medication-orders/{order_id}/stop", tags=["medication"])
def stop_order(order_id: str, body: StopIn, request: Request, user: User = Depends(require("medorder.write")),
               db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request, write=True)
    if o.status not in ("draft", *ACTIVE):
        fail(409, "NOT_STOPPABLE", "Đơn không ở trạng thái có thể dừng")
    if body.outcome == "cancelled" and db.scalars(select(DispenseEvent.id).where(
            DispenseEvent.order_id == o.id).limit(1)).first():
        fail(409, "ALREADY_DISPENSED", "Đơn đã có cấp phát – dùng 'stopped' thay vì hủy")
    o.status, o.stop_reason = body.outcome, body.reason
    audit(db, user, f"medication_order_{body.outcome}", "MedicationOrder", o.id, person_id=o.person_id,
          reason=body.reason, request=request)
    # bản điều chỉnh còn nháp của đơn này bị hủy theo – không thể xác nhận để dùng lại thuốc đã dừng
    for d in db.scalars(select(MedicationOrder).where(MedicationOrder.parent_order_id == o.id,
                                                      MedicationOrder.status == "draft")):
        d.status, d.stop_reason = "cancelled", f"Đơn gốc đã chuyển '{body.outcome}': {body.reason}"
        audit(db, user, "medication_order_cancelled", "MedicationOrder", d.id, person_id=d.person_id,
              reason=d.stop_reason, request=request)
    db.commit()
    return order_out(db, o)


# ----------------------------------------------------------------- cấp phát
class DispenseIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    quantity: float = Field(ge=0.01)   # tối thiểu 0,01 đơn vị: chặn cấp "vụn" lọt qua sai số so sánh
    kind: str = Field(default="dispense", pattern="^(dispense|return|cancel)$")
    ref_dispense_id: str | None = None
    occurred_at: datetime | None = None
    note: str | None = None
    acknowledge_warnings: bool = False
    ack_note: str | None = None


@router.post("/medication-orders/{order_id}/dispenses", tags=["medication"])
def dispense(order_id: str, body: DispenseIn, request: Request, user: User = Depends(require("dispense.write")),
             db: Session = Depends(get_db)):
    def work():
        o = _load_order(db, user, order_id, request, write=True)
        now = utcnow()
        occ = norm_dt(body.occurred_at) or now
        if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
            fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
        t = dispense_totals(db, o)   # đọc SAU khi đã khóa đơn -> các lần cấp song song không cùng thấy "còn lại"
        new_warns = []
        if body.kind == "dispense":
            if o.status not in ACTIVE:  # BR-04: chỉ cấp theo đơn còn hiệu lực
                fail(409, "ORDER_NOT_EFFECTIVE", f"Đơn đang ở trạng thái '{o.status}', không thể cấp phát")
            last_day = o.start_date + timedelta(days=o.duration_days - 1)
            if occ.date() < o.start_date:
                fail(409, "ORDER_NOT_STARTED", f"Đơn chỉ có hiệu lực từ {o.start_date.strftime('%d/%m/%Y')}")
            if occ.date() > last_day:  # BR-04: chỉ cấp theo đơn còn hiệu lực
                fail(409, "ORDER_EXPIRED", f"Đơn đã hết liệu trình (đến {last_day.strftime('%d/%m/%Y')}) – cần bác sĩ đánh giá, tái kê hoặc điều chỉnh",
                     expired_on=str(last_day))
            if body.quantity > t["remaining"] + EPS:
                fail(409, "OVER_DISPENSE", "Vượt số lượng được kê", remaining=t["remaining"])
            new_warns = require_allergy_ack(db, o, body.acknowledge_warnings, body.ack_note, user, request, "cấp phát")
            status = "full" if body.quantity >= t["remaining"] - EPS else "partial"
        else:
            if not body.ref_dispense_id or not body.note:
                fail(422, "REF_REQUIRED", "Hoàn trả/hủy cần ref_dispense_id và lý do (note)")
            ref = db.get(DispenseEvent, body.ref_dispense_id)
            if not ref or ref.order_id != o.id or ref.kind != "dispense":
                fail(404, "REF_NOT_FOUND", "Không tìm thấy lần cấp phát tham chiếu")
            if occ < ref.occurred_at:
                fail(422, "BEFORE_DISPENSE", "Thời điểm hoàn trả/hủy không được trước lần cấp phát tham chiếu")
            returnable = _returnable(db, ref)
            if body.quantity > returnable + EPS:
                fail(409, "OVER_RETURN", "Số lượng hoàn trả vượt số đã cấp", returnable=returnable)
            status = "partial"
        d = DispenseEvent(order_id=o.id, kind=body.kind, ref_dispense_id=body.ref_dispense_id, quantity=body.quantity,
                          status=status, note=body.note, dispensed_by=user.id, occurred_at=occ, recorded_at=now)
        db.add(d)
        if o.status == "confirmed" and body.kind == "dispense":
            o.status = "active"
        audit(db, user, f"medication_{body.kind}", "DispenseEvent", d.id, person_id=o.person_id, request=request)
        db.flush()
        return 201, {**to_dict(d), "order": order_out(db, o), "new_warnings": new_warns}
    return run_idempotent(db, request, user, {"o": order_id, **body.model_dump()}, work)


def _returnable(db: Session, ref: DispenseEvent) -> float:
    returned = sum(x.quantity for x in db.scalars(select(DispenseEvent).where(DispenseEvent.ref_dispense_id == ref.id)))
    return round(ref.quantity - returned, 6)


class AdminIn(BaseModel):
    administered: bool
    dispense_id: str | None = None
    reason: str | None = None
    occurred_at: datetime | None = None
    acknowledge_warnings: bool = False
    ack_note: str | None = None


@router.post("/medication-orders/{order_id}/administrations", status_code=201, tags=["medication"])
@idempotent(201)
def administer(order_id: str, body: AdminIn, request: Request, user: User = Depends(require("admin.write")),
               db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request, write=True)
    now = utcnow()
    occ = norm_dt(body.occurred_at) or now
    if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
        fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
    if not body.administered and not (body.reason and body.reason.strip()):
        fail(422, "REASON_REQUIRED", "Không sử dụng thuốc (từ chối/quên liều/đổi thuốc) phải ghi lý do")
    if o.status not in ACTIVE:  # nháp chưa xác nhận / đã dừng / đã thay bằng bản mới: không ghi nhận liều
        fail(409, "ORDER_NOT_EFFECTIVE", f"Đơn đang ở trạng thái '{o.status}', không thể ghi nhận sử dụng thuốc")
    if occ.replace(tzinfo=timezone.utc).astimezone().date() < o.start_date:   # start_date là ngày theo giờ địa phương
        fail(422, "BEFORE_ORDER_START", f"Thời điểm dùng thuốc trước ngày bắt đầu của đơn ({o.start_date.strftime('%d/%m/%Y')})")
    ids = course_order_ids(db, o)   # liều thuốc cấp ở phiên bản trước vẫn dùng tiếp theo bản điều chỉnh
    d = None
    if body.dispense_id:
        d = db.get(DispenseEvent, body.dispense_id)
        if not d or d.order_id not in ids or d.kind != "dispense":
            fail(404, "REF_NOT_FOUND", "Lần cấp phát không thuộc đơn này")
        if occ < d.occurred_at:
            fail(422, "BEFORE_DISPENSE", "Thời điểm dùng thuốc trước lần cấp phát được chọn")
    new_warns = []
    if body.administered:
        net = dispense_totals(db, o)["dispensed_net"]
        if net <= 0:
            fail(409, "NOT_DISPENSED", "Chưa có cấp phát – không thể xác nhận đã dùng thuốc")
        if not db.scalars(select(DispenseEvent.id).where(DispenseEvent.order_id.in_(ids), DispenseEvent.kind == "dispense",
                                                         DispenseEvent.occurred_at <= occ).limit(1)).first():
            fail(422, "BEFORE_DISPENSE", "Thời điểm dùng thuốc trước lần cấp phát đầu tiên")
        given = lambda *cond: db.scalar(select(func.count()).select_from(AdministrationEvent).where(  # noqa: E731
            AdministrationEvent.administered.is_(True), *cond))
        # mỗi lần xác nhận đã dùng tiêu tối thiểu 1 đơn vị đã cấp (ròng, sau hoàn trả)
        if d:
            avail = _returnable(db, d)
            if avail <= EPS:
                fail(409, "DISPENSE_RETURNED", "Lần cấp phát này đã được hoàn trả/hủy toàn bộ")
            if given(AdministrationEvent.dispense_id == d.id) + 1 > avail + EPS:
                fail(409, "OVER_ADMINISTER", "Số lần đã dùng vượt số lượng của lần cấp phát được chọn", available=avail)
        if given(AdministrationEvent.order_id.in_(ids)) + 1 > net + EPS:
            fail(409, "OVER_ADMINISTER", "Số lần đã dùng vượt số lượng đã cấp phát (ròng)", dispensed_net=net)
        new_warns = require_allergy_ack(db, o, body.acknowledge_warnings, body.ack_note, user, request, "cho dùng thuốc")
    a = AdministrationEvent(order_id=o.id, dispense_id=body.dispense_id, administered=body.administered,
                            reason=body.reason, confirmed_by=user.id, occurred_at=occ, recorded_at=now)
    db.add(a)
    audit(db, user, "medication_administration", "AdministrationEvent", a.id, person_id=o.person_id, request=request)
    return {**to_dict(a), "new_warnings": new_warns}


@router.get("/dispense-queue", tags=["medication"])
def dispense_queue(request: Request, user: User = Depends(require("dispense.write")), db: Session = Depends(get_db)):
    """Đơn đã xác nhận còn thiếu số lượng cần cấp – giữ phần còn thiếu để xử lý."""
    out = []
    for o in db.scalars(select(MedicationOrder).where(MedicationOrder.facility_id == user.facility_id,
                                                      MedicationOrder.status.in_(ACTIVE))):
        if not dispensable_today(o):   # chưa tới ngày bắt đầu hoặc đã hết liệu trình -> chờ bác sĩ, không đưa vào hàng đợi cấp phát
            continue
        t = dispense_totals(db, o)
        if t["remaining"] > 0:
            person = db.get(Person, o.person_id)
            new = new_allergy_warnings(db, o)   # dị ứng ghi nhận sau khi kê đơn -> hiện ngay ở hàng đợi
            out.append({**order_out(db, o), "warnings": [*(o.warnings or []), *new],
                        "requires_ack": any(w["severe"] for w in new),
                        "person_name": person.full_name if person else None})
    return out


def course_end(o: MedicationOrder) -> date:
    return o.start_date + timedelta(days=o.duration_days - 1)


def dispensable_today(o: MedicationOrder) -> bool:
    return o.start_date <= date.today() <= course_end(o)
