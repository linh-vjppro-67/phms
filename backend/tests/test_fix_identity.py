"""Hồi quy: định danh, đợt tiếp nhận, bàn giao/chuyển trại, gộp hồ sơ (báo cáo kiểm thử thực tế IntakeHandover/EM/MB/CC)."""
import unicodedata
from datetime import date, timedelta

from app.db import SessionLocal
from app.models import (AuditEvent, CarePlan, ClinicalOrder, CustodyStay, Encounter, Handover, MedicationOrder,
                        Appointment)


def err(r):
    return r.json()["error"]["code"]


def handover(api, sid, kind="transfer", user="officer1", **kw):
    body = {"kind": kind, "reason": "Điều chuyển", **({"to_facility_id": api.f2} if kind == "transfer" else {}), **kw}
    r = api.post(user, f"/api/stays/{sid}/handover", body)
    assert r.status_code == 201, r.text
    return r.json()


def summarize(api, hid, **kw):
    r = api.put("nurse1", f"/api/handovers/{hid}/summary", {"summary": "Tóm tắt y tế bàn giao đầy đủ", **kw})
    assert r.status_code == 200, r.text
    return r


# ---------------------------------------------------------------- #3, #15: định danh
def test_duplicate_check_and_search_ignore_case_unicode_form_spaces_and_diacritics(api):
    body = {"full_name": "Đỗ Văn Nam", "date_of_birth": "1979-05-05"}
    assert api.post("officer1", "/api/persons", body).status_code == 201
    for variant in ("ĐỖ VĂN NAM", "đỗ  văn nam ", unicodedata.normalize("NFD", "Đỗ Văn Nam"), "Do Van Nam"):
        r = api.post("officer1", "/api/persons", {**body, "full_name": variant})
        assert r.status_code == 409 and err(r) == "DUPLICATE_SUSPECTED", variant
    api.post("officer1", "/api/persons", {"full_name": "Đặng Ánh Xuân", "date_of_birth": "1990-01-01"})
    for q in ("đặng ánh", "ĐẶNG ÁNH", "dang anh", unicodedata.normalize("NFD", "đặng  ánh")):
        assert [p["full_name"] for p in api.get("officer1", f"/api/persons?q={q}").json()] == ["Đặng Ánh Xuân"], q


def test_names_are_stored_normalized_and_blank_names_rejected(api):
    r = api.post("officer1", "/api/persons", {"full_name": "  Lê   Thị  Ánh ", "date_of_birth": "1980-01-01"})
    assert r.status_code == 201 and r.json()["full_name"] == "Lê Thị Ánh"
    assert api.post("officer1", "/api/persons", {"full_name": "   "}).status_code == 422
    assert api.post("officer1", "/api/persons", {"full_name": " x "}).status_code == 422


def test_same_name_without_birth_date_is_suspected_duplicate(api):
    assert api.post("officer1", "/api/persons", {"full_name": "Trịnh Không Ngày"}).status_code == 201
    r = api.post("officer1", "/api/persons", {"full_name": "trịnh không ngày"})
    assert r.status_code == 409 and err(r) == "DUPLICATE_SUSPECTED"
    # một bên có ngày sinh, bên kia thiếu -> vẫn nghi trùng; khác ngày sinh rõ ràng -> không
    r = api.post("officer1", "/api/persons", {"full_name": "Trịnh Không Ngày", "date_of_birth": "1970-01-01"})
    assert r.status_code == 409
    api.post("officer1", "/api/persons", {"full_name": "Phan Có Ngày", "date_of_birth": "1970-01-01"})
    assert api.post("officer1", "/api/persons", {"full_name": "Phan Có Ngày", "date_of_birth": "1971-01-01"}).status_code == 201


def test_external_id_uniqueness_ignores_case_and_whitespace(api):
    api.person("IH-x")
    for src, ext in (("QLPN", "ih-x"), ("QLPN", " IH-x "), ("qlpn", "IH-x"), (" QLPN", "IH-X")):
        r = api.post("officer1", "/api/persons", {"full_name": "Người Khác", "date_of_birth": "1999-09-09",
                                                  "source_system": src, "external_id": ext})
        assert r.status_code == 409 and err(r) == "PERSON_EXISTS", (src, ext)


