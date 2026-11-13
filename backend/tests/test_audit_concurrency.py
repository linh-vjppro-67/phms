"""Chuỗi băm nhật ký phải liền mạch dù nhiều người ghi đồng thời (trước đây hai yêu cầu song song làm chuỗi rẽ nhánh)."""
import os
import tempfile
import threading

from sqlalchemy.orm import sessionmaker

from app.audit import audit, verify_chain
from app.db import Base, make_engine
from app.migrate import ensure_schema


def test_hash_chain_stays_linear_under_concurrent_writers():
    path = os.path.join(tempfile.mkdtemp(prefix="phms-chain-"), "chain.db")
    eng = make_engine(f"sqlite:///{path}")
    ensure_schema(eng)
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    errors: list[Exception] = []

    def worker(n: int):
        try:
            for i in range(25):
                with Session() as db:
                    audit(db, None, "concurrent_test", reason=f"w{n}-{i}")
                    db.commit()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors[:3]
    with Session() as db:
        v = verify_chain(db)
    assert v == {"ok": True, "checked": 200}, v


def test_repair_relinks_a_forked_chain_without_changing_event_content_and_leaves_a_trace():
    from sqlalchemy import update
    from app.audit_repair import repair
    from app.db import SessionLocal
    from app.models import AuditEvent
    with SessionLocal() as db:
        for i in range(6):
            audit(db, None, "t", reason=f"e{i}")
        db.commit()
        db.execute(update(AuditEvent).where(AuditEvent.seq == 4).values(prev_hash="x" * 64))   # mô phỏng nhánh rẽ
        db.commit()
        assert verify_chain(db)["ok"] is False
        reasons = [e.reason for e in db.query(AuditEvent).order_by(AuditEvent.seq)]
        assert repair(db, apply=False)["status"] == "dry-run" and verify_chain(db)["ok"] is False    # chạy thử không ghi
        r = repair(db, apply=True)
        assert r["status"] == "repaired" and r["verify_after"]["ok"] is True
        evs = db.query(AuditEvent).order_by(AuditEvent.seq).all()
        assert [e.reason for e in evs[:6]] == reasons                                               # nội dung không đổi
        assert evs[-1].action == "audit_chain_repaired"                                             # có dấu vết sửa
        assert repair(db, apply=True)["status"] == "ok"
