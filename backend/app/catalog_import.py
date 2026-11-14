"""Nạp danh mục ICD-10 (app/catalog_data.py) và thuốc thiết yếu (app/drug_data.py) vào CSDL đang chạy. Idempotent: chỉ THÊM mục còn thiếu,
không sửa/xóa mục có sẵn (chỉ bổ sung thông tin nhóm/dạng cho thuốc cũ chưa có). Không tạo tài khoản hay dữ liệu nào khác (an toàn chạy ở môi trường thật).   python -m app.catalog_import
"""
from sqlalchemy import select

from .catalog_data import ICD_VN
from .drug_data import DRUGS_VN
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


def import_drugs(db) -> tuple[int, int]:
    """Thêm thuốc còn thiếu; với mục đã có mà chưa có thông tin nhóm/dạng/đường dùng thì CHỈ bổ sung `extra` (không đổi tên/mã/phiên bản)."""
    have = {i.code: i for i in db.scalars(select(CatalogItem).where(CatalogItem.catalog == "drug"))}
    added = filled = 0
    for d in DRUGS_VN:
        cur = have.get(d["code"])
        if cur is None:
            db.add(CatalogItem(catalog="drug", code=d["code"], name=d["name"], extra=d["extra"]))
            added += 1
        elif not cur.extra:
            cur.extra = d["extra"]
            filled += 1
    db.commit()
    return added, filled


def import_catalogs(db) -> dict:
    a, f = import_drugs(db)
    return {"icd_added": import_icd(db), "drug_added": a, "drug_extra_filled": f}


if __name__ == "__main__":
    ensure_schema(engine)
    with SessionLocal() as s:
        r = import_catalogs(s)
        print(f"ICD: thêm {r['icd_added']} mã (gói có {len(ICD_VN)}). Thuốc: thêm {r['drug_added']} mục, bổ sung thông tin nhóm cho {r['drug_extra_filled']} mục có sẵn (gói có {len(DRUGS_VN)}).")
