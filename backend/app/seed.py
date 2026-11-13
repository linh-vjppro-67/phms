"""Dữ liệu khởi tạo: cơ sở, tài khoản mẫu theo vai trò, danh mục. Chạy: python -m app.seed [--demo]"""
import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog_data import ICD_VN
from .db import Base, SessionLocal, engine
from .migrate import ensure_schema
from .models import CatalogItem, Facility, User
from .security import hash_password

DEFAULT_PASSWORD = os.getenv("PHMS_SEED_PASSWORD", "Phms@2026dev")
USERS = [
    ("admin", "Quản trị hệ thống", "sysadmin", None),
    ("officer1", "Cán bộ tiếp nhận 1", "custody_officer", "F01"),
    ("nurse1", "Điều dưỡng 1", "nurse", "F01"),
    ("doctor1", "Bác sĩ 1", "doctor", "F01"),
    ("pharm1", "Dược sĩ 1", "pharmacist", "F01"),
    ("approver1", "Người điều phối 1", "approver", "F01"),
    ("manager1", "Quản lý y tế 1", "manager", "F01"),
    ("officer2", "Cán bộ tiếp nhận 2", "custody_officer", "F02"),
    ("doctor2", "Bác sĩ 2", "doctor", "F02"),
    ("nurse2", "Điều dưỡng 2", "nurse", "F02"),
    ("pharm2", "Dược sĩ 2", "pharmacist", "F02"),
    ("approver2", "Người điều phối 2", "approver", "F02"),
    ("manager2", "Quản lý y tế 2", "manager", "F02"),
]
DRUGS = [("PARA500", "Paracetamol 500mg"), ("AMOX500", "Amoxicillin 500mg"), ("MET850", "Metformin 850mg"),
         ("AMLO5", "Amlodipine 5mg"), ("OMEP20", "Omeprazole 20mg"), ("LOSA50", "Losartan 50mg"),
         ("RIFA150", "Rifampicin 150mg"), ("INH100", "Isoniazid 100mg"), ("CETI10", "Cetirizine 10mg"),
         ("IBU400", "Ibuprofen 400mg"), ("METRO250", "Metronidazole 250mg"), ("CIPRO500", "Ciprofloxacin 500mg"),
         ("GLIC30", "Gliclazide 30mg"), ("ORS", "Oresol gói")]
ICD = ICD_VN   # danh mục ICD-10 thường gặp ở Việt Nam (app/catalog_data.py)
UNITS = [("mmHg", "mmHg"), ("bpm", "lần/phút"), ("C", "°C"), ("kg", "kg"), ("mmol/L", "mmol/L")]


def seed(db: Session) -> None:
    from .models import AuditHead
    if not db.get(AuditHead, 1):
        db.add(AuditHead(id=1, counter=0))
    fac = {}
    for code, name in (("F01", "Trại giam số 1"), ("F02", "Trại giam số 2")):
        f = db.scalars(select(Facility).where(Facility.code == code)).first() or Facility(code=code, name=name)
        db.add(f)
        db.flush()
        fac[code] = f.id
    for username, full, role, fcode in USERS:
        if not db.scalars(select(User).where(User.username == username)).first():
            db.add(User(username=username, full_name=full, role=role, facility_id=fac.get(fcode),
                        password_hash=hash_password(DEFAULT_PASSWORD)))
    for cat, items in (("drug", DRUGS), ("icd", ICD), ("unit", UNITS)):
        for code, name in items:
            if not db.scalars(select(CatalogItem).where(CatalogItem.catalog == cat, CatalogItem.code == code)).first():
                db.add(CatalogItem(catalog=cat, code=code, name=name))
    db.commit()


if __name__ == "__main__":
    ensure_schema(engine)
    with SessionLocal() as s:
        seed(s)
    print(f"Seed xong. Tài khoản mẫu: {', '.join(u[0] for u in USERS)} / mật khẩu: {DEFAULT_PASSWORD}")
    print("CẢNH BÁO: đổi mật khẩu/PHMS_SECRET trước khi dùng dữ liệu thật.")
    sys.exit(0)
