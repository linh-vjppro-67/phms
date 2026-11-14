import os
import threading

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kw: dict = {}
    mem = url in ("sqlite://", "sqlite:///:memory:")
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False, "timeout": 30}   # chờ khóa ghi thay vì báo lỗi ngay
        if mem:
            kw["poolclass"] = StaticPool
        else:   # số kết nối >= số luồng xử lý để yêu cầu không phải xếp hàng chờ kết nối
            kw.update(pool_size=40, max_overflow=20, pool_timeout=60)
    else:
        # mỗi worker có một pool riêng: (pool_size + overflow) × số worker phải < max_connections của PostgreSQL
        kw.update(pool_size=int(os.getenv("PHMS_DB_POOL", "10")), max_overflow=int(os.getenv("PHMS_DB_OVERFLOW", "10")),
                  pool_timeout=60, pool_pre_ping=True, pool_recycle=1800)
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")   # ràng buộc khóa ngoại (NFR-05)
            if not mem:
                dbapi_conn.execute("PRAGMA journal_mode=WAL")      # đọc song song với ghi, commit nhanh
                dbapi_conn.execute("PRAGMA synchronous=NORMAL")
                dbapi_conn.execute("PRAGMA busy_timeout=30000")
    return eng


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------- khóa hàng (chống tranh chấp kiểu "kiểm tra rồi ghi")
# Dùng Lock thường (không phải RLock): FastAPI chạy phần chuẩn bị/xử lý/dọn dẹp của một yêu cầu ở các luồng khác nhau nên khóa có thể được nhả từ luồng khác.
_STRIPES = [threading.Lock() for _ in range(256)]      # SQLite (một tiến trình): khóa theo băm khóa, số khóa cố định nên không rò bộ nhớ


def lock_row(db: Session, model, pk: str):
    """Tuần tự hóa mọi thao tác "đọc điều kiện → ghi" trên CÙNG một hàng (cấp phát ≤ số kê, một phiếu bàn giao/một đợt, hoàn tất lịch hẹn…).
    PostgreSQL: SELECT … FOR UPDATE (giữ đến hết giao dịch). SQLite: khóa trong tiến trình (giữ đến hết giao dịch) + bỏ ảnh chụp đọc cũ rồi đọc lại.
    Gọi TRƯỚC khi đọc điều kiện và trước mọi thao tác ghi trong giao dịch; trả về hàng đã làm mới (hoặc None nếu không có)."""
    if db.get_bind().dialect.name == "postgresql":
        return db.get(model, pk, with_for_update=True, populate_existing=True)
    idx = hash((model.__tablename__, pk)) % len(_STRIPES)
    held: set = db.info.setdefault("row_stripes", set())
    if idx not in held:                                  # phiên này đã giữ khóa này rồi (hai hàng cùng ô băm) -> không tự khóa chính mình
        if not _STRIPES[idx].acquire(timeout=30):
            from .utils import fail
            fail(503, "BUSY", "Hệ thống đang bận xử lý cùng dữ liệu, vui lòng thử lại sau ít giây")
        held.add(idx)
    db.info["_refreshing"] = True
    try:
        db.rollback()      # bỏ ảnh chụp đọc cũ để thấy dữ liệu người khác vừa ghi xong (SQLite WAL cố định ảnh chụp ở lần đọc đầu)
    finally:
        db.info["_refreshing"] = False
    return db.get(model, pk, populate_existing=True)


@event.listens_for(Session, "after_transaction_end")
def _release_row_locks(session, transaction):
    if transaction.parent is None and not session.info.get("_refreshing"):
        for idx in session.info.pop("row_stripes", set()):
            _STRIPES[idx].release()
