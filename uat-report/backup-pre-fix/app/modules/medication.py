"""M05/M06: kê đơn – cấp phát – xác nhận dùng thuốc (WF-03).

Bất biến cốt lõi: MedicationOrder ≠ DispenseEvent ≠ AdministrationEvent.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..db import get_db, lock_row
from ..deps import ensure_clinical_access, ensure_clinical_write, require
from ..idempotency import idempotent, run_idempotent
from ..notify import emit, person_name
from ..models import (AdministrationEvent, Allergy, CatalogItem, DispenseEvent, Encounter, HealthRecord,
                      MedicationOrder, Person, User)
from ..utils import bump_version, fail, norm_dt, to_dict, utcnow
from .clinical import load_encounter, require_editable

router = APIRouter()
ACTIVE = ("confirmed", "active")


def order_chain(db: Session, order: MedicationOrder) -> list[str]:
    """Đơn + các bản trước của nó (điều chỉnh = bản mới tham chiếu bản cũ). Lượng đã cấp được cộng dồn qua cả chuỗi."""
    ids, cur = [order.id], order
    while cur.parent_order_id and cur.parent_order_id not in ids:
        cur = db.get(MedicationOrder, cur.parent_order_id)
        if not cur:
            break
        ids.append(cur.id)
    return ids


def dispense_totals(db: Session, order: MedicationOrder) -> dict:
    evs = db.scalars(select(DispenseEvent).where(DispenseEvent.order_id.in_(order_chain(db, order)))).all()
    net = sum(e.quantity if e.kind == "dispense" else -e.quantity for e in evs)
    status = "none" if net <= 0 else ("full" if net >= order.quantity_prescribed else "partial")
    return {"dispensed_net": net, "remaining": max(order.quantity_prescribed - net, 0), "dispense_status": status}


def order_out(db: Session, o: MedicationOrder) -> dict:
    return {**to_dict(o), **dispense_totals(db, o)}


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


def compute_warnings(db: Session, person_id: str, drug_name: str, drug_code: str | None,
                     exclude_ids: set[str]) -> list[dict]:
    warns = []
    rec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == person_id)).first()
    dn = drug_name.lower()
    if rec:
        drug_classes = _classes_of(dn)
        for a in db.scalars(select(Allergy).where(Allergy.record_id == rec.id, Allergy.active.is_(True))):
            s = a.substance.lower()
            tag = " (đã xác nhận)" if a.confirmed else ""
            if s in dn or dn in s:
                warns.append({"type": "allergy", "message": f"Dị ứng đã ghi nhận với '{a.substance}'" + tag, "allergy_id": a.id})
            else:
                shared = drug_classes & _classes_of(s)
                if shared:
                    warns.append({"type": "allergy", "message": f"Dị ứng '{a.substance}'{tag} – cùng nhóm {sorted(shared)[0]} với '{drug_name}' (nguy cơ dị ứng chéo)",
                                  "allergy_id": a.id})
    for o in db.scalars(select(MedicationOrder).where(MedicationOrder.person_id == person_id,
                                                      MedicationOrder.status.in_(ACTIVE))):
        if o.id in exclude_ids:
            continue
        if o.drug_name.lower() == dn or (drug_code and o.drug_code == drug_code):
            warns.append({"type": "duplicate", "message": f"Đã có đơn đang hiệu lực cùng thuốc ({o.drug_name})",
                          "order_id": o.id})
    return warns


class OrderIn(BaseModel):
    drug_code: str | None = None
    drug_name: str = Field(min_length=2)
    strength: str | None = None
    dose: str = Field(min_length=1)
    route: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    start_date: date
    duration_days: int = Field(gt=0, le=3650)
    quantity_prescribed: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
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
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    duration_days: int | None = Field(default=None, gt=0)
    quantity_prescribed: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    instructions: str | None = None
    supervised: bool | None = None
    expected_version: int | None = None


def _load_order(db: Session, user: User, order_id: str, request: Request, write: bool = False) -> MedicationOrder:
    o = db.get(MedicationOrder, order_id)
    if not o:
        fail(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn thuốc")
    (ensure_clinical_write if write else ensure_clinical_access)(db, user, o.person_id, request)
    if write and o.facility_id != user.facility_id:
        fail(403, "FACILITY_SCOPE", "Đơn thuộc cơ sở khác")
    return o


@router.get("/medication-orders/{order_id}", tags=["medication"])
def get_order(order_id: str, request: Request, user: User = Depends(require("clinical.read")),
              db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request)
    audit(db, user, "view_medication_order", "MedicationOrder", o.id, person_id=o.person_id, request=request)
    db.commit()
    return {**order_out(db, o),
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
    if o.parent_order_id:
        parent = db.get(MedicationOrder, o.parent_order_id)
        if parent and parent.status in (*ACTIVE, "draft"):
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
    if p.status not in ACTIVE:
        fail(409, "NOT_REVISABLE", "Chỉ đơn đã xác nhận/đang hiệu lực mới điều chỉnh")
    if db.scalars(select(MedicationOrder.id).where(MedicationOrder.parent_order_id == p.id,
                                                   MedicationOrder.status == "draft")).first():
        fail(409, "REVISION_PENDING", "Đã có bản điều chỉnh đang chờ xác nhận")
    e = load_encounter(db, user, body.encounter_id or p.encounter_id, request, write=True)
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
    reason: str | None = Field(default=None, max_length=1000)      # bắt buộc (≥3 ký tự) trừ khi xóa ĐƠN NHÁP


@router.post("/medication-orders/{order_id}/stop", tags=["medication"])
def stop_order(order_id: str, body: StopIn, request: Request, user: User = Depends(require("medorder.write")),
               db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request, write=True)
    if o.status not in ("draft", *ACTIVE):
        fail(409, "NOT_STOPPABLE", "Đơn không ở trạng thái có thể dừng")
    if o.status == "draft" and body.outcome == "cancelled":
        body.reason = (body.reason or "").strip() or "Xóa đơn nháp"      # đơn nháp chưa có hiệu lực: bỏ đơn không cần lý do
    elif len((body.reason or "").strip()) < 3:
        fail(422, "REASON_REQUIRED", "Cần nêu lý do (tối thiểu 3 ký tự)")
    if body.outcome == "cancelled" and db.scalars(select(DispenseEvent.id).where(
            DispenseEvent.order_id == o.id).limit(1)).first():
        fail(409, "ALREADY_DISPENSED", "Đơn đã có cấp phát – dùng 'stopped' thay vì hủy")
    o.status, o.stop_reason = body.outcome, body.reason
    audit(db, user, f"medication_order_{body.outcome}", "MedicationOrder", o.id, person_id=o.person_id,
          reason=body.reason, request=request)
    db.commit()
    return order_out(db, o)


# ----------------------------------------------------------------- cấp phát
class DispenseIn(BaseModel):
    quantity: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    kind: str = Field(default="dispense", pattern="^(dispense|return|cancel)$")
    ref_dispense_id: str | None = None
    occurred_at: datetime | None = None
    note: str | None = None


@router.post("/medication-orders/{order_id}/dispenses", tags=["medication"])
def dispense(order_id: str, body: DispenseIn, request: Request, user: User = Depends(require("dispense.write")),
             db: Session = Depends(get_db)):
    def work():
        o = _load_order(db, user, order_id, request, write=True)
        o = lock_row(db, MedicationOrder, o.id)       # tuần tự hóa: hai lần cấp cùng lúc không thể cùng vượt số kê
        now = utcnow()
        occ = norm_dt(body.occurred_at) or now
        if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
            fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
        t = dispense_totals(db, o)
        if body.kind == "dispense":
            if o.status not in ACTIVE:  # BR-04: chỉ cấp theo đơn còn hiệu lực
                fail(409, "ORDER_NOT_EFFECTIVE", f"Đơn đang ở trạng thái '{o.status}', không thể cấp phát")
            last_day = o.start_date + timedelta(days=o.duration_days - 1)
            if occ.date() < o.start_date:
                fail(409, "ORDER_NOT_STARTED", f"Đơn chỉ có hiệu lực từ {o.start_date.strftime('%d/%m/%Y')}")
            if occ.date() > last_day:  # BR-04: chỉ cấp theo đơn còn hiệu lực
                fail(409, "ORDER_EXPIRED", f"Đơn đã hết liệu trình (đến {last_day.strftime('%d/%m/%Y')}) – cần bác sĩ đánh giá, tái kê hoặc điều chỉnh",
                     expired_on=str(last_day))
            if body.quantity > t["remaining"] + 1e-9:
                fail(409, "OVER_DISPENSE", "Vượt số lượng được kê", remaining=t["remaining"])
            status = "full" if body.quantity >= t["remaining"] - 1e-9 else "partial"
        else:
            if not body.ref_dispense_id or not body.note:
                fail(422, "REF_REQUIRED", "Hoàn trả/hủy cần ref_dispense_id và lý do (note)")
            ref = db.get(DispenseEvent, body.ref_dispense_id)
            if not ref or ref.order_id not in order_chain(db, o) or ref.kind != "dispense":
                fail(404, "REF_NOT_FOUND", "Không tìm thấy lần cấp phát tham chiếu")
            returned = sum(x.quantity for x in db.scalars(select(DispenseEvent).where(
                DispenseEvent.ref_dispense_id == ref.id)))
            if body.quantity > ref.quantity - returned + 1e-9:
                fail(409, "OVER_RETURN", "Số lượng hoàn trả vượt số đã cấp", returnable=ref.quantity - returned)
            status = "partial"
        d = DispenseEvent(order_id=o.id, kind=body.kind, ref_dispense_id=body.ref_dispense_id, quantity=body.quantity,
                          status=status, note=body.note, dispensed_by=user.id, occurred_at=occ, recorded_at=now)
        db.add(d)
        if o.status == "confirmed" and body.kind == "dispense":
            o.status = "active"
        audit(db, user, f"medication_{body.kind}", "DispenseEvent", d.id, person_id=o.person_id, request=request)
        db.flush()
        return 201, {**to_dict(d), "order": order_out(db, o)}
    return run_idempotent(db, request, user, {"o": order_id, **body.model_dump()}, work)


class AdminIn(BaseModel):
    administered: bool
    dispense_id: str | None = None
    reason: str | None = None
    occurred_at: datetime | None = None


@router.post("/medication-orders/{order_id}/administrations", status_code=201, tags=["medication"])
@idempotent(201)
def administer(order_id: str, body: AdminIn, request: Request, user: User = Depends(require("admin.write")),
               db: Session = Depends(get_db)):
    o = _load_order(db, user, order_id, request, write=True)
    now = utcnow()
    occ = norm_dt(body.occurred_at) or now
    if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
        fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
    if o.status not in ACTIVE:      # đơn nháp/đã dừng/đã hủy/đã thay thế: không có việc "dùng thuốc"
        fail(409, "ORDER_NOT_ACTIVE", f"Đơn đang ở trạng thái '{o.status}' – chỉ ghi nhận dùng thuốc với đơn đã xác nhận/đang hiệu lực")
    if occ.date() < o.start_date:
        fail(409, "ORDER_NOT_STARTED", f"Đơn chỉ có hiệu lực từ {o.start_date.strftime('%d/%m/%Y')}")
    if not body.administered and not (body.reason and body.reason.strip()):
        fail(422, "REASON_REQUIRED", "Không sử dụng thuốc (từ chối/quên liều/đổi thuốc) phải ghi lý do")
    if body.administered:
        if dispense_totals(db, o)["dispensed_net"] <= 0:
            fail(409, "NOT_DISPENSED", "Chưa có cấp phát – không thể xác nhận đã dùng thuốc")
    if body.dispense_id:
        d = db.get(DispenseEvent, body.dispense_id)
        if not d or d.order_id != o.id or d.kind != "dispense":
            fail(404, "REF_NOT_FOUND", "Lần cấp phát không thuộc đơn này")
    a = AdministrationEvent(order_id=o.id, dispense_id=body.dispense_id, administered=body.administered,
                            reason=body.reason, confirmed_by=user.id, occurred_at=occ, recorded_at=now)
    db.add(a)
    audit(db, user, "medication_administration", "AdministrationEvent", a.id, person_id=o.person_id, request=request)
    return to_dict(a)


@router.get("/dispense-queue", tags=["medication"])
def dispense_queue(request: Request, user: User = Depends(require("dispense.write")), db: Session = Depends(get_db)):
    """Đơn đã xác nhận còn thiếu số lượng cần cấp – giữ phần còn thiếu để xử lý."""
    out = []
    for o in db.scalars(select(MedicationOrder).where(MedicationOrder.facility_id == user.facility_id,
                                                      MedicationOrder.status.in_(ACTIVE))):
        if not dispensable_today(o):   # chưa tới ngày bắt đầu hoặc đã hết liệu trình -> chờ bác sĩ, không đưa vào hàng đợi cấp phát
            continue
        d = order_out(db, o)
        if d["remaining"] > 0:
            person = db.get(Person, o.person_id)
            out.append({**d, "person_name": person.full_name if person else None})
    return out


def course_end(o: MedicationOrder) -> date:
    return o.start_date + timedelta(days=o.duration_days - 1)


def dispensable_today(o: MedicationOrder) -> bool:
    return o.start_date <= date.today() <= course_end(o)
