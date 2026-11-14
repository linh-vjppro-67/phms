"""M12: tài liệu y tế (WF-09): kiểm tra file, checksum, mã hóa khi lưu, phiên bản, audit xem/tải."""
import base64
import hashlib
import os
from datetime import date

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..audit import audit
from ..db import get_db
from ..deps import ensure_clinical_access, ensure_not_break_glass_only, require
from ..models import Encounter, MedicalDocument, Referral, CustodyStay, User
from ..utils import fail, to_dict, uid

router = APIRouter()

SIGNATURES = {  # magic bytes -> mime
    b"%PDF-": "application/pdf", b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg",
}
DOC_TYPES = {"referral_letter", "discharge_summary", "lab_result", "imaging", "handover", "consent", "other"}
EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.DOC_ENC_KEY.encode()).digest()))


def scan_bytes(data: bytes) -> None:
    """Điểm cắm quét mã độc (ClamAV...). Mặc định chỉ chặn chuỗi thử nghiệm EICAR."""
    if EICAR in data:
        fail(422, "MALWARE_DETECTED", "Tệp bị chặn bởi chính sách chống mã độc")


def _path(key: str) -> str:
    os.makedirs(config.DOC_STORAGE_DIR, exist_ok=True)
    return os.path.join(config.DOC_STORAGE_DIR, key)


def _detect_mime(data: bytes) -> str | None:
    for sig, mime in SIGNATURES.items():
        if data.startswith(sig):
            return mime
    return None


async def _store(db: Session, user: User, request: Request, file: UploadFile, *, person_id, encounter_id,
                 referral_id, stay_id, doc_type, source, issued_date, replaces: MedicalDocument | None):
    if doc_type not in DOC_TYPES:
        fail(422, "BAD_DOC_TYPE", f"Loại tài liệu hợp lệ: {sorted(DOC_TYPES)}")
    data = await file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not data:
        fail(422, "EMPTY_FILE", "Tệp rỗng")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        fail(413, "FILE_TOO_LARGE", f"Tệp vượt {config.MAX_UPLOAD_MB}MB")
    mime = _detect_mime(data)  # tin nội dung, không tin Content-Type do client gửi
    if not mime:
        fail(415, "UNSUPPORTED_TYPE", "Chỉ chấp nhận PDF/PNG/JPEG")
    scan_bytes(data)
    # liên kết nghiệp vụ -> suy ra person và kiểm tra nhất quán
    enc = db.get(Encounter, encounter_id) if encounter_id else None
    ref = db.get(Referral, referral_id) if referral_id else None
    stay = db.get(CustodyStay, stay_id) if stay_id else None
    if (encounter_id and not enc) or (referral_id and not ref) or (stay_id and not stay):
        fail(404, "LINK_NOT_FOUND", "Đối tượng liên kết không tồn tại")
    pid = person_id or (enc.person_id if enc else None) or (ref.person_id if ref else None) \
        or (stay.person_id if stay else None)
    if not pid:
        fail(422, "LINK_REQUIRED", "Tài liệu phải gắn Person, Encounter, Referral hoặc CustodyStay")
    for o in (enc, ref, stay):
        if o and o.person_id != pid:
            fail(422, "LINK_MISMATCH", "Các đối tượng liên kết thuộc người khác nhau")
    ensure_not_break_glass_only(db, user, pid, request)
    key = uid()
    with open(_path(key), "wb") as f:
        f.write(_fernet().encrypt(data))
    name = os.path.basename(file.filename or "document")[:255]
    d = MedicalDocument(person_id=pid, encounter_id=encounter_id, referral_id=referral_id, stay_id=stay_id,
                        facility_id=user.facility_id, doc_type=doc_type, source=source, issued_date=issued_date,
                        filename=name, mime=mime, size=len(data), checksum=hashlib.sha256(data).hexdigest(),
                        storage_key=key, uploaded_by=user.id,
                        version=(replaces.version + 1) if replaces else 1,
                        replaces_id=replaces.id if replaces else None)
    db.add(d)
    if replaces:
        replaces.status = "superseded"
    audit(db, user, "document_uploaded", "MedicalDocument", d.id, person_id=pid, request=request,
          reason=f"{doc_type} v{d.version} sha256={d.checksum[:12]}")
    db.commit()
    return d


