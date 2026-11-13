"""M07/M08: khám định kỳ, bệnh mạn tính, kế hoạch theo dõi, lịch hẹn, cảnh báo, scheduler (WF-04, WF-05)."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..idempotency import idempotent
from ..db import get_db, lock_row
from ..deps import active_stay, current_user, ensure_clinical_access, require
from ..notify import emit, person_name, purge
from ..models import (MedicationOrder, Alert, Appointment, CarePlan, CheckupRound, CustodyStay, Encounter, Handover, HealthProblem,
                      Person, Referral, User)
from ..permissions import perms_of
from ..utils import bump_version, fail, to_dict, utcnow
from .identity import get_or_create_record

router = APIRouter()


OPEN_APPT = ("scheduled", "due")


def close_overdue_alerts(db: Session, appt_ids, resolution: str) -> None:
    """Lịch đã được xử lý (hoàn tất/hoãn/không thực hiện/kết thúc kế hoạch) -> cảnh báo quá hạn của lịch đó đóng theo,
    tránh cảnh báo mồ côi bị nâng mức."""
    keys = [f"overdue:{i}" for i in appt_ids]
    if not keys:
        return
    for a in db.scalars(select(Alert).where(Alert.dedupe_key.in_(keys), Alert.status.in_(("new", "acknowledged")))):
        a.status, a.resolution, a.handled_at = "resolved", resolution, utcnow()


def check_assignee(db: Session, user_id: str | None, facility_id: str | None) -> str | None:
    """Người phụ trách/được giao phải là nhân viên y tế (khám được) đang hoạt động của đúng cơ sở."""
    if user_id is None:
        return None
    u = db.get(User, user_id)
    if not u or not u.active or u.facility_id != facility_id or "encounter.write" not in perms_of(u):
        fail(422, "BAD_ASSIGNEE", "Người phụ trách phải là nhân viên y tế đang hoạt động của cơ sở")
    return u.id


def complete_appointment(db: Session, ap: Appointment, encounter_id: str | None = None) -> bool:
    """Hoàn tất lịch – CHỈ khi lịch còn mở (scheduled/due) và đợt khám (nếu có) chưa khóa. Lịch đã hoàn tất/hoãn/
    không thực hiện giữ nguyên (không tạo trùng lịch theo dõi, không đổi thống kê đợt đã khóa). Người gọi khóa dòng lịch."""
    if ap.status not in OPEN_APPT:
        return False
    if ap.round_id:
        r = db.get(CheckupRound, ap.round_id)
        if r and r.status == "locked":
            return False
    ap.status, ap.completed_at, ap.completed_encounter_id = "completed", utcnow(), encounter_id
    if ap.care_plan_id:
        cp = db.get(CarePlan, ap.care_plan_id)
        if cp and cp.status == "active":
            db.add(Appointment(person_id=ap.person_id, facility_id=ap.facility_id, kind="care_plan",
                               care_plan_id=cp.id, due_date=date.today() + timedelta(days=cp.review_interval_days),
                               assignee_id=cp.responsible_user_id))
    close_overdue_alerts(db, [ap.id], "Lịch đã hoàn tất")
    return True


def appt_out(db: Session, a: Appointment, with_name: bool) -> dict:
    d = to_dict(a)
    d["overdue"] = a.status in ("scheduled", "due") and a.due_date < date.today()  # thuộc tính tính toán
    if with_name:
        p = db.get(Person, a.person_id)
        d["person_name"] = p.full_name if p else None
    return d


# ----------------------------------------------------------------- vấn đề sức khỏe & kế hoạch (WF-05)
class ProblemIn(BaseModel):
    name: str = Field(min_length=2)
    code: str | None = None
    confirmation: str = Field(default="confirmed", pattern="^(suspected|confirmed)$")
    effective_from: date | None = None
    source: str | None = None


@router.post("/persons/{person_id}/problems", status_code=201, tags=["scheduling"])
@idempotent(201)
def add_problem(person_id: str, body: ProblemIn, request: Request, user: User = Depends(require("problem.write")),
                db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request, write=True)
    rec = get_or_create_record(db, person_id)
    p = HealthProblem(record_id=rec.id, person_id=person_id, name=body.name, code=body.code,
                      confirmation=body.confirmation, source=body.source or f"Bác sĩ {user.full_name}",
                      effective_from=body.effective_from or date.today(), confirmed_by=user.id,
                      facility_id=user.facility_id)
    db.add(p)
    audit(db, user, "problem_added", "HealthProblem", p.id, person_id=person_id, request=request)
    return to_dict(p)


class ResolveIn(BaseModel):
    note: str = Field(min_length=3)


class ResolveProblemIn(ResolveIn):
    end_plans: bool = False   # True: kết thúc luôn các kế hoạch theo dõi đang hiệu lực của vấn đề này


def _end_plan(db: Session, cp: CarePlan, reason: str) -> None:
    cp.status, cp.end_reason = "ended", reason
    closed = []
    for a in db.scalars(select(Appointment).where(Appointment.care_plan_id == cp.id, Appointment.status.in_(OPEN_APPT))):
        a.status, a.status_reason = "not_done", "Kế hoạch theo dõi đã kết thúc"
        closed.append(a.id)
    close_overdue_alerts(db, closed, "Kế hoạch theo dõi đã kết thúc")


@router.post("/problems/{problem_id}/resolve", tags=["scheduling"])
def resolve_problem(problem_id: str, body: ResolveProblemIn, request: Request, user: User = Depends(require("problem.write")),
                    db: Session = Depends(get_db)):
    """Vấn đề đã hết hiệu lực thì kế hoạch theo dõi của nó không còn căn cứ: nếu còn kế hoạch đang hiệu lực, chặn (409 PLAN_ACTIVE)
    để bác sĩ quyết định – gửi lại với end_plans=true để kết thúc luôn các kế hoạch đó (cùng lý do)."""
    p = db.get(HealthProblem, problem_id)
    if not p:
        fail(404, "NOT_FOUND", "Không tìm thấy vấn đề sức khỏe")
    ensure_clinical_access(db, user, p.person_id, request, write=True)
    p = lock_row(db, HealthProblem, problem_id)
    if p.status != "active":
        fail(409, "PROBLEM_RESOLVED", "Vấn đề sức khỏe đã được đóng trước đó")
    plans = db.scalars(select(CarePlan).where(CarePlan.problem_id == p.id, CarePlan.status == "active")).all()
    if plans and not body.end_plans:
        fail(409, "PLAN_ACTIVE", "Vấn đề còn kế hoạch theo dõi đang hiệu lực – kết thúc kế hoạch trước (hoặc chọn kết thúc kèm theo)",
             care_plan_ids=[c.id for c in plans])
    p.status, p.effective_to = "resolved", date.today()
    for cp in plans:
        _end_plan(db, cp, f"Vấn đề sức khỏe đã đóng: {body.note}")
        audit(db, user, "care_plan_ended", "CarePlan", cp.id, person_id=cp.person_id, reason=cp.end_reason, request=request)
    audit(db, user, "problem_resolved", "HealthProblem", p.id, person_id=p.person_id, reason=body.note, request=request)
    db.commit()
    return to_dict(p)


class CarePlanIn(BaseModel):
    problem_id: str
    goals: str = Field(min_length=3)
    measures: list[dict] | None = None
    review_interval_days: int = Field(gt=0, le=730)
    start_date: date | None = None
    responsible_user_id: str | None = None


@router.post("/persons/{person_id}/care-plans", status_code=201, tags=["scheduling"])
@idempotent(201)
def create_care_plan(person_id: str, body: CarePlanIn, request: Request,
                     user: User = Depends(require("careplan.write")), db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request, write=True)
    prob = db.get(HealthProblem, body.problem_id)
    if not prob or prob.person_id != person_id or prob.status != "active":
        fail(409, "BAD_PROBLEM", "Vấn đề sức khỏe không hợp lệ hoặc không còn hiệu lực")
    stay = active_stay(db, person_id, user.facility_id)
    if not stay:
        fail(409, "NO_ACTIVE_STAY", "Không có đợt tiếp nhận hiệu lực tại cơ sở")
    start = body.start_date or date.today()
    responsible = check_assignee(db, body.responsible_user_id, user.facility_id)
    cp = CarePlan(person_id=person_id, problem_id=prob.id, facility_id=user.facility_id, goals=body.goals,
                  measures=body.measures, review_interval_days=body.review_interval_days, start_date=start,
                  responsible_user_id=responsible, created_by=user.id)
    db.add(cp)
    db.flush()
    db.add(Appointment(person_id=person_id, facility_id=user.facility_id, kind="care_plan", care_plan_id=cp.id,
                       due_date=start + timedelta(days=cp.review_interval_days),
                       assignee_id=responsible))
    audit(db, user, "care_plan_created", "CarePlan", cp.id, person_id=person_id, request=request)
    return to_dict(cp)


class CarePlanPatch(BaseModel):
    goals: str | None = None
    measures: list[dict] | None = None
    review_interval_days: int | None = Field(default=None, gt=0, le=730)
    responsible_user_id: str | None = None
    expected_version: int | None = None


@router.patch("/care-plans/{plan_id}", tags=["scheduling"])
def patch_care_plan(plan_id: str, body: CarePlanPatch, request: Request,
                    user: User = Depends(require("careplan.write")), db: Session = Depends(get_db)):
    cp = db.get(CarePlan, plan_id)
    if not cp:
        fail(404, "NOT_FOUND", "Không tìm thấy kế hoạch")
    ensure_clinical_access(db, user, cp.person_id, request, write=True)
    if cp.status != "active":
        fail(409, "PLAN_ENDED", "Kế hoạch đã kết thúc")
    changes = body.model_dump(exclude={"expected_version"}, exclude_none=True)
    if not changes:
        fail(422, "NOTHING_TO_UPDATE", "Không có thay đổi nào")
    if "goals" in changes and len(changes["goals"].strip()) < 3:
        fail(422, "GOALS_REQUIRED", "Mục tiêu không được để trống")
    if "responsible_user_id" in changes:
        check_assignee(db, changes["responsible_user_id"], cp.facility_id)
    old_interval = cp.review_interval_days
    bump_version(cp, body.expected_version)
    for k, v in changes.items():
        setattr(cp, k, v)
    rescheduled = 0
    if cp.review_interval_days != old_interval:
        # đổi chu kỳ: dời lịch đang mở theo chu kỳ mới, tính từ lần theo dõi gần nhất (hoặc ngày bắt đầu kế hoạch)
        last = db.scalar(select(func.max(Appointment.completed_at)).where(Appointment.care_plan_id == cp.id, Appointment.status == "completed"))
        base = last.date() if last else cp.start_date
        for a in db.scalars(select(Appointment).where(Appointment.care_plan_id == cp.id, Appointment.status.in_(("scheduled", "due")))):
            a.due_date = base + timedelta(days=cp.review_interval_days)
            a.assignee_id = changes.get("responsible_user_id", a.assignee_id)
            rescheduled += 1
    elif "responsible_user_id" in changes:
        for a in db.scalars(select(Appointment).where(Appointment.care_plan_id == cp.id, Appointment.status.in_(("scheduled", "due")))):
            a.assignee_id = cp.responsible_user_id
    audit(db, user, "care_plan_updated", "CarePlan", cp.id, person_id=cp.person_id, request=request,
          reason=f"đổi: {', '.join(sorted(changes))}" + (f"; dời {rescheduled} lịch" if rescheduled else ""))
    db.commit()
    return to_dict(cp)


@router.post("/care-plans/{plan_id}/end", tags=["scheduling"])
def end_care_plan(plan_id: str, body: ResolveIn, request: Request, user: User = Depends(require("careplan.write")),
                  db: Session = Depends(get_db)):
    cp = db.get(CarePlan, plan_id)
    if not cp:
        fail(404, "NOT_FOUND", "Không tìm thấy kế hoạch")
    ensure_clinical_access(db, user, cp.person_id, request, write=True)
    cp = lock_row(db, CarePlan, plan_id)
    if cp.status != "active":
        fail(409, "PLAN_ENDED", "Kế hoạch đã kết thúc")
    _end_plan(db, cp, body.note)
    audit(db, user, "care_plan_ended", "CarePlan", cp.id, person_id=cp.person_id, reason=body.note, request=request)
    db.commit()
    return to_dict(cp)


@router.get("/persons/{person_id}/care-plans", tags=["scheduling"])
def list_care_plans(person_id: str, request: Request, user: User = Depends(require("clinical.read")),
                    db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request)
    return [to_dict(c) for c in db.scalars(select(CarePlan).where(CarePlan.person_id == person_id))]


# ----------------------------------------------------------------- lịch hẹn
class ApptIn(BaseModel):
    person_id: str
    due_date: date
    note: str | None = None
    assignee_id: str | None = None


@router.post("/appointments", status_code=201, tags=["scheduling"])
@idempotent(201)
def create_appt(body: ApptIn, request: Request, user: User = Depends(require("schedule.write")),
                db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, body.person_id, request, write=True)
    if not active_stay(db, body.person_id, user.facility_id):
        fail(409, "NO_ACTIVE_STAY", "Không có đợt tiếp nhận hiệu lực tại cơ sở")
    if body.due_date < date.today():
        fail(422, "PAST_DUE_DATE", "Ngày hẹn không được ở quá khứ")
    a = Appointment(person_id=body.person_id, facility_id=user.facility_id, kind="follow_up", due_date=body.due_date,
                    note=body.note, assignee_id=check_assignee(db, body.assignee_id, user.facility_id))
    db.add(a)
    audit(db, user, "appointment_created", "Appointment", a.id, person_id=body.person_id, request=request)
    return appt_out(db, a, True)


@router.get("/appointments", tags=["scheduling"])
def list_appts(status: str | None = None, overdue: bool | None = None, assignee_id: str | None = None,
               round_id: str | None = None, kind: str | None = None, limit: int = 200,
               user: User = Depends(require("schedule.read")), db: Session = Depends(get_db)):
    """UAT-05: chỉ thấy nhiệm vụ đúng phạm vi cơ sở (ABAC)."""
    q = select(Appointment).where(Appointment.facility_id == user.facility_id).order_by(Appointment.due_date)
    if status:
        q = q.where(Appointment.status == status)
    if assignee_id:
        q = q.where(Appointment.assignee_id == assignee_id)
    if round_id:
        q = q.where(Appointment.round_id == round_id)
    if kind:
        q = q.where(Appointment.kind == kind)
    if overdue:
        q = q.where(Appointment.status.in_(("scheduled", "due")), Appointment.due_date < date.today())
    with_name = "person.read" in perms_of(user)
    return [appt_out(db, a, with_name) for a in db.scalars(q.limit(max(1, min(limit, 500))))]


class ApptStatusIn(BaseModel):
    to: str = Field(pattern="^(postponed|not_done)$")
    reason: str = Field(min_length=3)
    new_due_date: date | None = None


@router.post("/appointments/{appt_id}/status", tags=["scheduling"])
def appt_status(appt_id: str, body: ApptStatusIn, request: Request, user: User = Depends(require("schedule.write")),
                db: Session = Depends(get_db)):
    a = db.get(Appointment, appt_id)
    if not a or a.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy lịch hẹn")
    ensure_clinical_access(db, user, a.person_id, request, write=True)
    # hạn của lịch định kỳ là hạn chót của đợt, nên ngày hẹn mới được phép sớm hơn hạn cũ – chỉ cấm ngày quá khứ
    if body.to == "postponed" and body.new_due_date and body.new_due_date < date.today():
        fail(422, "BAD_DUE_DATE", "Ngày hẹn mới phải từ hôm nay trở đi")
    a = lock_row(db, Appointment, appt_id)
    if a.status not in OPEN_APPT:
        fail(409, "BAD_TRANSITION", f"Lịch đang ở trạng thái '{a.status}'")
    a.status, a.status_reason = body.to, body.reason
    if body.to == "postponed" and body.new_due_date:
        db.add(Appointment(person_id=a.person_id, facility_id=a.facility_id, kind=a.kind, care_plan_id=a.care_plan_id,
                           round_id=a.round_id, due_date=body.new_due_date, assignee_id=a.assignee_id))
        close_overdue_alerts(db, [a.id], f"Đã hoãn sang {body.new_due_date.strftime('%d/%m/%Y')}: {body.reason}")
    else:
        close_overdue_alerts(db, [a.id], f"{'Đã hoãn' if body.to == 'postponed' else 'Không thực hiện'}: {body.reason}")
    audit(db, user, f"appointment_{body.to}", "Appointment", a.id, person_id=a.person_id, reason=body.reason,
          request=request)
    db.commit()
    return appt_out(db, a, True)


# ----------------------------------------------------------------- cảnh báo
@router.get("/alerts", tags=["scheduling"])
def list_alerts(status: str | None = None, kind: str | None = None, user: User = Depends(require("schedule.read")),
                db: Session = Depends(get_db)):
    q = select(Alert).where(Alert.facility_id == user.facility_id).order_by(Alert.created_at.desc()).limit(300)
    if status:
        q = q.where(Alert.status == status)
    if kind:
        q = q.where(Alert.kind == kind)
    return [to_dict(a) for a in db.scalars(q)]


def _alert_for(db: Session, user: User, alert_id: str) -> Alert:
    a = db.get(Alert, alert_id)
    if not a or a.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy cảnh báo")
    return a


@router.post("/alerts/{alert_id}/acknowledge", tags=["scheduling"])
def ack_alert(alert_id: str, request: Request, user: User = Depends(require("alert.handle")),
              db: Session = Depends(get_db)):
    a = _alert_for(db, user, alert_id)
    if a.status != "new":
        fail(409, "BAD_TRANSITION", f"Cảnh báo đang ở trạng thái '{a.status}'")
    a.status, a.owner_id, a.acknowledged_at = "acknowledged", user.id, utcnow()
    audit(db, user, "alert_acknowledged", "Alert", a.id, person_id=a.person_id, request=request)
    db.commit()
    return to_dict(a)


@router.post("/alerts/{alert_id}/resolve", tags=["scheduling"])
def resolve_alert(alert_id: str, body: ResolveIn, request: Request, user: User = Depends(require("alert.handle")),
                  db: Session = Depends(get_db)):
    a = _alert_for(db, user, alert_id)
    if a.status not in ("new", "acknowledged"):
        fail(409, "BAD_TRANSITION", f"Cảnh báo đang ở trạng thái '{a.status}'")
    if a.kind == "referral_post_review":   # chỉ đóng qua bước hậu kiểm hồ sơ chuyển viện (người có thẩm quyền phê duyệt)
        fail(409, "POST_REVIEW_REQUIRED", "Cảnh báo hậu kiểm chuyển viện chỉ được đóng khi thực hiện hậu kiểm hồ sơ chuyển viện")
    a.owner_id = a.owner_id or user.id  # luôn có người chịu trách nhiệm
    a.status, a.resolution, a.handled_at = "resolved", body.note, utcnow()
    audit(db, user, "alert_resolved", "Alert", a.id, person_id=a.person_id, reason=body.note, request=request)
    db.commit()
    return to_dict(a)


# ----------------------------------------------------------------- đợt khám định kỳ (WF-04)
class RoundIn(BaseModel):
    name: str = Field(min_length=3)
    due_date: date
    min_days_since_last_periodic: int | None = Field(default=None, ge=0)


@router.post("/checkup-rounds", status_code=201, tags=["scheduling"])
def create_round(body: RoundIn, request: Request, user: User = Depends(require("checkup.manage")),
                 db: Session = Depends(get_db)):
    if body.due_date < date.today():
        fail(422, "PAST_DUE_DATE", "Hạn hoàn thành đợt khám không được ở quá khứ")
    r = CheckupRound(name=body.name, facility_id=user.facility_id, due_date=body.due_date, status="open",
                     criteria=body.model_dump(mode="json", exclude={"name", "due_date"}), created_by=user.id)
    db.add(r)
    db.flush()
    excluded, created = [], 0
    # WF-04: danh sách sinh theo hồ sơ ĐANG QUẢN LÝ (đã khám ban đầu); người mới tiếp nhận ghi vào danh sách loại trừ để không bị bỏ sót
    stays = db.scalars(select(CustodyStay).where(CustodyStay.facility_id == user.facility_id,
                                                 CustodyStay.status.in_(("received", "managed"))))
    for s in stays:
        reason = None
        if db.scalars(select(Referral.id).where(Referral.person_id == s.person_id,
                                                Referral.status == "in_external_treatment")).first():
            reason = "Đang điều trị ngoài trại (chuyển viện)"
        elif db.scalars(select(Handover.id).where(Handover.stay_id == s.id, Handover.status == "pending")).first():
            reason = "Đang chờ chuyển trại"
        elif s.status == "received":
            reason = "Chưa hoàn tất khám ban đầu"
        elif db.scalars(select(Appointment.id).where(   # mỗi người tối đa một lịch khám định kỳ đang mở (dù thuộc đợt nào, hạn nào)
                Appointment.person_id == s.person_id, Appointment.kind == "periodic",
                Appointment.status.in_(OPEN_APPT))).first():
            reason = "Đã có lịch khám định kỳ khác đang mở (tránh trùng lịch)"
        elif body.min_days_since_last_periodic is not None:
            last = db.scalar(select(func.max(Encounter.occurred_at)).where(
                Encounter.person_id == s.person_id, Encounter.type == "periodic", Encounter.status == "completed"))
            if last and (utcnow() - last).days < body.min_days_since_last_periodic:
                reason = "Đã khám định kỳ gần đây"
        if reason:
            excluded.append({"person_id": s.person_id, "reason": reason})
            continue
        db.add(Appointment(person_id=s.person_id, facility_id=s.facility_id, kind="periodic", round_id=r.id,
                           due_date=body.due_date))
        created += 1
    r.excluded = excluded
    audit(db, user, "checkup_round_created", "CheckupRound", r.id, reason=f"{created} nhiệm vụ", request=request)
    emit(db, kind="schedule.round", category="schedule", facility_id=user.facility_id, actor=user, perms=("encounter.write",),
         title=f"Đợt khám định kỳ mới: {r.name}", plain=f"{created} nhiệm vụ khám, hạn hoàn thành {body.due_date.strftime('%d/%m/%Y')}.",
         link_page="periodic", link_ref=r.id, dedupe=f"round:{r.id}:new")
    db.commit()
    return {**to_dict(r), "tasks_created": created}


def round_stats(db: Session, r: CheckupRound) -> dict:
    # mỗi người tính MỘT lần theo lịch mới nhất của họ trong đợt: hoãn kèm ngày mới -> bản thay thế thay cho bản đã hoãn
    latest: dict[str, tuple[str, date]] = {}
    for pid, st, due in db.execute(select(Appointment.person_id, Appointment.status, Appointment.due_date).where(
            Appointment.round_id == r.id).order_by(Appointment.recorded_at)):
        latest[pid] = (st, due)
    counts: dict[str, int] = {}
    for st, _ in latest.values():
        counts[st] = counts.get(st, 0) + 1
    total = len(latest)
    overdue = sum(1 for st, due in latest.values() if st in OPEN_APPT and due < date.today())
    done = counts.get("completed", 0)
    # vấn đề sức khỏe mới phát hiện: chỉ của người thuộc đợt, ghi nhận trong thời gian đợt mở (đến lúc khóa)
    new_problems = 0
    if latest:
        q = select(func.count()).select_from(HealthProblem).where(
            HealthProblem.facility_id == r.facility_id, HealthProblem.person_id.in_(list(latest)),
            HealthProblem.recorded_at >= r.recorded_at)
        if r.locked_at:
            q = q.where(HealthProblem.recorded_at <= r.locked_at)
        new_problems = db.scalar(q)
    return {"total": total, "completed": done, "postponed": counts.get("postponed", 0),
            "not_done": counts.get("not_done", 0), "pending": counts.get("scheduled", 0) + counts.get("due", 0),
            "overdue": overdue, "completion_rate": round(done / total, 4) if total else None,
            "excluded_count": len(r.excluded or []), "new_problems_detected": new_problems}


@router.get("/checkup-rounds", tags=["scheduling"])
def list_rounds(user: User = Depends(require("schedule.read")), db: Session = Depends(get_db)):
    return [{**to_dict(r), "stats": round_stats(db, r)} for r in db.scalars(
        select(CheckupRound).where(CheckupRound.facility_id == user.facility_id).order_by(CheckupRound.recorded_at.desc()))]


@router.get("/checkup-rounds/{round_id}", tags=["scheduling"])
def get_round(round_id: str, user: User = Depends(require("schedule.read")), db: Session = Depends(get_db)):
    r = db.get(CheckupRound, round_id)
    if not r or r.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy đợt khám")
    out = {**to_dict(r), "stats": round_stats(db, r)}
    if "person.read" in perms_of(user):
        names = {p.id: p.full_name for p in db.scalars(select(Person).where(
            Person.id.in_([x["person_id"] for x in (r.excluded or [])] or [""])))}
        out["excluded"] = [{**x, "person_name": names.get(x["person_id"])} for x in (r.excluded or [])]
    return out


@router.post("/checkup-rounds/{round_id}/lock", tags=["scheduling"])
def lock_round(round_id: str, request: Request, user: User = Depends(require("checkup.manage")),
               db: Session = Depends(get_db)):
    r = db.get(CheckupRound, round_id)
    if not r or r.facility_id != user.facility_id:
        fail(404, "NOT_FOUND", "Không tìm thấy đợt khám")
    r = lock_row(db, CheckupRound, round_id)
    if r.status == "locked":
        fail(409, "ALREADY_LOCKED", "Đợt khám đã khóa")
    closed = []
    for a in db.scalars(select(Appointment).where(Appointment.round_id == r.id,
                                                   Appointment.status.in_(OPEN_APPT)).with_for_update()):
        a.status, a.status_reason = "not_done", "Khóa đợt khám – chưa khám"  # không bỏ sót: ghi rõ chưa khám
        closed.append(a.id)
    close_overdue_alerts(db, closed, "Khóa đợt khám – chưa khám")
    r.status, r.locked_at = "locked", utcnow()
    audit(db, user, "checkup_round_locked", "CheckupRound", r.id, request=request)
    db.commit()
    return {**to_dict(r), "stats": round_stats(db, r)}


# ----------------------------------------------------------------- scheduler
def run_scheduler(db: Session, escalate_after_hours: float | None = None) -> dict:
    today, now = date.today(), utcnow()
    res = {"marked_due": 0, "overdue_alerts": 0, "care_plan_tasks": 0, "escalated": 0, "postponed_out_of_scope": 0, "notifications_purged": 0, "course_ending_alerts": 0, "course_alerts_closed": 0}
    for a in db.scalars(select(Appointment).where(Appointment.status == "scheduled", Appointment.due_date <= today)):
        a.status = "due"
        res["marked_due"] += 1
    for a in db.scalars(select(Appointment).where(Appointment.status.in_(("scheduled", "due")),
                                                   Appointment.due_date < today)):
        if not active_stay(db, a.person_id, a.facility_id):  # đã chuyển trại/kết thúc
            a.status, a.status_reason = "postponed", "Người không còn thuộc cơ sở"
            res["postponed_out_of_scope"] += 1
            continue
        key = f"overdue:{a.id}"
        if not db.scalars(select(Alert.id).where(Alert.dedupe_key == key)).first():
            al = Alert(person_id=a.person_id, facility_id=a.facility_id, kind="appointment_overdue",
                       message=f"{ {'periodic': 'Lịch khám định kỳ', 'care_plan': 'Lịch theo dõi bệnh mạn tính'}.get(a.kind, 'Lịch tái khám') } quá hạn từ {a.due_date.strftime('%d/%m/%Y')}", dedupe_key=key,
                       owner_id=a.assignee_id)
            db.add(al)
            emit(db, kind="schedule.overdue", category="schedule", severity="warning", facility_id=a.facility_id, perms=("alert.handle",),
                 user_ids=(a.assignee_id,) if a.assignee_id else (), title="Lịch quá hạn cần xử lý", plain=al.message,
                 named=f"{person_name(db, a.person_id)}: {al.message}", link_page="chronic", person_id=a.person_id, dedupe=f"alert:{al.id}:new")
            res["overdue_alerts"] += 1
    for cp in db.scalars(select(CarePlan).where(CarePlan.status == "active")):
        st = active_stay(db, cp.person_id)
        if st and not db.scalars(select(Appointment.id).where(
                Appointment.care_plan_id == cp.id, Appointment.status.in_(OPEN_APPT))).first():
            # lịch kế tiếp theo chu kỳ tính từ lần theo dõi hoàn tất gần nhất (không bắt đầu lại từ ngày chuyển trại)
            last = db.scalar(select(func.max(Appointment.completed_at)).where(
                Appointment.care_plan_id == cp.id, Appointment.status == "completed"))
            due = max(today, (last.date() if last else cp.start_date) + timedelta(days=cp.review_interval_days))
            ru = db.get(User, cp.responsible_user_id) if cp.responsible_user_id else None
            assignee = ru.id if ru and ru.active and ru.facility_id == st.facility_id else None   # không giao cho người cơ sở khác
            db.add(Appointment(person_id=cp.person_id, facility_id=st.facility_id, kind="care_plan",
                               care_plan_id=cp.id, due_date=due, assignee_id=assignee))
            res["care_plan_tasks"] += 1
    # WF-03 bước 6: nhắc hết liệu trình để bác sĩ đánh giá hiệu quả / tái kê / ngừng (không tự đổi trạng thái đơn)
    from .medication import course_end
    horizon = today + timedelta(days=config.MED_COURSE_REMIND_DAYS)
    for o in db.scalars(select(MedicationOrder).where(MedicationOrder.status.in_(("confirmed", "active")))):
        end = course_end(o)
        if end > horizon or not active_stay(db, o.person_id, o.facility_id):
            continue
        key = f"rx-end:{o.id}"
        if db.scalars(select(Alert.id).where(Alert.dedupe_key == key)).first():
            continue
        late = end < today
        msg = f"Đơn {o.drug_name} {'đã hết' if late else 'sắp hết'} liệu trình (đến {end.strftime('%d/%m/%Y')}) – cần đánh giá hiệu quả, tái kê hoặc ngừng thuốc."
        al = Alert(person_id=o.person_id, facility_id=o.facility_id, kind="medication_course_ending", message=msg, dedupe_key=key, owner_id=o.ordered_by)
        db.add(al)
        emit(db, kind="medication.course_ending", category="medication", severity="warning" if late else "info", facility_id=o.facility_id,
             perms=("medorder.write",), user_ids=(o.ordered_by,), title="Đơn thuốc " + ("đã hết" if late else "sắp hết") + " liệu trình", plain=msg,
             named=f"{person_name(db, o.person_id)}: {msg}", link_page="rx", link_ref=o.id, person_id=o.person_id, dedupe=f"alert:{al.id}:new")
        res["course_ending_alerts"] += 1
    # cảnh báo hết liệu trình tự đóng khi bác sĩ đã xử lý đơn (ngừng/hoàn thành/thay bằng bản mới)
    for al in db.scalars(select(Alert).where(Alert.kind == "medication_course_ending", Alert.status.in_(("new", "acknowledged")))):
        order = db.get(MedicationOrder, (al.dedupe_key or "").removeprefix("rx-end:"))
        if order and order.status not in ("confirmed", "active"):
            al.status, al.resolution, al.handled_at = "resolved", "Đơn đã được xử lý (ngừng/hoàn thành/thay bản mới)", now
            res["course_alerts_closed"] += 1
    hours = config.ALERT_ESCALATE_HOURS if escalate_after_hours is None else escalate_after_hours
    cutoff = now - timedelta(hours=hours)
    for al in db.scalars(select(Alert).where(Alert.status == "new", Alert.level < 3)):
        if (al.escalated_at or al.created_at) <= cutoff:
            al.level += 1
            al.escalated_at = now  # nâng cấp trách nhiệm theo cấu hình
            emit(db, kind="schedule.escalated", category="schedule", severity="critical", facility_id=al.facility_id, perms=("report.read",),
                 user_ids=(al.owner_id,) if al.owner_id else (), title=f"Cảnh báo chưa xử lý đã nâng mức {al.level}", plain=al.message,
                 link_page="chronic", person_id=al.person_id, dedupe=f"alert:{al.id}:esc:{al.level}")
            res["escalated"] += 1
    res["notifications_purged"] = purge(db)
    db.commit()
    return res


@router.post("/scheduler/run", tags=["scheduling"])
def scheduler_run(request: Request, escalate_after_hours: float | None = None,
                  user: User = Depends(require("scheduler.run")), db: Session = Depends(get_db)):
    res = run_scheduler(db, escalate_after_hours)
    audit(db, user, "scheduler_run", reason=str(res), request=request, commit=True)
    return res
