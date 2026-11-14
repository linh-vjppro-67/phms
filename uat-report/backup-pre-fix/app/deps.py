"""Xác thực + phân quyền (RBAC) + kiểm soát truy cập theo cơ sở (ABAC) + break-glass."""
from urllib.parse import unquote

from datetime import timedelta

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import audit
from .db import get_db
from .notify import emit
from .models import Alert, BreakGlassGrant, CustodyStay, Person, User
from .permissions import perms_of
from .security import decode_token
from .utils import fail, utcnow

bearer = HTTPBearer(auto_error=False)


# Phiên hạn chế (sau khi đăng nhập nhưng còn bước bắt buộc): chỉ gọi được các đường dẫn này
SCOPE_PATHS = {
    "pwd_change": ("/api/auth/me", "/api/auth/change-password"),
    "mfa_enroll": ("/api/auth/me", "/api/auth/mfa/setup", "/api/auth/mfa/enable"),
}
SCOPE_ERR = {"pwd_change": ("PASSWORD_CHANGE_REQUIRED", "Cần đổi mật khẩu trước khi sử dụng hệ thống"),
             "mfa_enroll": ("MFA_ENROLL_REQUIRED", "Vai trò của bạn bắt buộc bật xác thực 2 lớp (MFA)")}


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if not creds:
        fail(401, "UNAUTHENTICATED", "Chưa đăng nhập")
    data = decode_token(creds.credentials)
    user = db.get(User, data["sub"]) if data else None
    if not user or not user.active or user.token_version != data.get("ver"):
        fail(401, "INVALID_TOKEN", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn")
    scope = data.get("scope")
    if scope and request.url.path not in SCOPE_PATHS.get(scope, ()):
        code, msg = SCOPE_ERR.get(scope, ("SCOPE_RESTRICTED", "Phiên đăng nhập hạn chế"))
        fail(403, code, msg)
    if not scope and user.must_change_password and request.url.path not in SCOPE_PATHS["pwd_change"]:    # đề phòng: cờ bật sau khi phát token đầy đủ
        fail(403, "PASSWORD_CHANGE_REQUIRED", SCOPE_ERR["pwd_change"][1])
    return user


def require(perm: str):
    def dep(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if perm not in perms_of(user):
            audit(db, user, "access_denied", reason=f"thiếu quyền {perm}", result="denied",
                  request=request, commit=True)
            fail(403, "FORBIDDEN", f"Không có quyền thực hiện ({perm})")
        return user
    return dep


def require_any(*perms: str):
    def dep(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if not (set(perms) & perms_of(user)):
            audit(db, user, "access_denied", reason=f"thiếu một trong {perms}", result="denied",
                  request=request, commit=True)
            fail(403, "FORBIDDEN", "Không có quyền thực hiện")
        return user
    return dep


def person_or_404(db: Session, person_id: str, allow_merged: bool = False) -> Person:
    p = db.get(Person, person_id)
    if not p:
        fail(404, "PERSON_NOT_FOUND", "Không tìm thấy hồ sơ")
    if p.status == "merged" and not allow_merged:      # hồ sơ đã gộp: mọi dữ liệu nay thuộc hồ sơ giữ lại
        fail(409, "PERSON_MERGED", "Hồ sơ này đã được gộp vào hồ sơ khác", merged_into_id=p.merged_into_id)
    return p


def has_facility_link(db: Session, person_id: str, facility_id: str | None) -> bool:
    if not facility_id:
        return False
    return db.scalars(select(CustodyStay.id).where(
        CustodyStay.person_id == person_id, CustodyStay.facility_id == facility_id,
        CustodyStay.status != "voided").limit(1)).first() is not None


def active_stay(db: Session, person_id: str, facility_id: str | None = None) -> CustodyStay | None:
    q = select(CustodyStay).where(CustodyStay.person_id == person_id,
                                  CustodyStay.status.in_(("received", "managed")))
    if facility_id:
        q = q.where(CustodyStay.facility_id == facility_id)
    return db.scalars(q.limit(1)).first()


def active_grant(db: Session, user_id: str, person_id: str) -> BreakGlassGrant | None:
    return db.scalars(select(BreakGlassGrant).where(
        BreakGlassGrant.user_id == user_id, BreakGlassGrant.person_id == person_id,
        BreakGlassGrant.revoked_at.is_(None), BreakGlassGrant.expires_at > utcnow()).order_by(BreakGlassGrant.expires_at.desc())).first()


def grant_break_glass(db: Session, user: User, person_id: str, reason: str, request: Request | None = None) -> BreakGlassGrant:
    """Cấp quyền xem KHẨN CẤP có thời hạn (chỉ đọc). Bắt buộc lý do; ghi nhật ký; cảnh báo + thông báo hậu kiểm."""
    reason = (reason or "").strip()
    if "breakglass" not in perms_of(user):
        audit(db, user, "access_denied", "Person", person_id, person_id=person_id, result="denied",
              reason="không có quyền truy cập khẩn cấp", request=request, commit=True)
        fail(403, "FORBIDDEN", "Vai trò của bạn không được truy cập khẩn cấp")
    if len(reason) < 10:
        fail(422, "BREAK_GLASS_REASON", "Lý do truy cập khẩn cấp tối thiểu 10 ký tự")
    ex = active_grant(db, user.id, person_id)
    if ex:
        return ex
    g = BreakGlassGrant(user_id=user.id, person_id=person_id, reason=reason,
                        expires_at=utcnow() + timedelta(minutes=config.BREAK_GLASS_MINUTES))
    db.add(g)
    audit(db, user, "break_glass", "Person", person_id, person_id=person_id, reason=f"{reason} (hạn {config.BREAK_GLASS_MINUTES} phút)", request=request)
    db.add(Alert(person_id=person_id, facility_id=user.facility_id, kind="break_glass_review",
                 message=f"Truy cập khẩn cấp bởi {user.username}: {reason[:200]}", dedupe_key=f"bg:{g.id}"))
    msg = f"{user.username} ({user.role}) truy cập hồ sơ ngoài phạm vi cơ sở bằng quyền khẩn cấp (hạn {config.BREAK_GLASS_MINUTES} phút). Cần hậu kiểm."
    emit(db, kind="security.break_glass", category="security", severity="critical", facility_id=user.facility_id, perms=("report.read",),
         title="Truy cập khẩn cấp (break-glass) cần hậu kiểm", plain=msg, link_page="chronic", person_id=person_id, dedupe=f"bg:{g.id}")
    emit(db, kind="security.break_glass", category="security", severity="critical", facility_id=None, include_global=True, perms=("audit.read",),
         title="Truy cập khẩn cấp (break-glass) cần hậu kiểm", plain=msg, link_page="admin", person_id=person_id, dedupe=f"bg:{g.id}")
    db.flush()
    return g


def ensure_clinical_access(db: Session, user: User, person_id: str, request: Request | None = None) -> None:
    """ABAC + need-to-know: người dùng phải thuộc cơ sở có quan hệ quản lý với người bệnh.
    Ngoại lệ: break-glass – CÓ HẠN THỜI GIAN, chỉ đọc, bắt buộc lý do, hậu kiểm. Cấp bằng POST /persons/{id}/break-glass
    (hoặc header X-Break-Glass-Reason để tương thích API: tự tạo lượt cấp có hạn)."""
    if "clinical.read" not in perms_of(user):
        audit(db, user, "access_denied", "Person", person_id, person_id=person_id, result="denied",
              reason="thiếu quyền clinical.read", request=request, commit=True)
        fail(403, "FORBIDDEN", "Không có quyền xem thông tin lâm sàng")
    if has_facility_link(db, person_id, user.facility_id):
        return
    if active_grant(db, user.id, person_id):
        return
    reason = unquote(request.headers.get("X-Break-Glass-Reason", "")).strip() if request else ""  # header ASCII -> client mã hóa URL
    if reason and "breakglass" in perms_of(user):
        grant_break_glass(db, user, person_id, reason, request)
        return
    audit(db, user, "access_denied", "Person", person_id, person_id=person_id, result="denied",
          reason="ngoài phạm vi cơ sở", request=request, commit=True)
    fail(403, "FACILITY_SCOPE", "Hồ sơ nằm ngoài phạm vi cơ sở/nhiệm vụ của bạn", break_glass_allowed="breakglass" in perms_of(user))


def ensure_clinical_write(db: Session, user: User, person_id: str, request: Request | None = None) -> None:
    """Ghi dữ liệu lâm sàng cần: (1) đọc được hồ sơ, (2) người bệnh đang có đợt tiếp nhận HIỆU LỰC tại cơ sở của người ghi.
    Cơ sở cũ sau chuyển trại và người truy cập khẩn cấp (break-glass) chỉ được ĐỌC."""
    ensure_clinical_access(db, user, person_id, request)
    if active_stay(db, person_id, user.facility_id):
        return
    if not has_facility_link(db, person_id, user.facility_id):      # chỉ vào được nhờ break-glass
        audit(db, user, "access_denied", "Person", person_id, person_id=person_id, result="denied",
              reason="ghi dữ liệu khi truy cập khẩn cấp (chỉ đọc)", request=request, commit=True)
        fail(403, "BREAKGLASS_READ_ONLY", "Truy cập khẩn cấp chỉ được xem, không được ghi dữ liệu")
    fail(409, "NO_ACTIVE_STAY", "Người này không có đợt tiếp nhận hiệu lực tại cơ sở của bạn (đã chuyển trại/kết thúc) – chỉ được xem")