@router.post("/documents", status_code=201, tags=["documents"])
async def upload(request: Request, file: UploadFile = File(...), doc_type: str = Form(...),
                 person_id: str | None = Form(None), encounter_id: str | None = Form(None),
                 referral_id: str | None = Form(None), stay_id: str | None = Form(None),
                 source: str | None = Form(None), issued_date: date | None = Form(None),
                 user: User = Depends(require("document.write")), db: Session = Depends(get_db)):
    d = await _store(db, user, request, file, person_id=person_id, encounter_id=encounter_id, referral_id=referral_id,
                     stay_id=stay_id, doc_type=doc_type, source=source, issued_date=issued_date, replaces=None)
    return to_dict(d, exclude=("storage_key",))


@router.post("/documents/{doc_id}/replace", status_code=201, tags=["documents"])
async def replace(doc_id: str, request: Request, file: UploadFile = File(...), source: str | None = Form(None),
                  user: User = Depends(require("document.write")), db: Session = Depends(get_db)):
    old = db.get(MedicalDocument, doc_id)
    if not old:
        fail(404, "NOT_FOUND", "Không tìm thấy tài liệu")
    ensure_not_break_glass_only(db, user, old.person_id, request)   # kiểm quyền TRƯỚC khi lộ trạng thái tài liệu
    if old.status != "valid":
        fail(409, "NOT_VALID", "Chỉ thay thế được tài liệu đang hợp lệ")
    d = await _store(db, user, request, file, person_id=old.person_id, encounter_id=old.encounter_id,
                     referral_id=old.referral_id, stay_id=old.stay_id, doc_type=old.doc_type,
                     source=source or old.source, issued_date=old.issued_date, replaces=old)
    return to_dict(d, exclude=("storage_key",))


class InvalidIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/documents/{doc_id}/invalidate", tags=["documents"])
def invalidate(doc_id: str, body: InvalidIn, request: Request, user: User = Depends(require("document.write")),
               db: Session = Depends(get_db)):
    """Tài liệu sai người/trùng: đánh dấu không hợp lệ, KHÔNG sửa/xóa tệp gốc."""
    d = db.get(MedicalDocument, doc_id)
    if not d:
        fail(404, "NOT_FOUND", "Không tìm thấy tài liệu")
    ensure_not_break_glass_only(db, user, d.person_id, request)
    if d.status != "valid":
        fail(409, "NOT_VALID", "Tài liệu đã không còn hợp lệ")
    d.status, d.invalid_reason = "invalid", body.reason
    audit(db, user, "document_invalidated", "MedicalDocument", d.id, person_id=d.person_id, reason=body.reason,
          request=request)
    db.commit()
    return to_dict(d, exclude=("storage_key",))


@router.get("/documents", tags=["documents"])
def search(person_id: str, doc_type: str | None = None, request: Request = None,
           user: User = Depends(require("document.read")), db: Session = Depends(get_db)):
    ensure_clinical_access(db, user, person_id, request)
    q = select(MedicalDocument).where(MedicalDocument.person_id == person_id).order_by(MedicalDocument.recorded_at.desc())
    if doc_type:
        q = q.where(MedicalDocument.doc_type == doc_type)
    audit(db, user, "document_search", "Person", person_id, person_id=person_id, request=request)
    db.commit()
    return [to_dict(d, exclude=("storage_key",)) for d in db.scalars(q)]  # chỉ metadata


@router.get("/documents/{doc_id}/download", tags=["documents"])
def download(doc_id: str, request: Request, user: User = Depends(require("document.read")),
             db: Session = Depends(get_db)):
    d = db.get(MedicalDocument, doc_id)
    if not d:
        fail(404, "NOT_FOUND", "Không tìm thấy tài liệu")
    ensure_clinical_access(db, user, d.person_id, request)
    try:
        with open(_path(d.storage_key), "rb") as f:
            data = _fernet().decrypt(f.read())
    except (OSError, InvalidToken):
        audit(db, user, "document_download", "MedicalDocument", d.id, person_id=d.person_id, result="error",
              request=request, commit=True)
        fail(500, "STORAGE_ERROR", "Không đọc được tệp lưu trữ")
    if hashlib.sha256(data).hexdigest() != d.checksum:
        audit(db, user, "document_integrity_failure", "MedicalDocument", d.id, person_id=d.person_id, result="error",
              request=request, commit=True)
        fail(500, "CHECKSUM_MISMATCH", "Tệp không còn toàn vẹn")
    audit(db, user, "document_download", "MedicalDocument", d.id, person_id=d.person_id, request=request)
    db.commit()
    return Response(data, media_type=d.mime, headers={"Content-Disposition": f'attachment; filename="{d.id}"',
                                                       "X-Content-Type-Options": "nosniff"})
