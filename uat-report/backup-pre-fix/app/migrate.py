"""Nâng cấp lược đồ nhẹ: tạo bảng thiếu + thêm CỘT THIẾU (nullable) cho CSDL tạo từ phiên bản cũ.
Không xóa/đổi kiểu cột nào. Khi vận hành thật nên chuyển sang Alembic; đây chỉ để CSDL demo/dev không phải xóa làm lại."""
from sqlalchemy import inspect, text

from .db import Base


_PG_LOCK = 7_234_001   # khóa tư vấn PostgreSQL: nhiều worker khởi động cùng lúc chỉ có một tiến trình chạy nâng cấp schema


def ensure_schema(engine) -> list[str]:
    if engine.dialect.name == "postgresql":
        with engine.connect() as lock_conn:
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _PG_LOCK})
            try:
                return _ensure(engine)
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _PG_LOCK})
                lock_conn.commit()
    return _ensure(engine)


def _ensure(engine) -> list[str]:
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            if not col.nullable and col.server_default is None:
                raise RuntimeError(f"Cột bắt buộc mới {table.name}.{col.name} cần migration thủ công")
            ddl = col.type.compile(dialect=engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
            added.append(f"{table.name}.{col.name}")
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from .models import AuditHead, Person
    from .utils import name_key
    with Session(engine) as db:
        for p in db.scalars(select(Person).where(Person.name_key.is_(None))):     # hồ sơ cũ chưa có khóa tên
            p.name_key = name_key(p.full_name)
        db.commit()
        if not db.scalar(select(AuditHead.id).where(AuditHead.id == 1)):
            db.add(AuditHead(id=1, counter=0)); db.commit()
    return added
