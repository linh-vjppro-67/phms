"""WF-01, 04, 05, 06 (nhánh phụ), 07, 08: các luồng còn lại và quy tắc trạng thái."""
from datetime import date, timedelta


def test_wf01_initial_exam_moves_stay_to_managed_and_one_initial_only(api):
    p, s = api.patient()
    assert s["status"] == "received"
    assert api.post("officer1", f"/api/persons/{p['id']}/stays", {}).status_code == 409  # đang có kỳ hiệu lực
    e = api.encounter(p["id"], "initial")
    assert api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "initial"}).status_code == 409
    for t, v, u in (("Mạch", "78", "bpm"), ("Huyết áp tâm thu", "150", "mmHg")):
        assert api.post("nurse1", f"/api/encounters/{e['id']}/observations",
                        {"type": t, "value": v, "unit": u}).status_code == 201
    api.post("doctor1", f"/api/encounters/{e['id']}/diagnoses", {"code": "I10", "text": "Tăng huyết áp", "kind": "final"})
    assert api.post("nurse1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 403
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 200
    stays = api.get("officer1", f"/api/persons/{p['id']}/stays").json()
    assert stays[0]["status"] == "managed" and stays[0]["initial_exam_completed_at"]


def test_wf01_void_stay_only_without_clinical_data(api):
    p, s = api.patient()
    assert api.post("officer1", f"/api/stays/{s['id']}/void", {"reason": "Nhập nhầm người"}).json()["status"] == "voided"
    p2, s2 = api.patient("P002", "Bùi Văn B")
    api.encounter(p2["id"])
    assert api.post("officer1", f"/api/stays/{s2['id']}/void", {"reason": "Nhập nhầm người"}).status_code == 409


def test_no_encounter_without_active_stay(api):
    p = api.person()
    r = api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "ad_hoc"})
    assert r.status_code == 403  # chưa có quan hệ cơ sở: không truy cập được
    api.stay(p["id"])
    assert api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "bogus"}).status_code == 422


def test_wf04_checkup_round_generation_exclusions_and_lock(api):
    ps = [api.managed(f"P{i}", f"Người {i}")[0] for i in range(4)]
    newcomer, _ = api.patient("PNEW", "Người mới tiếp nhận")   # chưa khám ban đầu
    # P0 đang ở bệnh viện -> bị loại khỏi đợt khám
    e = api.encounter(ps[0]["id"], user="doctor1")
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals",
                   {"urgency": "emergency", "reason": "Đau ngực cấp", "destination": "BV Y"}).json()
    r = api.patch("nurse1", f"/api/referrals/{ref['id']}/status", {"to": "in_external_treatment"})
    assert r.status_code == 200 and r.json()["shortcut_used"] and r.json()["needs_post_review"]  # đường tắt cấp cứu
    # P1 đang chờ chuyển trại -> bị loại
    s1 = api.get("officer1", f"/api/persons/{ps[1]['id']}/stays").json()[0]
    api.post("officer1", f"/api/stays/{s1['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"})
    due = str(date.today() + timedelta(days=7))
    rnd = api.post("manager1", "/api/checkup-rounds", {"name": "Khám định kỳ Q4", "due_date": due}).json()
    assert rnd["tasks_created"] == 2 and {x["person_id"] for x in rnd["excluded"]} == {ps[0]["id"], ps[1]["id"], newcomer["id"]}
    assert {x["person_id"]: x["reason"] for x in rnd["excluded"]}[newcomer["id"]] == "Chưa hoàn tất khám ban đầu"
    tasks = api.get("nurse1", f"/api/appointments?round_id={rnd['id']}").json()
    assert len(tasks) == 2
    # thực hiện 1 người bằng Encounter định kỳ gắn lịch -> lịch tự hoàn tất
    t = tasks[0]
    e2 = api.encounter(t["person_id"], "periodic", appointment_id=t["id"])
    api.post("doctor1", f"/api/encounters/{e2['id']}/transition", {"to": "completed"})
    st = api.get("manager1", f"/api/checkup-rounds/{rnd['id']}").json()["stats"]
    assert st["completed"] == 1 and st["pending"] == 1 and st["completion_rate"] == 0.5
    # khóa đợt: người chưa khám ghi rõ not_done (không bỏ sót), báo cáo phản ánh
    locked = api.post("manager1", f"/api/checkup-rounds/{rnd['id']}/lock").json()
    assert locked["stats"]["not_done"] == 1 and locked["stats"]["pending"] == 0
    assert api.post("manager1", f"/api/checkup-rounds/{rnd['id']}/lock").status_code == 409
    rep = api.get("manager1", f"/api/reports/checkups?date_from={date.today()}&date_to={due}").json()["data"]
    assert rep["total_due"] == 2 and rep["completed"] == 1 and rep["not_done"] == 1
    # hậu kiểm đường tắt cấp cứu
    assert api.post("approver1", f"/api/referrals/{ref['id']}/post-review", {"note": "Hợp lệ"}).status_code == 200