def test_stay_start_date_not_in_future_nor_before_birth(api):
    p = api.person()
    r = api.post("officer1", f"/api/persons/{p['id']}/stays", {"start_date": str(date.today() + timedelta(days=1))})
    assert r.status_code == 422
    r = api.post("officer1", f"/api/persons/{p['id']}/stays", {"start_date": "1980-01-01"})   # sinh 1985
    assert r.status_code == 422
    assert api.post("officer1", f"/api/persons/{p['id']}/stays", {"start_date": "2020-01-01"}).status_code == 201


# ---------------------------------------------------------------- #6 / CC#2: đối soát danh tính
def test_verify_is_facility_scoped_validated_and_audits_old_values(api):
    p, _ = api.patient("V1", "Hồ Văn Gốc")
    r = api.post("officer2", f"/api/persons/{p['id']}/verify", {"full_name": "Hijacked by F02", "note": "doi soat"})
    assert r.status_code == 403
    assert api.get("officer1", f"/api/persons/{p['id']}").json()["full_name"] == "Hồ Văn Gốc"
    assert api.post("officer1", f"/api/persons/{p['id']}/verify", {"full_name": " ", "note": "doi soat"}).status_code == 422
    other = api.person("V2", "Lý Thị Khác", dob="1977-07-07")
    r = api.post("officer1", f"/api/persons/{p['id']}/verify",
                 {"full_name": "LÝ THỊ KHÁC", "date_of_birth": "1977-07-07", "note": "doi soat"})
    assert r.status_code == 409 and err(r) == "DUPLICATE_SUSPECTED" and r.json()["error"]["candidates"][0]["id"] == other["id"]
    r = api.post("officer1", f"/api/persons/{p['id']}/verify",
                 {"source_system": "qlpn", "external_id": "v2", "note": "doi ma"})
    assert r.status_code == 409 and err(r) == "PERSON_EXISTS"
    r = api.post("officer1", f"/api/persons/{p['id']}/verify", {"full_name": "Hồ Văn Mới", "note": "doi soat ho so giay"})
    assert r.status_code == 200 and r.json()["full_name"] == "Hồ Văn Mới"
    with SessionLocal() as db:
        ev = db.query(AuditEvent).filter_by(action="person_verified", person_id=p["id"]).one()
    assert "Hồ Văn Gốc" in ev.reason and "Hồ Văn Mới" in ev.reason


# ---------------------------------------------------------------- #4, #5, #14: hủy đợt / bàn giao
def test_void_only_active_stay_without_pending_handover(api):
    p, s = api.patient()
    h = handover(api, s["id"])
    r = api.post("officer1", f"/api/stays/{s['id']}/void", {"reason": "Nhập nhầm người"})
    assert r.status_code == 409 and err(r) == "HANDOVER_PENDING"
    summarize(api, h["id"])
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {}).status_code == 200
    r = api.post("officer1", f"/api/stays/{s['id']}/void", {"reason": "Nhập nhầm người"})
    assert r.status_code == 409 and err(r) == "STAY_NOT_ACTIVE"
    assert api.get("officer1", f"/api/persons/{p['id']}/stays").json()[0]["status"] == "transferred"


def test_confirm_requires_stay_still_active(api):
    """Dữ liệu cũ: hai phiếu chờ trên cùng một đợt (lỗi chạy đua) -> chỉ phiếu đầu được xác nhận."""
    p, s = api.patient()
    h1 = handover(api, s["id"])
    summarize(api, h1["id"])
    with SessionLocal() as db:
        u = db.get(Handover, h1["id"])
        h2 = Handover(stay_id=s["id"], person_id=p["id"], kind="release", from_facility_id=api.f1,
                      reason="phiếu thứ hai", initiated_by=u.initiated_by, summary="Tóm tắt y tế bàn giao")
        db.add(h2)
        db.commit()
        h2_id = h2.id
    assert api.post("officer1", f"/api/handovers/{h1['id']}/confirm", {}).status_code == 200
    r = api.post("officer1", f"/api/handovers/{h2_id}/confirm", {})
    assert r.status_code == 409 and err(r) == "STAY_NOT_ACTIVE"
    assert api.get("officer1", f"/api/persons/{p['id']}/stays").json()[0]["status"] == "transferred"


