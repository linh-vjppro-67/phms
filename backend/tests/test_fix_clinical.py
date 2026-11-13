"""Hồi quy các lỗi kiểm thử thực tế: nhánh quản lý (MB), sinh hiệu (IH#12), ghi lâm sàng chỉ ở cơ sở đang quản lý (C1)."""
from datetime import date, datetime, timedelta

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Appointment, CarePlan
from app.utils import utcnow


def uid(api, username):
    return next(u["id"] for u in api.get("admin", "/api/users").json() if u["username"] == username)


def plan_for(api, pid, user="doctor1", **extra):
    prob = api.post(user, f"/api/persons/{pid}/problems", {"name": "Tăng huyết áp"}).json()
    r = api.post(user, f"/api/persons/{pid}/care-plans", {"problem_id": prob["id"], "goals": "Huyết áp < 140/90",
                                                         "review_interval_days": 30, **extra})
    assert r.status_code == 201, r.text
    return prob, r.json()


def plan_appts(api, plan_id, user="nurse1"):
    return [a for a in api.get(user, "/api/appointments?kind=care_plan").json() if a["care_plan_id"] == plan_id]


def transfer(api, stay_id, pid):
    h = api.post("officer1", f"/api/stays/{stay_id}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Theo dõi huyết áp"})
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 200
    assert api.post("officer2", f"/api/persons/{pid}/stays", {}).status_code == 201


# ------------------------------------------------------------------ C1: ghi lâm sàng chỉ ở cơ sở đang quản lý
def test_old_facility_cannot_write_after_transfer(api):
    p, s = api.managed("CF1", "Chuyển Trại Ghi")
    prob, plan = plan_for(api, p["id"])
    e = api.encounter(p["id"])
    transfer(api, s["id"], p["id"])
    pid = p["id"]
    assert api.post("nurse1", f"/api/persons/{pid}/allergies", {"substance": "Penicillin"}).status_code == 403
    assert api.post("doctor1", f"/api/persons/{pid}/problems", {"name": "Đái tháo đường"}).status_code == 403
    assert api.patch("doctor1", f"/api/care-plans/{plan['id']}", {"goals": "Sửa từ trại cũ"}).status_code == 403
    assert api.post("doctor1", f"/api/problems/{prob['id']}/resolve", {"note": "Khỏi"}).status_code == 403
    assert api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Cần chụp CT ngoài"}).status_code == 403
    assert api.get("doctor1", f"/api/persons/{pid}/health-summary").status_code == 200       # cơ sở cũ vẫn xem được lịch sử


def test_break_glass_is_read_only(api):
    p, _ = api.managed("CF2", "Khẩn Cấp Chỉ Đọc")
    assert api.post("doctor2", f"/api/persons/{p['id']}/break-glass", {"reason": "Cấp cứu ngoài giờ cần xem tiền sử"}).status_code == 200
    assert api.get("doctor2", f"/api/persons/{p['id']}/health-summary").status_code == 200
    assert api.post("doctor2", f"/api/persons/{p['id']}/allergies", {"substance": "Penicillin", "confirmed": True}).status_code == 403
    assert api.post("doctor2", f"/api/persons/{p['id']}/allergy-status/none-confirmed").status_code == 403
    assert api.post("doctor2", f"/api/persons/{p['id']}/problems", {"name": "Vấn đề BG"}).status_code == 403