def test_wf05_chronic_care_plan_scheduler_alerts_and_escalation(api):
    p, _ = api.patient()
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp", "code": "I10"}).json()
    assert api.post("nurse1", f"/api/persons/{p['id']}/problems", {"name": "x1"}).status_code == 403
    cp = api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {
        "problem_id": prob["id"], "goals": "HA < 140/90", "review_interval_days": 14,
        "start_date": str(date.today() - timedelta(days=20)),
        "measures": [{"name": "Huyết áp", "unit": "mmHg"}]}).json()
    appts = api.get("nurse1", "/api/appointments").json()
    assert len(appts) == 1 and appts[0]["overdue"] is True  # quá hạn = thuộc tính tính toán
    assert appts[0]["status"] == "scheduled"
    res = api.post("admin", "/api/scheduler/run").json()
    assert res["overdue_alerts"] == 1 and res["marked_due"] == 1 and res["escalated"] == 0
    again = api.post("admin", "/api/scheduler/run?escalate_after_hours=0").json()
    assert again["overdue_alerts"] == 0 and again["escalated"] == 1  # không sinh cảnh báo trùng; nâng cấp mức nhắc
    alerts = api.get("nurse1", "/api/alerts?status=new").json()
    assert len(alerts) == 1 and alerts[0]["level"] == 1
    a = api.post("nurse1", f"/api/alerts/{alerts[0]['id']}/acknowledge").json()
    assert a["status"] == "acknowledged" and a["owner_id"]
    assert api.post("nurse1", f"/api/alerts/{a['id']}/acknowledge").status_code == 409
    # hoàn tất lịch -> cảnh báo tự giải quyết + sinh lịch kỳ kế tiếp
    e = api.encounter(p["id"], "periodic", appointment_id=appts[0]["id"])
    api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"})
    assert api.get("nurse1", "/api/alerts?status=resolved").json()
    nxt = api.get("nurse1", "/api/appointments?status=scheduled").json()
    assert len(nxt) == 1 and nxt[0]["due_date"] == str(date.today() + timedelta(days=14)) and nxt[0]["care_plan_id"] == cp["id"]
    # kết thúc kế hoạch -> lịch mở được đóng có lý do
    api.post("doctor1", f"/api/care-plans/{cp['id']}/end", {"note": "Ổn định, kết thúc"})
    assert api.get("nurse1", "/api/appointments?status=scheduled").json() == []


def test_postpone_appointment_creates_new_one(api):
    p, _ = api.patient()
    a = api.post("nurse1", "/api/appointments", {"person_id": p["id"], "due_date": str(date.today())}).json()
    assert api.post("nurse1", f"/api/appointments/{a['id']}/status", {"to": "postponed"}).status_code == 422
    r = api.post("nurse1", f"/api/appointments/{a['id']}/status",
                 {"to": "postponed", "reason": "Đang lao động", "new_due_date": str(date.today() + timedelta(days=2))})
    assert r.json()["status"] == "postponed"
    assert len(api.get("nurse1", "/api/appointments?status=scheduled").json()) == 1


