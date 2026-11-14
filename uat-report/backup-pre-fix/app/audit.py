"""Nhật ký kiểm toán append-only có hash chain (mục 10, NFR-07)."""
import hashlib

from fastapi import Request
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AuditEvent, AuditHead
from .utils import utcnow


def _digest(prev: str, e: AuditEvent) -> str:
    raw = "|".join(str(x) for x in (prev, e.id, e.actor_id, e.action, e.object_type, e.object_id,
                                     e.person_id, e.result, e.reason, e.at.isoformat()))
    return hashlib.sha256(raw.encode()).hexdigest()


def _lock_chain(db: Session) -> None:
    """Giữ khóa ghi chuỗi băm đến hết giao dịch (SQLite: khóa ghi CSDL; PostgreSQL: khóa hàng)."""
    for _ in range(2):
        if db.execute(update(AuditHead).where(AuditHead.id == 1).values(counter=AuditHead.counter + 1)).rowcount:
            return
        try:
            db.execute(insert(AuditHead).values(id=1, counter=0))
        except IntegrityError:   # tiến trình khác vừa tạo
            db.rollback()
    raise RuntimeError("Không khóa được chuỗi nhật ký kiểm toán")


def audit(db: Session, actor, action: str, object_type: str | None = None, object_id: str | None = None,
          *, person_id: str | None = None, result: str = "success", reason: str | None = None,
          request: Request | None = None, commit: bool = False) -> AuditEvent:
    db.flush()
    _lock_chain(db)
    last = db.scalars(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).first()
    ev = AuditEvent(
        actor_id=getattr(actor, "id", None), actor_name=getattr(actor, "username", None),
        action=action, object_type=object_type, object_id=object_id, person_id=person_id,
        result=result, reason=reason, at=utcnow(),
        source_ip=(request.client.host if request and request.client else None))
    from .utils import uid
    ev.id = uid()
    ev.prev_hash = last.hash if last else ""
    ev.hash = _digest(ev.prev_hash, ev)
    db.add(ev)
    db.flush()
    if commit:
        db.commit()
    return ev


def verify_chain(db: Session) -> dict:
    prev = ""
    n = 0
    for e in db.scalars(select(AuditEvent).order_by(AuditEvent.seq)):
        if e.prev_hash != prev or e.hash != _digest(prev, e):
            return {"ok": False, "broken_at_seq": e.seq, "checked": n}
        prev = e.hash
        n += 1
    return {"ok": True, "checked": n}
