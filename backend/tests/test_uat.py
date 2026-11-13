"""Kiểm thử nghiệm thu nghiệp vụ UAT-01 … UAT-12 (mục 12.2 tài liệu)."""
from datetime import date, timedelta


def test_uat01_no_duplicate_health_record_on_new_stay(api):
    """Given Person đã có hồ sơ, When xác nhận tiếp nhận mới, Then không tạo trùng HealthRecord."""
    p, s1 = api.patient()
    r1 = api.get("doctor1", f"/api/persons/{p['id']}/health-summary").json()
    rec1 = r1["clinical"]["health_record_id"]
    e = api.encounter(p["id"], "ad_hoc")
    api.post("doctor1", f"/api/encounters/{e['id']}/diagnoses", {"text": "Cảm cúm"})
    # chuyển trại -> kết thúc kỳ 1
    h = api.post("officer1", f"/api/stays/{s1['id']}/handover", {"kind": "release", "reason": "Mãn hạn"}).json()
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Tóm tắt y tế đầy đủ cho bàn giao"})
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm",
                    {"acknowledge_open_items": True}).status_code == 200
    # tái tiếp nhận kỳ mới
    s2 = api.stay(p["id"])
    assert s2["health_record_id"] == rec1
    summ = api.get("doctor1", f"/api/persons/{p['id']}/health-summary").json()
    assert summ["clinical"]["health_record_id"] == rec1
    assert len(summ["stays"]) == 2
    assert len(summ["clinical"]["recent_encounters"]) == 1  # lịch sử được giữ nguyên


def test_uat02_allergy_warning_requires_doctor_acknowledgement(api):
    p, _ = api.patient()
    api.post("nurse1", f"/api/persons/{p['id']}/allergies",
             {"substance": "Amoxicillin", "reaction": "Phát ban", "confirmed": True})
    e = api.encounter(p["id"])
    o = api.med_order(e["id"], drug_name="Amoxicillin 500mg", drug_code="AMOX500")
    assert any(w["type"] == "allergy" for w in o["warnings"])
    r = api.post("doctor1", f"/api/medication-orders/{o['id']}/confirm", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "WARNINGS_UNACKNOWLEDGED"
    r = api.post("doctor1", f"/api/medication-orders/{o['id']}/confirm",
                 {"acknowledge_warnings": True, "ack_note": "Cân nhắc lợi ích, theo dõi sát"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    audits = api.get("admin", "/api/audit?action=medication_warning_acknowledged").json()
    assert len(audits) == 1  # xử lý cảnh báo được ghi nhận


def test_uat03_partial_dispense_is_not_administered(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], quantity_prescribed=30)
    r = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 10})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "partial"
    assert body["order"]["dispense_status"] == "partial" and body["order"]["remaining"] == 20
    detail = api.get("doctor1", f"/api/medication-orders/{o['id']}").json()
    assert detail["administrations"] == []  # không tự suy ra "đã dùng"
    # xác nhận dùng là sự kiện riêng
    r = api.post("nurse1", f"/api/medication-orders/{o['id']}/administrations", {"administered": True})
    assert r.status_code == 201
    r = api.post("nurse1", f"/api/medication-orders/{o['id']}/administrations", {"administered": False})
    assert r.status_code == 422  # không dùng thì phải có lý do


def test_uat04_encounter_not_completed_while_order_open(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Công thức máu"}).json()
    r = api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OPEN_ORDERS"
    r = api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "awaiting_results"})
    assert r.json()["status"] == "awaiting_results"
    api.post("nurse1", f"/api/orders/{o['id']}/result", {"result_text": "Bình thường"})
    r = api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"})
    assert r.status_code == 200 and r.json()["status"] == "completed"


def test_uat05_followup_list_scoped_to_facility(api):
    p1, _ = api.patient("P001")
    p2 = api.person("P002", "Trần B")
    r = api.post("officer2", f"/api/persons/{p2['id']}/stays", {})
    assert r.status_code == 201  # ở cơ sở F02
    for pid, user in ((p1["id"], "nurse1"), (p2["id"], "nurse2")):
        api.post(user, "/api/appointments", {"person_id": pid, "due_date": str(date.today() + timedelta(days=3))})
    lst = api.get("nurse1", "/api/appointments").json()
    assert [a["person_id"] for a in lst] == [p1["id"]]
    assert lst[0]["person_name"] == "Nguyễn Văn A"
    assert [a["person_id"] for a in api.get("nurse2", "/api/appointments").json()] == [p2["id"]]