def test_wf06_referral_rules(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"urgency": "routine", "reason": "Cần siêu âm ngoài"}).json()
    rid = ref["id"]
    ch = lambda u, b: api.patch(u, f"/api/referrals/{rid}/status", b)  # noqa: E731
    assert ch("doctor1", {"to": "completed"}).status_code == 409                  # nhảy bước
    ch("doctor1", {"to": "pending"})
    assert ch("approver1", {"to": "coordinated"}).status_code == 422               # chưa có cơ sở tiếp nhận
    assert ch("approver1", {"to": "coordinated", "destination": "BV A"}).status_code == 200
    # bệnh viện không tiếp nhận -> quay lại chờ xử lý có lý do, ghi sự kiện
    assert ch("approver1", {"to": "pending"}).status_code == 422
    assert ch("approver1", {"to": "pending", "note": "BV A hết giường", "destination": "BV B"}).json()["destination"] == "BV B"
    # người điều phối chỉ thấy thông tin tối thiểu
    v = api.get("approver1", f"/api/referrals/{rid}").json()
    assert v["reason"] is None and v["clinical_hidden"] and v["status"] == "pending"
    assert api.get("doctor1", f"/api/referrals/{rid}").json()["reason"] == "Cần siêu âm ngoài"
    # tuyến không khẩn không được dùng đường tắt
    assert ch("doctor1", {"to": "in_external_treatment"}).status_code == 409
    assert ch("doctor1", {"to": "cancelled", "note": "BN từ chối"}).status_code == 200
    assert api.post("doctor1", f"/api/referrals/{rid}/events", {"note": "x1x"}).status_code == 409


def test_wf07_release_ends_stay_and_hides_appointments(api):
    p, s = api.patient()
    a = api.post("nurse1", "/api/appointments", {"person_id": p["id"], "due_date": str(date.today())}).json()
    h = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "release", "reason": "Mãn hạn tù"}).json()
    assert api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "release", "reason": "lần 2"}).status_code == 409
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Kết thúc quản lý, hồ sơ được lưu trữ"})
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 200
    stay = api.get("officer1", f"/api/persons/{p['id']}/stays").json()[0]
    assert stay["status"] == "ended"
    appts = api.get("nurse1", "/api/appointments?status=postponed").json()
    assert [x["id"] for x in appts] == [a["id"]]
    # kết thúc kỳ: không tạo Encounter mới (không còn kỳ hiệu lực) nhưng dữ liệu cũ còn đọc được tại cơ sở cũ
    assert api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "ad_hoc"}).status_code == 409
    assert api.get("doctor1", f"/api/persons/{p['id']}/health-summary").status_code == 200


def test_wf08_emergency_never_blocked_for_unknown_person(api):
    r = api.post("nurse1", "/api/emergency-events", {"temp_identity": "Không rõ"})
    assert r.status_code == 201
    p = api.get("officer1", f"/api/persons/{r.json()['person_id']}").json()
    assert p["is_temporary"] and p["status"] == "pending_verification" and p["full_name"].startswith("[TẠM]")
    stays = api.get("officer1", f"/api/persons/{p['id']}/stays").json()
    assert stays[0]["provisional"] is True
    assert api.post("nurse1", "/api/emergency-events", {}).status_code == 422


def test_clinical_order_cancel_and_result_rules(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "procedure", "description": "Khâu vết thương"}).json()
    assert api.post("doctor1", f"/api/orders/{o['id']}/cancel", {"reason": "Không cần"}).json()["status"] == "cancelled"
    assert api.post("nurse1", f"/api/orders/{o['id']}/result", {"result_text": "x"}).status_code == 409
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 200
    # sau hoàn tất không thêm dữ liệu trực tiếp
    assert api.post("nurse1", f"/api/encounters/{e['id']}/observations",
                    {"type": "a", "value": "1", "unit": "u"}).status_code == 409


def test_catalog_versioning_and_drug_code_validation(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    body = {"drug_name": "Thuốc lạ", "drug_code": "NOPE", "dose": "1", "route": "uống", "frequency": "1/ngày",
            "start_date": "2026-01-01", "duration_days": 5, "quantity_prescribed": 5}
    assert api.post("doctor1", f"/api/encounters/{e['id']}/medication-orders", body).json()["error"]["code"] == "UNKNOWN_DRUG_CODE"
    api.post("admin", "/api/catalogs", {"catalog": "drug", "code": "NOPE", "name": "Thuốc lạ 100mg"})
    assert api.post("doctor1", f"/api/encounters/{e['id']}/medication-orders", body).status_code == 201
    v2 = api.post("admin", "/api/catalogs", {"catalog": "drug", "code": "NOPE", "name": "Thuốc lạ 200mg"}).json()
    assert v2["version"] == 2
    items = [i for i in api.get("doctor1", "/api/catalogs/drug").json() if i["code"] == "NOPE"]
    assert len(items) == 1 and items[0]["name"].endswith("200mg")
    assert api.post("doctor1", "/api/catalogs", {"catalog": "drug", "code": "Z", "name": "Z"}).status_code == 403
