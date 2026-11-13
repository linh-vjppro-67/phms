"""WF-08: cấp cứu – ghi nhận tối thiểu, không chặn xử trí; hoàn thiện hồ sơ sau (BR-03)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..idempotency import idempotent
from ..db import get_db
from ..deps import active_stay, ensure_clinical_access, person_or_404, require
from ..notify import emit, person_name
from ..models import Appointment, CustodyStay, EmergencyEvent, Encounter, Person, User
from ..utils import fail, norm_dt, to_dict, uid, utcnow
from .identity import get_or_create_record

router = APIRouter()


class EmergencyIn(BaseModel):
    person_id: str | None = None
    temp_identity: str | None = None
    occurred_at: datetime | None = None
    location: str | None = None
    reporter: str | None = None
    description: str | None = None
    late_entry_reason: str | None = None


@router.post("/emergency-events", status_code=201, tags=["emergency"])
@idempotent(201)
def create_event(body: EmergencyIn, request: Request, user: User = Depends(require("emergency.write")),
                 db: Session = Depends(get_db)):
    now = utcnow()
    occ = norm_dt(body.occurred_at) or now
    if occ > now + timedelta(minutes=config.FUTURE_TOLERANCE_MIN):
        fail(422, "FUTURE_TIME", "occurred_at không được ở tương lai")
    if (now - occ) > timedelta(minutes=config.LATE_ENTRY_MIN) and not body.late_entry_reason:
        fail(422, "LATE_ENTRY_REASON", "Ghi nhận muộn cần nêu lý do (late_entry_reason)")
    if body.person_id:
        person_or_404(db, body.person_id)
        person = body.person_id
    elif body.temp_identity:
        # Chưa xác minh danh tính: hồ sơ tạm + đối soát bắt buộc sau đó (không tự gộp)
        tp = Person(full_name=f"[TẠM] {body.temp_identity}", source_system="TEMP", external_id=uid()[:12],
                    status="pending_verification", is_temporary=True, created_by=user.id)
        db.add(tp)
        db.flush()
        person = tp.id
    else:
        fail(422, "IDENTITY_REQUIRED", "Cần person_id hoặc mô tả nhận dạng tạm (temp_identity)")
    stay = active_stay(db, person, user.facility_id)
    if not stay:  # không chặn cấp cứu: tạo kỳ tạm, đánh dấu cần đối soát
        if active_stay(db, person):
            fail(409, "ACTIVE_STAY_ELSEWHERE", "Người này đang thuộc cơ sở khác – dùng break-glass để xử trí")
        stay = CustodyStay(person_id=person, facility_id=user.facility_id, start_date=date.today(), provisional=True,
                           created_by=user.id)
        db.add(stay)
    get_or_create_record(db, person)
    db.flush()
    enc = Encounter(person_id=person, stay_id=stay.id, facility_id=user.facility_id, type="emergency",
                    status="in_progress", priority="emergent", reason=body.description or "Cấp cứu", occurred_at=occ, recorded_at=now,
                    late_entry_reason=body.late_entry_reason, created_by=user.id)
    db.add(enc)
    db.flush()
    ev = EmergencyEvent(person_id=person, facility_id=user.facility_id, encounter_id=enc.id,
                        temp_identity=body.temp_identity, location=body.location, reporter=body.reporter,
                        description=body.description, late_entry_reason=body.late_entry_reason, occurred_at=occ,
                        recorded_at=now, created_by=user.id, timeline=[])
    db.add(ev)
    audit(db, user, "emergency_created", "EmergencyEvent", ev.id, person_id=person, request=request)
    desc = (body.description or "").strip()
    pn = person_name(db, person)
    emit(db, kind="emergency.created", category="emergency", severity="critical", facility_id=user.facility_id, actor=user, perms=("emergency.write",),
         title=f"CẤP CỨU{': ' + body.location if body.location else ''}", plain=desc or "Có sự cố y tế khẩn cấp, cần có mặt xử trí.",
         named=f"{pn} – {desc}" if desc else pn, link_page="emergency", link_ref=ev.id, person_id=person, dedupe=f"emg:{ev.id}")
    if not body.person_id:
        emit(db, kind="emergency.identity", category="emergency", severity="warning", facility_id=user.facility_id, actor=user, perms=("person.write",),
             title="Hồ sơ tạm từ cấp cứu cần đối soát danh tính", plain="Có người cấp cứu chưa rõ danh tính, cần đối soát với nguồn dữ liệu gốc.",
             link_page="intake", link_ref=person, person_id=person, dedupe=f"emg:{ev.id}:identity")
    return to_dict(ev)


class StepIn(BaseModel):
    action: str = Field(min_length=2)
    performer: str | None = None
    occurred_at: datetime | None = None


def _load(db, user, eid) -> EmergencyEvent:
    ev = db.get(EmergencyEvent, eid)
    if not ev or ev.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy sự kiện cấp cứu")
    return ev


@router.post("/emergency-events/{eid}/interventions", tags=["emergency"])
def add_step(eid: str, body: StepIn, request: Request, user: User = Depends(require("emergency.write")),
             db: Session = Depends(get_db)):
    ev = _load(db, user, eid)
    if ev.status != "open":
        fail(409, "EVENT_CLOSED", "Sự kiện đã đóng")
    ev.timeline = [*(ev.timeline or []), {
        "action": body.action, "performer": body.performer or user.full_name, "actor_id": user.id,
        "occurred_at": (norm_dt(body.occurred_at) or utcnow()).isoformat(), "recorded_at": utcnow().isoformat()}]
    audit(db, user, "emergency_intervention", "EmergencyEvent", ev.id, person_id=ev.person_id, request=request)
    db.commit()
    return to_dict(ev)


@router.get("/emergency-events/{eid}", tags=["emergency"])
def get_event(eid: str, request: Request, user: User = Depends(require("emergency.write")), db: Session = Depends(get_db)):
    ev = _load(db, user, eid)
    ensure_clinical_access(db, user, ev.person_id, request)
    return to_dict(ev)


class CloseIn(BaseModel):
    note: str = Field(min_length=3)
    follow_up_date: date | None = None


@router.post("/emergency-events/{eid}/close", tags=["emergency"])
def close_event(eid: str, body: CloseIn, request: Request, user: User = Depends(require("emergency.close")),
                db: Session = Depends(get_db)):
    ev = _load(db, user, eid)
    if ev.status != "open":
        fail(409, "EVENT_CLOSED", "Sự kiện đã đóng")
    problems = []
    enc = db.get(Encounter, ev.encounter_id)
    if enc and enc.status not in ("completed", "cancelled"):
        problems.append("Lượt khám cấp cứu chưa hoàn tất hồ sơ")
    p = db.get(Person, ev.person_id)
    if p and p.status != "verified":
        problems.append("Danh tính chưa được đối soát (bắt buộc)")
    if problems:
        fail(409, "INCOMPLETE_RECORD", "Chưa đủ điều kiện đóng sự kiện cấp cứu", problems=problems)
    ev.status, ev.closing_note, ev.closed_by = "closed", body.note, user.id
    if body.follow_up_date:
        db.add(Appointment(person_id=ev.person_id, facility_id=ev.facility_id, kind="follow_up",
                           due_date=body.follow_up_date, note="Theo dõi sau cấp cứu"))
    audit(db, user, "emergency_closed", "EmergencyEvent", ev.id, person_id=ev.person_id, reason=body.note, request=request)
    db.commit()
    return to_dict(ev)
