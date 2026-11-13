"""Các điểm đã rà soát lại cho khớp luồng nghiệp vụ trong tài liệu thiết kế (WF-02/03/04/06/07, BR-04, mục 10.1)."""
from datetime import date, timedelta
from urllib.parse import quote

from app import config
from app.db import SessionLocal
from app.migrate import ensure_schema
from app.models import Alert, BreakGlassGrant, Handover, MedicationOrder
from app.utils import utcnow


def kinds(api, user):
    return [n["kind"] for n in api.get(user, "/api/notifications").json()["items"]]


# ---------------------------------------------------------------- WF-04: đợt khám định kỳ
def test_round_only_includes_managed_and_avoids_duplicate_open_periodic(api):
    managed, _ = api.managed("P1", "Đang quản lý")
    fresh, _ = api.patient("P2", "Mới tiếp nhận")
    due = str(date.today() + timedelta(days=10))
    r1 = api.post("manager1", "/api/checkup-rounds", {"name": "Đợt thứ nhất", "due_date": due}).json()
    assert r1["tasks_created"] == 1
    assert {x["person_id"]: x["reason"] for x in r1["excluded"]} == {fresh["id"]: "Chưa hoàn tất khám ban đầu"}
    r2 = api.post("manager1", "/api/checkup-rounds", {"name": "Đợt thứ hai", "due_date": due}).json()
    assert r2["tasks_created"] == 0 and r2["excluded"][0]["reason"].startswith("Đã có lịch khám định kỳ khác")
    assert managed["id"] in {x["person_id"] for x in r2["excluded"]}


