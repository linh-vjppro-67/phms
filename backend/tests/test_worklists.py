"""API danh sách / dashboard phục vụ các màn hình nghiệp vụ – kiểm tra cả phạm vi quyền & cơ sở."""
from datetime import date, timedelta


def test_stays_worklist_flags_initial_exam_and_scopes_facility(api):
    p1, s1 = api.patient("P001", "Người một")
    p2 = api.person("P002", "Người hai")
    api.post("officer2", f"/api/persons/{p2['id']}/stays", {})
    rows = api.get("officer1", "/api/stays?status=active").json()
    assert [r["person_id"] for r in rows] == [p1["id"]]
    assert rows[0]["needs_initial_exam"] and rows[0]["initial_encounter_id"] is None and rows[0]["person_name"] == "Người một"
    e = api.encounter(p1["id"], "initial")
    r = api.get("nurse1", "/api/stays?status=received").json()[0]
    assert r["initial_encounter_id"] == e["id"] and r["initial_encounter_status"] == "in_progress"
    assert api.get("manager1", "/api/stays").status_code == 403


def test_person_search_shows_stay_status_for_my_facility(api):
    p, _ = api.patient()
    row = api.get("officer1", "/api/persons?q=Nguy").json()[0]
    assert row["facility_stay_status"] == "received" and row["active_elsewhere"] is False
    row2 = api.get("officer2", "/api/persons?q=Nguy").json()[0]
    assert row2["facility_stay_status"] is None and row2["active_elsewhere"] is True


def test_encounter_and_order_lists_are_clinical_and_facility_scoped(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    api.confirmed_order(e["id"])
    enc = api.get("doctor1", "/api/encounters?open_only=true").json()
    assert len(enc) == 1 and enc[0]["person_name"] == "Nguyễn Văn A"
    assert api.get("doctor2", "/api/encounters").json() == []
    assert api.get("officer1", "/api/encounters").status_code == 403
    orders = api.get("pharm1", "/api/medication-orders?status=confirmed,active").json()
    assert len(orders) == 1 and orders[0]["remaining"] == 30 and orders[0]["person_name"]
    d = api.get("doctor1", f"/api/encounters/{e['id']}").json()
    assert d["person_name"] == "Nguyễn Văn A" and "allergies" in d


def test_handover_emergency_careplan_lists(api):
    p, s = api.patient()
    h = api.post("officer1", f"/api/stays/{s['id']}/handover",
                 {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    out = api.get("officer1", "/api/handovers?status=pending").json()
    assert out[0]["id"] == h["id"] and out[0]["direction"] == "out" and out[0]["summary"] is None
    assert api.get("officer2", "/api/handovers").json()[0]["direction"] == "in"   # cơ sở đích cũng thấy
    assert api.get("manager1", "/api/handovers").status_code == 403
    api.post("nurse1", "/api/emergency-events", {"temp_identity": "Chưa rõ"})
    ev = api.get("nurse1", "/api/emergency-events?status=open").json()
    assert len(ev) == 1 and ev[0]["person_status"] == "pending_verification" and ev[0]["encounter_status"] == "in_progress"
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Đái tháo đường"}).json()
    api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {"problem_id": prob["id"], "goals": "HbA1c < 7",
                                                                "review_interval_days": 30})
    cps = api.get("doctor1", "/api/care-plans").json()
    assert cps[0]["problem_name"] == "Đái tháo đường" and cps[0]["next_due"] == str(date.today() + timedelta(days=30))


def test_dashboard_only_returns_metrics_for_role(api):
    api.patient()
    off = api.get("officer1", "/api/dashboard").json()
    assert off["awaiting_initial_exam"] == 1 and "open_encounters" not in off and "dispense_queue" not in off
    doc = api.get("doctor1", "/api/dashboard").json()
    assert "open_encounters" in doc and "open_referrals" in doc
    mgr = api.get("manager1", "/api/dashboard").json()
    assert "overdue_appointments" in mgr and "active_persons" not in mgr and "open_encounters" not in mgr
    assert api.get("admin", "/api/dashboard").json() == {}
    assert api.c.get("/api/dashboard").status_code == 401


def test_roles_matrix_only_for_admin(api):
    m = api.get("admin", "/api/roles").json()
    assert "clinical.read" not in m["sysadmin"] and "clinical.read" in m["doctor"]
    assert api.get("doctor1", "/api/roles").status_code == 403
