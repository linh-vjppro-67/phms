"""Nối lại chuỗi băm nhật ký bị đứt do lỗi đồng thời (đã sửa) – KHÔNG đổi nội dung bản ghi nào, chỉ tính lại prev_hash/hash.
Sự kiện sửa được ghi thành một bản ghi nhật ký mới (audit_chain_repaired) để vẫn truy vết được.
Mặc định chỉ chạy thử (không ghi). Chạy thật:  python -m app.audit_repair --apply
Lưu ý: nếu chuỗi đứt vì BỊ SỬA TRỰC TIẾP (tấn công), công cụ này sẽ che dấu vết – chỉ dùng khi biết nguyên nhân là lỗi đồng thời."""
import argparse

from sqlalchemy import select, update

from .audit import _digest, audit, verify_chain
from .db import SessionLocal
from .models import AuditEvent


def repair(db, apply: bool = False) -> dict:
    before = verify_chain(db)
    if before["ok"]:
        return {"status": "ok", "message": "Chuỗi nhật ký đang toàn vẹn, không cần sửa", **before}
    prev, relinked, first = "", 0, None
    for e in db.scalars(select(AuditEvent).order_by(AuditEvent.seq)).all():
        new = _digest(prev, e)
        if e.prev_hash != prev or e.hash != new:
            relinked += 1
            first = first or e.seq
            if apply:
                db.execute(update(AuditEvent).where(AuditEvent.seq == e.seq).values(prev_hash=prev, hash=new))   # Core: bỏ qua chốt append-only của ORM
        prev = new
    if apply:
        db.flush()
        audit(db, None, "audit_chain_repaired", "AuditEvent", reason=f"nối lại {relinked} bản ghi từ #{first} (lỗi ghi đồng thời đã được khắc phục)")
        db.commit()
    return {"status": "repaired" if apply else "dry-run", "relinked": relinked, "first_broken_seq": first, "verify_after": verify_chain(db) if apply else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Nối lại chuỗi băm nhật ký bị đứt do lỗi đồng thời")
    ap.add_argument("--apply", action="store_true", help="ghi thay đổi (mặc định chỉ chạy thử)")
    with SessionLocal() as s:
        print(repair(s, ap.parse_args().apply))
