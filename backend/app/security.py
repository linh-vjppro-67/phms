import base64
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone

import jwt

from . import config


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, config.PBKDF2_ITER)
    return f"pbkdf2${config.PBKDF2_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def password_policy_error(pw: str) -> str | None:
    if len(pw) < 10:
        return "Mật khẩu tối thiểu 10 ký tự"
    if not (re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw) and re.search(r"\d", pw)):
        return "Mật khẩu cần chữ hoa, chữ thường và chữ số"
    return None


def make_token(user, scope: str | None = None, ttl_min: int | None = None) -> str:
    """scope=None: phiên đầy đủ. scope='mfa_enroll'/'pwd_change': phiên hạn chế chỉ dùng cho thao tác bắt buộc sau đăng nhập."""
    now = datetime.now(timezone.utc)
    claims = {"sub": user.id, "ver": user.token_version, "iat": now,
              "exp": now + timedelta(minutes=ttl_min or config.TOKEN_TTL_MIN)}
    if scope:
        claims["scope"] = scope
    return jwt.encode(claims, config.SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------- TOTP (RFC 6238, SHA-1, 6 chữ số, bước 30 s)
def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("mfa|" + config.SECRET_KEY).encode()).digest()))


def encrypt_secret(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt_secret(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode()


def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(int.from_bytes(h[o:o + 4], 'big') & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_now(secret: str, at: float | None = None) -> str:
    import time
    return _hotp(secret, int((at if at is not None else time.time()) // 30))


def totp_verify(secret: str, code: str, last_step: int | None = None, at: float | None = None) -> int | None:
    """Trả về bước thời gian hợp lệ (để lưu chống dùng lại), hoặc None. Cho lệch ±1 bước (30 s)."""
    import time
    code = (code or "").strip().replace(" ", "")
    if not (len(code) == 6 and code.isdigit()):
        return None
    step = int((at if at is not None else time.time()) // 30)
    for s in (step - 1, step, step + 1):
        if hmac.compare_digest(_hotp(secret, s), code) and (last_step is None or s > last_step):
            return s
    return None


def totp_uri(secret: str, username: str) -> str:
    from urllib.parse import quote
    return f"otpauth://totp/{quote(config.MFA_ISSUER)}:{quote(username)}?secret={secret}&issuer={quote(config.MFA_ISSUER)}&digits=6&period=30"


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
