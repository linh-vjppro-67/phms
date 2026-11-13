"""Sao lưu / phục hồi PHMS (NFR-03): cơ sở dữ liệu + tệp tài liệu (đã mã hóa) + bản kê toàn vẹn.

  python -m app.backup create  [--out THƯ_MỤC]                 tạo gói phms-backup-<UTC>.tar.gz (SQLite hoặc PostgreSQL theo PHMS_DB_URL)
  python -m app.backup verify  GÓI [--check-docs]              kiểm SHA-256 từng tệp, chuỗi nhật ký (SQLite) / danh mục (PostgreSQL); --check-docs giải mã & đối chiếu checksum từng tài liệu
  python -m app.backup restore GÓI --db-url URL [--storage-dir D] [--force]   phục hồi sang CSDL/thư mục đích rồi TỰ KIỂM lại
  python -m app.backup prune   --out THƯ_MỤC --keep N          giữ N gói mới nhất

Lưu ý vận hành:
- Khóa mã hóa tài liệu (PHMS_DOC_KEY) và PHMS_SECRET KHÔNG nằm trong gói: giữ riêng ở nơi an toàn. Mất khóa = không đọc được tài liệu.
- Gói chứa dữ liệu y tế nhạy cảm: lưu ở nơi mã hóa, phân quyền chặt, và thử phục hồi định kỳ.
- PostgreSQL cần pg_dump/pg_restore trong PATH (hoặc đặt PHMS_PG_BIN).
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from . import config

FORMAT = 1


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pg(tool: str) -> str:
    d = os.getenv("PHMS_PG_BIN")
    p = os.path.join(d, tool) if d else shutil.which(tool)
    if not p or not os.path.exists(p):
        raise SystemExit(f"Không tìm thấy {tool} (cài PostgreSQL client hoặc đặt PHMS_PG_BIN)")
    return p


def _pg_args(url) -> list[str]:
    a = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    return a


def _env(url) -> dict:
    e = dict(os.environ)
    if url.password:
        e["PGPASSWORD"] = url.password
    return e


def _dump_sqlite(url, dest: str) -> None:
    src = sqlite3.connect(url.database)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)           # sao lưu trực tuyến nhất quán, không cần dừng hệ thống
    finally:
        out.close()
        src.close()


def _stats_sqlite(path: str) -> dict:
    c = sqlite3.connect(path)
    try:
        q = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
        return {"persons": q("select count(*) from person"), "audit_events": q("select count(*) from audit_event"),
                "documents": q("select count(*) from medical_document")}
    finally:
        c.close()


def _stats_engine(engine) -> dict:
    from .models import AuditEvent, MedicalDocument, Person
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        return {"persons": s.scalar(select(func.count()).select_from(Person)),
                "audit_events": s.scalar(select(func.count()).select_from(AuditEvent)),
                "documents": s.scalar(select(func.count()).select_from(MedicalDocument))}


def create(out_dir: str, db_url: str | None = None, storage_dir: str | None = None) -> str:
    db_url = db_url or config.DATABASE_URL
    storage_dir = storage_dir or config.DOC_STORAGE_DIR
    url = make_url(db_url)
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        files: dict[str, str] = {}
        if url.get_backend_name() == "sqlite":
            kind, dbfile = "sqlite", os.path.join(tmp, "database.sqlite")
            _dump_sqlite(url, dbfile)
            stats = _stats_sqlite(dbfile)
        elif url.get_backend_name() == "postgresql":
            kind, dbfile = "postgresql", os.path.join(tmp, "database.pgdump")
            subprocess.run([_pg("pg_dump"), *_pg_args(url), "-Fc", "-f", dbfile, url.database], check=True, env=_env(url))
            from .db import make_engine
            stats = _stats_engine(make_engine(db_url))
        else:
            raise SystemExit(f"CSDL không hỗ trợ sao lưu: {url.get_backend_name()}")
        files[os.path.basename(dbfile)] = _sha(dbfile)
        docs_dir = os.path.join(tmp, "documents")
        os.makedirs(docs_dir)
        if os.path.isdir(storage_dir):
            for name in sorted(os.listdir(storage_dir)):
                p = os.path.join(storage_dir, name)
                if os.path.isfile(p):
                    shutil.copy2(p, os.path.join(docs_dir, name))
                    files[f"documents/{name}"] = _sha(os.path.join(docs_dir, name))
        manifest = {"format": FORMAT, "created_at": stamp, "db_kind": kind, "files": files, "stats": stats,
                    "note": "Không chứa PHMS_DOC_KEY/PHMS_SECRET – giữ riêng."}
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        archive = os.path.join(out_dir, f"phms-backup-{stamp}.tar.gz")
        with tarfile.open(archive, "w:gz") as t:
            t.add(tmp, arcname="phms-backup")
        os.chmod(archive, 0o600)
    return archive


def _extract(archive: str, dest: str) -> dict:
    with tarfile.open(archive, "r:gz") as t:
        for m in t.getmembers():      # chống path traversal / liên kết độc hại trong gói
            if m.issym() or m.islnk() or os.path.isabs(m.name) or ".." in m.name.split("/"):
                raise SystemExit(f"Gói không hợp lệ (thành phần nguy hiểm: {m.name})")
        t.extractall(dest, filter="data")
    with open(os.path.join(dest, "phms-backup", "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def verify(archive: str, check_docs: bool = False) -> dict:
    """Kiểm gói: SHA-256 từng tệp khớp bản kê; với SQLite kiểm cả chuỗi băm nhật ký và (tuỳ chọn) từng tài liệu."""
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        man = _extract(archive, tmp)
        root = os.path.join(tmp, "phms-backup")
        for rel, sha in man["files"].items():
            p = os.path.join(root, rel)
            if not os.path.exists(p):
                problems.append(f"thiếu tệp {rel}")
            elif _sha(p) != sha:
                problems.append(f"sai SHA-256: {rel}")
        extra = []
        if man["db_kind"] == "sqlite":
            dbfile = os.path.join(root, "database.sqlite")
            if os.path.exists(dbfile):
                from .db import make_engine
                eng = make_engine(f"sqlite:///{dbfile}")
                chain, docs = _check_db(eng, os.path.join(root, "documents") if check_docs else None)
                problems += chain + docs
                eng.dispose()
        else:
            subprocess.run([_pg("pg_restore"), "--list", os.path.join(root, "database.pgdump")], check=True, capture_output=True)
            extra.append("PostgreSQL: danh mục gói đọc được; kiểm sâu bằng restore sang CSDL thử")
    return {"ok": not problems, "problems": problems, "stats": man["stats"], "created_at": man["created_at"], "db_kind": man["db_kind"], "notes": extra}


def _check_db(engine, docs_dir: str | None) -> tuple[list[str], list[str]]:
    from sqlalchemy.orm import Session
    from .audit import verify_chain
    from .models import MedicalDocument
    chain, docs = [], []
    with Session(engine) as s:
        v = verify_chain(s)
        if not v["ok"]:
            chain.append(f"chuỗi nhật ký đứt tại #{v.get('broken_at_seq')}")
        if docs_dir is not None:
            from cryptography.fernet import Fernet, InvalidToken
            f = Fernet(__import__("base64").urlsafe_b64encode(hashlib.sha256(config.DOC_ENC_KEY.encode()).digest()))
            for d in s.scalars(select(MedicalDocument)):
                p = os.path.join(docs_dir, d.storage_key)
                try:
                    data = f.decrypt(open(p, "rb").read())
                except (OSError, InvalidToken):
                    docs.append(f"không đọc/giải mã được tài liệu {d.id}")
                    continue
                if hashlib.sha256(data).hexdigest() != d.checksum:
                    docs.append(f"checksum tài liệu {d.id} không khớp")
    return chain, docs


def restore(archive: str, db_url: str, storage_dir: str | None = None, force: bool = False) -> dict:
    """Phục hồi sang CSDL đích (phải trống trừ khi --force) rồi tự kiểm lại chuỗi nhật ký + tài liệu."""
    url = make_url(db_url)
    v = verify(archive)
    if not v["ok"]:
        raise SystemExit("Gói không toàn vẹn, từ chối phục hồi: " + "; ".join(v["problems"]))
    storage_dir = storage_dir or config.DOC_STORAGE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        man = _extract(archive, tmp)
        root = os.path.join(tmp, "phms-backup")
        if man["db_kind"] != url.get_backend_name():
            raise SystemExit(f"Gói là {man['db_kind']} nhưng đích là {url.get_backend_name()}")
        if url.get_backend_name() == "sqlite":
            if os.path.exists(url.database) and not force:
                raise SystemExit(f"{url.database} đã tồn tại – dùng --force để ghi đè (hãy sao lưu bản hiện tại trước)")
            os.makedirs(os.path.dirname(os.path.abspath(url.database)), exist_ok=True)
            for ext in ("-wal", "-shm"):
                if os.path.exists(url.database + ext):
                    os.remove(url.database + ext)
            shutil.copyfile(os.path.join(root, "database.sqlite"), url.database)
        else:
            cmd = [_pg("pg_restore"), *_pg_args(url), "-d", url.database, "--no-owner", "--exit-on-error"]
            if force:
                cmd += ["--clean", "--if-exists"]
            subprocess.run([*cmd, os.path.join(root, "database.pgdump")], check=True, env=_env(url))
        if os.path.exists(storage_dir) and os.listdir(storage_dir) and not force:
            raise SystemExit(f"{storage_dir} không trống – dùng --force")
        os.makedirs(storage_dir, exist_ok=True)
        for name in os.listdir(os.path.join(root, "documents")):
            shutil.copy2(os.path.join(root, "documents", name), os.path.join(storage_dir, name))
    from .db import make_engine
    eng = make_engine(db_url)
    chain, docs = _check_db(eng, storage_dir)
    stats = _stats_engine(eng)
    eng.dispose()
    ok = not chain and not docs and stats == man["stats"]
    return {"ok": ok, "problems": chain + docs + ([] if stats == man["stats"] else [f"số liệu lệch: gói {man['stats']} / sau phục hồi {stats}"]), "stats": stats}


def prune(out_dir: str, keep: int) -> list[str]:
    files = sorted(f for f in os.listdir(out_dir) if f.startswith("phms-backup-") and f.endswith(".tar.gz"))
    gone = files[:-keep] if keep > 0 else files
    for f in gone:
        os.remove(os.path.join(out_dir, f))
    return gone


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.backup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--out", default="./backups")
    v = sub.add_parser("verify"); v.add_argument("archive"); v.add_argument("--check-docs", action="store_true")
    r = sub.add_parser("restore"); r.add_argument("archive"); r.add_argument("--db-url", required=True); r.add_argument("--storage-dir"); r.add_argument("--force", action="store_true")
    p = sub.add_parser("prune"); p.add_argument("--out", default="./backups"); p.add_argument("--keep", type=int, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "create":
        path = create(a.out)
        print(json.dumps({"archive": path, "verify": verify(path)}, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "verify":
        res = verify(a.archive, a.check_docs)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1
    if a.cmd == "restore":
        res = restore(a.archive, a.db_url, a.storage_dir, a.force)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1
    print(json.dumps({"removed": prune(a.out, a.keep)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