def test_wrong_handover_can_be_cancelled_and_redone(api):
    p, s = api.patient()
    h = handover(api, s["id"])
    assert api.post("officer2", f"/api/handovers/{h['id']}/cancel", {"reason": "Sai cơ sở đích"}).status_code == 404
    assert api.post("officer1", f"/api/handovers/{h['id']}/cancel", {"reason": "  "}).status_code == 422
    r = api.post("officer1", f"/api/handovers/{h['id']}/cancel", {"reason": "Sai cơ sở đích"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "Sai cơ sở đích"
    assert api.post("officer1", f"/api/handovers/{h['id']}/cancel", {"reason": "Sai cơ sở đích"}).status_code == 409
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {}).status_code == 409
    handover(api, s["id"], kind="release")        # đợt tiếp nhận còn nguyên -> lập phiếu đúng
    assert api.get("officer1", f"/api/persons/{p['id']}/stays").json()[0]["status"] == "received"


# ---------------------------------------------------------------- #10, #15, CC#9: phiếu bàn giao
def test_release_has_no_destination_and_destination_reads_summary_only_after_receipt(api):
    p, s = api.patient()
    r = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "release", "to_facility_id": api.f2, "reason": "Mãn hạn"})
    assert r.status_code == 422
    h = handover(api, s["id"])
    summarize(api, h["id"], summary="HIV dương tính, đang điều trị ARV")
    api.post("officer1", f"/api/handovers/{h['id']}/confirm", {})
    before = api.get("nurse2", f"/api/handovers/{h['id']}").json()
    assert before["summary"] is None and before["has_summary"] is True
    assert api.get("nurse1", f"/api/handovers/{h['id']}").json()["summary"].startswith("HIV")
    api.stay(p["id"], user="officer2")
    assert api.get("nurse2", f"/api/handovers/{h['id']}").json()["summary"].startswith("HIV")
    with SessionLocal() as db:
        assert db.query(AuditEvent).filter_by(action="view_handover", object_id=h["id"]).count() == 2


def test_handover_summary_documents_must_be_valid_documents_of_the_person(api):
    p, s = api.patient()
    h = handover(api, s["id"])
    r = api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Tóm tắt y tế bàn giao", "document_ids": ["does-not-exist"]})
    assert r.status_code == 422 and err(r) == "BAD_HANDOVER_DOC"


# ---------------------------------------------------------------- #13, MB#2, EM#8: việc đang mở đi theo người khi chuyển trại
def test_transfer_moves_long_running_items_and_closes_open_encounters(api):
    p, s = api.managed()
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"])
    lab = api.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Công thức máu"})
    assert lab.status_code == 201, lab.text
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}).json()
    cp = api.post("doctor1", f"/api/persons/{p['id']}/care-plans",
                  {"problem_id": prob["id"], "goals": "HA < 140/90", "review_interval_days": 30,
                   "responsible_user_id": api.get("doctor1", "/api/auth/me").json()["id"]}).json()
    h = handover(api, s["id"])
    summarize(api, h["id"])
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 200
    with SessionLocal() as db:
        assert db.get(MedicationOrder, o["id"]).facility_id == api.f2
        plan = db.get(CarePlan, cp["id"])
        assert plan.facility_id == api.f2 and plan.responsible_user_id is None and plan.status == "active"
        appts = db.query(Appointment).filter_by(care_plan_id=cp["id"]).all()
        assert appts and all(a.facility_id == api.f2 and a.assignee_id is None and a.status == "scheduled" for a in appts)
        enc = db.get(Encounter, e["id"])
        assert enc.status == "cancelled" and enc.cancel_reason == "Chuyển trại – đã bàn giao"
        assert db.get(ClinicalOrder, lab.json()["id"]).status == "cancelled"


