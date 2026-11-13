"""Tính năng mức production: đổi/đặt lại mật khẩu, MFA, SSO, header bảo mật, idempotency, chặn trùng + gộp hồ sơ có duyệt,
ưu tiên yêu cầu khám, tài liệu bàn giao chuyển viện."""
import base64
import time
import uuid

import pytest

from app import config, security
from app.seed import DEFAULT_PASSWORD

STRONG = "Moi@2026Strong1"
PDF = b"%PDF-1.4\n%production test document\n"


def login(api, user, password=DEFAULT_PASSWORD, **extra):
    return api.c.post("/api/auth/login", json={"username": user, "password": password, **extra})


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


# ------------------------------------------------------------------ mật khẩu
def test_seeded_accounts_are_not_forced_to_change_password(api):
    for u in ("admin", "doctor1", "officer2"):
        r = login(api, u).json()
        assert r["requires"] is None and r["user"]["must_change_password"] is False


def test_admin_created_user_must_change_password_before_anything_else(api):
    r = api.post("admin", "/api/users", {"username": "newdoc", "password": "Tam@2026Pass1", "full_name": "BS Mới", "role": "doctor", "facility_id": api.f1})
    assert r.status_code == 201 and r.json()["must_change_password"] is True
    s = login(api, "newdoc", "Tam@2026Pass1").json()
    assert s["requires"] == "password_change"
    h = bearer(s["access_token"])
    r = api.c.get("/api/persons", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert api.c.get("/api/auth/me", headers=h).status_code == 200
    r = api.c.post("/api/auth/change-password", headers=h, json={"old_password": "Tam@2026Pass1", "new_password": STRONG})
    assert r.status_code == 200 and r.json()["requires"] is None
    assert api.c.get("/api/persons", headers=bearer(r.json()["access_token"])).status_code == 200
    assert api.c.get("/api/persons", headers=h).status_code == 401           # phiên hạn chế cũ bị thu hồi


def test_change_password_rules(api):
    h = api.h("nurse2")
    post = lambda old, new: api.c.post("/api/auth/change-password", headers=h, json={"old_password": old, "new_password": new})  # noqa: E731
    assert post("sai-mat-khau", STRONG).status_code == 401
    assert post(DEFAULT_PASSWORD, "yeu").status_code == 422
    assert post(DEFAULT_PASSWORD, DEFAULT_PASSWORD).json()["error"]["code"] == "SAME_PASSWORD"
    assert post(DEFAULT_PASSWORD, "Nurse2" + "Aa1xyz").status_code == 200


def test_admin_reset_password_revokes_sessions_and_forces_change(api):
    uid = next(u["id"] for u in api.get("admin", "/api/users").json() if u["username"] == "pharm1")
    old = api.h("pharm1")
    r = api.post("admin", f"/api/users/{uid}/reset-password", {})
    assert r.status_code == 200
    tmp = r.json()["temporary_password"]
    assert len(tmp) >= 10 and config  # đạt chính sách
    assert api.c.get("/api/dispense-queue", headers=old).status_code == 401
    assert login(api, "pharm1", DEFAULT_PASSWORD).status_code == 401
    assert login(api, "pharm1", tmp).json()["requires"] == "password_change"
    assert api.post("doctor1", "/api/users/x/reset-password", {}).status_code == 403         # chỉ quản trị
    me = next(u["id"] for u in api.get("admin", "/api/users").json() if u["username"] == "admin")
    assert api.post("admin", f"/api/users/{me}/reset-password", {}).status_code == 409       # không tự đặt lại bằng chức năng này
    log = api.get("admin", "/api/audit?limit=50").json()
    assert any("password_reset" in str(x) for x in (log if isinstance(log, list) else log.get("items", [])))


def test_user_response_never_leaks_secrets(api):
    users = api.get("admin", "/api/users").json()
    flat = str(users).lower()
    assert "password_hash" not in flat and "mfa_secret" not in flat and "mfa_pending" not in flat


# ------------------------------------------------------------------ MFA
def enroll(api, user):
    h = api.h(user)
    sec = api.c.post("/api/auth/mfa/setup", headers=h).json()["secret"]
    r = api.c.post("/api/auth/mfa/enable", headers=h, json={"code": security.totp_now(sec)})
    assert r.status_code == 200, r.text
    return sec


def test_totp_matches_rfc6238_vectors():
    secret = base64.b32encode(b"12345678901234567890").decode()      # vector chuẩn RFC 6238 (SHA-1)
    assert security.totp_now(secret, 59) == "287082"
    assert security.totp_now(secret, 1111111109) == "081804"
    assert security.totp_now(secret, 20000000000) == "353130"


def test_mfa_enroll_login_replay_and_disable(api, monkeypatch):
    sec = enroll(api, "doctor2")                                              # bước hiện tại đã dùng để bật MFA
    base = time.time()
    r = login(api, "doctor2")
    assert r.status_code == 401 and r.json()["error"]["code"] == "MFA_REQUIRED"
    assert login(api, "doctor2", otp="000000").json()["error"]["code"] == "BAD_OTP"
    assert login(api, "doctor2", otp=security.totp_now(sec, base)).status_code == 401     # mã dùng để bật không dùng lại để đăng nhập
    monkeypatch.setattr(time, "time", lambda: base + 30)                      # sang bước kế tiếp
    code = security.totp_now(sec, base + 30)
    ok = login(api, "doctor2", otp=code)
    assert ok.status_code == 200 and ok.json()["requires"] is None
    assert login(api, "doctor2", otp=code).status_code == 401                 # mã đã dùng không dùng lại được (replay)
    h = bearer(ok.json()["access_token"])
    assert api.c.post("/api/auth/mfa/setup", headers=h).status_code == 409    # đã bật
    monkeypatch.setattr(time, "time", lambda: base + 60)
    off = api.c.post("/api/auth/mfa/disable", headers=h, json={"password": DEFAULT_PASSWORD, "code": security.totp_now(sec, base + 60)})
    assert off.status_code == 200
    assert login(api, "doctor2").json()["requires"] is None                   # tắt xong đăng nhập không cần OTP


def test_mfa_secret_is_encrypted_at_rest(api):
    sec = enroll(api, "manager2")
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as s:
        u = s.query(User).filter_by(username="manager2").one()
        assert sec not in u.mfa_secret and u.mfa_enabled is True


def test_mfa_wrong_codes_count_toward_lockout(api):
    enroll(api, "pharm2")
    for _ in range(config.MAX_FAILED_LOGINS):
        login(api, "pharm2", otp="111111")
    assert login(api, "pharm2", otp="111111").status_code == 423


def test_mfa_mandatory_role_must_enroll_before_use(api, monkeypatch):
    monkeypatch.setattr(config, "MFA_REQUIRED_ROLES", {"approver"})
    s = login(api, "approver2").json()
    assert s["requires"] == "mfa_enroll"
    h = bearer(s["access_token"])
    r = api.c.get("/api/referrals", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "MFA_ENROLL_REQUIRED"
    sec = api.c.post("/api/auth/mfa/setup", headers=h).json()["secret"]
    full = api.c.post("/api/auth/mfa/enable", headers=h, json={"code": security.totp_now(sec)}).json()
    assert full["requires"] is None and api.c.get("/api/referrals", headers=bearer(full["access_token"])).status_code == 200
    assert api.c.post("/api/auth/mfa/disable", headers=bearer(full["access_token"]),
                      json={"password": DEFAULT_PASSWORD, "code": "000000"}).status_code == 403   # vai trò bắt buộc không tự tắt được
    assert login(api, "doctor1").json()["requires"] is None                   # vai trò khác không bị ảnh hưởng


def test_admin_can_reset_mfa(api):
    enroll(api, "nurse1")
    uid = next(u["id"] for u in api.get("admin", "/api/users").json() if u["username"] == "nurse1")
    assert api.post("admin", f"/api/users/{uid}/reset-mfa").status_code == 200
    assert login(api, "nurse1").json()["requires"] is None


# ------------------------------------------------------------------ SSO (IdP giả lập)
def test_sso_flow_with_mock_idp(api, monkeypatch):
    import jwt as pyjwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.modules import sso
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(config, "OIDC_ISSUER", "https://idp.test")
    monkeypatch.setattr(config, "OIDC_CLIENT_ID", "phms")
    monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setattr(config, "OIDC_REDIRECT_URI", "https://phms.test/api/auth/sso/callback")
    monkeypatch.setattr(config, "OIDC_ENABLED", True)
    monkeypatch.setattr(sso, "_discovery", lambda: {"authorization_endpoint": "https://idp.test/auth", "token_endpoint": "https://idp.test/token", "jwks_uri": "https://idp.test/jwks"})
    monkeypatch.setattr(sso, "_signing_key", lambda tok, uri: key.public_key())
    c = api.c
    assert c.get("/api/auth/sso/config").json()["enabled"] is True
    r = c.get("/api/auth/sso/login", follow_redirects=False)
    assert r.status_code == 302 and "code_challenge_method=S256" in r.headers["location"]
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(r.headers["location"]).query)
    state, nonce = q["state"][0], q["nonce"][0]

    def idtoken(**over):
        claims = {"iss": "https://idp.test", "aud": "phms", "exp": int(time.time()) + 300, "nonce": nonce, "preferred_username": "doctor1", **over}
        return pyjwt.encode(claims, key, algorithm="RS256")

    monkeypatch.setattr(sso, "_exchange_code", lambda ep, code, ver: {"id_token": idtoken()})
    ok = c.get(f"/api/auth/sso/callback?code=abc&state={state}", follow_redirects=False)
    assert ok.status_code == 302 and ok.headers["location"].startswith("/#/sso?token=")
    tok = ok.headers["location"].split("token=")[1]
    me = c.get("/api/auth/me", headers=bearer(tok)).json()
    assert me["username"] == "doctor1"
    # sai state / sai nonce / sai chữ ký / tài khoản không tồn tại -> từ chối
    c.cookies.clear()
    c.get("/api/auth/sso/login", follow_redirects=False)
    assert "bad_state" in c.get("/api/auth/sso/callback?code=abc&state=wrong", follow_redirects=False).headers["location"]
    for bad in (idtoken(nonce="khac"), idtoken(preferred_username="ghost"), idtoken(aud="khac"),
                pyjwt.encode({"iss": "https://idp.test", "aud": "phms", "exp": int(time.time()) + 300, "nonce": nonce, "preferred_username": "doctor1"},
                             rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256")):
        c.cookies.clear()
        st = parse_qs(urlparse(c.get("/api/auth/sso/login", follow_redirects=False).headers["location"]).query)
        monkeypatch.setattr(sso, "_exchange_code", lambda ep, code, ver, b=bad: {"id_token": b})
        loc = c.get(f"/api/auth/sso/callback?code=abc&state={st['state'][0]}", follow_redirects=False).headers["location"]
        assert "sso_error" in loc and "token=" not in loc


def test_sso_disabled_by_default(api):
    assert api.c.get("/api/auth/sso/config").json()["enabled"] is False
    assert api.c.get("/api/auth/sso/login", follow_redirects=False).status_code == 404


def test_password_login_can_be_disabled_except_sysadmin(api, monkeypatch):
    monkeypatch.setattr(config, "PASSWORD_LOGIN_DISABLED", True)
    assert login(api, "doctor1").status_code == 403
    assert login(api, "admin").status_code == 200


# ------------------------------------------------------------------ header bảo mật / cấu hình production
def test_security_headers_and_hsts_behind_https(api):
    r = api.c.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers
    r = api.c.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert "max-age=31536000" in r.headers["strict-transport-security"]
    assert api.c.get("/docs").status_code == 200                      # dev: có tài liệu API


def test_production_refuses_default_secret(monkeypatch):
    from app import main
    monkeypatch.setattr(config, "IS_PROD", True)
    monkeypatch.setattr(config, "PBKDF2_ITER", 200_000)
    with pytest.raises(RuntimeError):
        main._check_production_config()
    monkeypatch.setattr(config, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(config, "DOC_ENC_KEY", "x" * 40)
    with pytest.raises(RuntimeError):                       # khóa tài liệu trùng khóa ký phiên -> từ chối
        main._check_production_config()
    monkeypatch.setattr(config, "DOC_ENC_KEY", "y" * 40)
    main._check_production_config()


# ------------------------------------------------------------------ idempotency
def test_idempotency_key_on_creation_endpoints(api):
    def twice(user, path, body, key, **kw):
        a = api.post(user, path, body, headers={"Idempotency-Key": key})
        b = api.post(user, path, body, headers={"Idempotency-Key": key})
        assert a.status_code == b.status_code == 201, (path, a.text, b.text)
        assert a.json()["id"] == b.json()["id"], path
        assert b.headers.get("Idempotent-Replay") == "true"
        return a.json()

    p = twice("officer1", "/api/persons", {"full_name": "Idem Một", "date_of_birth": "1990-01-01"}, "p1")
    s = twice("officer1", f"/api/persons/{p['id']}/stays", {}, "s1")
    e = api.encounter(p["id"])
    twice("nurse1", f"/api/encounters/{e['id']}/observations", {"type": "Mạch", "value": "80", "unit": "lần/phút"}, "o1")
    twice("doctor1", f"/api/encounters/{e['id']}/diagnoses", {"text": "Viêm họng", "kind": "preliminary"}, "d1")
    twice("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Công thức máu"}, "c1")
    twice("doctor1", f"/api/persons/{p['id']}/allergies", {"substance": "Phấn hoa", "severity": "mild"}, "a1")
    twice("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Hen phế quản"}, "pr1")
    assert len(api.get("doctor1", f"/api/encounters/{e['id']}").json()["observations"]) == 1
    assert len(api.get("officer1", f"/api/persons/{p['id']}/stays").json()) == 1 and s["id"]
    # cùng key nhưng nội dung khác -> từ chối
    r = api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": "Mạch", "value": "99", "unit": "lần/phút"}, headers={"Idempotency-Key": "o1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    # key khác -> bản ghi mới
    assert api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": "Mạch", "value": "81", "unit": "lần/phút"}, headers={"Idempotency-Key": "o2"}).status_code == 201


def test_idempotent_error_is_not_cached(api):
    p, _ = api.patient("IDM2", "Idem Hai")
    e = api.encounter(p["id"])
    bad = {"type": "Mạch", "value": "abc", "unit": "x"}
    assert api.post("nurse1", f"/api/encounters/{e['id']}/observations", bad, headers={"Idempotency-Key": "k"}).status_code == 422
    good = {"type": "Mạch", "value": "70", "unit": "lần/phút"}
    assert api.post("nurse1", f"/api/encounters/{e['id']}/observations", good, headers={"Idempotency-Key": "k2"}).status_code == 201


# ------------------------------------------------------------------ trùng hồ sơ + gộp có duyệt
def test_api_blocks_silent_duplicate_but_allows_explicit_distinct(api):
    body = {"full_name": "Trùng Tên", "date_of_birth": "1991-03-03"}
    assert api.post("officer1", "/api/persons", body).status_code == 201
    r = api.post("officer1", "/api/persons", body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_SUSPECTED" and len(r.json()["error"]["candidates"]) == 1
    r = api.post("officer1", "/api/persons", {**body, "full_name": "  trùng tên ", "confirm_distinct": True})
    assert r.status_code == 201 and r.json()["status"] == "pending_verification" and len(r.json()["duplicate_candidates"]) == 1


def merge_pair(api):
    keep, _ = api.patient("KEEP1", "Phạm Giữ Lại")
    ghost = api.post("officer1", "/api/persons", {"full_name": "Phạm Giữ Lại", "date_of_birth": "1985-05-05", "confirm_distinct": True}).json()
    return keep, ghost


def test_merge_requires_approval_and_moves_all_data(api):
    # hồ sơ nguồn là bản trùng ĐÃ có dữ liệu (đợt tiếp nhận, khám, dị ứng, tài liệu); hồ sơ giữ lại chưa có kỳ
    src, _ = api.patient("SRC1", "Trần Nguồn")
    e = api.encounter(src["id"])
    api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": "Mạch", "value": "75", "unit": "lần/phút"})
    api.post("doctor1", f"/api/persons/{src['id']}/allergies", {"substance": "Penicillin", "severity": "severe"})
    d = api.c.post("/api/documents", headers=api.h("nurse1"), data={"doc_type": "lab_result", "person_id": src["id"]}, files={"file": ("x.pdf", PDF, "application/pdf")}).json()
    tgt = api.post("officer1", "/api/persons", {"full_name": "Trần Nguồn", "date_of_birth": "1985-05-05", "confirm_distinct": True}).json()

    m = api.post("officer1", "/api/person-merges", {"source_id": src["id"], "target_id": tgt["id"], "reason": "Cùng họ tên, ngày sinh, nhập 2 lần"})
    assert m.status_code == 201 and m.json()["status"] == "pending"
    mid = m.json()["id"]
    # chưa duyệt thì chưa gộp
    assert api.get("officer1", f"/api/persons/{src['id']}").json()["status"] != "merged"
    # chỉ người có quyền duyệt; lý do từ chối bắt buộc
    assert api.post("officer1", f"/api/person-merges/{mid}/decision", {"approve": True}).status_code == 403
    assert api.post("approver1", f"/api/person-merges/{mid}/decision", {"approve": False}).status_code == 422
    r = api.post("approver1", f"/api/person-merges/{mid}/decision", {"approve": True, "note": "Đã đối chiếu"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["moved"]["encounter"] == 1

    # dữ liệu đã sang hồ sơ giữ lại, hồ sơ nguồn không bị xóa mà chỉ đánh dấu đã gộp
    hs = api.get("doctor1", f"/api/persons/{tgt['id']}/health-summary").json()
    assert hs["stays"] and any(a["substance"] == "Penicillin" for a in hs["clinical"]["allergies"])
    assert len(api.get("doctor1", f"/api/persons/{tgt['id']}/encounters").json()) == 1
    assert api.get("doctor1", f"/api/documents?person_id={tgt['id']}").json()[0]["id"] == d["id"]
    srcp = api.get("officer1", f"/api/persons/{src['id']}").json()
    assert srcp["status"] == "merged" and srcp["merged_into_id"] == tgt["id"]
    assert src["id"] not in [p["id"] for p in api.get("officer1", "/api/persons?q=Nguồn").json()]
    r = api.post("officer1", f"/api/persons/{src['id']}/stays", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PERSON_MERGED" and r.json()["error"]["merged_into_id"] == tgt["id"]
    assert api.post("approver1", f"/api/person-merges/{mid}/decision", {"approve": True}).status_code == 409   # không duyệt lại
    assert api.get("admin", "/api/audit/verify").json()["ok"] is True
    log = str(api.get("admin", "/api/audit?limit=100").json())
    assert "persons_merged" in log and "merge_requested" in log


def test_merge_four_eyes_reject_cancel_and_guards(api, monkeypatch):
    from app import permissions
    monkeypatch.setitem(permissions.ROLE_PERMS, "custody_officer", permissions.ROLE_PERMS["custody_officer"] | {"person.merge.approve"})
    keep, ghost = merge_pair(api)
    r = api.post("officer1", "/api/person-merges", {"source_id": ghost["id"], "target_id": keep["id"], "reason": "ngắn"})
    assert r.status_code == 422
    r = api.post("officer1", "/api/person-merges", {"source_id": keep["id"], "target_id": keep["id"], "reason": "Cùng một hồ sơ nhập nhầm"})
    assert r.status_code == 422
    m = api.post("officer1", "/api/person-merges", {"source_id": ghost["id"], "target_id": keep["id"], "reason": "Cùng họ tên và ngày sinh"}).json()
    assert api.post("officer1", "/api/person-merges", {"source_id": ghost["id"], "target_id": keep["id"], "reason": "Cùng họ tên và ngày sinh"}).status_code == 409
    r = api.post("officer1", f"/api/person-merges/{m['id']}/decision", {"approve": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FOUR_EYES"           # người lập không tự duyệt
    assert api.post("officer2", f"/api/person-merges/{m['id']}/cancel").status_code == 403
    rej = api.post("approver1", f"/api/person-merges/{m['id']}/decision", {"approve": False, "note": "Hai người khác nhau"})
    assert rej.json()["status"] == "rejected"
    assert api.get("officer1", f"/api/persons/{ghost['id']}").json()["status"] != "merged"
    m2 = api.post("officer1", "/api/person-merges", {"source_id": ghost["id"], "target_id": keep["id"], "reason": "Đề nghị lại sau khi có thêm căn cứ"}).json()
    assert api.post("officer1", f"/api/person-merges/{m2['id']}/cancel").json()["status"] == "cancelled"


def test_merge_requests_are_scoped_to_the_requesters_facility(api):
    a, _ = api.patient("SC1", "Phạm Vi Một")
    ghost = api.post("officer1", "/api/persons", {"full_name": "Phạm Vi Một", "date_of_birth": "1985-05-05", "confirm_distinct": True}).json()
    m = api.post("officer1", "/api/person-merges", {"source_id": ghost["id"], "target_id": a["id"], "reason": "Cùng họ tên, ngày sinh nhập hai lần"}).json()
    assert [x["id"] for x in api.get("approver1", "/api/person-merges").json()] == [m["id"]]
    assert api.get("approver2", "/api/person-merges").json() == []                        # cơ sở khác không thấy
    assert api.get("officer2", "/api/person-merges").json() == []
    r = api.post("approver2", f"/api/person-merges/{m['id']}/decision", {"approve": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FACILITY_SCOPE"          # cũng không duyệt được
    assert api.get("officer1", f"/api/persons/{ghost['id']}").json()["status"] != "merged"


def test_merge_blocked_when_both_have_active_stay_and_scope(api):
    a, _ = api.patient("A1", "Người Một")
    b, _ = api.patient("B1", "Người Hai")
    r = api.post("officer1", "/api/person-merges", {"source_id": a["id"], "target_id": b["id"], "reason": "Nghi ngờ cùng một người"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BOTH_ACTIVE"
    c = api.post("officer2", "/api/persons", {"full_name": "Ngoài Phạm Vi", "date_of_birth": "1970-01-01"}).json()
    d = api.post("officer2", "/api/persons", {"full_name": "Ngoài Phạm Vi 2", "date_of_birth": "1970-01-02"}).json()
    assert api.post("officer1", "/api/person-merges", {"source_id": c["id"], "target_id": d["id"], "reason": "Cơ sở khác lập đề nghị"}).status_code == 403
    assert api.post("nurse1", "/api/person-merges", {"source_id": a["id"], "target_id": b["id"], "reason": "Điều dưỡng không có quyền này"}).status_code == 403


# ------------------------------------------------------------------ ưu tiên yêu cầu khám
def test_encounter_priority_and_worklist_order(api):
    low, _ = api.patient("PR1", "Ưu Tiên Thấp")
    high, _ = api.patient("PR2", "Ưu Tiên Cao")
    mid, _ = api.patient("PR3", "Ưu Tiên Giữa")
    api.encounter(low["id"], start=False)
    api.encounter(high["id"], start=False, priority="emergent")
    api.encounter(mid["id"], start=False, priority="urgent")
    rows = api.get("doctor1", "/api/encounters?open_only=true").json()
    assert [r["priority"] for r in rows][:3] == ["emergent", "urgent", "routine"]
    assert api.post("doctor1", "/api/encounters", {"person_id": low["id"], "type": "ad_hoc", "priority": "whenever"}).status_code == 422
    ev = api.post("doctor1", "/api/emergency-events", {"person_id": low["id"], "description": "Ngất"}).json()
    assert api.get("doctor1", f"/api/encounters/{ev['encounter_id']}").json()["priority"] == "emergent"


# ------------------------------------------------------------------ tài liệu bàn giao chuyển viện
def test_referral_handover_documents_validated(api):
    p, _ = api.patient("RD1", "Chuyển Viện Tài Liệu")
    other, _ = api.patient("RD2", "Người Khác")
    e = api.encounter(p["id"])
    up = lambda pid, name="x.pdf": api.c.post("/api/documents", headers=api.h("nurse1"), data={"doc_type": "lab_result", "person_id": pid}, files={"file": (name, PDF, "application/pdf")}).json()  # noqa: E731
    d1, dx = up(p["id"]), up(other["id"])
    mk = lambda docs: api.post("doctor1", f"/api/encounters/{e['id']}/referrals", {"reason": "Nghi viêm ruột thừa cấp", "handover_docs": docs})  # noqa: E731
    assert mk([dx["id"]]).json()["error"]["code"] == "BAD_HANDOVER_DOC"                # tài liệu của người khác
    assert mk(["khong-ton-tai"]).status_code == 422
    r = mk([d1["id"], d1["id"]])
    assert r.status_code == 201 and r.json()["handover_docs"] == [d1["id"]]
    assert r.json()["handover_docs_detail"][0]["filename"] == "x.pdf"
    rid = r.json()["id"]
    d2 = api.c.post(f"/api/documents/{d1['id']}/replace", headers=api.h("nurse1"), files={"file": ("x2.pdf", PDF, "application/pdf")}).json()
    assert api.put("doctor1", f"/api/referrals/{rid}/handover-docs", {"handover_docs": [d1["id"]]}).json()["error"]["code"] == "DOC_NOT_VALID"   # bản cũ đã bị thay thế
    ok = api.put("doctor1", f"/api/referrals/{rid}/handover-docs", {"handover_docs": [d2["id"]]})
    assert ok.status_code == 200 and ok.json()["handover_docs"] == [d2["id"]]
    seen = api.get("approver1", f"/api/referrals/{rid}").json()                       # người điều phối: thấy có tài liệu, không thấy tên tệp
    assert len(seen["handover_docs_detail"]) == 1 and seen["handover_docs_detail"][0]["filename"] is None
    api.patch("doctor1", f"/api/referrals/{rid}/status", {"to": "pending"})
    api.patch("approver1", f"/api/referrals/{rid}/status", {"to": "coordinated", "destination": "BV Đa khoa tỉnh"})
    api.patch("doctor1", f"/api/referrals/{rid}/status", {"to": "in_external_treatment", "left_at": "2026-11-12T08:00:00"})
    assert api.put("doctor1", f"/api/referrals/{rid}/handover-docs", {"handover_docs": []}).status_code == 409   # đã chuyển đi: khóa
    assert uuid.UUID(rid)


# ------------------------------------------------------------------ sửa kế hoạch theo dõi (WF-05 bước 5)
def test_care_plan_edit_validates_and_reschedules_open_appointment(api):
    from datetime import date, timedelta
    p, _ = api.managed("CP1", "Kế Hoạch Theo Dõi")
    prob = api.post("doctor1", f"/api/persons/{p['id']}/problems", {"name": "Tăng huyết áp"}).json()
    plan = api.post("doctor1", f"/api/persons/{p['id']}/care-plans", {"problem_id": prob["id"], "goals": "Huyết áp < 140/90",
                    "measures": [{"name": "Mạch", "unit": "lần/phút"}], "review_interval_days": 14}).json()
    due = lambda: [a["due_date"] for a in api.get("doctor1", "/api/appointments?kind=care_plan").json() if a["care_plan_id"] == plan["id"]]  # noqa: E731
    assert due() == [str(date.today() + timedelta(days=14))]
    patch = lambda body: api.patch("doctor1", f"/api/care-plans/{plan['id']}", body)  # noqa: E731
    assert patch({}).status_code == 422
    assert patch({"goals": " "}).json()["error"]["code"] == "GOALS_REQUIRED"
    assert patch({"review_interval_days": 0}).status_code == 422
    assert patch({"responsible_user_id": api.get("admin", "/api/users").json()[0]["id"]}).json()["error"]["code"] == "BAD_ASSIGNEE"   # người phụ trách phải thuộc cơ sở
    assert api.patch("nurse1", f"/api/care-plans/{plan['id']}", {"goals": "Sửa trái quyền"}).status_code == 403
    ok = patch({"review_interval_days": 30, "goals": "Huyết áp < 130/80", "expected_version": plan["version"]})
    assert ok.status_code == 200 and ok.json()["goals"] == "Huyết áp < 130/80" and ok.json()["version"] == plan["version"] + 1
    assert due() == [str(date.today() + timedelta(days=30))]                        # lịch đang mở dời theo chu kỳ mới
    assert patch({"goals": "Lại sửa", "expected_version": plan["version"]}).status_code == 409   # xung đột phiên bản (người khác đã sửa)
    api.post("doctor1", f"/api/care-plans/{plan['id']}/end", {"note": "Ổn định, kết thúc"})
    assert patch({"goals": "Sau khi kết thúc"}).json()["error"]["code"] == "PLAN_ENDED"


# ------------------------------------------------------------------ gỡ dị ứng ghi nhầm (BR-02)
def test_retract_allergy_keeps_record_and_removes_warning(api):
    p, _ = api.patient("AL1", "Gỡ Dị Ứng")
    e = api.encounter(p["id"])
    a = api.post("nurse1", f"/api/persons/{p['id']}/allergies", {"substance": "thuốc trừ sâu", "severity": "Nhẹ"}).json()
    assert api.get("doctor1", f"/api/persons/{p['id']}/health-summary").json()["clinical"]["allergy_status"] == "recorded"
    assert api.post("nurse1", f"/api/allergies/{a['id']}/retract", {"reason": "ngắn"}).status_code == 422           # lý do bắt buộc
    assert api.post("doctor2", f"/api/allergies/{a['id']}/retract", {"reason": "Khác cơ sở"}).status_code == 403    # ngoài phạm vi cơ sở
    r = api.post("nurse1", f"/api/allergies/{a['id']}/retract", {"reason": "Nhập nhầm người bệnh khác"})
    assert r.status_code == 200 and r.json()["allergy_status"] == "unknown"                                          # không tự thành "không dị ứng"
    assert api.post("nurse1", f"/api/allergies/{a['id']}/retract", {"reason": "Gỡ lần hai"}).status_code == 409
    hs = api.get("doctor1", f"/api/persons/{p['id']}/health-summary").json()["clinical"]
    assert hs["allergies"] == []
    d = api.med_order(e["id"], drug_name="thuốc trừ sâu", drug_code="PARA500")                                      # hết cảnh báo dị ứng
    assert not any(w["type"] == "allergy" for w in d["warnings"])
    log = str(api.get("admin", "/api/audit?limit=50").json())
    assert "allergy_retracted" in log and "Nhập nhầm người bệnh khác" in log                                         # còn dấu vết
    assert api.get("admin", "/api/audit/verify").json()["ok"]
    # dị ứng ĐÃ XÁC NHẬN: điều dưỡng không gỡ được, bác sĩ gỡ được
    c = api.post("doctor1", f"/api/persons/{p['id']}/allergies", {"substance": "Penicillin", "confirmed": True}).json()
    assert api.post("nurse1", f"/api/allergies/{c['id']}/retract", {"reason": "Điều dưỡng thử gỡ"}).status_code == 403
    assert api.post("doctor1", f"/api/allergies/{c['id']}/retract", {"reason": "Bác sĩ đính chính sau khi xác minh"}).status_code == 200
