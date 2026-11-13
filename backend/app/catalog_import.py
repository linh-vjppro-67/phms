"""Nạp danh mục ICD-10 Việt Nam (app/catalog_data.py) vào CSDL đang chạy. Idempotent: chỉ THÊM mã còn thiếu, không sửa/xóa mục có sẵn.
Không tạo tài khoản hay dữ liệu nào khác (an toàn chạy ở môi trường thật).   python -m app.catalog_import
"""
from sqlalchemy import select

from .catalog_data import ICD_VN
from .db import SessionLocal, engine
from .migrate import ensure_schema
from .models import CatalogItem


def import_icd(db) -> int:
    have = set(db.scalars(select(CatalogItem.code).where(CatalogItem.catalog == "icd")))
    added = 0
    for code, name in ICD_VN:
        if code not in have:
            db.add(CatalogItem(catalog="icd", code=code, name=name))
            have.add(code)
            added += 1
    db.commit()
    return added


if __name__ == "__main__":
    ensure_schema(engine)
    with SessionLocal() as s:
        print(f"Đã thêm {import_icd(s)} mã ICD (danh mục có {len(ICD_VN)} mã trong gói).")
