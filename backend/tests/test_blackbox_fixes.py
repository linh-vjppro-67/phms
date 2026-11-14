"""Hồi quy cho các lỗi tìm ra khi kiểm thử hộp đen theo sơ đồ luồng (truy cập, tranh chấp đồng thời, tiếp nhận, chuyển trại, thuốc, quản trị)."""
import threading
import time
import uuid
from datetime import date, timedelta

import jwt
import pytest

from app import config
from app.db import SessionLocal, engine
from app.migrate import ensure_schema
from app.models import Person
from app.utils import name_key

needs_real_concurrency = pytest.mark.skipif(engine.dialect.name == "sqlite", reason="SQLite bộ nhớ dùng một kết nối chung; chạy trên PostgreSQL (và đã kiểm trên SQLite tệp bằng máy chủ thật)")


def transfer(api, ext, name, to=None):
    p, s = api.managed(ext, name)
    h = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": to or api.f2, "reason": "Điều chuyển"}).json()
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Tóm tắt y tế đầy đủ để bàn giao"})
    return p, s, h


# ------------------------------------------------------------------ truy cập
def test_old_facility_and_break_glass_are_read_only_for_clinical_writes(api):
    p, s, h = transfer(api, "BB1", "Chuyển Trại Chỉ Đọc")
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 200
    # cơ sở cũ: xem được, ghi thì không
    assert api.get("doctor1", f"/api/persons/{p['id']}/health-summary").status_code == 200
    for path, body in ((f"/api/persons/{p['id']}/allergies", {"substance": "Penicillin"}), (f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}),
                       (f"/api/persons/{p['id']}/allergy-status/none-confirmed", None)):
        r = api.post("doctor1", path, body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "NO_ACTIVE_STAY", path
    # break-glass: chỉ đọc
    q, _ = api.managed("BB2", "Break Glass Chỉ Đọc")
    api.post("doctor2", f"/api/persons/{q['id']}/break-glass", {"reason": "Cấp cứu: tra cứu người bệnh bất tỉnh"})
    assert api.get("doctor2", f"/api/persons/{q['id']}/health-summary").status_code == 200
    r = api.post("doctor2", f"/api/persons/{q['id']}/allergies", {"substance": "Aspirin"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "BREAKGLASS_READ_ONLY"
    assert api.post("doctor2", f"/api/persons/{q['id']}/problems", {"name": "Ghi lén"}).status_code == 403
    assert api.get("doctor1", f"/api/persons/{q['id']}/health-summary").json()["clinical"]["allergies"] == []
    # cơ sở đang quản lý vẫn ghi bình thường
    assert api.post("doctor1", f"/api/persons/{q['id']}/allergies", {"substance": "Aspirin"}).status_code == 201


# ------------------------------------------------------------------ tiếp nhận
def test_duplicate_check_and_search_ignore_accents_case_and_spaces(api):
    base = {"date_of_birth": "1990-05-05"}
    api.post("officer1", "/api/persons", {"full_name": "Nguyễn Văn Ân", **base})
    for v in ("NGUYỄN VĂN ÂN", "nguyễn văn ân", "Nguyen Van An", "  Nguyễn   Văn  Ân "):
        r = api.post("officer1", "/api/persons", {"full_name": v, **base})
        assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_SUSPECTED", v
    api.post("officer1", "/api/persons", {"full_name": "Trần Thị Bé", "source_system": "QLPN", "external_id": "TTB-77"})
    for q in ("tran thi be", "TRẦN THỊ BÉ", "thi  bé", "ttb-77"):
        assert len(api.get("officer1", f"/api/persons?q={q}").json()) == 1, q
    assert name_key("  ĐỖ  Văn Ân ") == "do van an"


def test_existing_people_without_name_key_are_backfilled():
    from sqlalchemy import text
    with SessionLocal() as s:
        s.add(Person(full_name="Hồ Sơ Cũ Không Khóa"))
        s.commit()
        s.execute(text("update person set name_key = NULL"))
        s.commit()
    ensure_schema(engine)
    with SessionLocal() as s:
        assert s.query(Person).one().name_key == "ho so cu khong khoa"


def test_identity_verify_is_scoped_to_managing_facility_and_audits_changes(api):
    p = api.post("officer1", "/api/persons", {"full_name": "Đối Soát Phạm Vi"}).json()
    api.stay(p["id"])
    r = api.post("officer2", f"/api/persons/{p['id']}/verify", {"source_system": "QLPN", "external_id": "SC-1", "full_name": "Bị Đổi Tên", "note": "Cơ sở khác thử"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FACILITY_SCOPE"
    assert api.get("officer1", f"/api/persons/{p['id']}").json()["full_name"] == "Đối Soát Phạm Vi"
    ok = api.post("officer1", f"/api/persons/{p['id']}/verify", {"source_system": "QLPN", "external_id": "SC-1", "full_name": "Đối Soát Phạm Vi Chuẩn", "note": "Đối chiếu hồ sơ QLPN"})
    assert ok.status_code == 200
    log = str(api.get("admin", "/api/audit?limit=20").json())
    assert "họ tên: 'Đối Soát Phạm Vi' → 'Đối Soát Phạm Vi Chuẩn'" in log and "nguồn: '/' → 'QLPN/SC-1'" in log


def test_merge_cannot_touch_person_managed_at_another_facility(api):
    src = api.post("officer1", "/api/persons", {"full_name": "Gộp Nguồn Cơ Sở Một"}).json()
    api.stay(src["id"])
    tgt = api.post("officer2", "/api/persons", {"full_name": "Gộp Đích Ở Cơ Sở Hai", "source_system": "QLPN", "external_id": "MG-F2"}).json()
    api.stay(tgt["id"], user="officer2")
    api.post("doctor1", "/api/encounters", {"person_id": src["id"], "type": "ad_hoc"})
    r = api.post("officer1", "/api/person-merges", {"source_id": src["id"], "target_id": tgt["id"], "reason": "Thử gộp vào người ở cơ sở khác"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTIVE_ELSEWHERE"
    nostay = api.post("officer1", "/api/persons", {"full_name": "Gộp Nguồn Không Kỳ"}).json()
    assert api.post("officer1", "/api/person-merges", {"source_id": nostay["id"], "target_id": tgt["id"], "reason": "Thử gộp vào người ở cơ sở khác"}).status_code == 409


# ------------------------------------------------------------------ chuyển trại
def test_handover_cancel_and_double_confirm_guard(api):
    p, s, h = transfer(api, "HC1", "Hủy Phiếu Bàn Giao")
    assert api.post("pharm1", f"/api/handovers/{h['id']}/cancel", {"reason": "Dược sĩ thử hủy phiếu"}).status_code == 403
    assert api.post("officer1", f"/api/handovers/{h['id']}/cancel", {"reason": "ngắn"}).status_code == 422
    r = api.post("officer1", f"/api/handovers/{h['id']}/cancel", {"reason": "Quyết định điều chuyển bị thay đổi"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 409
    assert api.post("officer1", f"/api/handovers/{h['id']}/cancel", {"reason": "Hủy lần hai"}).status_code == 409
    # hủy xong thì lập phiếu mới được
    assert api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Lập lại"}).status_code == 201
    assert "handover_cancelled" in str(api.get("admin", "/api/audit?limit=30").json())


def test_transfer_hands_over_orders_care_plans_and_appointments(api):
    p, s = api.managed("HO1", "Bàn Giao Theo Người")
    e = api.encounter(p["id"])
    keep = api.confirmed_order(e["id"])
    draft = api.med_order(e["id"], drug_name="Ibuprofen 400mg", drug_code="IBU400")
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}).json()
    cp = api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {"problem_id": prob["id"], "goals": "Huyết áp ổn", "review_interval_days": 14}).json()
    api.post("doctor1", "/api/appointments", {"person_id": p["id"], "due_date": str(date.today() + timedelta(days=3))})
    h = api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Đang dùng thuốc huyết áp, có kế hoạch theo dõi"})
    assert api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True}).status_code == 200
    api.stay(p["id"], user="officer2")
    assert [x["drug_name"] for x in api.get("pharm2", "/api/dispense-queue").json()] == [keep["drug_name"]]                  # dược Trại 2 thấy đơn
    assert api.get("pharm1", "/api/dispense-queue").json() == []                                                              # Trại 1 không còn
    assert [x["person_id"] for x in api.get("doctor2", "/api/care-plans").json()] == [p["id"]] and api.get("doctor1", "/api/care-plans").json() == []
    assert len([a for a in api.get("nurse2", "/api/appointments?limit=100").json() if a["person_id"] == p["id"]]) >= 1
    assert all(a["assignee_id"] is None for a in api.get("nurse2", "/api/appointments?limit=100").json() if a["person_id"] == p["id"])
    assert api.get("doctor2", f"/api/medication-orders/{draft['id']}").json()["status"] == "cancelled"                        # đơn nháp bị hủy, không chuyển
    assert api.post("pharm1", f"/api/medication-orders/{keep['id']}/dispenses", {"quantity": 1}).status_code == 409             # cơ sở cũ hết quyền cấp (không còn đợt hiệu lực)
    assert api.post("pharm2", f"/api/medication-orders/{keep['id']}/dispenses", {"quantity": 1}).status_code == 201
    assert cp["id"]


def test_official_intake_adopts_provisional_emergency_stay(api):
    ev = api.post("nurse1", "/api/emergency-events", {"temp_identity": "Nam khoảng 40 tuổi áo số 9", "description": "Co giật"}).json()
    pid = ev["person_id"]
    stays = api.get("officer1", f"/api/persons/{pid}/stays").json()
    assert len(stays) == 1 and stays[0]["provisional"] is True
    assert api.post("officer1", f"/api/persons/{pid}/stays", {}).status_code == 409                                           # chưa đối soát
    api.post("officer1", f"/api/persons/{pid}/verify", {"full_name": "Người Có Tên Thật", "source_system": "QLPN", "external_id": "AD-1", "note": "Đối chiếu ảnh"})
    r = api.post("officer1", f"/api/persons/{pid}/stays", {"source_ref": "QĐ 88/TG"})
    assert r.status_code == 201 and r.json()["provisional"] is False and r.json()["source_ref"] == "QĐ 88/TG"
    stays = api.get("officer1", f"/api/persons/{pid}/stays").json()
    assert len(stays) == 1 and stays[0]["provisional"] is False                                                               # vẫn MỘT đợt, đã chính thức


# ------------------------------------------------------------------ thuốc
def test_dispensed_totals_carry_across_revisions_and_returns_work(api):
    p, _ = api.managed("MD1", "Điều Chỉnh Đơn")
    e = api.encounter(p["id"])
    o = api.confirmed_order(e["id"])                                                                                          # 30
    d1 = api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 20}).json()
    v2 = api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "Đổi liều", "dose": "2 viên"}).json()
    assert v2["dispensed_net"] == 20 and v2["remaining"] == 10                                                                 # cộng dồn qua bản điều chỉnh
    api.post("doctor1", f"/api/medication-orders/{v2['id']}/confirm", {})
    over = api.post("pharm1", f"/api/medication-orders/{v2['id']}/dispenses", {"quantity": 30})
    assert over.status_code == 409 and over.json()["error"]["code"] == "OVER_DISPENSE" and over.json()["error"]["remaining"] == 10
    assert api.post("pharm1", f"/api/medication-orders/{v2['id']}/dispenses", {"quantity": 10}).status_code == 201
    ret = api.post("pharm1", f"/api/medication-orders/{v2['id']}/dispenses", {"kind": "return", "quantity": 5, "ref_dispense_id": d1["id"], "note": "Người nhận trả lại"})
    assert ret.status_code == 201                                                                                              # hoàn trả lần cấp ở BẢN CŨ
    assert api.get("doctor1", f"/api/medication-orders/{v2['id']}").json()["dispensed_net"] == 25