def test_open_items_count_only_the_sending_facility(api):
    p, s = api.patient()
    e = api.encounter(p["id"])
    api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"urgency": "routine", "reason": "Cần chụp CT ngoài", "destination": "BV X"})
    h = handover(api, s["id"])
    summarize(api, h["id"])
    api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True})
    s2 = api.stay(p["id"], user="officer2")
    h2 = handover(api, s2["id"], kind="release", user="officer2")
    items = api.get("nurse2", f"/api/handovers/{h2['id']}").json()["open_items"]
    assert items is not None and not any(items.values())        # việc của F01 không bắt F02 xác nhận


# ---------------------------------------------------------------- C4 / EM#5, EM#7: kỳ tạm cấp cứu
def test_intake_adopts_same_facility_provisional_stay(api):
    p = api.person()
    ev = api.post("nurse1", "/api/emergency-events", {"person_id": p["id"]}).json()
    prov = api.get("officer1", f"/api/persons/{p['id']}/stays").json()
    assert len(prov) == 1 and prov[0]["provisional"] is True
    r = api.post("officer1", f"/api/persons/{p['id']}/stays", {})
    assert r.status_code == 201 and r.json()["id"] == prov[0]["id"] and r.json()["provisional"] is False
    stays = api.get("officer1", f"/api/persons/{p['id']}/stays").json()
    assert len(stays) == 1 and stays[0]["status"] == "received"
    assert api.get("nurse1", f"/api/emergency-events/{ev['id']}").status_code == 200


def test_merge_temp_emergency_record_into_managed_person(api):
    real, s = api.managed("REAL1", "Vũ Văn Thật")
    ev = api.post("nurse1", "/api/emergency-events", {"temp_identity": "Nam ~40 tuổi, buồng 5"}).json()
    temp_id = ev["person_id"]
    r = api.post("officer1", "/api/person-merges", {"source_id": temp_id, "target_id": real["id"],
                                                    "reason": "Đối chiếu ảnh: hồ sơ tạm cấp cứu là người đang quản lý"})
    assert r.status_code == 201, r.text
    assert api.post("approver1", f"/api/person-merges/{r.json()['id']}/decision", {"approve": True}).status_code == 200
    with SessionLocal() as db:
        enc = db.get(Encounter, ev["encounter_id"])
        assert enc.person_id == real["id"] and enc.stay_id == s["id"]
        stays = {x.id: x for x in db.query(CustodyStay).filter_by(person_id=real["id"])}
    assert stays[s["id"]].status in ("received", "managed")
    assert [x.status for k, x in stays.items() if k != s["id"]] == ["voided"]


# ---------------------------------------------------------------- #7: gộp hồ sơ của cơ sở khác
def test_cannot_merge_away_a_person_active_at_another_facility(api):
    x, _ = api.patient("X1", "Mai Văn Xa")
    x_stays = api.get("officer1", f"/api/persons/{x['id']}/stays").json()
    api.post("officer1", f"/api/stays/{x_stays[0]['id']}/void", {"reason": "Nhập nhầm cơ sở"})
    api.stay(x["id"], user="officer2")                              # X đang quản lý tại F02
    y = api.post("officer1", "/api/persons", {"full_name": "Mai Văn Xa", "date_of_birth": "1985-05-05", "confirm_distinct": True}).json()
    for src, tgt in ((x["id"], y["id"]), (y["id"], x["id"])):
        r = api.post("officer1", "/api/person-merges", {"source_id": src, "target_id": tgt, "reason": "Cùng họ tên và ngày sinh"})
        assert r.status_code == 403 and err(r) == "ACTIVE_ELSEWHERE"
    assert api.get("officer1", f"/api/persons/{x['id']}").json()["status"] != "merged"
