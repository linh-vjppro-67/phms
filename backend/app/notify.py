"""Dịch vụ thông báo: phát sinh từ sự kiện nghiệp vụ, gửi đúng người (vai trò + cơ sở), không lộ dữ liệu y tế.

Nguyên tắc:
- Ghi cùng giao dịch với sự kiện gốc (hoặc cùng thành công, hoặc cùng không).
- Người nhận = người dùng đang hoạt động CÓ QUYỀN liên quan, thuộc đúng cơ sở; không báo cho chính người thực hiện.
- Nội dung chỉ nêu việc cần làm; tên người bệnh chỉ hiện với người có quyền xem danh tính (person.read);
  không bao giờ nêu chẩn đoán, thuốc điều trị cụ thể ngoài tên thuốc trong thông báo cấp phát cho nhân viên cấp phát.
- Khử trùng lặp bằng dedupe_key (mỗi người một khóa) nên scheduler/retry không tạo thông báo trùng.
- Nhóm bắt buộc (cấp cứu, bảo mật) không thể tắt.
"""
from datetime import timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from . import config
from .models import Notification, NotificationPref, Person, User
from .permissions import perms_of
from .utils import utcnow

# category -> (nhãn, mô tả, bắt buộc)
CATEGORIES: dict[str, tuple[str, str, bool]] = {
    "emergency": ("Cấp cứu", "Sự cố y tế khẩn cấp và hồ sơ tạm cần đối soát danh tính", True),
    "security": ("Bảo mật", "Truy cập khẩn cấp (break-glass), tài khoản bị khóa", True),
    "referral": ("Chuyển viện", "Đề nghị chờ duyệt, đã điều phối, có kết quả, cần hậu kiểm", False),
    "medication": ("Thuốc & xét nghiệm", "Đơn thuốc chờ cấp phát, có kết quả xét nghiệm/thủ thuật", False),
    "handover": ("Chuyển trại & bàn giao", "Cần soạn tóm tắt, sẵn sàng xác nhận, người chuyển đến", False),
    "schedule": ("Lịch & cảnh báo", "Lịch quá hạn, cảnh báo nâng mức, đợt khám định kỳ mới", False),
    "intake": ("Tiếp nhận", "Người mới tiếp nhận cần khám ban đầu", False),
}
SEVERITIES = ("info", "warning", "critical")


def person_name(db: Session, person_id: str | None) -> str | None:
    p = db.get(Person, person_id) if person_id else None
    return p.full_name if p else None


def _disabled(db: Session, user_ids: list[str], category: str) -> set[str]:
    if not user_ids:
        return set()
    return set(db.scalars(select(NotificationPref.user_id).where(
        NotificationPref.user_id.in_(user_ids), NotificationPref.category == category, NotificationPref.enabled.is_(False))))


def emit(db: Session, *, kind: str, category: str, severity: str = "info", facility_id: str | None, title: str,
         plain: str | None = None, named: str | None = None, perms: tuple[str, ...] = (), user_ids: tuple[str, ...] = (),
         actor: User | None = None, link_page: str | None = None, link_ref: str | None = None,
         person_id: str | None = None, dedupe: str | None = None, include_global: bool = False) -> int:
    """Phát thông báo tới mọi người dùng thỏa: (có một trong `perms` VÀ cùng cơ sở) hoặc nằm trong `user_ids`.
    `named` thay `plain` cho người có quyền person.read (để tên người bệnh chỉ lộ cho người được phép).
    include_global: cho phép cả tài khoản không thuộc cơ sở nào (quản trị hệ thống)."""
    assert category in CATEGORIES and severity in SEVERITIES
    db.flush()
    scope = [User.facility_id == facility_id] if facility_id else []
    if include_global:
        scope.append(User.facility_id.is_(None))
    cands: dict[str, User] = {}
    if perms and scope:
        for u in db.scalars(select(User).where(User.active.is_(True), or_(*scope))):
            if perms_of(u) & set(perms):
                cands[u.id] = u
    if user_ids:
        for u in db.scalars(select(User).where(User.active.is_(True), User.id.in_(list(user_ids)))):
            cands[u.id] = u
    if actor:
        cands.pop(actor.id, None)
    if not cands:
        return 0
    if not CATEGORIES[category][2]:  # nhóm không bắt buộc: tôn trọng tùy chọn của người dùng
        for uid_ in _disabled(db, list(cands), category):
            cands.pop(uid_, None)
    if dedupe:
        for uid_ in db.scalars(select(Notification.user_id).where(Notification.user_id.in_(list(cands)), Notification.dedupe_key == dedupe)):
            cands.pop(uid_, None)
    n = 0
    for u in cands.values():
        body = named if (named and "person.read" in perms_of(u)) else plain
        db.add(Notification(user_id=u.id, category=category, kind=kind, severity=severity, title=title[:200],
                            body=(body or None) and body[:500], link_page=link_page, link_ref=link_ref,
                            person_id=person_id, facility_id=facility_id, dedupe_key=dedupe))
        n += 1
    return n


def purge(db: Session) -> int:
    """Chính sách lưu giữ: xóa thông báo đã đọc/đã ẩn quá NOTIFY_RETENTION_DAYS, và mọi thông báo quá NOTIFY_MAX_AGE_DAYS."""
    now = utcnow()
    old_done = now - timedelta(days=config.NOTIFY_RETENTION_DAYS)
    ancient = now - timedelta(days=config.NOTIFY_MAX_AGE_DAYS)
    r = db.execute(delete(Notification).where(or_(
        (Notification.created_at < old_done) & (Notification.read_at.is_not(None) | Notification.dismissed_at.is_not(None)),
        Notification.created_at < ancient)))
    return r.rowcount or 0


def unread_counts(db: Session, user_id: str) -> dict:
    base = (Notification.user_id == user_id, Notification.read_at.is_(None), Notification.dismissed_at.is_(None))
    return {"unread": db.scalar(select(func.count()).select_from(Notification).where(*base)) or 0,
            "critical": db.scalar(select(func.count()).select_from(Notification).where(*base, Notification.severity == "critical")) or 0}
