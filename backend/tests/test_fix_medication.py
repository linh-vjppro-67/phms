"""Hồi quy các lỗi quy trình thuốc tìm thấy khi kiểm thử thực tế (EM#…)."""
import json
from datetime import timedelta

from app.db import SessionLocal
from app.models import MedicationOrder
from app.utils import utcnow


def _code(r):
    return r.json()["error"]["code"]


def _dispense(api, oid, qty, **kw):
    return api.post("pharm1", f"/api/medication-orders/{oid}/dispenses", {"quantity": qty, **kw})


def _admin(api, oid, **kw):
    return api.post("nurse1", f"/api/medication-orders/{oid}/administrations", {"administered": True, **kw})


def _revise_confirmed(api, oid, **kw):
    n = api.post("doctor1", f"/api/medication-orders/{oid}/revise", {"reason": "tăng liều", "dose": "2 viên", **kw})
    assert n.status_code == 201, n.text
    r = api.post("doctor1", f"/api/medication-orders/{n.json()['id']}/confirm", {})
    assert r.status_code == 200, r.text
    return r.json()


def test_revision_carries_dispensed_quantity_forward(api):  # EM#2
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], quantity_prescribed=10)
    assert _dispense(api, o["id"], 10).status_code == 201
    v2 = _revise_confirmed(api, o["id"])
    assert v2["remaining"] == 0 and v2["dispensed_net"] == 10 and v2["dispense_status"] == "full"
    assert _code(_dispense(api, v2["id"], 10)) == "OVER_DISPENSE"
    v3 = _revise_confirmed(api, v2["id"], quantity_prescribed=15)
    assert v3["remaining"] == 5
    assert _dispense(api, v3["id"], 5).status_code == 201
    assert _code(_dispense(api, v3["id"], 1)) == "OVER_DISPENSE"


def test_revise_rejects_other_persons_encounter_and_stale_version(api):  # EM#3, EM#15
    p, _ = api.patient()
    q, _ = api.patient("P002", "Trần Văn B")
    e, eq = api.encounter(p["id"]), api.encounter(q["id"])
    o = api.confirmed_order(e["id"])
    r = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "xxx", "encounter_id": eq["id"]})
    assert r.status_code == 422 and _code(r) == "ENCOUNTER_PERSON_MISMATCH"
    assert all(m["person_id"] == q["id"] for m in api.get("doctor1", f"/api/encounters/{eq['id']}").json()["medication_orders"])
    r = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "xxx", "expected_version": 99})
    assert r.status_code == 409 and _code(r) == "VERSION_CONFLICT"
    r = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "xxx", "expected_version": o["version"]})
    assert r.status_code == 201


def test_non_finite_quantities_rejected_and_legacy_rows_readable(api):  # EM#4
    p, _ = api.patient()
    e = api.encounter(p["id"])
    raw = ('{"drug_name":"Paracetamol 500mg","dose":"1 viên","route":"uống","frequency":"2 lần/ngày",'
           f'"start_date":"{utcnow().date()}","duration_days":5,"quantity_prescribed":Infinity}}')
    r = api.c.post(f"/api/encounters/{e['id']}/medication-orders", content=raw,
                   headers=api.h("doctor1", **{"Content-Type": "application/json"}))
    assert r.status_code == 422
    assert api.get("doctor1", f"/api/persons/{p['id']}/medication-orders").json() == []
    o = api.confirmed_order(e["id"], quantity_prescribed=10)
    r = api.c.post(f"/api/medication-orders/{o['id']}/dispenses", content='{"quantity":Infinity}',
                   headers=api.h("pharm1", **{"Content-Type": "application/json"}))
    assert r.status_code == 422
    # dữ liệu cũ đã lưu Infinity: đọc không được lỗi 500
    with SessionLocal() as db:
        db.get(MedicationOrder, o["id"]).quantity_prescribed = float("inf")
        db.commit()
    r = api.get("doctor1", f"/api/persons/{p['id']}/medication-orders")
    assert r.status_code == 200 and r.json()[0]["quantity_prescribed"] is None
    assert api.get("doctor1", f"/api/medication-orders/{o['id']}").status_code == 200
    assert api.get("doctor1", "/api/medication-orders").status_code == 200
    assert api.post("doctor1", f"/api/medication-orders/{o['id']}/stop",
                    {"outcome": "cancelled", "reason": "nhập sai"}).status_code == 200


def test_administration_requires_effective_order(api):  # EM#9, EM#12
    p, _ = api.patient()
    e = api.encounter(p["id"])
    draft = api.med_order(e["id"], drug_name="Omeprazole 20mg", drug_code="OMEP20")
    assert _code(_admin(api, draft["id"], administered=False, reason="từ chối")) == "ORDER_NOT_EFFECTIVE"
    o = api.confirmed_order(e["id"], quantity_prescribed=10)
    _dispense(api, o["id"], 5)
    v2 = _revise_confirmed(api, o["id"])
    assert _code(_admin(api, o["id"])) == "ORDER_NOT_EFFECTIVE"   # bản cũ đã bị thay thế
    assert _admin(api, v2["id"]).status_code == 201                # liều đã cấp ở bản cũ dùng tiếp theo bản mới
    api.post("doctor1", f"/api/medication-orders/{v2['id']}/stop", {"outcome": "stopped", "reason": "tác dụng phụ"})
    assert _code(_admin(api, v2["id"])) == "ORDER_NOT_EFFECTIVE"


