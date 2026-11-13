"""M10: báo cáo & chỉ số quản trị. Định nghĩa đếm rõ ràng: lượt ≠ người ≠ đợt (UAT-12).
Chỉ trả số liệu tổng hợp, không có định danh; luôn lọc theo cơ sở của người dùng."""
import csv
import io
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import require
from ..models import (Alert, Appointment, CustodyStay, Encounter, HealthProblem, MedicationOrder, Referral, User)
from ..permissions import perms_of
from ..utils import fail, utcnow
from .medication import dispense_totals

router = APIRouter()


def _range(date_from: date | None, date_to: date | None):
    to = date_to or date.today()
    frm = date_from or (to - timedelta(days=30))
    if frm > to:
        fail(422, "BAD_RANGE", "date_from phải ≤ date_to")
    return datetime.combine(frm, time.min), datetime.combine(to, time.max), frm, to


def r_encounters(db, fac, a, b, frm, to):
    rows = db.execute(select(Encounter.type, func.count(Encounter.id), func.count(func.distinct(Encounter.person_id)))
                      .where(Encounter.facility_id == fac, Encounter.occurred_at.between(a, b),
                             Encounter.status != "cancelled").group_by(Encounter.type)).all()
    total_persons = db.scalar(select(func.count(func.distinct(Encounter.person_id))).where(
        Encounter.facility_id == fac, Encounter.occurred_at.between(a, b), Encounter.status != "cancelled"))
    return {"by_type": {t: {"encounter_count": c, "distinct_person_count": p} for t, c, p in rows},
            "total_encounters": sum(c for _, c, _ in rows), "total_distinct_persons": total_persons or 0,
            "cancelled_encounters": db.scalar(select(func.count()).select_from(Encounter).where(
                Encounter.facility_id == fac, Encounter.occurred_at.between(a, b), Encounter.status == "cancelled")),
            "definition": "Lượt khám đếm theo Encounter; số người đếm distinct person_id."}


def r_checkups(db, fac, a, b, frm, to):
    q = select(Appointment.status, func.count()).where(Appointment.facility_id == fac, Appointment.kind == "periodic",
                                                       Appointment.due_date.between(frm, to)).group_by(Appointment.status)
    c = dict(db.execute(q).all())
    total = sum(c.values())
    overdue = db.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.facility_id == fac, Appointment.kind == "periodic", Appointment.due_date.between(frm, to),
        Appointment.status.in_(("scheduled", "due")), Appointment.due_date < date.today()))
    return {"total_due": total, "completed": c.get("completed", 0), "postponed": c.get("postponed", 0),
            "not_done": c.get("not_done", 0), "pending": c.get("scheduled", 0) + c.get("due", 0), "overdue": overdue,
            "completion_rate": round(c.get("completed", 0) / total, 4) if total else None}


def r_problems(db, fac, a, b, frm, to):
    # theo cơ sở ĐANG quản lý người bệnh (đợt tiếp nhận còn hiệu lực), không theo cơ sở đã ghi nhận vấn đề;
    # vấn đề tính khi có hiệu lực trong khoảng ngày [date_from, date_to]
    managed_here = select(CustodyStay.id).where(CustodyStay.person_id == HealthProblem.person_id, CustodyStay.facility_id == fac,
                                                CustodyStay.status.in_(("received", "managed"))).exists()
    in_range = and_(HealthProblem.effective_from <= to,
                    or_(and_(HealthProblem.effective_to.is_(None), HealthProblem.status == "active"),
                        HealthProblem.effective_to >= frm))
    n = func.count(func.distinct(HealthProblem.person_id))
    rows = db.execute(select(HealthProblem.name, n).where(managed_here, in_range)
                      .group_by(HealthProblem.name).order_by(n.desc())).all()
    return {"active_by_problem": {name: c for name, c in rows},
            "note": "Số người đang do cơ sở quản lý có vấn đề sức khỏe còn hiệu lực trong khoảng ngày; không kèm định danh."}


