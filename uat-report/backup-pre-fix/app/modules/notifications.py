"""API hộp thư thông báo. Mọi truy vấn đều ràng buộc user_id = người đang đăng nhập (chống IDOR)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Notification, NotificationPref, User
from ..notify import CATEGORIES, unread_counts
from ..utils import fail, to_dict, utcnow

router = APIRouter(prefix="/notifications", tags=["notifications"])
MAX_PAGE = 100


def _out(n: Notification) -> dict:
    return to_dict(n, exclude=("user_id", "dedupe_key"))


@router.get("")
def list_notifications(unread: bool = False, category: str | None = None, limit: int = 30, before_seq: int | None = None,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    limit = max(1, min(limit, MAX_PAGE))
    q = select(Notification).where(Notification.user_id == user.id, Notification.dismissed_at.is_(None))
    if unread:
        q = q.where(Notification.read_at.is_(None))
    if category:
        q = q.where(Notification.category == category)
    if before_seq:
        q = q.where(Notification.seq < before_seq)
    rows = db.scalars(q.order_by(Notification.seq.desc()).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [_out(n) for n in rows], "next_before_seq": rows[-1].seq if more and rows else None, **unread_counts(db, user.id)}


@router.get("/poll")
def poll(after_seq: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Client hỏi định kỳ: chỉ trả thông báo MỚI hơn after_seq + số chưa đọc (nhẹ, phù hợp qua proxy)."""
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.seq > after_seq,
                                                 Notification.dismissed_at.is_(None))
                      .order_by(Notification.seq).limit(50)).all()
    latest = db.scalar(select(Notification.seq).where(Notification.user_id == user.id).order_by(Notification.seq.desc()).limit(1)) or 0
    return {"items": [_out(n) for n in rows], "latest_seq": latest, **unread_counts(db, user.id)}


def _mine(db: Session, user: User, nid: str) -> Notification:
    n = db.scalars(select(Notification).where(Notification.id == nid, Notification.user_id == user.id)).first()
    if not n:
        fail(404, "NOTIFICATION_NOT_FOUND", "Không tìm thấy thông báo")
    return n


@router.post("/read-all")
def read_all(category: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow())
    if category:
        q = q.where(Notification.category == category)
    r = db.execute(q)
    db.commit()
    return {"updated": r.rowcount, **unread_counts(db, user.id)}


@router.post("/{nid}/read")
def read_one(nid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = _mine(db, user, nid)
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {**_out(n), **unread_counts(db, user.id)}


@router.post("/{nid}/dismiss")
def dismiss(nid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = _mine(db, user, nid)
    n.dismissed_at = utcnow()
    n.read_at = n.read_at or n.dismissed_at
    db.commit()
    return unread_counts(db, user.id)


@router.get("/preferences")
def get_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    off = {p.category for p in db.scalars(select(NotificationPref).where(NotificationPref.user_id == user.id, NotificationPref.enabled.is_(False)))}
    return [{"category": k, "label": v[0], "description": v[1], "mandatory": v[2], "enabled": v[2] or k not in off} for k, v in CATEGORIES.items()]


class PrefsIn(BaseModel):
    categories: dict[str, bool]


@router.put("/preferences")
def put_prefs(body: PrefsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for cat, enabled in body.categories.items():
        if cat not in CATEGORIES:
            fail(422, "UNKNOWN_CATEGORY", f"Nhóm thông báo không hợp lệ: {cat}")
        if CATEGORIES[cat][2] and not enabled:
            fail(422, "MANDATORY_CATEGORY", f"Nhóm “{CATEGORIES[cat][0]}” là bắt buộc, không thể tắt")
        pref = db.scalars(select(NotificationPref).where(NotificationPref.user_id == user.id, NotificationPref.category == cat)).first()
        if pref:
            pref.enabled = enabled
        else:
            db.add(NotificationPref(user_id=user.id, category=cat, enabled=enabled))
    db.commit()
    return get_prefs(user, db)