def test_non_finite_numbers_are_rejected_and_nothing_is_saved(api):
    p, _ = api.managed("NF1", "Số Không Hữu Hạn")
    e = api.encounter(p["id"])
    base = '{"drug_name":"Paracetamol 500mg","drug_code":"PARA500","dose":"1 viên","route":"uống","frequency":"2 lần/ngày","start_date":"%s","duration_days":5,"quantity_prescribed":%s}'
    for q in ("Infinity", "-Infinity", "NaN", "1e999", "99999999"):
        r = api.c.post(f"/api/encounters/{e['id']}/medication-orders", headers={**api.h("doctor1"), "content-type": "application/json"}, content=base % (date.today(), q))
        assert r.status_code == 422, q
    assert api.get("doctor1", f"/api/persons/{p['id']}/medication-orders").json() == []                                       # không lưu gì, danh sách vẫn đọc được
    o = api.confirmed_order(e["id"])
    for q in ("Infinity", "NaN"):
        assert api.c.post(f"/api/medication-orders/{o['id']}/dispenses", headers={**api.h("pharm1"), "content-type": "application/json"}, content='{"quantity": %s}' % q).status_code == 422


def test_administration_only_on_active_orders(api):
    p, _ = api.managed("AD1", "Ghi Nhận Dùng Thuốc")
    e = api.encounter(p["id"])
    draft = api.med_order(e["id"])
    r = api.post("nurse1", f"/api/medication-orders/{draft['id']}/administrations", {"administered": False, "reason": "thử"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ORDER_NOT_ACTIVE"
    o = api.confirmed_order(e["id"], drug_name="Ibuprofen 400mg", drug_code="IBU400")
    api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 5})
    assert api.post("nurse1", f"/api/medication-orders/{o['id']}/administrations", {"administered": True}).status_code == 201
    api.post("doctor1", f"/api/medication-orders/{o['id']}/stop", {"outcome": "stopped", "reason": "Dừng thử"})
    assert api.post("nurse1", f"/api/medication-orders/{o['id']}/administrations", {"administered": True}).json()["error"]["code"] == "ORDER_NOT_ACTIVE"


