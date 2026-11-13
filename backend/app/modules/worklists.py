"""Danh sách công việc (worklist), bảng điều khiển và ma trận quyền – phục vụ các màn hình nghiệp vụ."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user, require, require_any
from ..models import (Alert, Appointment, CarePlan, CustodyStay, EmergencyEvent, Encounter, Handover, HealthProblem,
                      MedicationOrder, Person, Referral, User)
from ..permissions import ROLE_PERMS, perms_of
from ..utils import to_dict
from .identity import _handover_out
from .medication import ACTIVE, dispensable_today, dispense_totals, order_out
from .referral import OPEN_STATES

router = APIRouter()
OPEN_ENC = ("draft", "in_progress", "awaiting_results", "in_treatment")


def _people(db: Session, ids) -> dict:
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    return {p.id: p for p in db.scalars(select(Person).where(Person.id.in_(ids)))}


def _named(db, rows, extra=None):
    people = _people(db, [r.person_id for r in rows])
    out = []
    for r in rows:
        d = to_dict(r)
        p = people.get(r.person_id)
        d["person_name"] = p.full_name if p else None
        d["person_external_id"] = p.external_id if p else None
        out.append(d)
    return out


@router.get("/stays", tags=["worklists"])
def list_stays(status: str | None = None, limit: int = 200, user: User = Depends(require("person.read")),
               db: Session = Depends(get_db)):
    """status: active | received | managed | transferred | ended."""
    q = select(CustodyStay).where(CustodyStay.facility_id == user.facility_id, CustodyStay.status != "voided")
    if status == "active":
        q = q.where(CustodyStay.status.in_(("received", "managed")))
    elif status:
        q = q.where(CustodyStay.status == status)
    stays = db.scalars(q.order_by(CustodyStay.recorded_at.desc()).limit(min(limit, 500))).all()
    out = _named(db, stays)
    for d in out:
        init = db.scalars(select(Encounter).where(Encounter.stay_id == d["id"], Encounter.type == "initial",
                                                   Encounter.status != "cancelled")).first()
        d["initial_encounter_id"] = init.id if init else None
        d["initial_encounter_status"] = init.status if init else None
        d["needs_initial_exam"] = d["status"] == "received"
    return out


@router.get("/encounters", tags=["worklists"])
def list_encounters(status: str | None = None, type: str | None = None, open_only: bool = False, limit: int = 200,
                    request: Request = None, user: User = Depends(require("clinical.read")),
                    db: Session = Depends(get_db)):
    # ưu tiên cao lên trước (emergent > urgent > còn lại), cùng mức thì mới nhất trước
    prio = case((Encounter.priority == "emergent", 0), (Encounter.priority == "urgent", 1), else_=2)
    q = select(Encounter).where(Encounter.facility_id == user.facility_id).order_by(prio, Encounter.occurred_at.desc())
    if status:
        q = q.where(Encounter.status == status)
    if type:
        q = q.where(Encounter.type == type)
    if open_only:
        q = q.where(Encounter.status.in_(OPEN_ENC))
    audit(db, user, "list_encounters", reason=f"status={status} type={type}", request=request)
    db.commit()
    return _named(db, db.scalars(q.limit(min(limit, 500))).all())


@router.get("/medication-orders", tags=["worklists"])
def list_orders(status: str | None = None, limit: int = 200, user: User = Depends(require("clinical.read")),
                db: Session = Depends(get_db)):
    q = select(MedicationOrder).where(MedicationOrder.facility_id == user.facility_id).order_by(
        MedicationOrder.recorded_at.desc())
    if status:
        q = q.where(MedicationOrder.status.in_(status.split(",")))
    rows = db.scalars(q.limit(min(limit, 500))).all()
    people = _people(db, [r.person_id for r in rows])
    return [{**order_out(db, r), "person_name": people[r.person_id].full_name} for r in rows]


@router.get("/handovers", tags=["worklists"])
def list_handovers(status: str | None = None, user: User = Depends(require_any(
        "handover.initiate", "handover.confirm", "handover.summary")), db: Session = Depends(get_db)):
    q = select(Handover).where((Handover.from_facility_id == user.facility_id) |
                               (Handover.to_facility_id == user.facility_id)).order_by(Handover.recorded_at.desc())
    if status:
        q = q.where(Handover.status == status)
    rows = db.scalars(q.limit(200)).all()
    people = _people(db, [r.person_id for r in rows])
    return [{**_handover_out(h, user), "person_name": people[h.person_id].full_name,
             "direction": "out" if h.from_facility_id == user.facility_id else "in"} for h in rows]


@router.get("/emergency-events", tags=["worklists"])
def list_emergencies(status: str | None = None, user: User = Depends(require("emergency.write")),
                     db: Session = Depends(get_db)):
    q = select(EmergencyEvent).where(EmergencyEvent.facility_id == user.facility_id).order_by(
        EmergencyEvent.occurred_at.desc())
    if status:
        q = q.where(EmergencyEvent.status == status)
    rows = db.scalars(q.limit(200)).all()
    people = _people(db, [r.person_id for r in rows])
    out = []
    for r in rows:
        d = to_dict(r)
        p = people.get(r.person_id)
        d["person_name"], d["person_status"] = (p.full_name, p.status) if p else (None, None)
        enc = db.get(Encounter, r.encounter_id) if r.encounter_id else None
        d["encounter_status"] = enc.status if enc else None
        out.append(d)
    return out


@router.get("/care-plans", tags=["worklists"])
def list_care_plans(status: str = "active", user: User = Depends(require("clinical.read")),
                    db: Session = Depends(get_db)):
    rows = db.scalars(select(CarePlan).where(CarePlan.facility_id == user.facility_id, CarePlan.status == status)).all()
    people = _people(db, [r.person_id for r in rows])
    out = []
    for r in rows:
        d = to_dict(r)
        d["person_name"] = people[r.person_id].full_name
        prob = db.get(HealthProblem, r.problem_id)
        d["problem_name"] = prob.name if prob else None
        nxt = db.scalars(select(Appointment).where(Appointment.care_plan_id == r.id,
                                                    Appointment.status.in_(("scheduled", "due")))
                         .order_by(Appointment.due_date)).first()
        d["next_due"] = nxt.due_date if nxt else None
        d["overdue"] = bool(nxt and nxt.due_date < date.today())
        out.append(d)
    return out


@router.get("/roles", tags=["users"])
def roles(_: User = Depends(require("user.manage"))):
    return {k: sorted(v) for k, v in ROLE_PERMS.items()}


@router.get("/dashboard", tags=["worklists"])
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Chỉ trả các chỉ số trong phạm vi quyền của vai trò (need-to-know)."""
    f, perms, today = user.facility_id, perms_of(user), date.today()
    cnt = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    out: dict = {}
    if "person.read" in perms:
        out["active_persons"] = cnt(select(func.count()).select_from(CustodyStay).where(
            CustodyStay.facility_id == f, CustodyStay.status.in_(("received", "managed"))))
        out["awaiting_initial_exam"] = cnt(select(func.count()).select_from(CustodyStay).where(
            CustodyStay.facility_id == f, CustodyStay.status == "received"))
        out["pending_verification"] = cnt(select(func.count(func.distinct(Person.id))).select_from(Person).join(
            CustodyStay, CustodyStay.person_id == Person.id).where(
            CustodyStay.facility_id == f, CustodyStay.status.in_(("received", "managed")),
            Person.status == "pending_verification"))
    if "schedule.read" in perms:
        out["overdue_appointments"] = cnt(select(func.count()).select_from(Appointment).where(
            Appointment.facility_id == f, Appointment.status.in_(("scheduled", "due")), Appointment.due_date < today))
        out["appointments_today"] = cnt(select(func.count()).select_from(Appointment).where(
            Appointment.facility_id == f, Appointment.status.in_(("scheduled", "due")), Appointment.due_date == today))
        out["unresolved_alerts"] = cnt(select(func.count()).select_from(Alert).where(
            Alert.facility_id == f, Alert.status.in_(("new", "acknowledged"))))
        out["new_alerts"] = cnt(select(func.count()).select_from(Alert).where(Alert.facility_id == f, Alert.status == "new"))
    if "clinical.read" in perms:
        out["open_encounters"] = cnt(select(func.count()).select_from(Encounter).where(
            Encounter.facility_id == f, Encounter.status.in_(OPEN_ENC)))
        out["awaiting_results"] = cnt(select(func.count()).select_from(Encounter).where(
            Encounter.facility_id == f, Encounter.status == "awaiting_results"))
        out["orders_draft"] = cnt(select(func.count()).select_from(MedicationOrder).where(
            MedicationOrder.facility_id == f, MedicationOrder.status == "draft"))
    if "dispense.write" in perms:
        out["dispense_queue"] = sum(1 for o in db.scalars(select(MedicationOrder).where(
            MedicationOrder.facility_id == f, MedicationOrder.status.in_(ACTIVE)))
            if dispensable_today(o) and dispense_totals(db, o)["remaining"] > 0)
    if "referral.read" in perms:
        out["open_referrals"] = cnt(select(func.count()).select_from(Referral).where(
            Referral.facility_id == f, Referral.status.in_(OPEN_STATES)))
        out["referrals_post_review"] = cnt(select(func.count()).select_from(Referral).where(
            Referral.facility_id == f, Referral.needs_post_review.is_(True)))
    if perms & {"handover.initiate", "handover.confirm", "handover.summary"}:
        out["pending_handovers"] = cnt(select(func.count()).select_from(Handover).where(
            Handover.from_facility_id == f, Handover.status == "pending"))
    if "emergency.write" in perms:
        out["open_emergencies"] = cnt(select(func.count()).select_from(EmergencyEvent).where(
            EmergencyEvent.facility_id == f, EmergencyEvent.status == "open"))
    return out
