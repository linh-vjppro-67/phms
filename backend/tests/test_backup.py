"""Sao lưu / phục hồi (NFR-03): gói toàn vẹn, phát hiện hỏng/giả mạo, phục hồi đúng dữ liệu + tài liệu mã hóa + chuỗi nhật ký."""
import hashlib
import io
import os
import sqlite3
import tarfile
import time

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app import backup, config
from app.audit import audit, verify_chain
from app.db import make_engine
from app.migrate import ensure_schema
from app.models import MedicalDocument, Person
from app.seed import seed


def _fernet():
    import base64
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.DOC_ENC_KEY.encode()).digest()))


@pytest.fixture()
def env(tmp_path):
    """CSDL SQLite dạng tệp có dữ liệu thật: 2 hồ sơ, 1 tài liệu mã hóa, vài sự kiện nhật ký."""
    db_file = tmp_path / "live.db"
    url = f"sqlite:///{db_file}"
    eng = make_engine(url)
    ensure_schema(eng)
    storage = tmp_path / "storage"
    storage.mkdir()
    payload = b"%PDF-1.4 ket qua xet nghiem"
    with Session(eng) as s:
        seed(s)
        p1, p2 = Person(full_name="Sao Lưu Một"), Person(full_name="Sao Lưu Hai")
        s.add_all([p1, p2])
        s.flush()
        from app.models import Facility, User
        fac = s.query(Facility).first()
        uploader = s.query(User).filter_by(username="nurse1").one()
        (storage / "blob1").write_bytes(_fernet().encrypt(payload))
        s.add(MedicalDocument(person_id=p1.id, facility_id=fac.id, doc_type="lab_result", filename="x.pdf", mime="application/pdf", size=len(payload),
                              checksum=hashlib.sha256(payload).hexdigest(), storage_key="blob1", uploaded_by=uploader.id))
        for i in range(5):
            audit(s, None, "demo_event", "Person", p1.id, person_id=p1.id, reason=f"sự kiện {i}")
        s.commit()
    eng.dispose()
    return {"url": url, "db": str(db_file), "storage": str(storage), "tmp": tmp_path}


def test_backup_verify_and_restore_roundtrip(env, tmp_path):
    arch = backup.create(str(tmp_path / "out"), env["url"], env["storage"])
    assert os.path.basename(arch).startswith("phms-backup-") and oct(os.stat(arch).st_mode & 0o777) == "0o600"
    v = backup.verify(arch, check_docs=False)
    assert v["ok"] and v["stats"]["persons"] == 2 and v["stats"]["documents"] == 1 and v["stats"]["audit_events"] >= 5

    # phục hồi sang nơi KHÁC rồi kiểm chứng toàn bộ
    new_url, new_storage = f"sqlite:///{tmp_path / 'restored.db'}", str(tmp_path / "storage2")
    r = backup.restore(arch, new_url, new_storage)
    assert r["ok"], r["problems"]
    assert r["stats"] == v["stats"]
    eng = make_engine(new_url)
    with Session(eng) as s:
        assert verify_chain(s)["ok"]
        d = s.query(MedicalDocument).one()
        assert _fernet().decrypt(open(os.path.join(new_storage, d.storage_key), "rb").read()).startswith(b"%PDF")
    eng.dispose()
    # không ghi đè ngầm
    with pytest.raises(SystemExit):
        backup.restore(arch, new_url, new_storage)
    assert backup.restore(arch, new_url, new_storage, force=True)["ok"]


def test_backup_is_consistent_while_db_is_being_written(env, tmp_path):
    """Sao lưu trực tuyến (không dừng hệ thống) vẫn cho gói nhất quán: chuỗi nhật ký nguyên vẹn."""
    import threading
    stop = threading.Event()

    def writer():
        eng = make_engine(env["url"])
        i = 0
        while not stop.is_set():
            with Session(eng) as s:
                audit(s, None, "bg_write", reason=f"n{i}", commit=True)
            i += 1
        eng.dispose()
    t = threading.Thread(target=writer)
    t.start()
    try:
        time.sleep(0.2)
        arch = backup.create(str(tmp_path / "out"), env["url"], env["storage"])
    finally:
        stop.set()
        t.join()
    assert backup.verify(arch)["ok"]


def test_verify_detects_tampering_and_corruption(env, tmp_path):
    # 1) CSDL bị sửa trực tiếp trước khi sao lưu -> chuỗi băm nhật ký đứt, verify phải báo
    c = sqlite3.connect(env["db"])
    c.execute("update audit_event set reason='bị sửa lén' where seq=3")
    c.commit()
    c.close()
    arch = backup.create(str(tmp_path / "out1"), env["url"], env["storage"])
    v = backup.verify(arch)
    assert not v["ok"] and any("chuỗi nhật ký đứt" in p for p in v["problems"])
    with pytest.raises(SystemExit):
        backup.restore(arch, f"sqlite:///{tmp_path / 'x.db'}", str(tmp_path / "s3"))    # gói không toàn vẹn -> restore TỪ CHỐI


def test_verify_detects_flipped_bytes_and_missing_key(env, tmp_path):
    arch = backup.create(str(tmp_path / "out"), env["url"], env["storage"])
    # lật 1 byte trong tệp tài liệu bên trong gói
    work = tmp_path / "unpack"
    with tarfile.open(arch) as t:
        t.extractall(work)
    blob = work / "phms-backup" / "documents" / "blob1"
    data = bytearray(blob.read_bytes())
    data[10] ^= 0xFF
    blob.write_bytes(bytes(data))
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as t:
        t.add(work / "phms-backup", arcname="phms-backup")
    v = backup.verify(str(bad))
    assert not v["ok"] and any("SHA-256" in p for p in v["problems"])
    # khóa tài liệu sai -> kiểm sâu phải báo không giải mã được
    ok_arch = backup.create(str(tmp_path / "out2"), env["url"], env["storage"])
    old = config.DOC_ENC_KEY
    config.DOC_ENC_KEY = "khoa-khac-hoan-toan"
    try:
        v2 = backup.verify(ok_arch, check_docs=True)
    finally:
        config.DOC_ENC_KEY = old
    assert not v2["ok"] and any("giải mã" in p for p in v2["problems"])
    assert backup.verify(ok_arch, check_docs=True)["ok"]


def test_malicious_archive_is_rejected(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as t:
        info = tarfile.TarInfo("phms-backup/../../escape.txt")
        info.size = 3
        t.addfile(info, io.BytesIO(b"bad"))
    with pytest.raises(SystemExit):
        backup.verify(str(evil))
    assert not (tmp_path.parent / "escape.txt").exists()


def test_prune_keeps_newest(tmp_path):
    out = tmp_path / "b"
    out.mkdir()
    for n in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        (out / f"phms-backup-{n}.tar.gz").write_bytes(b"x")
    gone = backup.prune(str(out), 1)
    assert gone == ["phms-backup-20260101T000000Z.tar.gz", "phms-backup-20260102T000000Z.tar.gz"]
    assert os.listdir(out) == ["phms-backup-20260103T000000Z.tar.gz"]