# ------------------------------------------------------------------ lịch / quản trị / xác thực
def test_date_validation_for_appointments_rounds_and_plans(api):
    p, _ = api.managed("DT1", "Kiểm Tra Ngày")
    past, far = str(date.today() - timedelta(days=2)), str(date.today() + timedelta(days=4000))
    assert api.post("doctor1", "/api/appointments", {"person_id": p["id"], "due_date": past}).status_code == 422
    assert api.post("doctor1", "/api/appointments", {"person_id": p["id"], "due_date": far}).status_code == 422
    ok = api.post("doctor1", "/api/appointments", {"person_id": p["id"], "due_date": str(date.today() + timedelta(days=3))})
    assert ok.status_code == 201
    assert api.post("nurse1", f"/api/appointments/{ok.json()['id']}/status", {"to": "postponed", "reason": "hoãn thử", "new_due_date": past}).status_code == 422
    assert api.post("manager1", "/api/checkup-rounds", {"name": "Đợt quá cũ", "due_date": str(date.today() - timedelta(days=900))}).status_code == 422
    assert api.post("manager1", "/api/checkup-rounds", {"name": "Đợt vừa qua", "due_date": str(date.today() - timedelta(days=15))}).status_code == 201
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Hen phế quản"}).json()
    assert api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {"problem_id": prob["id"], "goals": "Kiểm soát cơn", "review_interval_days": 30, "start_date": "1900-01-01"}).status_code == 422