def test_uat06_referral_full_flow(api):
    p, s = api.patient()
    e = api.encounter(p["id"])
    r = api.post("doctor1", f"/api/encounters/{e['id']}/referrals",
                 {"urgency": "urgent", "reason": "Nghi viêm ruột thừa cấp", "destination": "BV Đa khoa"})
    ref = r.json()
    rid = ref["id"]
    ch = lambda user, body: api.patch(user, f"/api/referrals/{rid}/status", body)  # noqa: E731
    assert ch("doctor1", {"to": "pending"}).status_code == 200
    assert ch("doctor1", {"to": "coordinated"}).status_code == 403  # bác sĩ không tự duyệt hành chính
    assert ch("approver1", {"to": "coordinated"}).status_code == 200
    assert ch("nurse1", {"to": "in_external_treatment"}).json()["left_at"]
    assert ch("nurse1", {"to": "result_received"}).status_code == 422  # chưa có kết quả
    assert ch("nurse1", {"to": "result_received", "result_note": "Đã mổ, ổn định"}).status_code == 200
    assert ch("doctor1", {"to": "completed"}).status_code == 422  # thiếu kế hoạch sau viện
    done = ch("doctor1", {"to": "completed", "post_referral_plan": "Tái khám sau 7 ngày", "outcome": "returned"}).json()
    assert done["status"] == "completed" and len(done["events"]) >= 6
    # BR-05: chuyển viện không kết thúc đợt tiếp nhận
    stays = api.get("officer1", f"/api/persons/{p['id']}/stays").json()
    assert stays[0]["status"] in ("received", "managed")


def test_uat07_emergency_minimal_then_complete_later(api):
    r = api.post("nurse1", "/api/emergency-events",
                 {"temp_identity": "Nam ~40 tuổi, buồng 5", "location": "Buồng 5", "reporter": "Quản giáo X"})
    assert r.status_code == 201  # không cần đủ hồ sơ
    ev = r.json()
    assert ev["occurred_at"] and ev["recorded_at"]
    api.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": "Sơ cứu, ép tim"})
    r = api.post("doctor1", f"/api/emergency-events/{ev['id']}/close", {"note": "Ổn định"})
    assert r.status_code == 409 and len(r.json()["error"]["problems"]) == 2  # chưa hoàn thiện + chưa đối soát
    # bổ sung sau
    enc_id = ev["encounter_id"]
    api.post("doctor1", f"/api/encounters/{enc_id}/diagnoses", {"text": "Ngất", "kind": "final"})
    assert api.post("doctor1", f"/api/encounters/{enc_id}/transition", {"to": "completed"}).status_code == 200
    api.post("officer1", f"/api/persons/{ev['person_id']}/verify",
             {"full_name": "Lê Văn C", "source_system": "QLPN", "external_id": "P777", "note": "Đối soát hồ sơ giấy"})
    r = api.post("doctor1", f"/api/emergency-events/{ev['id']}/close",
                 {"note": "Đã hoàn thiện", "follow_up_date": str(date.today() + timedelta(days=2))})
    assert r.status_code == 200 and r.json()["status"] == "closed"


def test_uat07b_late_entry_needs_reason_and_keeps_both_timestamps(api):
    p, _ = api.patient()
    past = (date.today() - timedelta(days=1)).isoformat() + "T08:00:00"
    r = api.post("nurse1", "/api/emergency-events", {"person_id": p["id"], "occurred_at": past})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LATE_ENTRY_REASON"
    r = api.post("nurse1", "/api/emergency-events", {"person_id": p["id"], "occurred_at": past,
                                                      "late_entry_reason": "Mất điện, nhập bổ sung"})
    ev = r.json()
    assert ev["occurred_at"] < ev["recorded_at"]  # BR-03


