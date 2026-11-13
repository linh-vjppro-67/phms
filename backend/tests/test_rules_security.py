"""Business rules BR-01…07, bảo mật, audit, idempotency, tài liệu."""
from datetime import date, timedelta
from urllib.parse import quote

from app.db import SessionLocal
from app.models import AuditEvent

PDF = b"%PDF-1.4\nhello"


# ------------------------------------------------------------------ BR
def test_br01_external_id_unique_and_no_auto_merge(api):
    p = api.person("P001", "Nguyễn Văn A", "1985-05-05")
    r = api.post("officer1", "/api/persons", {"full_name": "Khác", "source_system": "QLPN", "external_id": "P001"})
    assert r.status_code == 409 and r.json()["error"]["existing_person_id"] == p["id"]
    # cùng mã ở hệ thống nguồn khác là người khác (mã ngoài không phải khóa toàn cục)
    assert api.post("officer1", "/api/persons", {"full_name": "Khác", "source_system": "HT2",
                                                  "external_id": "P001"}).status_code == 201
    # trùng tên+ngày sinh -> chờ đối soát, KHÔNG tự gộp
    q = api.person("P002", "nguyễn văn a", "1985-05-05")
    assert q["id"] != p["id"] and q["status"] == "pending_verification" and q["duplicate_candidates"] == [p["id"]]
    # thiếu định danh -> chờ đối soát
    r = api.post("officer1", "/api/persons", {"full_name": "Không rõ mã"})
    assert r.json()["status"] == "pending_verification"
    assert api.post("officer1", "/api/persons", {"full_name": "X", "external_id": "1"}).status_code == 422


def test_br02_no_physical_delete_and_cancel_needs_reason(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    assert api.c.delete(f"/api/encounters/{e['id']}", headers=api.h("doctor1")).status_code == 405
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "cancelled"}).status_code == 422
    r = api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "cancelled", "reason": "Nhập nhầm"})
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "Nhập nhầm"
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_progress"}).status_code == 409


def test_br03_occurred_vs_recorded_and_future_rejected(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    past = (date.today() - timedelta(days=1)).isoformat() + "T07:30:00"
    o = api.post("nurse1", f"/api/encounters/{e['id']}/observations",
                 {"type": "Huyết áp tâm thu", "value": "130", "unit": "mmHg", "occurred_at": past}).json()
    assert o["occurred_at"].startswith(past[:10]) and o["recorded_at"] > o["occurred_at"] and o["numeric_value"] == 130
    fut = (date.today() + timedelta(days=2)).isoformat() + "T07:30:00"
    assert api.post("nurse1", f"/api/encounters/{e['id']}/observations",
                    {"type": "x", "value": "1", "unit": "u", "occurred_at": fut}).status_code == 422
    assert api.post("nurse1", f"/api/encounters/{e['id']}/observations",
                    {"type": "Nhiệt độ", "value": "37", "unit": ""}).status_code == 422  # bắt buộc đơn vị đo


def test_br04_dispense_must_reference_effective_order_and_not_exceed(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    draft = api.med_order(e["id"])
    assert api.post("pharm1", f"/api/medication-orders/{draft['id']}/dispenses",
                    {"quantity": 1}).json()["error"]["code"] == "ORDER_NOT_EFFECTIVE"
    o = api.confirmed_order(e["id"], drug_name="Metformin 850mg", drug_code="MET850", quantity_prescribed=30)
    assert api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses",
                    {"quantity": 31}).json()["error"]["code"] == "OVER_DISPENSE"
    r1 = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 10}).json()
    r2 = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 20}).json()
    assert r2["status"] == "full" and r2["order"]["dispense_status"] == "full"
    # hoàn trả ghi riêng, tham chiếu lần cấp
    assert api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses",
                    {"kind": "return", "quantity": 4, "ref_dispense_id": r1["id"]}).status_code == 422  # thiếu lý do
    rr = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses",
                  {"kind": "return", "quantity": 4, "ref_dispense_id": r1["id"], "note": "Người nhận trả lại"}).json()
    assert rr["order"]["dispensed_net"] == 26 and rr["order"]["dispense_status"] == "partial"
    assert api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses",
                    {"kind": "return", "quantity": 7, "ref_dispense_id": r1["id"], "note": "quá"}).status_code == 409
    # không xác nhận 'đã dùng' khi chưa cấp
    o2 = api.confirmed_order(e["id"], drug_name="Omeprazole 20mg", drug_code="OMEP20")
    assert api.post("nurse1", f"/api/medication-orders/{o2['id']}/administrations",
                    {"administered": True}).json()["error"]["code"] == "NOT_DISPENSED"
    # pharmacist không được sửa chỉ định
    assert api.post("pharm1", f"/api/medication-orders/{o2['id']}/revise", {"dose": "9", "reason": "xxx"}).status_code == 403


