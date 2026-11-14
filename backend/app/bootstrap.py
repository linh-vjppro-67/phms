"""Khởi tạo hệ thống THẬT (production): cơ sở + quản trị viên đầu tiên + danh mục. KHÔNG tạo tài khoản mẫu.

Dùng:
  PHMS_BOOTSTRAP_ADMIN_PASSWORD='<mật khẩu mạnh>' python -m app.bootstrap \\
      --facility F01="Trại giam số 1" --facility F02="Trại giam số 2" [--admin-username admin] [--admin-name "Quản trị hệ thống"]
Nếu không đặt PHMS_BOOTSTRAP_ADMIN_PASSWORD, hệ thống sinh mật khẩu ngẫu nhiên và in MỘT LẦN ra màn hình.
Quản trị viên phải đổi mật khẩu ở lần đăng nhập đầu (và đăng ký MFA nếu PHMS_MFA_REQUIRED_ROLES có sysadmin).
Chạy lại nhiều lần an toàn (idempotent): không ghi đè người dùng/cơ sở đã có. Sau đó tạo người dùng khác trong giao diện Quản trị.
"""
import argparse
import os
import secrets
import sys

from sqlalchemy import select

from .db import SessionLocal, engine
from .migrate import ensure_schema
from .models import AuditHead, Facility, User
from .security import hash_password, password_policy_error
from .utils import utcnow


def _new_password() -> str:
    return "Ph!" + secrets.token_urlsafe(18) + "7a"       # đủ dài + có chữ hoa/thường/số/ký tự đặc biệt


def bootstrap(facilities: list[tuple[str, str]], admin_username: str = "admin", admin_name: str = "Quản trị hệ thống",
              admin_password: str | None = None) -> dict:
    ensure_schema(engine)
    generated = None
    if not admin_password:
        admin_password = generated = _new_password()
    err = password_policy_error(admin_password)
    if err:
        raise SystemExit(f"Mật khẩu quản trị không đạt chính sách: {err}")
    out = {"facilities": [], "admin_created": False, "generated_password": None}
    with SessionLocal() as db:
        if not db.get(AuditHead, 1):
            db.add(AuditHead(id=1, counter=0))
        for code, name in facilities:
            f = db.scalars(select(Facility).where(Facility.code == code)).first()
            if not f:
                db.add(Facility(code=code, name=name))
                out["facilities"].append(code)
        if not db.scalars(select(User).where(User.username == admin_username)).first():
            db.add(User(username=admin_username, full_name=admin_name, role="sysadmin", facility_id=None,
                        password_hash=hash_password(admin_password), must_change_password=True, password_changed_at=None,
                        created_at=utcnow()))
            out["admin_created"] = True
            out["generated_password"] = generated
        db.commit()
    from .catalog_import import import_catalogs
    from .seed import UNITS
    from .models import CatalogItem
    with SessionLocal() as db:
        for code, name in UNITS:
            if not db.scalars(select(CatalogItem).where(CatalogItem.catalog == "unit", CatalogItem.code == code)).first():
                db.add(CatalogItem(catalog="unit", code=code, name=name))
        db.commit()
        import_catalogs(db)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facility", action="append", required=True, metavar='MÃ="Tên cơ sở"', help="lặp lại cho nhiều cơ sở")
    ap.add_argument("--admin-username", default="admin")
    ap.add_argument("--admin-name", default="Quản trị hệ thống")
    a = ap.parse_args(argv)
    facs = []
    for f in a.facility:
        if "=" not in f:
            sys.exit(f"--facility phải có dạng MÃ=Tên, nhận được: {f!r}")
        code, name = f.split("=", 1)
        facs.append((code.strip(), name.strip()))
    r = bootstrap(facs, a.admin_username, a.admin_name, os.getenv("PHMS_BOOTSTRAP_ADMIN_PASSWORD"))
    print(f"Cơ sở mới tạo: {', '.join(r['facilities']) or '(không – đã có sẵn)'}")
    if r["admin_created"]:
        print(f"Đã tạo quản trị viên '{a.admin_username}' (bắt buộc đổi mật khẩu ở lần đăng nhập đầu).")
        if r["generated_password"]:
            print(f"MẬT KHẨU TẠM (chỉ hiện một lần, hãy ghi lại): {r['generated_password']}")
    else:
        print(f"Quản trị viên '{a.admin_username}' đã tồn tại – không thay đổi.")


if __name__ == "__main__":
    main()