def test_administration_bounded_by_dispensed(api):  # EM#10
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], quantity_prescribed=10)
    d1 = _dispense(api, o["id"], 1).json()
    assert _admin(api, o["id"], dispense_id=d1["id"]).status_code == 201
    assert _code(_admin(api, o["id"], dispense_id=d1["id"])) == "OVER_ADMINISTER"
    assert _code(_admin(api, o["id"])) == "OVER_ADMINISTER"
    d2 = _dispense(api, o["id"], 2).json()
    _dispense(api, o["id"], 2, kind="return", ref_dispense_id=d2["id"], note="trả lại")
    assert _code(_admin(api, o["id"], dispense_id=d2["id"])) == "DISPENSE_RETURNED"


def test_administration_and_return_times_follow_timeline(api):  # EM#11
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], quantity_prescribed=10)
    d = _dispense(api, o["id"], 5).json()
    early = (utcnow() - timedelta(hours=2)).isoformat()
    assert _code(_admin(api, o["id"], occurred_at=early)) == "BEFORE_DISPENSE"
    assert _code(_admin(api, o["id"], dispense_id=d["id"], occurred_at=early)) == "BEFORE_DISPENSE"
    assert _code(_admin(api, o["id"], occurred_at="2021-01-01T08:00:00")) == "BEFORE_ORDER_START"
    r = _dispense(api, o["id"], 1, kind="return", ref_dispense_id=d["id"], note="trả", occurred_at="2020-01-01T08:00:00")
    assert r.status_code == 422 and _code(r) == "BEFORE_DISPENSE"


def test_allergy_added_after_confirm_is_rechecked(api):  # EM#13
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], drug_name="Amoxicillin 500mg", drug_code=None, quantity_prescribed=10)
    assert api.post("doctor1", f"/api/persons/{p['id']}/allergies", {"substance": "Penicillin", "reaction": "sốc phản vệ",
                    "severity": "severe", "confirmed": True}).status_code == 201
    row = next(x for x in api.get("pharm1", "/api/dispense-queue").json() if x["id"] == o["id"])
    assert row["requires_ack"] and any(w["type"] == "allergy" for w in row["warnings"])
    r = _dispense(api, o["id"], 5)
    assert r.status_code == 409 and _code(r) == "WARNINGS_UNACKNOWLEDGED"
    assert _dispense(api, o["id"], 5, acknowledge_warnings=True, ack_note="ok").status_code == 409  # ghi chú quá ngắn
    r = _dispense(api, o["id"], 5, acknowledge_warnings=True, ack_note="Đã báo bác sĩ, theo dõi sát")
    assert r.status_code == 201 and r.json()["new_warnings"]
    assert _admin(api, o["id"]).status_code == 201  # cảnh báo đã được xác nhận & lưu vào đơn


def test_allergy_recheck_blocks_administration(api):  # EM#13
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], drug_name="Amoxicillin 500mg", drug_code=None, quantity_prescribed=10)
    _dispense(api, o["id"], 5)
    api.post("doctor1", f"/api/persons/{p['id']}/allergies", {"substance": "Penicillin", "severity": "severe", "confirmed": True})
    assert _code(_admin(api, o["id"])) == "WARNINGS_UNACKNOWLEDGED"
    assert _admin(api, o["id"], acknowledge_warnings=True, ack_note="Bác sĩ đồng ý tiếp tục").status_code == 201


def test_stop_cancels_pending_revision(api):  # EM#14
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"])
    n = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "xxx", "dose": "2 viên"}).json()
    api.post("doctor1", f"/api/medication-orders/{o['id']}/stop", {"outcome": "stopped", "reason": "tác dụng phụ"})
    assert api.get("doctor1", f"/api/medication-orders/{n['id']}").json()["status"] == "cancelled"
    r = api.post("doctor1", f"/api/medication-orders/{n['id']}/confirm", {})
    assert r.status_code == 409


def test_confirm_revision_of_stopped_parent_rejected(api):  # EM#14 (bản nháp tạo trước khi có hủy theo)
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"])
    n = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "xxx", "dose": "2 viên"}).json()
    with SessionLocal() as db:
        db.get(MedicationOrder, o["id"]).status = "stopped"
        db.commit()
    r = api.post("doctor1", f"/api/medication-orders/{n['id']}/confirm", {})
    assert r.status_code == 409 and _code(r) == "PARENT_NOT_ACTIVE"


def test_tiny_quantity_over_dispense_rejected(api):  # EM#20
    p, _ = api.patient()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"], quantity_prescribed=10)
    assert _dispense(api, o["id"], 10).status_code == 201
    assert _dispense(api, o["id"], 1e-10).status_code == 422
    assert _code(_dispense(api, o["id"], 0.01)) == "OVER_DISPENSE"


def test_idempotent_response_not_committed_when_unserializable(api, monkeypatch):  # EM#4 (idempotency.py)
    import app.modules.medication as med
    p, _ = api.patient()
    e = api.encounter(p["id"])
    real = med.order_out
    monkeypatch.setattr(med, "order_out", lambda db, o: {**real(db, o), "x": float("nan")})
    body = {"drug_name": "Paracetamol 500mg", "dose": "1 viên", "route": "uống", "frequency": "2 lần/ngày",
            "start_date": str(utcnow().date()), "duration_days": 5, "quantity_prescribed": 10}
    for headers in ({}, {"Idempotency-Key": "inf-1"}):
        try:
            r = api.post("doctor1", f"/api/encounters/{e['id']}/medication-orders", body, headers=headers)
            assert r.status_code == 500
        except ValueError:   # TestClient ném lại lỗi máy chủ
            pass
    monkeypatch.undo()
    assert api.get("doctor1", f"/api/persons/{p['id']}/medication-orders").json() == []
    assert json.loads(api.post("doctor1", f"/api/encounters/{e['id']}/medication-orders", body,
                               headers={"Idempotency-Key": "inf-1"}).text)["quantity_prescribed"] == 10