def r_dispensing(db, fac, a, b, frm, to):
    orders = db.scalars(select(MedicationOrder).where(
        MedicationOrder.facility_id == fac, MedicationOrder.confirmed_at.between(a, b),
        MedicationOrder.status != "draft")).all()
    out = {"confirmed_orders": len(orders), "fully_dispensed": 0, "partially_dispensed": 0, "not_dispensed": 0}
    for o in orders:
        out[{"full": "fully_dispensed", "partial": "partially_dispensed", "none": "not_dispensed"}[
            dispense_totals(db, o)["dispense_status"]]] += 1
    from ..models import DispenseEvent
    out["dispense_events"] = db.scalar(select(func.count()).select_from(DispenseEvent).join(
        MedicationOrder, MedicationOrder.id == DispenseEvent.order_id).where(
        MedicationOrder.facility_id == fac, DispenseEvent.kind == "dispense", DispenseEvent.occurred_at.between(a, b)))
    out["note"] = "Số đơn ≠ số lần uống; cấp phát ≠ sử dụng."
    return out


def r_referrals(db, fac, a, b, frm, to):
    refs = db.scalars(select(Referral).where(Referral.facility_id == fac, Referral.recorded_at.between(a, b))).all()
    by: dict[str, int] = {}
    for r in refs:
        by[r.status] = by.get(r.status, 0) + 1
    hrs = [(r.left_at - r.recorded_at).total_seconds() / 3600 for r in refs if r.left_at]
    return {"total": len(refs), "by_status": by,
            "avg_hours_to_departure": round(sum(hrs) / len(hrs), 2) if hrs else None,
            "without_result": sum(1 for r in refs if r.status == "in_external_treatment"),
            "needs_post_review": sum(1 for r in refs if r.needs_post_review)}


def r_alerts(db, fac, a, b, frm, to):
    overdue = db.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.facility_id == fac, Appointment.status.in_(("scheduled", "due")), Appointment.due_date < date.today()))
    unresolved = db.scalar(select(func.count()).select_from(Alert).where(
        Alert.facility_id == fac, Alert.status.in_(("new", "acknowledged"))))
    by_role: dict[str, list[float]] = {}
    for al, role in db.execute(select(Alert, User.role).join(User, User.id == Alert.owner_id).where(
            Alert.facility_id == fac, Alert.handled_at.is_not(None), Alert.created_at.between(a, b))):
        by_role.setdefault(role, []).append((al.handled_at - al.created_at).total_seconds() / 3600)
    return {"overdue_appointments": overdue, "unresolved_alerts": unresolved,
            "avg_handle_hours_by_role": {k: round(sum(v) / len(v), 2) for k, v in by_role.items()}}


REPORTS = {"encounters": r_encounters, "checkups": r_checkups, "health-problems": r_problems,
           "dispensing": r_dispensing, "referrals": r_referrals, "alerts": r_alerts}


def _flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


@router.get("/reports/{name}", tags=["reports"])
def report(name: str, request: Request, date_from: date | None = None, date_to: date | None = None,
           format: str = "json", purpose: str | None = None, user: User = Depends(require("report.read")),
           db: Session = Depends(get_db)):
    if name not in REPORTS:
        fail(404, "UNKNOWN_REPORT", f"Báo cáo hợp lệ: {sorted(REPORTS)}")
    a, b, frm, to = _range(date_from, date_to)
    data = REPORTS[name](db, user.facility_id, a, b, frm, to)
    body = {"report": name, "facility_id": user.facility_id, "date_from": frm, "date_to": to,
            "generated_at": utcnow(), "data": data}
    if format == "csv":
        if "report.export" not in perms_of(user):
            audit(db, user, "report_export_denied", name, result="denied", request=request, commit=True)
            fail(403, "FORBIDDEN", "Không có quyền xuất dữ liệu")
        if not purpose or len(purpose.strip()) < 5:
            fail(422, "PURPOSE_REQUIRED", "Xuất dữ liệu phải nêu mục đích/căn cứ")
        audit(db, user, "report_exported", name, reason=purpose, request=request)
        db.commit()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["metric", "value"])
        for k, v in _flatten(data):
            w.writerow([k, v])
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    audit(db, user, "report_viewed", name, request=request)
    db.commit()
    return body
