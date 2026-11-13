"""Hồi quy: kiểm soát xuyên suốt (tài liệu, quản trị người dùng, xác thực, báo cáo, kiểm toán) và cấp cứu."""
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt

from app import config

PDF = b"%PDF-1.4\n%controls regression\n"


def upload(api, user, pid, **form):
    return api.c.post("/api/documents", headers=api.h(user), data={"doc_type": "lab_result", "person_id": pid, **form},
                      files={"file": ("x.pdf", PDF, "application/pdf")})


def transfer_to_f2(api, s, receive=False):
    h = api.post("officer1", f"/api/stays/{s['id']}/handover",
                 {"kind": "transfer", "to_facility_id": api.f2, "reason": "Điều chuyển"}).json()
    api.put("nurse1", f"/api/handovers/{h['id']}/summary", {"summary": "Theo dõi huyết áp"})
    r = api.post("officer1", f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True})
    assert r.status_code == 200, r.text
    if receive:
        r = api.post("officer2", f"/api/persons/{s['person_id']}/stays", {})
        assert r.status_code == 201, r.text
    return h


def audit_actions(api, action):
    return api.get("admin", f"/api/audit?action={action}").json()


# ---------------------------------------------------------------- tài liệu
def test_break_glass_cannot_write_documents(api):
    p, _ = api.managed()
    doc = upload(api, "nurse1", p["id"]).json()
    bg = {"X-Break-Glass-Reason": "Cap cuu ngoai gio can xem tien su"}
    assert api.get("doctor2", f"/api/documents?person_id={p['id']}", headers=bg).status_code == 200   # đọc được
    r = api.c.post("/api/documents", headers=api.h("doctor2", **bg), data={"doc_type": "lab_result", "person_id": p["id"]},
                   files={"file": ("x.pdf", PDF, "application/pdf")})
    assert r.status_code == 403
    assert api.post("doctor2", f"/api/documents/{doc['id']}/invalidate", {"reason": "nham nguoi"}, headers=bg).status_code == 403
    assert api.get("nurse1", f"/api/documents?person_id={p['id']}").json()[0]["status"] == "valid"


def test_old_facility_cannot_upload_after_transfer(api):
    p, s = api.managed()
    transfer_to_f2(api, s, receive=True)
    assert upload(api, "nurse1", p["id"]).status_code == 403
    assert upload(api, "nurse2", p["id"]).status_code == 201


def test_break_glass_header_on_unknown_person_is_404(api):
    bg = {"X-Break-Glass-Reason": "Cap%20cuu%20khan%20cap%20test"}
    ghost = str(uuid.uuid4())
    assert api.get("nurse2", f"/api/documents?person_id={ghost}", headers=bg).status_code == 404
    r = api.c.post("/api/documents", headers=api.h("nurse2", **bg), data={"doc_type": "lab_result", "person_id": ghost},
                   files={"file": ("x.pdf", PDF, "application/pdf")})
    assert r.status_code == 404


def test_invalidate_only_valid_documents(api):
    p, _ = api.managed()
    d1 = upload(api, "nurse1", p["id"]).json()
    api.c.post(f"/api/documents/{d1['id']}/replace", headers=api.h("nurse1"), files={"file": ("v2.pdf", PDF + b"v2", "application/pdf")})
    r = api.post("nurse1", f"/api/documents/{d1['id']}/invalidate", {"reason": "nham"})
    assert r.status_code == 409    # bản đã bị thay thế giữ trạng thái superseded
    d3 = upload(api, "nurse1", p["id"]).json()
    assert api.post("nurse1", f"/api/documents/{d3['id']}/invalidate", {"reason": "lan dau"}).status_code == 200
    assert api.post("nurse1", f"/api/documents/{d3['id']}/invalidate", {"reason": "lan hai"}).status_code == 409
    docs = {d["id"]: d for d in api.get("nurse1", f"/api/documents?person_id={p['id']}").json()}
    assert docs[d1["id"]]["status"] == "superseded" and docs[d3["id"]]["invalid_reason"] == "lan dau"


def test_document_issued_date_not_in_future(api):
    p, _ = api.managed()
    r = upload(api, "nurse1", p["id"], issued_date=str(date.today() + timedelta(days=1)))
    assert r.status_code == 422
    assert upload(api, "nurse1", p["id"], issued_date=str(date.today())).status_code == 201