# ------------------------------------------------------------------ MB#3/#4: lịch hẹn – lượt khám
def test_one_open_encounter_per_appointment_and_no_duplicate_follow_up(api):
    p, _ = api.managed("CF3", "Một Lịch Một Lượt")
    _, plan = plan_for(api, p["id"])
    ap = plan_appts(api, plan["id"])[0]
    e1 = api.encounter(p["id"], appointment_id=ap["id"])
    r = api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "ad_hoc", "appointment_id": ap["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPOINTMENT_IN_PROGRESS"
    assert api.post("doctor1", f"/api/encounters/{e1['id']}/transition", {"to": "completed"}).status_code == 200
    open_ = [a for a in plan_appts(api, plan["id"]) if a["status"] in ("scheduled", "due")]
    assert len(open_) == 1


def test_completing_encounter_does_not_touch_closed_appointment(api):
    p, _ = api.managed("CF4", "Lịch Đã Hoãn")
    _, plan = plan_for(api, p["id"])
    ap = plan_appts(api, plan["id"])[0]
    e = api.encounter(p["id"], appointment_id=ap["id"])
    assert api.post("nurse1", f"/api/appointments/{ap['id']}/status", {"to": "not_done", "reason": "Từ chối khám"}).status_code == 200
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 200
    rows = plan_appts(api, plan["id"])
    assert [a["status"] for a in rows] == ["not_done"]                     # không bị ghi đè, không sinh lịch theo dõi mới


def test_locked_round_does_not_change_after_lock(api):
    p, _ = api.managed("CF5", "Đợt Đã Khóa")
    rnd = api.post("manager1", "/api/checkup-rounds", {"name": "Đợt khóa", "due_date": str(date.today() + timedelta(days=5))}).json()
    ap = api.get("nurse1", f"/api/appointments?round_id={rnd['id']}").json()[0]
    e = api.encounter(p["id"], type="periodic", appointment_id=ap["id"])
    before = api.post("manager1", f"/api/checkup-rounds/{rnd['id']}/lock").json()["stats"]
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 200
    after = api.get("manager1", f"/api/checkup-rounds/{rnd['id']}").json()["stats"]
    assert before["completed"] == after["completed"] == 0 and after["not_done"] == 1
    assert api.get("nurse1", f"/api/appointments?round_id={rnd['id']}").json()[0]["status"] == "not_done"


# ------------------------------------------------------------------ MB#5 / IH#12: sinh hiệu
def test_abnormal_vital_creates_alert_and_notifies_doctor(api):
    p, _ = api.managed("CF6", "Sinh Hiệu Bất Thường")
    e = api.encounter(p["id"])
    obs = lambda t, v, u: api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": t, "value": v, "unit": u})  # noqa: E731
    assert obs("SpO2", "97", "%").status_code == 201
    assert not [a for a in api.get("nurse1", "/api/alerts?kind=abnormal_result").json() if a["person_id"] == p["id"]]
    assert obs("SpO2", "82", "%").status_code == 201
    alerts = [a for a in api.get("nurse1", "/api/alerts?kind=abnormal_result").json() if a["person_id"] == p["id"]]
    assert len(alerts) == 1 and "SpO2" in alerts[0]["message"] and "82" not in alerts[0]["message"]
    inbox = api.get("doctor1", "/api/notifications").json()["items"]
    assert any(n["kind"] == "clinical.abnormal" for n in inbox)


def test_vital_type_normalized_and_unit_checked(api):
    p, _ = api.patient("CF7", "Sinh Hiệu Chuẩn Hóa")
    e = api.encounter(p["id"])
    obs = lambda t, v, u: api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": t, "value": v, "unit": u})  # noqa: E731
    for t in ("mạch", "Mạch ", "MẠCH", "Mach"):
        r = obs(t, "500", "lần/phút")
        assert r.status_code == 422 and r.json()["error"]["code"] == "OBS_OUT_OF_RANGE", t
    assert obs("Nhiệt độ", "37", "°F").json()["error"]["code"] == "OBS_BAD_UNIT"
    assert obs("Cân nặng", "70", "g").json()["error"]["code"] == "OBS_BAD_UNIT"
    assert obs("Huyết áp", "400/300", "mmHg").json()["error"]["code"] == "OBS_OUT_OF_RANGE"
    ok = obs("  mạch", "80", "bpm")
    assert ok.status_code == 201 and ok.json()["type"] == "Mạch" and ok.json()["unit"] == "lần/phút"


# ------------------------------------------------------------------ MB#6/#7: người phụ trách / lịch hẹn
def test_assignee_validated_on_care_plan_and_appointment(api):
    p, _ = api.managed("CF8", "Người Phụ Trách")
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}).json()
    body = {"problem_id": prob["id"], "goals": "Huyết áp ổn", "review_interval_days": 30}
    for bad in ("00000000-0000-0000-0000-000000000000", uid(api, "doctor2"), uid(api, "officer1")):
        r = api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {**body, "responsible_user_id": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "BAD_ASSIGNEE"
        r = api.post("nurse1", "/api/appointments", {"person_id": p["id"], "due_date": str(date.today()), "assignee_id": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "BAD_ASSIGNEE"
    assert api.post("nurse1", "/api/appointments", {"person_id": p["id"], "due_date": "2000-01-01"}).status_code == 422
    assert api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {**body, "responsible_user_id": uid(api, "nurse1")}).status_code == 201


# ------------------------------------------------------------------ MB#8/#9/#10: kết thúc kế hoạch, vấn đề
def overdue_plan(api, ext):
    p, _ = api.managed(ext, "Quá Hạn " + ext)
    prob, plan = plan_for(api, p["id"], start_date=str(date.today() - timedelta(days=40)))
    api.post("admin", "/api/scheduler/run")
    alert = next(a for a in api.get("nurse1", "/api/alerts?kind=appointment_overdue").json() if a["person_id"] == p["id"])
    return p, prob, plan, alert


def alert_status(api, alert_id):
    return next(a["status"] for a in api.get("nurse1", "/api/alerts").json() if a["id"] == alert_id)


def test_ending_plan_resolves_overdue_alert_and_cannot_repeat(api):
    _, _, plan, alert = overdue_plan(api, "CF9")
    assert api.post("doctor1", f"/api/care-plans/{plan['id']}/end", {"note": "Ổn định"}).status_code == 200
    assert alert_status(api, alert["id"]) == "resolved"
    r = api.post("doctor1", f"/api/care-plans/{plan['id']}/end", {"note": "Lần hai"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLAN_ENDED"


def test_postpone_resolves_overdue_alert_and_validates_date(api):
    _, _, plan, alert = overdue_plan(api, "CF10")
    ap = plan_appts(api, plan["id"])[0]
    st = lambda d: api.post("nurse1", f"/api/appointments/{ap['id']}/status", {"to": "postponed", "reason": "Lao động", "new_due_date": d})  # noqa: E731
    assert st("2000-01-01").status_code == 422
    assert st(str(date.today() + timedelta(days=3))).status_code == 200
    assert alert_status(api, alert["id"]) == "resolved"


def test_resolving_problem_with_active_plan_and_twice(api):
    p, _ = api.managed("CF11", "Vấn Đề Còn Kế Hoạch")
    prob, plan = plan_for(api, p["id"])
    r = api.post("doctor1", f"/api/problems/{prob['id']}/resolve", {"note": "Đã khỏi"})
    assert r.status_code == 409 and r.json()["error"]["care_plan_ids"] == [plan["id"]]
    assert api.post("doctor1", f"/api/problems/{prob['id']}/resolve", {"note": "Đã khỏi", "end_plans": True}).status_code == 200
    assert api.get("doctor1", f"/api/persons/{p['id']}/care-plans").json()[0]["status"] == "ended"
    assert not [a for a in plan_appts(api, plan["id"]) if a["status"] in ("scheduled", "due")]
    assert api.post("doctor1", f"/api/problems/{prob['id']}/resolve", {"note": "Lần hai"}).status_code == 409


# ------------------------------------------------------------------ MB#11/#12/#21: đợt khám định kỳ
def test_round_rejects_past_due_and_duplicate_open_periodic(api):
    p, _ = api.managed("CF12", "Đợt Trùng")
    assert api.post("manager1", "/api/checkup-rounds", {"name": "Đợt cũ", "due_date": "2020-01-01"}).status_code == 422
    api.post("manager1", "/api/checkup-rounds", {"name": "Đợt 1", "due_date": str(date.today() + timedelta(days=10))})
    r2 = api.post("manager1", "/api/checkup-rounds", {"name": "Đợt 2", "due_date": str(date.today() + timedelta(days=5))}).json()
    assert r2["tasks_created"] == 0 and r2["excluded"][0]["person_id"] == p["id"]


def test_postponed_round_task_counted_once(api):
    api.managed("CF13", "Hoãn Đợt")
    rnd = api.post("manager1", "/api/checkup-rounds", {"name": "Đợt hoãn", "due_date": str(date.today() + timedelta(days=2))}).json()
    ap = api.get("nurse1", f"/api/appointments?round_id={rnd['id']}").json()[0]
    api.post("nurse1", f"/api/appointments/{ap['id']}/status", {"to": "postponed", "reason": "Lao động", "new_due_date": str(date.today() + timedelta(days=4))})
    stats = api.get("manager1", f"/api/checkup-rounds/{rnd['id']}").json()["stats"]
    assert stats["total"] == 1 and stats["pending"] == 1 and stats["postponed"] == 0


def test_round_new_problems_only_round_people_until_lock(api):
    a, _ = api.managed("CF14", "Trong Đợt")
    b, _ = api.patient("CF15", "Ngoài Đợt")                      # mới tiếp nhận -> bị loại khỏi đợt
    rnd = api.post("manager1", "/api/checkup-rounds", {"name": "Đợt vấn đề", "due_date": str(date.today() + timedelta(days=2))}).json()
    stat = lambda: api.get("manager1", f"/api/checkup-rounds/{rnd['id']}").json()["stats"]["new_problems_detected"]  # noqa: E731
    api.post("doctor1", f"/api/persons/{b['id']}/problems", {"name": "Viêm da"})
    assert stat() == 0
    api.post("doctor1", f"/api/persons/{a['id']}/problems", {"name": "Viêm phế quản"})
    assert stat() == 1
    api.post("manager1", f"/api/checkup-rounds/{rnd['id']}/lock")
    api.post("doctor1", f"/api/persons/{a['id']}/problems", {"name": "Đau lưng"})
    assert stat() == 1


# ------------------------------------------------------------------ MB#13–#17: chuyển viện
def referral(api, pid, urgency="routine", user="doctor1"):
    e = api.encounter(pid)
    r = api.post(user, f"/api/encounters/{e['id']}/referrals", {"urgency": urgency, "reason": "Cần chụp CT ngoài", "destination": "BV A"})
    assert r.status_code == 201, r.text
    return e, r.json()


def test_post_review_alert_only_closed_by_post_review(api):
    p, _ = api.managed("CF16", "Hậu Kiểm")
    _, ref = referral(api, p["id"], "emergency")
    assert api.patch("nurse1", f"/api/referrals/{ref['id']}/status", {"to": "in_external_treatment"}).json()["needs_post_review"]
    al = next(a for a in api.get("nurse1", "/api/alerts?kind=referral_post_review").json() if a["person_id"] == p["id"])
    r = api.post("nurse1", f"/api/alerts/{al['id']}/resolve", {"note": "Đã xem"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "POST_REVIEW_REQUIRED"
    assert api.post("approver1", f"/api/referrals/{ref['id']}/post-review", {"note": "Hợp lý"}).status_code == 200
    assert alert_status(api, al["id"]) == "resolved"


def test_approved_emergency_referral_is_not_a_shortcut(api):
    p, _ = api.managed("CF17", "Cấp Cứu Đã Duyệt")
    _, ref = referral(api, p["id"], "emergency")
    ch = lambda u, b: api.patch(u, f"/api/referrals/{ref['id']}/status", b)  # noqa: E731
    ch("doctor1", {"to": "pending"})
    ch("approver1", {"to": "coordinated"})
    r = ch("nurse1", {"to": "in_external_treatment"}).json()
    assert r["status"] == "in_external_treatment" and not r["shortcut_used"] and not r["needs_post_review"]


def test_referral_rejected_on_cancelled_encounter(api):
    p, _ = api.managed("CF18", "Lượt Khám Hủy")
    e = api.encounter(p["id"])
    api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "cancelled", "reason": "Nhầm người"})
    r = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Cần chụp CT ngoài"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ENCOUNTER_CANCELLED"


def test_one_referral_in_progress_per_person(api):
    p, _ = api.managed("CF19", "Hai Bệnh Viện")
    _, r1 = referral(api, p["id"])
    _, r2 = referral(api, p["id"])                               # nháp thứ hai được lập
    assert api.patch("doctor1", f"/api/referrals/{r1['id']}/status", {"to": "pending"}).status_code == 200
    r = api.patch("doctor1", f"/api/referrals/{r2['id']}/status", {"to": "pending"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REFERRAL_OPEN"
    e3 = api.encounter(p["id"])
    assert api.post("doctor1", f"/api/encounters/{e3['id']}/referrals", {"reason": "Lần ba"}).json()["error"]["code"] == "REFERRAL_OPEN"


def test_left_at_validated(api):
    p, _ = api.managed("CF20", "Rời Trại")
    _, ref = referral(api, p["id"])
    ch = lambda u, b: api.patch(u, f"/api/referrals/{ref['id']}/status", b)  # noqa: E731
    ch("doctor1", {"to": "pending"})
    ch("approver1", {"to": "coordinated"})
    future = (utcnow() + timedelta(days=30)).isoformat()
    assert ch("nurse1", {"to": "in_external_treatment", "left_at": future}).json()["error"]["code"] == "FUTURE_TIME"
    assert ch("nurse1", {"to": "in_external_treatment", "left_at": "2001-01-01T00:00:00"}).json()["error"]["code"] == "BAD_LEFT_AT"
    assert ch("nurse1", {"to": "in_external_treatment", "left_at": utcnow().isoformat()}).status_code == 200


# ------------------------------------------------------------------ MB#20 / MB#22 / CC#13
def test_encounter_not_before_stay_start(api):
    p, _ = api.patient("CF21", "Khám Trước Tiếp Nhận")
    r = api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "ad_hoc", "occurred_at": "2001-01-01T08:00:00"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "BEFORE_STAY"


def test_scheduler_follow_up_uses_interval_and_same_facility_assignee(api):
    p, _ = api.managed("CF22", "Lịch Sau Chuyển")
    _, plan = plan_for(api, p["id"], responsible_user_id=uid(api, "doctor1"))
    # dữ liệu cũ: lần theo dõi gần nhất 10 ngày trước, người phụ trách nay thuộc cơ sở khác, không còn lịch mở
    other = uid(api, "doctor2")   # gọi API TRƯỚC khi mở phiên DB (CSDL thử dùng chung một kết nối)
    with SessionLocal() as s:
        s.execute(update(Appointment).where(Appointment.care_plan_id == plan["id"]).values(
            status="completed", completed_at=datetime.combine(date.today() - timedelta(days=10), datetime.min.time())))
        s.execute(update(CarePlan).where(CarePlan.id == plan["id"]).values(responsible_user_id=other))
        s.commit()
    assert api.post("admin", "/api/scheduler/run").json()["care_plan_tasks"] == 1
    nxt = next(a for a in plan_appts(api, plan["id"]) if a["status"] == "scheduled")
    assert nxt["due_date"] == str(date.today() + timedelta(days=20)) and nxt["assignee_id"] is None


def test_worklist_negative_limit_is_clamped(api):
    for i in range(2):
        p, _ = api.patient(f"CF3{i}", f"Giới Hạn {i}")
        api.encounter(p["id"])
    assert len(api.get("doctor1", "/api/encounters?limit=-1").json()) == 1
    assert len(api.get("nurse1", "/api/appointments?limit=-1").json()) <= 1