def test_br05_transfer_does_not_end_health_record_referral_not_end_stay(api):
    p, s = api.patient()
    e = api.encounter(p["id"])
    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals",
                   {"urgency": "routine", "reason": "Cần chụp CT ngoài", "destination": "BV X"}).json()
    h = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2,
                                                                "reason": "chuyển"}).json()
    assert h["open_items"] is None  # cán bộ quản lý không thấy nội dung y tế
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Đang chờ chuyển viện chụp CT"})
    r = api.post("officer1", f"/api/handovers/{h['id']}/confirm", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OPEN_ITEMS"  # điều trị đang mở phải được xác nhận
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 200
    with SessionLocal() as db:
        from app.models import HealthRecord, Referral
        assert db.query(HealthRecord).filter_by(person_id=p["id"]).count() == 1
        assert db.get(Referral, ref["id"]).status == "draft"  # chuyển trại không đụng trạng thái chuyển viện


def test_br06_idempotency_and_optimistic_locking(api):
    p, _ = api.patient()
    body = {"person_id": p["id"], "type": "ad_hoc", "reason": "x"}
    k = {"Idempotency-Key": "abc-1"}
    r1 = api.post("doctor1", "/api/encounters", body, headers=k)
    r2 = api.post("doctor1", "/api/encounters", body, headers=k)
    assert r1.json()["id"] == r2.json()["id"] and r2.headers.get("Idempotent-Replay") == "true"
    assert api.post("doctor1", "/api/encounters", {**body, "reason": "khác"}, headers=k).status_code == 422
    assert len(api.get("doctor1", f"/api/persons/{p['id']}/encounters").json()) == 1
    # dispense double-submit
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], quantity_prescribed=30)
    d = {"quantity": 20}
    a = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", d, headers={"Idempotency-Key": "d1"})
    b = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", d, headers={"Idempotency-Key": "d1"})
    assert a.json()["id"] == b.json()["id"]
    assert api.get("doctor1", f"/api/medication-orders/{o['id']}").json()["dispensed_net"] == 20
    # version conflict
    r = api.patch("doctor1", f"/api/encounters/{e['id']}", {"summary": "A", "expected_version": e["version"]})
    assert r.status_code == 200
    r = api.patch("doctor1", f"/api/encounters/{e['id']}", {"summary": "B", "expected_version": e["version"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "VERSION_CONFLICT"


def test_br07_no_data_is_not_negative(api):
    p, _ = api.patient()
    c = api.get("doctor1", f"/api/persons/{p['id']}/health-summary").json()["clinical"]
    assert c["allergy_status"] == "unknown" and c["allergies"] == [] and "CHƯA GHI NHẬN" in c["notice"]
    api.post("doctor1", f"/api/persons/{p['id']}/allergy-status/none-confirmed")
    assert api.get("doctor1", f"/api/persons/{p['id']}/health-summary").json()["clinical"]["allergy_status"] == "none_confirmed"


# ------------------------------------------------------------------ bảo mật
def test_auth_required_lockout_and_token_revocation(api):
    assert api.c.get("/api/persons").status_code == 401
    assert api.c.get("/api/persons", headers={"Authorization": "Bearer junk"}).status_code == 401
    for _ in range(5):
        assert api.c.post("/api/auth/login", json={"username": "nurse2", "password": "bad"}).status_code == 401
    assert api.c.post("/api/auth/login", json={"username": "nurse2", "password": "Phms@2026dev"}).status_code == 423
    tok = api.h("officer2")
    r = api.c.post("/api/auth/change-password", headers=tok, json={"old_password": "Phms@2026dev", "new_password": "weak"})
    assert r.status_code == 422
    r = api.c.post("/api/auth/change-password", headers=tok, json={"old_password": "Phms@2026dev", "new_password": "NewPass#2026x"})
    assert r.status_code == 200
    assert api.c.get("/api/auth/me", headers=tok).status_code == 401  # phiên cũ bị thu hồi


def test_rbac_matrix_samples(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    assert api.post("nurse1", f"/api/encounters/{e['id']}/diagnoses", {"text": "x"}).status_code == 403
    assert api.post("nurse1", f"/api/encounters/{e['id']}/medication-orders", {}).status_code == 403
    assert api.post("manager1", "/api/persons", {"full_name": "Zz"}).status_code == 403
    assert api.get("manager1", f"/api/persons/{p['id']}").status_code == 403
    assert api.get("nurse1", "/api/users").status_code == 403
    assert api.get("nurse1", "/api/audit").status_code == 403
    assert api.post("nurse1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 403
    assert api.post("admin", "/api/users", {"username": "bs3", "password": "Abcdefghij1", "full_name": "BS",
                                            "role": "doctor", "facility_id": api.f1}).status_code == 201
    assert api.post("admin", "/api/users", {"username": "bs4", "password": "short", "full_name": "BS",
                                            "role": "doctor", "facility_id": api.f1}).status_code == 422


def test_facility_isolation_and_break_glass(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    assert api.get("doctor2", f"/api/persons/{p['id']}/health-summary").status_code == 403
    assert api.get("doctor2", f"/api/encounters/{e['id']}").status_code == 403
    # break-glass: bắt buộc lý do, có audit + cảnh báo hậu kiểm
    assert api.get("doctor2", f"/api/persons/{p['id']}/health-summary",
                   headers={"X-Break-Glass-Reason": quote("ngắn")}).status_code == 422
    r = api.get("doctor2", f"/api/persons/{p['id']}/health-summary",
                headers={"X-Break-Glass-Reason": quote("Cấp cứu nghi ngộ độc, cần tiền sử dị ứng")})
    assert r.status_code == 200
    assert api.get("admin", "/api/audit?action=break_glass").json()
    # pharmacist không có break-glass
    assert api.get("pharm1", f"/api/persons/{p['id']}/health-summary").status_code == 200  # cùng cơ sở


def test_audit_chain_is_tamper_evident_and_append_only(api):
    p, _ = api.patient()
    api.get("doctor1", f"/api/persons/{p['id']}/health-summary")
    assert api.get("admin", "/api/audit/verify").json()["ok"] is True
    import pytest
    with SessionLocal() as db:
        ev = db.query(AuditEvent).first()
        ev.reason = "tamper"
        with pytest.raises(RuntimeError):
            db.commit()
        db.rollback()
        db.execute(AuditEvent.__table__.update().where(AuditEvent.seq == 1).values(reason="tamper"))  # sửa trực tiếp DB
        db.commit()
    v = api.get("admin", "/api/audit/verify").json()
    assert v["ok"] is False and v["broken_at_seq"] == 1


def test_documents_validation_versioning_and_integrity(api):
    p, _ = api.patient()
    up = lambda name, data, **f: api.c.post("/api/documents", headers=api.h("nurse1"), data={  # noqa: E731
        "doc_type": "lab_result", "person_id": p["id"], **f}, files={"file": (name, data, "application/pdf")})
    assert up("evil.pdf", b"MZ\x90\x00 not a pdf").status_code == 415            # sai magic bytes
    assert up("e.pdf", PDF + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE").status_code == 422
    assert up("big.pdf", PDF + b"0" * (10 * 1024 * 1024)).status_code == 413
    assert api.c.post("/api/documents", headers=api.h("nurse1"), data={"doc_type": "lab_result"},
                      files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 422  # thiếu liên kết
    d = up("../../etc/passwd.pdf", PDF).json()
    assert d["filename"] == "passwd.pdf"                                           # chống path traversal
    n = api.c.post(f"/api/documents/{d['id']}/replace", headers=api.h("nurse1"),
                   files={"file": ("v2.pdf", PDF + b"v2", "application/pdf")}).json()
    assert n["version"] == 2 and n["replaces_id"] == d["id"]
    docs = {x["id"]: x for x in api.get("doctor1", f"/api/documents?person_id={p['id']}").json()}
    assert docs[d["id"]]["status"] == "superseded" and docs[n["id"]]["status"] == "valid"
    assert api.post("nurse1", f"/api/documents/{n['id']}/invalidate", {"reason": "Sai người"}).json()["status"] == "invalid"
    # tệp lưu mã hóa; sửa tệp trên đĩa -> phát hiện mất toàn vẹn
    import os
    from app import config
    from app.models import MedicalDocument
    with SessionLocal() as db:
        key = db.get(MedicalDocument, d["id"]).storage_key
    raw = open(os.path.join(config.DOC_STORAGE_DIR, key), "rb").read()
    assert PDF not in raw
    open(os.path.join(config.DOC_STORAGE_DIR, key), "wb").write(raw[:-3] + b"xxx")
    assert api.c.get(f"/api/documents/{d['id']}/download", headers=api.h("doctor1")).status_code == 500


def test_report_export_needs_purpose_and_is_audited(api):
    assert api.get("manager1", "/api/reports/encounters?format=csv").status_code == 422
    r = api.get("manager1", "/api/reports/encounters?format=csv&purpose=Báo cáo tháng gửi cấp trên")
    assert r.status_code == 200 and r.text.startswith("metric,value")
    assert api.get("admin", "/api/audit?action=report_exported").json()
    assert api.get("nurse1", "/api/reports/encounters").status_code == 403


def test_validation_errors_are_structured(api):
    r = api.post("officer1", "/api/persons", {"full_name": "A"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.get("officer1", "/api/persons/does-not-exist").status_code == 404
