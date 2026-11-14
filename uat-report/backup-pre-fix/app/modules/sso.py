"""Đăng nhập một lần (SSO) theo OpenID Connect – luồng authorization code + PKCE.

- Chỉ bật khi đặt đủ PHMS_OIDC_ISSUER / CLIENT_ID / CLIENT_SECRET / REDIRECT_URI.
- KHÔNG tự tạo tài khoản: danh tính từ IdP phải khớp một tài khoản PHMS đang hoạt động (claim PHMS_OIDC_USER_CLAIM ~ username).
  Vai trò, cơ sở, quyền vẫn do PHMS quản lý (RBAC/ABAC không đổi). MFA do IdP đảm nhiệm với người dùng SSO.
- id_token được kiểm chữ ký (JWKS của IdP), issuer, audience, hạn dùng và nonce.
"""
import base64
import hashlib
import json
import os
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..db import get_db
from ..models import User
from ..security import make_token
from ..utils import fail

router = APIRouter()
COOKIE = "phms_sso"
_disc_cache: dict = {}


def _discovery() -> dict:
    c = _disc_cache.get("d")
    if c and c[0] > time.time():
        return c[1]
    r = httpx.get(f"{config.OIDC_ISSUER}/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    d = r.json()
    _disc_cache["d"] = (time.time() + 3600, d)
    return d


def _exchange_code(token_endpoint: str, code: str, verifier: str) -> dict:
    r = httpx.post(token_endpoint, timeout=10, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": config.OIDC_REDIRECT_URI,
        "client_id": config.OIDC_CLIENT_ID, "client_secret": config.OIDC_CLIENT_SECRET, "code_verifier": verifier})
    r.raise_for_status()
    return r.json()


def _signing_key(id_token: str, jwks_uri: str):
    return jwt.PyJWKClient(jwks_uri, timeout=10).get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token: str, jwks_uri: str, nonce: str) -> dict:
    claims = jwt.decode(id_token, _signing_key(id_token, jwks_uri), algorithms=["RS256", "ES256"],
                        audience=config.OIDC_CLIENT_ID, issuer=config.OIDC_ISSUER,
                        options={"require": ["exp", "iss", "aud"]})
    if claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("nonce không khớp")
    return claims


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _fail_redirect(code: str):
    return RedirectResponse(f"/#/login?sso_error={code}", status_code=302)


@router.get("/auth/sso/config", tags=["auth"])
def sso_config():
    return {"enabled": config.OIDC_ENABLED, "password_login_disabled": config.PASSWORD_LOGIN_DISABLED}


@router.get("/auth/sso/login", tags=["auth"], include_in_schema=False)
def sso_login():
    if not config.OIDC_ENABLED:
        fail(404, "SSO_DISABLED", "SSO chưa được bật")
    state, nonce, verifier = _b64(os.urandom(16)), _b64(os.urandom(16)), _b64(os.urandom(32))
    q = urlencode({"response_type": "code", "client_id": config.OIDC_CLIENT_ID, "redirect_uri": config.OIDC_REDIRECT_URI,
                   "scope": "openid profile email", "state": state, "nonce": nonce,
                   "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"})
    resp = RedirectResponse(f"{_discovery()['authorization_endpoint']}?{q}", status_code=302)
    sealed = jwt.encode({"s": state, "n": nonce, "v": verifier, "exp": int(time.time()) + 600}, config.SECRET_KEY, algorithm="HS256")
    resp.set_cookie(COOKIE, sealed, max_age=600, httponly=True, samesite="lax", secure=config.IS_PROD, path="/api/auth/sso")
    return resp


@router.get("/auth/sso/callback", tags=["auth"], include_in_schema=False)
def sso_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                 db: Session = Depends(get_db)):
    if not config.OIDC_ENABLED:
        fail(404, "SSO_DISABLED", "SSO chưa được bật")
    if error or not code or not state:
        return _fail_redirect("idp_error")
    try:
        sealed = jwt.decode(request.cookies.get(COOKIE, ""), config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return _fail_redirect("state_expired")
    if sealed["s"] != state:
        audit(db, None, "sso_failed", result="denied", reason="state không khớp", request=request, commit=True)
        return _fail_redirect("bad_state")
    try:
        disc = _discovery()
        tok = _exchange_code(disc["token_endpoint"], code, sealed["v"])
        claims = verify_id_token(tok["id_token"], disc["jwks_uri"], sealed["n"])
    except Exception as e:  # noqa: BLE001 – mọi lỗi IdP/chữ ký đều quy về từ chối, ghi nhật ký
        audit(db, None, "sso_failed", result="denied", reason=f"{type(e).__name__}"[:60], request=request, commit=True)
        return _fail_redirect("idp_verify")
    ident = str(claims.get(config.OIDC_USER_CLAIM) or "").strip().lower()
    u = db.scalars(select(User).where(func.lower(User.username) == ident)).first() if ident else None
    if not u or not u.active:
        audit(db, None, "sso_failed", result="denied", reason=f"không có tài khoản PHMS cho '{ident[:40]}'", request=request, commit=True)
        return _fail_redirect("no_account")
    audit(db, u, "login_sso", request=request)
    u.failed_attempts, u.locked_until = 0, None
    if config.PASSWORD_LOGIN_DISABLED:
        u.must_change_password = False      # người dùng SSO-only không dùng mật khẩu PHMS nên không bắt đổi
    db.commit()
    resp = RedirectResponse("/#/sso?token=" + make_token(u), status_code=302)
    resp.delete_cookie(COOKIE, path="/api/auth/sso")
    return resp