# ---------------------------------------------------------------- quản trị người dùng
def _new_user(api, username, role, facility_id=None):
    r = api.post("admin", "/api/users", {"username": username, "password": "Str0ng!Passw0rd#", "full_name": username,
                                         "role": role, "facility_id": facility_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_patch_user_rejects_unknown_facility(api):
    u = _new_user(api, "cc_doc", "doctor", api.f1)
    r = api.patch("admin", f"/api/users/{u['id']}", {"facility_id": "NONEXISTENT-FAC"})
    assert r.status_code == 422


def test_patch_user_enforces_role_facility_rule(api):
    sa = _new_user(api, "cc_sa", "sysadmin")
    assert api.patch("admin", f"/api/users/{sa['id']}", {"role": "doctor"}).status_code == 422          # nghiệp vụ cần cơ sở
    r = api.patch("admin", f"/api/users/{sa['id']}", {"role": "doctor", "facility_id": api.f1})
    assert r.status_code == 200 and r.json()["facility_id"] == api.f1
    doc = _new_user(api, "cc_doc2", "doctor", api.f1)
    assert api.patch("admin", f"/api/users/{doc['id']}", {"role": "sysadmin", "facility_id": api.f1}).status_code == 422
    r = api.patch("admin", f"/api/users/{doc['id']}", {"role": "sysadmin"})                          # tự bỏ cơ sở
    assert r.status_code == 200 and r.json()["role"] == "sysadmin" and r.json()["facility_id"] is None
    assert api.post("admin", "/api/users", {"username": "cc_sa3", "password": "Str0ng!Passw0rd#", "full_name": "x",
                                            "role": "sysadmin", "facility_id": api.f1}).status_code == 422


def test_admin_cannot_change_own_role_facility_or_active(api):
    me = api.get("admin", "/api/auth/me").json()
    for body in ({"role": "nurse", "facility_id": api.f1}, {"active": False}, {"facility_id": api.f1}):
        assert api.patch("admin", f"/api/users/{me['id']}", body).status_code == 403
    assert api.get("admin", "/api/auth/me").json()["role"] == "sysadmin"


# ---------------------------------------------------------------- xác thực
def test_wrong_old_password_counts_toward_lockout(api):
    for _ in range(config.MAX_FAILED_LOGINS):
        r = api.post("nurse1", "/api/auth/change-password", {"old_password": "sai-mat-khau", "new_password": "N3w!Passw0rd#x"})
        assert r.status_code == 401
    from app.seed import DEFAULT_PASSWORD
    r = api.c.post("/api/auth/login", json={"username": "nurse1", "password": DEFAULT_PASSWORD})
    assert r.status_code == 423


def test_token_requires_exp_and_sub(api):
    me = api.get("doctor1", "/api/auth/me").json()
    now = datetime.now(timezone.utc)
    no_exp = jwt.encode({"sub": me["id"], "ver": me["token_version"], "iat": now}, config.SECRET_KEY, algorithm="HS256")
    no_sub = jwt.encode({"ver": me["token_version"], "iat": now, "exp": now + timedelta(minutes=5)}, config.SECRET_KEY, algorithm="HS256")
    for tok in (no_exp, no_sub):
        assert api.c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


# ---------------------------------------------------------------- kiểm toán + báo cáo
def test_audit_list_limit_clamped_and_reads_audited(api):
    api.managed()
    assert len(api.get("admin", "/api/audit?limit=-1").json()) == 1
    assert audit_actions(api, "audit_viewed")


def test_health_problem_report_follows_managing_facility_and_range(api):
    p, s = api.managed()
    assert api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}).status_code == 201
    assert api.get("manager1", "/api/reports/health-problems").json()["data"]["active_by_problem"] == {"Tăng huyết áp": 1}
    transfer_to_f2(api, s, receive=True)
    assert api.get("manager1", "/api/reports/health-problems").json()["data"]["active_by_problem"] == {}
    assert api.get("manager2", "/api/reports/health-problems").json()["data"]["active_by_problem"] == {"Tăng huyết áp": 1}
    old = f"date_from={date.today() - timedelta(days=120)}&date_to={date.today() - timedelta(days=90)}"
    assert api.get("manager2", f"/api/reports/health-problems?{old}").json()["data"]["active_by_problem"] == {}


# ---------------------------------------------------------------- cấp cứu
def test_emergency_at_sending_facility_blocked_while_transfer_unreceived(api):
    p, s = api.managed()
    transfer_to_f2(api, s)
    r = api.post("nurse1", "/api/emergency-events", {"person_id": p["id"], "description": "Ngất"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TRANSFER_IN_PROGRESS"
    assert api.post("nurse2", "/api/emergency-events", {"person_id": p["id"], "description": "Ngất"}).status_code == 201
    assert api.post("officer2", f"/api/persons/{p['id']}/stays", {}).status_code == 201     # cơ sở đích vẫn tiếp nhận được


def _event(api, user="nurse1"):
    p, _ = api.managed()
    r = api.post(user, "/api/emergency-events", {"person_id": p["id"], "description": "Đau ngực"})
    assert r.status_code == 201, r.text
    return p, r.json()


def test_intervention_time_must_fit_event_timeline(api):
    _, ev = _event(api)
    url = f"/api/emergency-events/{ev['id']}/interventions"
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    before = (datetime.fromisoformat(ev["occurred_at"]) - timedelta(days=365)).isoformat()
    assert api.post("nurse1", url, {"action": "Thở oxy", "occurred_at": future}).status_code == 422
    assert api.post("nurse1", url, {"action": "Thở oxy", "occurred_at": before}).status_code == 422
    assert api.post("nurse1", url, {"action": "Thở oxy"}).status_code == 200


def test_close_rejects_past_follow_up_and_cancelled_encounter(api):
    _, ev = _event(api)
    url = f"/api/emergency-events/{ev['id']}/close"
    r = api.post("doctor1", f"/api/encounters/{ev['encounter_id']}/transition", {"to": "cancelled", "reason": "Nhập nhầm"})
    assert r.status_code == 200, r.text
    past = str(date.today() - timedelta(days=30))
    assert api.post("doctor1", url, {"note": "Ổn định", "follow_up_date": past}).status_code == 422
    r = api.post("doctor1", url, {"note": "Ổn định"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INCOMPLETE_RECORD"


def test_emergency_write_blocked_after_transfer(api):
    p, s = api.managed()
    ev = api.post("nurse1", "/api/emergency-events", {"person_id": p["id"], "description": "Đau ngực"}).json()
    transfer_to_f2(api, s, receive=True)
    assert api.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": "Thở oxy"}).status_code == 403


def test_view_emergency_event_is_audited(api):
    _, ev = _event(api)
    assert api.get("nurse1", f"/api/emergency-events/{ev['id']}").status_code == 200
    assert any(e["object_id"] == ev["id"] for e in audit_actions(api, "view_emergency_event"))
