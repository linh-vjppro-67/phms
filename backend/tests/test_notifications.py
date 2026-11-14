"""Thông báo: đúng người nhận, đúng cơ sở, riêng tư, không trùng, chống IDOR, tùy chọn, lưu giữ."""
from datetime import timedelta
from urllib.parse import quote

from app import notify
from app.db import SessionLocal
from app.models import AuditEvent, Notification
from app.utils import utcnow


def inbox(api, user, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return api.get(user, "/api/notifications" + (f"?{qs}" if qs else "")).json()


def kinds(api, user):
    return [n["kind"] for n in inbox(api, user)["items"]]


# ------------------------------------------------------------ người nhận đúng
def test_emergency_notifies_clinical_staff_of_same_facility_but_not_actor_or_other_facility(api):
    r = api.post("nurse1", "/api/emergency-events", {"temp_identity": "Nam ~40 tuổi, buồng 5", "location": "Buồng 5", "description": "Co giật toàn thân"})
    assert r.status_code == 201
    d = inbox(api, "doctor1")
    n = next(x for x in d["items"] if x["kind"] == "emergency.created")
    assert n["severity"] == "critical" and n["title"].startswith("CẤP CỨU") and n["link_page"] == "emergency" and n["link_ref"] == r.json()["id"]
    assert "Co giật" in n["body"] and d["unread"] == 1 and d["critical"] == 1
    assert "emergency.created" not in kinds(api, "nurse1")      # không tự báo cho người thực hiện
    assert kinds(api, "doctor2") == [] and kinds(api, "nurse2") == []   # cơ sở khác không nhận
    assert kinds(api, "manager1") == [] and kinds(api, "pharm1") == []  # không có quyền liên quan
    # hồ sơ tạm cần đối soát -> cán bộ tiếp nhận (không phải nhân viên y tế)
    o = inbox(api, "officer1")["items"]
    assert [x["kind"] for x in o] == ["emergency.identity"] and o[0]["link_page"] == "intake"
    assert "Co giật" not in str(o)    # cán bộ quản lý không được thấy nội dung lâm sàng


def test_referral_flow_routes_to_right_roles(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"urgency": "urgent", "reason": "Nghi viêm ruột thừa", "destination": "BV A"}).json()
    ch = lambda u, b: api.patch(u, f"/api/referrals/{ref['id']}/status", b)  # noqa: E731
    ch("doctor1", {"to": "pending"})
    a = [n for n in inbox(api, "approver1")["items"] if n["kind"] == "referral.pending"]
    assert len(a) == 1 and a[0]["severity"] == "warning" and a[0]["link_ref"] == ref["id"] and p["full_name"] in a[0]["body"]
    assert "Nghi viêm" not in str(a)                       # không lộ lý do chuyên môn
    assert "referral.pending" not in kinds(api, "doctor1")   # người gửi không tự nhận
    ch("approver1", {"to": "coordinated"})
    assert "referral.coordinated" in kinds(api, "doctor1") and "referral.coordinated" in kinds(api, "nurse1")
    assert "referral.coordinated" not in kinds(api, "approver1")
    ch("nurse1", {"to": "in_external_treatment"})
    ch("nurse1", {"to": "result_received", "result_note": "ổn định"})
    assert "referral.result" in kinds(api, "doctor1")


def test_emergency_shortcut_is_critical_for_approver_and_manager_without_patient_name(api):
    p, _ = api.patient(name="Trần Văn Cấp Cứu")
    e = api.encounter(p["id"])
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"urgency": "emergency", "reason": "Đau ngực cấp", "destination": "BV Tim"}).json()
    assert api.patch("nurse1", f"/api/referrals/{ref['id']}/status", {"to": "in_external_treatment"}).status_code == 200
    ap = next(n for n in inbox(api, "approver1")["items"] if n["kind"] == "referral.shortcut")
    mg = next(n for n in inbox(api, "manager1")["items"] if n["kind"] == "referral.shortcut")
    assert ap["severity"] == mg["severity"] == "critical"
    assert "Trần Văn Cấp Cứu" in ap["body"]          # approver có person.read
    assert "Trần Văn Cấp Cứu" not in mg["body"]      # manager không có quyền xem danh tính