def test_uat08_transfer_keeps_health_record(api):
    p, s = api.patient()
    h = api.post("officer1", f"/api/stays/{s['id']}/handover",
                 {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    r = api.post("officer1", f"/api/handovers/{h['id']}/confirm", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SUMMARY_REQUIRED"
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Cần theo dõi huyết áp mỗi tuần"})
    r = api.post("officer1", f"/api/handovers/{h['id']}/confirm", {})
    assert r.status_code == 200
    stays = api.get("officer1", f"/api/persons/{p['id']}/stays").json()
    assert stays[0]["status"] == "transferred" and stays[0]["end_date"]
    # đơn vị đích tiếp nhận kỳ mới -> cùng HealthRecord, truy cập được
    r = api.post("officer2", f"/api/persons/{p['id']}/stays", {})
    assert r.status_code == 201
    summ = api.get("doctor2", f"/api/persons/{p['id']}/health-summary").json()
    assert summ["clinical"]["health_record_id"] == r.json()["health_record_id"]


def test_uat09_custody_officer_cannot_see_clinical_data_in_ui_or_api(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    api.post("doctor1", f"/api/encounters/{e['id']}/diagnoses", {"text": "Lao phổi", "kind": "final"})
    summ = api.get("officer1", f"/api/persons/{p['id']}/health-summary").json()
    assert summ["clinical"] is None and summ["clinical_hidden"] is True
    assert "Lao" not in str(summ)
    assert api.get("officer1", f"/api/encounters/{e['id']}").status_code == 403
    assert api.get("officer1", f"/api/persons/{p['id']}/encounters").status_code == 403
    assert api.get("officer1", f"/api/persons/{p['id']}/medication-orders").status_code == 403
    assert api.get("admin", f"/api/persons/{p['id']}/health-summary").status_code == 403  # sysadmin ≠ đọc bệnh án


def test_uat10_completed_record_corrected_by_addendum_not_overwrite(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    api.patch("doctor1", f"/api/encounters/{e['id']}", {"summary": "Bản gốc"})
    api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"})
    assert api.patch("doctor1", f"/api/encounters/{e['id']}", {"summary": "Ghi đè"}).status_code == 409
    r = api.post("doctor1", f"/api/encounters/{e['id']}/addenda", {"text": "Bổ sung kết quả", "reason": "Sót thông tin"})
    assert r.status_code == 201
    d = api.get("doctor1", f"/api/encounters/{e['id']}").json()
    assert d["summary"] == "Bản gốc" and len(d["addenda"]) == 1 and d["version"] > 1
    assert api.get("admin", "/api/audit?action=encounter_addendum").json()
    # đơn đã xác nhận: không sửa âm thầm, tạo phiên bản mới
    e2 = api.encounter(p["id"])
    o = api.confirmed_order(e2["id"])
    assert api.patch("doctor1", f"/api/medication-orders/{o['id']}", {"dose": "2 viên"}).status_code == 409
    n = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"dose": "2 viên", "reason": "Tăng liều"}).json()
    assert n["version"] == 2 and n["parent_order_id"] == o["id"] and n["status"] == "draft"
    api.post("doctor1", f"/api/medication-orders/{n['id']}/confirm", {"acknowledge_warnings": True, "ack_note": "thay thế"})
    assert api.get("doctor1", f"/api/medication-orders/{o['id']}").json()["status"] == "superseded"


PDF = b"%PDF-1.4\n%test document content\n"


def test_uat11_document_access_checked_and_audited(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    r = api.c.post("/api/documents", headers=api.h("nurse1"), data={"doc_type": "referral_letter", "encounter_id": e["id"]},
                   files={"file": ("giay.pdf", PDF, "application/pdf")})
    assert r.status_code == 201, r.text
    d = r.json()
    assert "storage_key" not in d and len(d["checksum"]) == 64
    assert api.c.get(f"/api/documents/{d['id']}/download", headers=api.h("doctor1")).content == PDF
    assert api.c.get(f"/api/documents/{d['id']}/download", headers=api.h("officer1")).status_code == 403
    assert api.c.get(f"/api/documents/{d['id']}/download", headers=api.h("doctor2")).status_code == 403  # cơ sở khác
    acts = [a["action"] for a in api.get("admin", f"/api/audit?person_id={p['id']}").json()]
    assert "document_uploaded" in acts and "document_download" in acts and "access_denied" in acts


def test_uat12_report_counts_follow_definition_and_facility(api):
    p1, _ = api.patient("P001")
    p2 = api.person("P002", "Trần B")
    api.post("officer2", f"/api/persons/{p2['id']}/stays", {})
    api.encounter(p1["id"])
    api.encounter(p1["id"])                      # cùng 1 người, 2 lượt
    api.encounter(p2["id"], user="doctor2")      # cơ sở khác – không được tính
    rep = api.get("manager1", "/api/reports/encounters").json()["data"]
    assert rep["total_encounters"] == 2 and rep["total_distinct_persons"] == 1
    assert rep["by_type"]["ad_hoc"] == {"encounter_count": 2, "distinct_person_count": 1}
    rep2 = api.get("manager1", "/api/reports/referrals").json()["data"]
    assert rep2["total"] == 0
