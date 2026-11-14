"""Hồi quy cho các lỗi UAT 13/11/2026 (DEF-01…04, REQ-01/02) và cứng hóa production."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import config
from app.db import engine

PDF = b"%PDF-1.4\n%uat fix test\n"
BG = {"reason": "Cần tiền sử dị ứng gấp cho ca cấp cứu"}
file_db_only = pytest.mark.skipif(engine.url.database in (None, "", ":memory:"),
                                  reason="cần CSDL tệp/PostgreSQL (SQLite bộ nhớ dùng chung một kết nối)")


def _upload(api, user, pid, headers=None):
    return api.c.post("/api/documents", headers=api.h(user, **(headers or {})), data={"doc_type": "lab_result", "person_id": pid},
                      files={"file": ("a.pdf", PDF, "application/pdf")})


# ---------------------------------------------------------------- DEF-01: break-glass chỉ đọc, kể cả tài liệu
def test_def01_break_glass_cannot_write_documents(api):
    p, _ = api.patient()
    doc = _upload(api, "nurse1", p["id"]).json()
    assert api.post("doctor2", f"/api/persons/{p['id']}/break-glass", BG).status_code in (200, 201)
    assert api.get("doctor2", f"/api/documents?person_id={p['id']}").status_code == 200        # đọc vẫn được
    up = _upload(api, "doctor2", p["id"])
    assert up.status_code == 403 and up.json()["error"]["code"] == "BREAKGLASS_READ_ONLY"
    rep = api.c.post(f"/api/documents/{doc['id']}/replace", headers=api.h("doctor2"), files={"file": ("b.pdf", PDF + b"2", "application/pdf")})
    assert rep.status_code == 403 and rep.json()["error"]["code"] == "BREAKGLASS_READ_ONLY"
    inv = api.post("doctor2", f"/api/documents/{doc['id']}/invalidate", {"reason": "Thử xóa trái phép"})
    assert inv.status_code == 403 and inv.json()["error"]["code"] == "BREAKGLASS_READ_ONLY"
    docs = api.get("doctor1", f"/api/documents?person_id={p['id']}").json()
    assert len(docs) == 1 and docs[0]["status"] == "valid"                                      # không có gì bị ghi
    assert _upload(api, "nurse1", p["id"]).status_code == 201                                   # cơ sở đúng vẫn ghi được


def test_def01_break_glass_header_path_cannot_write_documents(api):
    p, _ = api.patient()
    r = _upload(api, "doctor2", p["id"], headers={"X-Break-Glass-Reason": "Can%20tien%20su%20di%20ung%20gap%20cho%20ca%20cap%20cuu"})
    assert r.status_code == 403
    assert api.get("doctor1", f"/api/documents?person_id={p['id']}").json() == []


def test_replace_checks_permission_before_revealing_document_state(api):
    p, _ = api.patient()
    doc = _upload(api, "nurse1", p["id"]).json()
    api.post("nurse1", f"/api/documents/{doc['id']}/invalidate", {"reason": "Sai người bệnh"})
    r = api.c.post(f"/api/documents/{doc['id']}/replace", headers=api.h("nurse2"), files={"file": ("b.pdf", PDF, "application/pdf")})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FACILITY_SCOPE"             # không lộ "NOT_VALID" cho người ngoài phạm vi
    assert api.post("nurse1", f"/api/documents/{doc['id']}/invalidate", {"reason": "Lần hai"}).status_code == 409


# ---------------------------------------------------------------- DEF-02: khám ban đầu trùng khi gửi đồng thời
@file_db_only
def test_def02_concurrent_initial_encounters_create_exactly_one(api):
    p, _ = api.patient()
    barrier = threading.Barrier(6)

    def go(_):
        barrier.wait()
        return api.post("doctor1", "/api/encounters", {"person_id": p["id"], "type": "initial", "reason": "khám ban đầu"}).status_code

    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(go, range(6)))
    assert codes.count(201) == 1 and codes.count(409) == 5, codes
    encs = [e for e in api.get("doctor1", f"/api/persons/{p['id']}/encounters").json() if e["type"] == "initial"]
    assert len(encs) == 1


# ---------------------------------------------------------------- DEF-03: thiếu khóa ở các bước chuyển trạng thái
@file_db_only
def test_def03_concurrent_confirm_revise_approve_ack_succeed_once(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])

    def race(fn, n=4):
        barrier = threading.Barrier(n)

        def go(_):
            barrier.wait()
            return fn().status_code
        with ThreadPoolExecutor(n) as ex:
            return list(ex.map(go, range(n)))

    o = api.med_order(e["id"])
    codes = race(lambda: api.post("doctor1", f"/api/medication-orders/{o['id']}/confirm", {}))
    assert codes.count(200) == 1, codes
    events = api.get("admin", f"/api/audit?action=medication_order_confirmed&person_id={p['id']}").json()
    assert len(events) == 1, events                                                          # DEF-03: trước đây 3 sự kiện "confirmed" cho một đơn
    codes = race(lambda: api.post("doctor1", f"/api/medication-orders/{o['id']}/revise", {"reason": "Đổi liều", "dose": "2 viên"}))
    assert codes.count(201) == 1, codes

    ref = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Cần chụp CT ngoài", "destination": "BV A"}).json()
    assert api.patch("doctor1", f"/api/referrals/{ref['id']}/status", {"to": "pending"}).status_code == 200
    codes = race(lambda: api.patch("approver1", f"/api/referrals/{ref['id']}/status", {"to": "coordinated", "destination": "BV A"}))
    assert codes.count(200) == 1, codes
    r = api.get("approver1", f"/api/referrals/{ref['id']}").json()
    assert len([ev for ev in r["events"] if ev["to_status"] == "coordinated"]) == 1


# ---------------------------------------------------------------- DEF-04: chuyển viện trên lượt khám đã hủy
def test_def04_referral_on_cancelled_encounter_is_rejected(api):
    p, _ = api.patient()
    e = api.encounter(p["id"])
    assert api.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "cancelled", "reason": "Nhập nhầm người bệnh"}).status_code == 200
    r = api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Cần chụp CT ngoài", "destination": "BV A"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ENCOUNTER_CANCELLED"
    assert api.get("doctor1", "/api/referrals").json() == []                       # không sinh hồ sơ mồ côi


# ---------------------------------------------------------------- REQ-02: tra cứu danh tính liên cơ sở
def test_req02_identity_lookup_is_scoped_except_identity_roles(api):
    p, _ = api.patient(ext="P-F1", name="Trần Văn Riêng")          # tiếp nhận tại Trại 1
    names = lambda user: [x["id"] for x in api.get(user, "/api/persons?q=Trần Văn Riêng").json()]  # noqa: E731
    for u in ("doctor2", "nurse2", "pharm2"):
        assert p["id"] not in names(u), u                           # Trại 2 không thấy người của Trại 1
        assert api.get(u, f"/api/persons/{p['id']}").status_code == 403
    assert p["id"] in names("officer2")                              # cán bộ tiếp nhận: tra liên cơ sở (phát hiện trùng khi tiếp nhận)
    assert api.get("officer2", f"/api/persons/{p['id']}").status_code == 200
    for u in ("doctor1", "nurse1", "pharm1"):                        # cơ sở sở tại vẫn thấy (dược sĩ tra cứu người nhận thuốc)
        assert p["id"] in names(u), u
        assert api.get(u, f"/api/persons/{p['id']}").status_code == 200


def test_req02_break_glass_grant_makes_identity_visible(api):
    p, _ = api.patient(ext="P-F1", name="Lê Văn Khẩn")
    assert api.get("doctor2", f"/api/persons/{p['id']}").status_code == 403
    api.post("doctor2", f"/api/persons/{p['id']}/break-glass", BG)
    assert api.get("doctor2", f"/api/persons/{p['id']}").status_code == 200
    assert p["id"] in [x["id"] for x in api.get("doctor2", "/api/persons?q=Lê Văn Khẩn").json()]


# ---------------------------------------------------------------- production
def test_production_refuses_sqlite_unless_explicitly_allowed(monkeypatch):
    from app import main
    monkeypatch.setattr(config, "IS_PROD", True)
    monkeypatch.setattr(config, "PBKDF2_ITER", 200_000)
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(config, "DOC_ENC_KEY", "y" * 40)
    monkeypatch.setattr(config, "DATABASE_URL", "sqlite:///./phms.db")
    monkeypatch.delenv("PHMS_ALLOW_SQLITE", raising=False)
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        main._check_production_config()
    monkeypatch.setenv("PHMS_ALLOW_SQLITE", "1")
    main._check_production_config()
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+psycopg://u:p@db/phms")
    monkeypatch.delenv("PHMS_ALLOW_SQLITE")
    main._check_production_config()


def test_production_refuses_sample_accounts_with_public_default_password(api, monkeypatch):
    from app import main
    monkeypatch.setattr(config, "IS_PROD", True)
    monkeypatch.delenv("PHMS_ALLOW_SAMPLE_ACCOUNTS", raising=False)
    with pytest.raises(RuntimeError, match="tài khoản mẫu"):
        main._check_no_sample_accounts()
    monkeypatch.setenv("PHMS_ALLOW_SAMPLE_ACCOUNTS", "1")
    main._check_no_sample_accounts()
    monkeypatch.setattr(config, "IS_PROD", False)               # dev: tài khoản mẫu giữ nguyên, không bị chặn
    monkeypatch.delenv("PHMS_ALLOW_SAMPLE_ACCOUNTS")
    main._check_no_sample_accounts()


def test_bootstrap_creates_admin_without_sample_accounts_and_is_idempotent(api):
    from sqlalchemy import select
    from app.bootstrap import bootstrap
    from app.db import Base, SessionLocal
    from app.models import Facility, User
    from app.security import verify_password
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    r = bootstrap([("T01", "Trại thật 1")], "quantri", "Quản trị", None)
    assert r["admin_created"] and r["generated_password"] and "T01" in r["facilities"]
    with SessionLocal() as db:
        users = list(db.scalars(select(User)))
        assert [u.username for u in users] == ["quantri"] and users[0].role == "sysadmin" and users[0].must_change_password
        assert verify_password(r["generated_password"], users[0].password_hash)
        assert [f.code for f in db.scalars(select(Facility))] == ["T01"]
    r2 = bootstrap([("T01", "Trại thật 1")], "quantri", "Quản trị", None)
    assert not r2["admin_created"] and r2["facilities"] == []
    with pytest.raises(SystemExit):
        bootstrap([("T01", "x")], "khac", "Khác", "yeu")           # mật khẩu yếu bị từ chối


def test_readiness_endpoint(api):
    assert api.c.get("/api/health/ready").json() == {"status": "ready"}
