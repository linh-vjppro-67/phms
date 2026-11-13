"""BR-06: chống bấm lưu lặp. Cùng Idempotency-Key + cùng nội dung -> trả lại kết quả cũ."""
import functools
import hashlib
import json

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IdempotencyRecord
from .utils import dumps, fail


def run_idempotent(db: Session, request: Request, user, payload, fn):
    """fn() -> (status_code, body). fn không được tự commit."""
    key = request.headers.get("Idempotency-Key")
    if not key:
        status, body = fn()
        db.commit()
        return JSONResponse(jsonable_encoder(body), status_code=status)
    h = hashlib.sha256(dumps(payload).encode()).hexdigest()
    path = request.url.path

    def existing():
        return db.scalars(select(IdempotencyRecord).where(
            IdempotencyRecord.key == key, IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.path == path)).first()

    rec = existing()
    if rec is None:
        status, body = fn()
        body = jsonable_encoder(body)
        db.add(IdempotencyRecord(key=key, user_id=user.id, path=path, request_hash=h,
                                 status_code=status, response_json=json.dumps(body)))
        try:
            db.commit()
            return JSONResponse(body, status_code=status)
        except IntegrityError:  # request song song cùng key
            db.rollback()
            rec = existing()
    if rec.request_hash != h:
        fail(422, "IDEMPOTENCY_MISMATCH", "Idempotency-Key đã được dùng với nội dung khác")
    return JSONResponse(json.loads(rec.response_json), status_code=rec.status_code,
                        headers={"Idempotent-Replay": "true"})


def idempotent(status: int = 201):
    """Decorator cho endpoint tạo bản ghi: hỗ trợ Idempotency-Key (BR-06) mà không đổi chữ ký hàm.
    Hàm được bọc KHÔNG được tự commit (commit cùng bản ghi idempotency trong run_idempotent)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            payload = {k: (v.model_dump(mode="json") if isinstance(v, BaseModel) else v)
                       for k, v in kw.items() if k not in ("request", "user", "db")}
            return run_idempotent(kw["db"], kw["request"], kw["user"], payload, lambda: (status, fn(*a, **kw)))
        return wrapper
    return deco
