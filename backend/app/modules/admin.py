"""M11: người dùng, đăng nhập, phân quyền, danh mục, nhật ký kiểm toán."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit, verify_chain
from ..db import get_db
from ..deps import current_user, require
from ..notify import emit
from ..models import AuditEvent, CatalogItem, Facility, User
from ..permissions import ROLES, perms_of
from ..security import (decrypt_secret, encrypt_secret, hash_password, make_token, new_totp_secret, password_policy_error, totp_uri,
                        totp_verify, verify_password)
from ..utils import fail, to_dict, utcnow

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str
    otp: str | None = None


_HIDDEN = ("password_hash", "mfa_secret", "mfa_pending_secret", "mfa_last_step")


def _user_out(u: User) -> dict:
    d = to_dict(u, exclude=_HIDDEN)
    d["permissions"] = sorted(perms_of(u))
    d["mfa_enabled"] = bool(u.mfa_enabled)
    d["mfa_required"] = u.role in config.MFA_REQUIRED_ROLES
    return d


def session_for(u: User) -> dict:
    """Quyết định phiên: đầy đủ, hay hạn chế (bắt đổi mật khẩu / đăng ký MFA trước khi dùng hệ thống)."""
    if u.must_change_password:
        return {"access_token": make_token(u, "pwd_change", 15), "requires": "password_change", "user": _user_out(u)}
    if u.role in config.MFA_REQUIRED_ROLES and not u.mfa_enabled:
        return {"access_token": make_token(u, "mfa_enroll", 15), "requires": "mfa_enroll", "user": _user_out(u)}
    return {"access_token": make_token(u), "token_type": "bearer", "requires": None, "user": _user_out(u)}


def _fail_login(db, u, request, why: str):
    if u:
        u.failed_attempts += 1
        if u.failed_attempts >= config.MAX_FAILED_LOGINS:
            u.locked_until = utcnow() + timedelta(minutes=config.LOCKOUT_MINUTES)
            u.failed_attempts = 0
            emit(db, kind="security.lockout", category="security", severity="warning", facility_id=None, include_global=True, perms=("audit.read",),
                 title="Tài khoản bị khóa do đăng nhập sai nhiều lần", plain=f"Tài khoản {u.username} bị khóa {config.LOCKOUT_MINUTES} phút sau {config.MAX_FAILED_LOGINS} lần sai.",
                 link_page="admin", dedupe=f"lock:{u.id}:{u.locked_until.isoformat()}")
    audit(db, u, "login_failed", result="denied", reason=why[:64], request=request, commit=True)


@router.post("/auth/login", tags=["auth"])
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    u = db.scalars(select(User).where(User.username == body.username)).first()
    now = utcnow()
    if u and u.locked_until and u.locked_until > now:
        audit(db, u, "login_locked", result="denied", request=request, commit=True)
        fail(423, "ACCOUNT_LOCKED", "Tài khoản tạm khóa do đăng nhập sai nhiều lần")
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        _fail_login(db, u, request, body.username)
        fail(401, "BAD_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu")
    if config.PASSWORD_LOGIN_DISABLED and u.role != "sysadmin":
        audit(db, u, "login_denied_sso_only", result="denied", request=request, commit=True)
        fail(403, "SSO_ONLY", "Hệ thống yêu cầu đăng nhập một lần (SSO)")
    if u.mfa_enabled:
        if not body.otp:
            fail(401, "MFA_REQUIRED", "Nhập mã xác thực 6 số từ ứng dụng xác thực")
        step = totp_verify(decrypt_secret(u.mfa_secret), body.otp, u.mfa_last_step)
        if step is None:
            _fail_login(db, u, request, "mfa:" + body.username)
            fail(401, "BAD_OTP", "Mã xác thực không đúng hoặc đã dùng")
        u.mfa_last_step = step
    u.failed_attempts = 0
    u.locked_until = None
    audit(db, u, "login", request=request)
    db.commit()
    return session_for(u)


@router.get("/auth/me", tags=["auth"])
def me(user: User = Depends(current_user)):
    return _user_out(user)


class PwdIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/auth/change-password", tags=["auth"])
def change_password(body: PwdIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        audit(db, user, "password_change_failed", result="denied", request=request, commit=True)
        fail(401, "BAD_CREDENTIALS", "Mật khẩu cũ không đúng")
    err = password_policy_error(body.new_password)
    if err:
        fail(422, "WEAK_PASSWORD", err)
    if body.new_password == body.old_password:
        fail(422, "SAME_PASSWORD", "Mật khẩu mới phải khác mật khẩu hiện tại")
    if body.new_password.lower() == user.username.lower():
        fail(422, "WEAK_PASSWORD", "Mật khẩu không được trùng tên đăng nhập")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # thu hồi mọi phiên cũ
    user.must_change_password = False
    user.password_changed_at = utcnow()
    audit(db, user, "password_changed", "User", user.id, request=request)
    db.commit()
    s = session_for(user)       # vai trò bắt buộc MFA mà chưa đăng ký -> tiếp tục bước đăng ký
    return {"access_token": s["access_token"], "requires": s["requires"], "user": s["user"]}


# ---- quản lý người dùng (sysadmin)
class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str
    full_name: str
    role: str
    facility_id: str | None = None


@router.post("/users", status_code=201, tags=["users"])
def create_user(body: UserIn, request: Request, actor: User = Depends(require("user.manage")),
                db: Session = Depends(get_db)):
    if body.role not in ROLES:
        fail(422, "BAD_ROLE", f"Vai trò không hợp lệ: {sorted(ROLES)}")
    if body.role != "sysadmin" and not (body.facility_id and db.get(Facility, body.facility_id)):
        fail(422, "FACILITY_REQUIRED", "Người dùng nghiệp vụ phải thuộc một cơ sở hợp lệ")
    err = password_policy_error(body.password)
    if err:
        fail(422, "WEAK_PASSWORD", err)
    if db.scalars(select(User).where(User.username == body.username)).first():
        fail(409, "USERNAME_TAKEN", "Tên đăng nhập đã tồn tại")
    u = User(username=body.username, password_hash=hash_password(body.password), full_name=body.full_name,
             role=body.role, facility_id=body.facility_id, must_change_password=True)   # mật khẩu do quản trị cấp -> bắt đổi lần đầu
    db.add(u)
    audit(db, actor, "user_created", "User", u.id, reason=f"{u.username} (vai trò {body.role})", request=request)
    db.commit()
    return _user_out(u)


@router.get("/users", tags=["users"])
def list_users(_: User = Depends(require("user.manage")), db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.username))]


class UserPatch(BaseModel):
    role: str | None = None
    facility_id: str | None = None
    active: bool | None = None


@router.patch("/users/{user_id}", tags=["users"])
def patch_user(user_id: str, body: UserPatch, request: Request, actor: User = Depends(require("user.manage")),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        fail(404, "NOT_FOUND", "Không tìm thấy người dùng")
    demoting = (body.role is not None and body.role != u.role) or body.active is False
    if u.id == actor.id and demoting:
        fail(409, "SELF_CHANGE", "Không tự đổi vai trò hoặc tự khóa tài khoản của chính mình – nhờ một quản trị viên khác")
    if u.role == "sysadmin" and u.active and (body.active is False or (body.role is not None and body.role != "sysadmin")):
        others = db.scalar(select(func.count()).select_from(User).where(User.role == "sysadmin", User.active.is_(True), User.id != u.id))
        if not others:
            fail(409, "LAST_ADMIN", "Đây là quản trị viên hoạt động cuối cùng – không thể hạ quyền hoặc khóa")
    if body.role is not None:
        if body.role not in ROLES:
            fail(422, "BAD_ROLE", "Vai trò không hợp lệ")
        u.role = body.role
    if body.facility_id is not None:
        u.facility_id = body.facility_id
    if body.active is not None:
        u.active = body.active
    u.token_version += 1  # đổi quyền / khóa -> thu hồi phiên
    audit(db, actor, "user_updated", "User", u.id, reason=f"{u.username}: {body.model_dump(exclude_none=True)}", request=request)
    db.commit()
    return _user_out(u)


class ResetPwdIn(BaseModel):
    new_password: str | None = None      # bỏ trống -> hệ thống sinh mật khẩu tạm ngẫu nhiên


@router.post("/users/{user_id}/reset-password", tags=["users"])
def reset_password(user_id: str, body: ResetPwdIn, request: Request, actor: User = Depends(require("user.manage")),
                   db: Session = Depends(get_db)):
    """Quản trị đặt lại mật khẩu: người dùng bị buộc đổi ở lần đăng nhập kế tiếp; mọi phiên cũ bị thu hồi; mật khẩu tạm chỉ hiện một lần."""
    u = db.get(User, user_id)
    if not u:
        fail(404, "NOT_FOUND", "Không tìm thấy người dùng")
    if u.id == actor.id:
        fail(409, "SELF_RESET", "Tự đổi mật khẩu bằng chức năng 'Đổi mật khẩu', không dùng đặt lại")
    pw = body.new_password
    if pw:
        err = password_policy_error(pw)
        if err:
            fail(422, "WEAK_PASSWORD", err)
    else:
        pw = _temp_password()
    u.password_hash = hash_password(pw)
    u.must_change_password = True
    u.token_version += 1
    u.failed_attempts, u.locked_until = 0, None
    audit(db, actor, "password_reset", "User", u.id, reason=u.username, request=request)
    db.commit()
    return {"username": u.username, "temporary_password": pw, "must_change_password": True}


def _temp_password() -> str:
    import secrets
    import string
    while True:
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        if not password_policy_error(pw):
            return pw


@router.post("/users/{user_id}/reset-mfa", tags=["users"])
def reset_mfa(user_id: str, request: Request, actor: User = Depends(require("user.manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        fail(404, "NOT_FOUND", "Không tìm thấy người dùng")
    u.mfa_enabled, u.mfa_secret, u.mfa_pending_secret, u.mfa_last_step = False, None, None, None
    u.token_version += 1
    audit(db, actor, "mfa_reset", "User", u.id, reason=u.username, request=request)
    db.commit()
    return _user_out(u)


# ---- MFA tự phục vụ (TOTP)
@router.post("/auth/mfa/setup", tags=["auth"])
def mfa_setup(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.mfa_enabled:
        fail(409, "MFA_ALREADY_ENABLED", "MFA đã bật; tắt trước khi đăng ký lại")
    secret = new_totp_secret()
    user.mfa_pending_secret = encrypt_secret(secret)
    audit(db, user, "mfa_setup_started", "User", user.id, request=request)
    db.commit()
    return {"secret": secret, "otpauth_uri": totp_uri(secret, user.username)}


class OtpIn(BaseModel):
    code: str


@router.post("/auth/mfa/enable", tags=["auth"])
def mfa_enable(body: OtpIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.mfa_pending_secret:
        fail(409, "MFA_NOT_STARTED", "Chưa bắt đầu đăng ký MFA")
    secret = decrypt_secret(user.mfa_pending_secret)
    step = totp_verify(secret, body.code)
    if step is None:
        audit(db, user, "mfa_enable_failed", result="denied", request=request, commit=True)
        fail(422, "BAD_OTP", "Mã xác thực không đúng")
    user.mfa_secret, user.mfa_pending_secret, user.mfa_enabled, user.mfa_last_step = user.mfa_pending_secret, None, True, step
    user.token_version += 1
    audit(db, user, "mfa_enabled", "User", user.id, request=request)
    db.commit()
    s = session_for(user)
    return {"access_token": s["access_token"], "requires": s["requires"], "user": s["user"]}


class MfaOffIn(BaseModel):
    password: str
    code: str


@router.post("/auth/mfa/disable", tags=["auth"])
def mfa_disable(body: MfaOffIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role in config.MFA_REQUIRED_ROLES:
        fail(403, "MFA_MANDATORY", "Vai trò của bạn bắt buộc dùng MFA")
    if not user.mfa_enabled:
        fail(409, "MFA_NOT_ENABLED", "MFA chưa bật")
    if not verify_password(body.password, user.password_hash) or totp_verify(decrypt_secret(user.mfa_secret), body.code, user.mfa_last_step) is None:
        audit(db, user, "mfa_disable_failed", result="denied", request=request, commit=True)
        fail(401, "BAD_CREDENTIALS", "Mật khẩu hoặc mã xác thực không đúng")
    user.mfa_enabled, user.mfa_secret, user.mfa_last_step = False, None, None
    user.token_version += 1
    audit(db, user, "mfa_disabled", "User", user.id, request=request)
    db.commit()
    return {"access_token": make_token(user), "user": _user_out(user)}


@router.get("/facilities", tags=["users"])
def facilities(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [to_dict(f) for f in db.scalars(select(Facility))]


# ---- danh mục có phiên bản
class CatalogIn(BaseModel):
    catalog: str
    code: str
    name: str
    extra: dict | None = None


@router.get("/catalogs/{catalog}", tags=["catalog"])
def list_catalog(catalog: str, q: str | None = None, _: User = Depends(require("catalog.read")),
                 db: Session = Depends(get_db)):
    stmt = select(CatalogItem).where(CatalogItem.catalog == catalog, CatalogItem.active.is_(True))
    if q:
        stmt = stmt.where(CatalogItem.name.ilike(f"%{q}%") | CatalogItem.code.ilike(f"%{q}%"))
    latest: dict[str, CatalogItem] = {}
    for it in db.scalars(stmt.order_by(CatalogItem.version)):
        latest[it.code] = it  # lấy phiên bản mới nhất còn hiệu lực
    return [to_dict(i) for i in latest.values()]


@router.post("/catalogs", status_code=201, tags=["catalog"])
def upsert_catalog(body: CatalogIn, request: Request, actor: User = Depends(require("catalog.write")),
                   db: Session = Depends(get_db)):
    cur = db.scalars(select(CatalogItem).where(CatalogItem.catalog == body.catalog, CatalogItem.code == body.code)
                     .order_by(CatalogItem.version.desc())).first()
    item = CatalogItem(catalog=body.catalog, code=body.code, name=body.name, extra=body.extra,
                       version=(cur.version + 1) if cur else 1)
    if cur:
        cur.active = False  # giữ bản cũ để truy vết
    db.add(item)
    audit(db, actor, "catalog_changed", "CatalogItem", item.id, reason=f"{body.catalog}:{body.code} v{item.version}",
          request=request)
    db.commit()
    return to_dict(item)


# ---- audit
@router.get("/audit", tags=["audit"])
def list_audit(person_id: str | None = None, actor: str | None = None, action: str | None = None,
               limit: int = 100, user: User = Depends(require("audit.read")), db: Session = Depends(get_db)):
    q = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(max(1, min(limit, 500)))
    if person_id:
        q = q.where(AuditEvent.person_id == person_id)
    if actor:
        q = q.where(AuditEvent.actor_name == actor)
    if action:
        q = q.where(AuditEvent.action == action)
    return [to_dict(e) for e in db.scalars(q)]


@router.get("/audit/verify", tags=["audit"])
def audit_verify(_: User = Depends(require("audit.read")), db: Session = Depends(get_db)):
    return verify_chain(db)
