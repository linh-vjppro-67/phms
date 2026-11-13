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