def test_lab_result_goes_only_to_ordering_doctor(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Công thức máu"}).json()
    api.post("nurse1", f"/api/orders/{o['id']}/result", {"result_text": "Bình thường"})
    n = [x for x in inbox(api, "doctor1")["items"] if x["kind"] == "clinical.resulted"]
    assert len(n) == 1 and n[0]["link_page"] == "exam" and n[0]["link_ref"] == e["id"]
    assert "clinical.resulted" not in kinds(api, "nurse1") and kinds(api, "doctor2") == []


def test_confirmed_order_notifies_dispensers_not_prescriber(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"])
    assert "medication.confirmed" in kinds(api, "pharm1") and "medication.confirmed" not in kinds(api, "nurse1")   # điều dưỡng không cấp phát
    assert "medication.confirmed" not in kinds(api, "doctor1") and kinds(api, "pharm2") == []
    assert inbox(api, "pharm1")["items"][0]["link_ref"] == o["id"]


def test_handover_chain_notifications(api):
    p, s = api.patient()
    h = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    assert "handover.initiated" in kinds(api, "nurse1") and "handover.initiated" not in kinds(api, "officer1")
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Cần theo dõi huyết áp hằng tuần"})
    assert "handover.ready" in kinds(api, "officer1") and "handover.ready" in kinds(api, "approver1")
    api.post("officer1", f"/api/handovers/{h['id']}/confirm", {})
    inc = next(n for n in inbox(api, "officer2")["items"] if n["kind"] == "handover.incoming")
    assert inc["link_page"] == "intake" and inc["link_ref"] == p["id"]
    assert kinds(api, "officer1").count("handover.incoming") == 0


def test_new_intake_notifies_clinical_staff(api):
    p = api.person()
    api.stay(p["id"])
    assert "intake.new_person" in kinds(api, "nurse1") and "intake.new_person" in kinds(api, "doctor1")
    assert kinds(api, "nurse2") == [] and "intake.new_person" not in kinds(api, "officer1")


def test_security_events_reach_managers_and_admins(api):
    p, _ = api.patient()
    api.get("doctor2", f"/api/persons/{p['id']}/health-summary", headers={"X-Break-Glass-Reason": quote("Nghi ngộ độc, cần tiền sử dị ứng gấp")})
    for u in ("manager2", "admin"):
        n = [x for x in inbox(api, u)["items"] if x["kind"] == "security.break_glass"]
        assert len(n) == 1 and n[0]["severity"] == "critical"
        assert p["full_name"] not in str(n)           # không nêu tên người bệnh
    assert kinds(api, "manager1") == []                # manager cơ sở của người bệnh không phải cơ sở người xem
    for _ in range(5):
        api.c.post("/api/auth/login", json={"username": "nurse2", "password": "sai"})
    assert "security.lockout" in kinds(api, "admin")


def test_scheduler_overdue_and_escalation_notify_once(api):
    from datetime import date
    p, _ = api.patient()
    api.post("nurse1", "/api/appointments", {"person_id": p["id"], "due_date": str(date.today())})
    with SessionLocal() as db:   # đẩy lịch về quá khứ
        from app.models import Appointment
        for a in db.query(Appointment).all():
            a.due_date = date.today() - timedelta(days=3)
        db.commit()
    api.post("admin", "/api/scheduler/run")
    api.post("admin", "/api/scheduler/run")      # chạy lại: không trùng
    assert kinds(api, "nurse1").count("schedule.overdue") == 1 and kinds(api, "manager1").count("schedule.overdue") == 1
    api.post("admin", "/api/scheduler/run?escalate_after_hours=0")
    api.post("admin", "/api/scheduler/run?escalate_after_hours=0")   # mức 2
    esc = [n for n in inbox(api, "manager1")["items"] if n["kind"] == "schedule.escalated"]
    assert sorted(n["title"][-1] for n in esc) == ["1", "2"] and all(n["severity"] == "critical" for n in esc)


# ------------------------------------------------------------ API hộp thư
def test_read_unread_dismiss_pagination_and_poll(api):
    for i in range(3):
        api.person(f"P{i}", f"Người {i}")
        api.stay(api.get("officer1", f"/api/persons?external_id=P{i}").json()[0]["id"])
    box = inbox(api, "nurse1")
    assert box["unread"] == 3 and len(box["items"]) == 3
    first, last = box["items"][0], box["items"][-1]
    assert first["seq"] > last["seq"]                          # mới nhất trước
    page = inbox(api, "nurse1", limit=2)
    assert len(page["items"]) == 2 and page["next_before_seq"] == page["items"][-1]["seq"]
    assert len(inbox(api, "nurse1", before_seq=page["next_before_seq"])["items"]) == 1
    r = api.post("nurse1", f"/api/notifications/{first['id']}/read").json()
    assert r["unread"] == 2 and r["read_at"]
    assert len(inbox(api, "nurse1", unread="true")["items"]) == 2
    up = api.get("nurse1", f"/api/notifications/poll?after_seq={last['seq']}").json()
    assert [n["seq"] for n in up["items"]] == sorted(n["seq"] for n in box["items"] if n["seq"] > last["seq"]) and up["latest_seq"] == first["seq"]
    assert api.get("nurse1", f"/api/notifications/poll?after_seq={first['seq']}").json()["items"] == []
    assert api.post("nurse1", f"/api/notifications/{last['id']}/dismiss").json()["unread"] == 1
    assert all(n["id"] != last["id"] for n in inbox(api, "nurse1")["items"])
    assert api.post("nurse1", "/api/notifications/read-all").json() == {"updated": 1, "unread": 0, "critical": 0}


def test_notifications_are_private_per_user(api):
    api.patient()
    mine = inbox(api, "nurse1")["items"][0]
    assert api.post("doctor1", f"/api/notifications/{mine['id']}/read").status_code == 404      # IDOR
    assert api.post("doctor1", f"/api/notifications/{mine['id']}/dismiss").status_code == 404
    assert api.get("nurse1", "/api/notifications").json()["unread"] == 1                        # không bị đọc hộ
    assert all(n["id"] != mine["id"] for n in inbox(api, "doctor1")["items"])
    assert api.c.get("/api/notifications").status_code == 401 and api.c.get("/api/notifications/poll").status_code == 401


def test_dedupe_and_preferences(api):
    pr = api.get("pharm1", "/api/notifications/preferences").json()
    assert {x["category"]: x["mandatory"] for x in pr}["emergency"] is True
    assert api.put("pharm1", "/api/notifications/preferences", {"categories": {"emergency": False}}).status_code == 422
    assert api.put("pharm1", "/api/notifications/preferences", {"categories": {"nope": False}}).status_code == 422
    out = api.put("pharm1", "/api/notifications/preferences", {"categories": {"medication": False}}).json()
    assert {x["category"]: x["enabled"] for x in out}["medication"] is False
    p, _ = api.patient()
    api.confirmed_order(api.encounter(p["id"])["id"])
    assert "medication.confirmed" not in kinds(api, "pharm1")                                                      # người đã tắt bị bỏ qua
    api.put("pharm1", "/api/notifications/preferences", {"categories": {"medication": True}})
    with SessionLocal() as db:        # emit cùng khóa hai lần -> chỉ một bản ghi
        from app.models import User
        u = db.query(User).filter_by(username="pharm1").one()
        for _ in range(2):
            notify.emit(db, kind="x", category="medication", facility_id=u.facility_id, title="t", perms=("dispense.write",), dedupe="same-key")
        db.commit()
        assert db.query(Notification).filter_by(user_id=u.id, dedupe_key="same-key").count() == 1


def test_retention_purges_old_read_items_only(api):
    api.patient()
    with SessionLocal() as db:
        n = db.query(Notification).first()
        old = utcnow() - timedelta(days=200)
        keep_unread = Notification(user_id=n.user_id, category="intake", kind="old.unread", title="u", created_at=old)
        old_read = Notification(user_id=n.user_id, category="intake", kind="old.read", title="r", created_at=old, read_at=old)
        ancient = Notification(user_id=n.user_id, category="intake", kind="ancient", title="a", created_at=utcnow() - timedelta(days=400))
        db.add_all([keep_unread, old_read, ancient])
        db.commit()
        assert notify.purge(db) == 2
        db.commit()
        left = {x.kind for x in db.query(Notification).all()}
        assert "old.unread" in left and "old.read" not in left and "ancient" not in left and "intake.new_person" in left


# ------------------------------------------------------------ lỗi kiểm toán thiếu mã đối tượng (đã sửa)
def test_audit_events_of_new_objects_carry_object_and_person_ids(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    with SessionLocal() as db:
        ev = db.query(AuditEvent).filter_by(action="person_created").one()
        assert ev.object_id == p["id"] and ev.person_id == p["id"]
        assert db.query(AuditEvent).filter_by(action="encounter_created").one().object_id == e["id"]
        assert db.query(AuditEvent).filter(AuditEvent.action.in_(("stay_created", "person_created", "encounter_created")), AuditEvent.object_id.is_(None)).count() == 0