def test_second_completion_of_same_appointment_does_not_duplicate_next_visit(api):
    p, _ = api.managed("AP1", "Hoàn Tất Lịch Hai Lần")
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}).json()
    api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {"problem_id": prob["id"], "goals": "Huyết áp ổn", "review_interval_days": 14})
    ap = next(a for a in api.get("doctor1", "/api/appointments?kind=care_plan").json() if a["person_id"] == p["id"])
    e1 = api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "periodic", "appointment_id": ap["id"]}).json()
    e2 = api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "periodic", "appointment_id": ap["id"]}).json()    # cùng lịch (cùng lúc)
    for e in (e1, e2):
        api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_progress"})
        assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"}).status_code == 200
    open_care = [a for a in api.get("doctor1", "/api/appointments?kind=care_plan").json() if a["person_id"] == p["id"] and a["status"] in ("scheduled", "due")]
    assert len(open_care) == 1                                                                                                 # chỉ MỘT lịch kế tiếp


def test_admin_cannot_demote_or_lock_self_nor_the_last_sysadmin(api):
    users = {u["username"]: u for u in api.get("admin", "/api/users").json()}
    me = users["admin"]["id"]
    for body in ({"role": "doctor"}, {"active": False}):
        r = api.patch("admin", f"/api/users/{me}", body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "SELF_CHANGE", body
    r = api.post("admin", "/api/users", {"username": "admin2", "password": "Tam@2026Pass1", "full_name": "QT 2", "role": "sysadmin"})
    assert r.status_code == 201
    a2 = r.json()["id"]
    assert api.patch("admin", f"/api/users/{a2}", {"active": False}).status_code == 200            # còn admin gốc -> khóa được admin2
    assert api.patch("admin", f"/api/users/{a2}", {"active": True}).status_code == 200
    assert api.patch("admin", f"/api/users/{users['doctor1']['id']}", {"role": "nurse"}).status_code == 200    # vai trò khác vẫn đổi được


def test_jwt_requires_exp_sub_ver_and_audit_limit_is_clamped(api):
    uid = next(u for u in api.get("admin", "/api/users").json() if u["username"] == "officer1")
    now = int(time.time())
    ok = jwt.encode({"sub": uid["id"], "ver": uid["token_version"], "exp": now + 600}, config.SECRET_KEY, algorithm="HS256")
    assert api.c.get("/api/auth/me", headers={"Authorization": f"Bearer {ok}"}).status_code == 200
    for claims in ({"sub": uid["id"], "ver": uid["token_version"]}, {"ver": 1, "exp": now + 600}, {"sub": uid["id"], "exp": now + 600}):
        t = jwt.encode(claims, config.SECRET_KEY, algorithm="HS256")
        assert api.c.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401, claims
    for _ in range(5):
        api.get("admin", "/api/audit/verify")
    assert len(api.get("admin", "/api/audit?limit=-1").json()) == 1 and len(api.get("admin", "/api/audit?limit=0").json()) == 1


# ------------------------------------------------------------------ tranh chấp đồng thời (cần kết nối riêng cho mỗi luồng → chạy trên PostgreSQL)
def run_threads(n, fn):
    out, bar = [None] * n, threading.Barrier(n)

    def w(i):
        bar.wait()
        out[i] = fn(i)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


@needs_real_concurrency
def test_concurrent_dispenses_never_exceed_prescription(api):
    p, _ = api.managed("RC1", "Cấp Phát Đồng Thời")
    o = api.confirmed_order(api.encounter(p["id"])["id"])
    for h in ("pharm1",):
        api.h(h)
    res = run_threads(8, lambda i: api.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 30}))
    assert sorted(r.status_code for r in res) == [201] + [409] * 7
    assert api.get("doctor1", f"/api/medication-orders/{o['id']}").json()["dispensed_net"] == 30


@needs_real_concurrency
def test_concurrent_handover_and_stay_creation_are_serialized(api):
    p, s = api.patient("RC2", "Phiếu Đồng Thời")
    api.h("officer1")
    res = run_threads(6, lambda i: api.post("officer1", f"/api/stays/{s['id']}/handover", {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}))
    assert sorted(r.status_code for r in res) == [201] + [409] * 5
    q = api.post("officer1", "/api/persons", {"full_name": "Tiếp Nhận Đồng Thời"}).json()
    res = run_threads(6, lambda i: api.post("officer1", f"/api/persons/{q['id']}/stays", {}))
    assert sorted(r.status_code for r in res) == [201] + [409] * 5
    assert len(api.get("officer1", f"/api/persons/{q['id']}/stays").json()) == 1
    code = "RC-" + uuid.uuid4().hex[:6]
    res = run_threads(6, lambda i: api.post("officer1", "/api/persons", {"full_name": "Cùng Mã Đồng Thời", "source_system": "QLPN", "external_id": code}))
    assert sorted(r.status_code for r in res) == [201] + [409] * 5                                                              # 409 (không phải 500)