# ---------------------------------------------------------------- BR-04 / WF-03: hiệu lực đơn + nhắc hết liệu trình
def test_dispense_only_within_order_validity_window(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], start_date=str(date.today() - timedelta(days=10)), duration_days=5, quantity_prescribed=10)
    r = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 5})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ORDER_EXPIRED"
    ok = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 5, "occurred_at": (utcnow() - timedelta(days=8)).isoformat()})
    assert ok.status_code == 201            # cấp lùi ngày trong thời gian hiệu lực vẫn được ghi nhận
    future = api.confirmed_order(e["id"], drug_name="Omeprazole 20mg", drug_code="OMEP20", start_date=str(date.today() + timedelta(days=3)))
    assert future["status"] == "confirmed"
    r = api.post("pharm1", f"/api/medication-orders/{future['id']}/dispenses", {"quantity": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ORDER_NOT_STARTED"


def test_scheduler_reminds_once_when_course_is_ending(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    api.confirmed_order(e["id"], start_date=str(date.today() - timedelta(days=12)), duration_days=14)   # hết sau 1 ngày
    ending = api.confirmed_order(e["id"], drug_name="Omeprazole 20mg", drug_code="OMEP20", duration_days=60)  # còn dài
    assert api.post("admin", "/api/scheduler/run").json()["course_ending_alerts"] == 1
    assert api.post("admin", "/api/scheduler/run").json()["course_ending_alerts"] == 0   # không trùng
    al = [a for a in api.get("doctor1", "/api/alerts").json() if a["kind"] == "medication_course_ending"]
    assert len(al) == 1 and "Paracetamol" in al[0]["message"] and "Omeprazole" not in al[0]["message"]
    n = [x for x in api.get("doctor1", "/api/notifications").json()["items"] if x["kind"] == "medication.course_ending"]
    assert len(n) == 1 and n[0]["link_page"] == "rx"
    assert ending["status"] in ("active", "confirmed")


# ---------------------------------------------------------------- lượt khám ↔ đơn thuốc/chỉ định/chuyển viện
def test_cannot_complete_encounter_with_draft_medication_order(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    api.med_order(e["id"])                                   # đơn nháp
    r = api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DRAFT_ORDERS"
    oid = api.get("doctor1", f"/api/encounters/{e['id']}").json()["medication_orders"][0]["id"]
    api.post("doctor1", f"/api/medication-orders/{oid}/confirm", {})
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 200


def test_cancel_encounter_cascades_orders_but_not_when_already_dispensed(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    draft = api.med_order(e["id"])
    lab = api.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Công thức máu"}).json()
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Cần chụp CT ngoài", "destination": "BV A"}).json()
    r = api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "cancelled", "reason": "Nhập nhầm người bệnh"})
    assert r.status_code == 200
    d = api.get("doctor1", f"/api/encounters/{e['id']}").json()
    assert d["medication_orders"][0]["status"] == "cancelled" and "Nhập nhầm" in d["medication_orders"][0]["stop_reason"]
    assert d["orders"][0]["status"] == "cancelled" and d["referrals"][0]["status"] == "cancelled"
    # đơn đã cấp phát -> không được hủy lượt khám
    e2 = api.encounter(p["id"])
    o = api.confirmed_order(e2["id"], drug_name="Omeprazole 20mg", drug_code="OMEP20")
    api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 3})
    r = api.post("doctor1", f"/api/encounters/{e2['id']}/transition", {"to": "cancelled", "reason": "Nhầm lượt khám"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ORDERS_DISPENSED"
    # chuyển viện đang xử lý -> không được hủy
    e3 = api.encounter(p["id"])
    ref = api.post("doctor1", f"/api/encounters/{e3['id']}/referrals", {"reason": "Cần siêu âm ngoài", "destination": "BV B"}).json()
    api.patch("doctor1", f"/api/referrals/{ref['id']}/status", {"to": "pending"})
    r = api.post("doctor1", f"/api/encounters/{e3['id']}/transition", {"to": "cancelled", "reason": "Nhầm lượt khám"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OPEN_REFERRALS"


def test_encounter_shows_clinical_context_needed_at_the_bedside(api):
    p, _ = api.patient()
    api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp", "code": "I10"})
    e0 = api.encounter(p["id"])
    api.confirmed_order(e0["id"])
    api.post("doctor1", f"/api/encounters/{e0['id']}/transition", {"to": "completed"})
    d = api.get("doctor1", f"/api/encounters/{api.encounter(p['id'])['id']}").json()
    assert [m["drug_name"] for m in d["context"]["active_medications"]] == ["Paracetamol 500mg"]
    assert [x["name"] for x in d["context"]["open_problems"]] == ["Tăng huyết áp"]


# ---------------------------------------------------------------- WF-06: kết cục tử vong / không trở lại
def _finish_referral(api, outcome):
    p, _ = api.patient(f"P-{outcome}", "Nguyễn Văn " + {"returned": "Trở Lại", "deceased": "Kết Cục"}[outcome])
    e = api.encounter(p["id"])
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Cần điều trị chuyên khoa", "destination": "BV A"}).json()
    ch = lambda u, b: api.patch(u, f"/api/referrals/{ref['id']}/status", b)  # noqa: E731
    ch("doctor1", {"to": "pending"}); ch("approver1", {"to": "coordinated"}); ch("nurse1", {"to": "in_external_treatment"})
    ch("nurse1", {"to": "result_received", "result_note": "Đã có kết quả"})
    return ch("doctor1", {"to": "completed", "post_referral_plan": "Theo quy trình", "outcome": outcome}).json()


def test_unusual_referral_outcomes_require_approver_review_not_silent_close(api):
    ok = _finish_referral(api, "returned")
    assert ok["needs_post_review"] is False
    bad = _finish_referral(api, "deceased")
    assert bad["status"] == "completed" and bad["needs_post_review"] is True
    n = [x for x in api.get("approver1", "/api/notifications").json()["items"] if x["kind"] == "referral.unusual_outcome"]
    assert len(n) == 1 and n[0]["severity"] == "critical" and "deceased" not in n[0]["body"]
    assert api.post("approver1", f"/api/referrals/{bad['id']}/post-review", {"note": "Đã báo cáo theo quy trình"}).status_code == 200


# ---------------------------------------------------------------- WF-07: biên nhận của cơ sở nhận
def test_receiving_facility_stay_acknowledges_the_handover(api):
    p, s = api.patient()
    h = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Theo dõi huyết áp hằng tuần"})
    api.post("officer1", f"/api/handovers/{h['id']}/confirm", {})
    before = api.get("officer2", "/api/handovers").json()[0]
    assert before["received_at"] is None
    st = api.post("officer2", f"/api/persons/{p['id']}/stays", {}).json()
    after = {x["id"]: x for x in api.get("officer1", "/api/handovers").json()}[h["id"]]
    assert after["received_at"] and after["received_stay_id"] == st["id"]
    assert "handover.received" in kinds(api, "officer1")       # cơ sở gửi được báo đã nhận
    # kỳ mới thứ hai không "nhận" lại phiếu cũ
    with SessionLocal() as db:
        assert db.query(Handover).filter(Handover.received_at.is_not(None)).count() == 1


# ---------------------------------------------------------------- mục 10.1: break-glass có hạn thời gian, chỉ đọc
def test_break_glass_grant_is_time_limited_read_only_and_reviewed(api):
    p, _ = api.patient()
    api.encounter(p["id"])
    r = api.get("doctor2", f"/api/persons/{p['id']}/health-summary")
    assert r.status_code == 403 and r.json()["error"]["break_glass_allowed"] is True
    assert api.post("doctor2", f"/api/persons/{p['id']}/break-glass", {"reason": "ngắn"}).status_code == 422
    assert api.post("officer2", f"/api/persons/{p['id']}/break-glass", {"reason": "Cần tiền sử dị ứng gấp cho ca cấp cứu"}).status_code == 403
    g = api.post("doctor2", f"/api/persons/{p['id']}/break-glass", {"reason": "Cần tiền sử dị ứng gấp cho ca cấp cứu"}).json()
    assert g["read_only"] is True and g["minutes"] == config.BREAK_GLASS_MINUTES
    assert api.get("doctor2", f"/api/persons/{p['id']}/health-summary").status_code == 200       # không cần header nữa
    assert api.get("doctor2", f"/api/persons/{p['id']}/break-glass").json()["active"] is True
    assert api.get("doctor2", f"/api/persons/{p['id']}/encounters").status_code == 200
    # chỉ ĐỌC: không ghi được dữ liệu ở cơ sở khác
    e = api.get("doctor2", f"/api/persons/{p['id']}/encounters").json()[0]
    assert api.post("doctor2", f"/api/encounters/{e['id']}/observations", {"type": "Mạch", "value": "80", "unit": "bpm"}).status_code == 403
    # hậu kiểm: có cảnh báo + thông báo + nhật ký
    assert any(a["kind"] == "break_glass_review" for a in api.get("manager2", "/api/alerts").json())
    assert "security.break_glass" in kinds(api, "manager2") and "security.break_glass" in kinds(api, "admin")
    assert api.get("admin", "/api/audit?action=break_glass").json()
    # hết hạn -> bị chặn lại
    with SessionLocal() as db:
        db.query(BreakGlassGrant).update({"expires_at": utcnow() - timedelta(minutes=1)})
        db.commit()
    assert api.get("doctor2", f"/api/persons/{p['id']}/health-summary").status_code == 403
    assert api.get("doctor2", f"/api/persons/{p['id']}/break-glass").json()["active"] is False
    # người cùng cơ sở không cần break-glass
    assert api.post("doctor1", f"/api/persons/{p['id']}/break-glass", {"reason": "Không cần thiết phải dùng"}).status_code == 409


def test_header_based_break_glass_still_creates_a_limited_grant(api):
    p, _ = api.patient()
    assert api.get("doctor2", f"/api/persons/{p['id']}/health-summary", headers={"X-Break-Glass-Reason": quote("Ca cấp cứu cần tiền sử gấp")}).status_code == 200
    with SessionLocal() as db:
        g = db.query(BreakGlassGrant).one()
        assert 0 < (g.expires_at - utcnow()).total_seconds() <= config.BREAK_GLASS_MINUTES * 60


# ---------------------------------------------------------------- nâng cấp lược đồ cho CSDL cũ
def test_schema_upgrade_adds_missing_columns_idempotently():
    from sqlalchemy import inspect, text
    from app.db import engine
    with engine.begin() as c:
        c.execute(text("ALTER TABLE handover DROP COLUMN received_at"))
    assert "handover.received_at" in ensure_schema(engine)
    assert "received_at" in {c["name"] for c in inspect(engine).get_columns("handover")}
    assert ensure_schema(engine) == []


def test_expired_orders_leave_the_dispense_queue_and_course_alert_closes_when_handled(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    old = api.confirmed_order(e["id"], start_date=str(date.today() - timedelta(days=12)), duration_days=10, drug_name="Metformin 850mg", drug_code="MET850")
    ok = api.confirmed_order(e["id"], drug_name="Omeprazole 20mg", drug_code="OMEP20", duration_days=14)
    q = api.get("pharm1", "/api/dispense-queue").json()
    assert [o["id"] for o in q] == [ok["id"]]                      # đơn hết hạn không vào hàng đợi
    assert api.get("pharm1", "/api/dashboard").json()["dispense_queue"] == 1
    api.post("admin", "/api/scheduler/run")
    assert any(a["kind"] == "medication_course_ending" and a["status"] == "new" for a in api.get("doctor1", "/api/alerts").json())
    api.post("doctor1", f"/api/medication-orders/{old['id']}/stop", {"outcome": "completed", "reason": "Hoàn thành liệu trình, đã đánh giá hiệu quả"})
    res = api.post("admin", "/api/scheduler/run").json()
    assert res["course_alerts_closed"] == 1
    al = [a for a in api.get("doctor1", "/api/alerts").json() if a["kind"] == "medication_course_ending"][0]
    assert al["status"] == "resolved"
