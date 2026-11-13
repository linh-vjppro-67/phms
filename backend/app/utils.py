import json
import math
import unicodedata
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect


def uid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Giờ UTC naive – quy ước lưu trữ duy nhất của hệ thống."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def norm_dt(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    if v.tzinfo:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def clean_name(s: str | None) -> str:
    """Họ tên lưu trữ: Unicode NFC, bỏ khoảng trắng đầu/cuối và gộp khoảng trắng lặp."""
    return " ".join(unicodedata.normalize("NFC", s or "").split())


def name_key(s: str | None) -> str:
    """Khóa so khớp họ tên tiếng Việt: không phân biệt hoa/thường, dạng Unicode (NFC/NFD), khoảng trắng và dấu
    (đ -> d). Dùng cho kiểm tra trùng và tìm kiếm – SQLite lower()/ILIKE chỉ xử lý ký tự ASCII."""
    s = unicodedata.normalize("NFD", s or "").replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.casefold().split())


def fail(status: int, code: str, message: str, **extra):
    raise HTTPException(status, detail={"code": code, "message": message, **extra})


def _finite(v):
    # JSON không biểu diễn được inf/nan -> trả null thay vì lỗi 500 khi tuần tự hóa
    return None if isinstance(v, float) and not math.isfinite(v) else v


def to_dict(obj, exclude: tuple = ()) -> dict:
    return {c.key: _finite(getattr(obj, c.key)) for c in sa_inspect(obj).mapper.column_attrs if c.key not in exclude}


def bump_version(obj, expected: int | None):
    """BR-06: kiểm soát thay đổi đồng thời bằng version (optimistic locking)."""
    if expected is not None and obj.version != expected:
        fail(409, "VERSION_CONFLICT", "Dữ liệu đã được người khác thay đổi, hãy tải lại.",
             current_version=obj.version)
    obj.version += 1


def dumps(o) -> str:
    return json.dumps(o, default=str, sort_keys=True, ensure_ascii=False)
