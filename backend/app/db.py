import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
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


def lock_row(db, model, pk):
    """Khóa ghi một dòng đến hết giao dịch để tuần tự hóa kiểu "kiểm tra rồi ghi" (chống chạy đua).
    PostgreSQL: SELECT ... FOR UPDATE. SQLite (không có FOR UPDATE): UPDATE không đổi giá trị để giành khóa ghi
    của CSDL – yêu cầu đồng thời khác phải chờ (busy_timeout) tới khi giao dịch này commit/rollback.
    Trả về đối tượng đã nạp lại từ CSDL (dữ liệu mới nhất), None nếu không tồn tại."""
    from sqlalchemy import select, update
    if db.get_bind().dialect.name == "sqlite":
        db.execute(update(model).where(model.id == pk).values(id=model.id).execution_options(synchronize_session=False))
    else:
        db.execute(select(model.id).where(model.id == pk).with_for_update())
    return db.get(model, pk, populate_existing=True)
