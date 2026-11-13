"""M09: chuyển viện (WF-06). Trạng thái độc lập với CustodyStay (BR-05)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import ensure_clinical_access, require
from ..idempotency import run_idempotent
from ..notify import emit, person_name
from ..models import Alert, Encounter, MedicalDocument, Referral, ReferralEvent, User
from ..permissions import perms_of
from ..utils import bump_version, fail, norm_dt, to_dict, utcnow
from .clinical import load_encounter

router = APIRouter()

# (từ, đến) -> quyền cần có.  Quyết định y khoa (doctor) tách khỏi duyệt/điều phối hành chính (approver).
TRANS = {
    ("draft", "pending"): "referral.write",
    ("pending", "coordinated"): "referral.approve",
    ("coordinated", "in_external_treatment"): "referral.update",
    ("coordinated", "pending"): "referral.update",        # BV đổi/không tiếp nhận
    ("in_external_treatment", "result_received"): "referral.update",
    ("result_received", "completed"): "referral.write",
    ("draft", "cancelled"): "referral.write", ("pending", "cancelled"): "referral.write",
    ("coordinated", "cancelled"): "referral.write",
}
OPEN_STATES = ("draft", "pending", "coordinated", "in_external_treatment", "result_received")


def referral_out(r: Referral, user: User, db: Session) -> dict:
    d = to_dict(r)
    d["events"] = [to_dict(e) for e in db.scalars(select(ReferralEvent).where(ReferralEvent.referral_id == r.id)
                                                  .order_by(ReferralEvent.recorded_at))]
    ids = r.handover_docs or []
    d["handover_docs_detail"] = [{"id": x.id, "filename": x.filename, "doc_type": x.doc_type, "status": x.status, "version": x.version}
                                 for x in db.scalars(select(MedicalDocument).where(MedicalDocument.id.in_(ids)))] if ids else []
    if "clinical.read" not in perms_of(user):  # người điều phối chỉ thấy thông tin tối thiểu
        for k in ("reason", "result_note", "post_referral_plan"):
            d[k] = None
        for x in d["handover_docs_detail"]:      # người điều phối chỉ biết CÓ bao nhiêu/loại tài liệu, không thấy tên tệp
            x["filename"] = None
        d["clinical_hidden"] = True
    return d


def _event(db, r, frm, to, user, note, occurred_at=None):
    db.add(ReferralEvent(referral_id=r.id, from_status=frm, to_status=to, note=note, actor_id=user.id,
                         occurred_at=occurred_at or utcnow()))


class ReferralIn(BaseModel):
    urgency: str = Field(default="routine", pattern="^(routine|urgent|emergency)$")
    reason: str = Field(min_length=5)
    destination: str | None = None
    handover_docs: list[str] | None = Field(default=None, max_length=30)   # id tài liệu của người bệnh sẽ bàn giao kèm (WF-06 bước 1)


def check_handover_docs(db: Session, person_id: str, ids: list[str] | None) -> list[str] | None:
    """Tài liệu bàn giao phải là tài liệu HỢP LỆ của đúng người bệnh này (không đính kèm nhầm người / bản đã bị thay thế)."""
    if not ids:
        return None
    ids = list(dict.fromkeys(ids))
    docs = {d.id: d for d in db.scalars(select(MedicalDocument).where(MedicalDocument.id.in_(ids)))}
    for i in ids:
        d = docs.get(i)
        if not d or d.person_id != person_id:
            fail(422, "BAD_HANDOVER_DOC", "Tài liệu bàn giao không tồn tại hoặc không thuộc người bệnh này")
        if d.status != "valid":
            fail(422, "DOC_NOT_VALID", f"Tài liệu '{d.filename}' không còn hiệu lực (đã thay thế/không hợp lệ)")
    return ids


@router.post("/encounters/{enc_id}/referrals", tags=["referral"])
def create_referral(enc_id: str, body: ReferralIn, request: Request, user: User = Depends(require("referral.write")),
                    db: Session = Depends(get_db)):
    def work():
        e = load_encounter(db, user, enc_id, request, write=True)
        data = body.model_dump()
        data["handover_docs"] = check_handover_docs(db, e.person_id, body.handover_docs)
        r = Referral(encounter_id=e.id, person_id=e.person_id, facility_id=e.facility_id, created_by=user.id, **data)
        db.add(r)
        db.flush()
        _event(db, r, None, "draft", user, "Lập đề nghị chuyển viện")
        audit(db, user, "referral_created", "Referral", r.id, person_id=r.person_id, request=request)
        return 201, referral_out(r, user, db)
    return run_idempotent(db, request, user, {"e": enc_id, **body.model_dump()}, work)


class StatusIn(BaseModel):
    to: str
    note: str | None = None
    destination: str | None = None
    left_at: datetime | None = None
    result_note: str | None = None
    post_referral_plan: str | None = None
    outcome: str | None = Field(default=None, pattern="^(returned|deceased|not_returned)$")
    expected_version: int | None = None


def _load(db: Session, user: User, rid: str, request: Request) -> Referral:
    r = db.get(Referral, rid)
    if not r:
        fail(404, "REFERRAL_NOT_FOUND", "Không tìm thấy hồ sơ chuyển viện")
    if r.facility_id != user.facility_id:
        fail(403, "FACILITY_SCOPE", "Hồ sơ chuyển viện thuộc cơ sở khác")
    return r


class DocsIn(BaseModel):
    handover_docs: list[str] = Field(max_length=30)


@router.put("/referrals/{rid}/handover-docs", tags=["referral"])
def set_handover_docs(rid: str, body: DocsIn, request: Request, user: User = Depends(require("referral.write")),
                      db: Session = Depends(get_db)):
    """Chọn/đổi tài liệu bàn giao kèm đề nghị chuyển viện – chỉ khi chưa chuyển đi (nháp/chờ xử lý/đã điều phối)."""
    r = _load(db, user, rid, request)
    if r.status not in ("draft", "pending", "coordinated"):
        fail(409, "NOT_EDITABLE", "Đề nghị đã chuyển đi hoặc đã đóng – không đổi tài liệu bàn giao")
    ensure_clinical_access(db, user, r.person_id, request)
    r.handover_docs = check_handover_docs(db, r.person_id, body.handover_docs)
    bump_version(r, None)
    audit(db, user, "referral_handover_docs", "Referral", r.id, person_id=r.person_id, reason=f"{len(r.handover_docs or [])} tài liệu", request=request)
    db.commit()
    return referral_out(r, user, db)


@router.patch("/referrals/{rid}/status", tags=["referral"])
def change_status(rid: str, body: StatusIn, request: Request, user: User = Depends(require("referral.read")),
                  db: Session = Depends(get_db)):
    r = _load(db, user, rid, request)
    perms = perms_of(user)
    frm, to = r.status, body.to
    emergency_shortcut = r.urgency == "emergency" and frm in ("draft", "pending", "coordinated") \
        and to == "in_external_treatment"
    if emergency_shortcut:
        # Đường tắt cấp cứu: không chặn xử trí y tế, nhưng bắt buộc hậu kiểm
        if not ({"referral.write", "referral.update"} & perms):
            fail(403, "FORBIDDEN", "Không có quyền kích hoạt chuyển viện cấp cứu")
        r.shortcut_used = r.needs_post_review = True
        db.add(Alert(person_id=r.person_id, facility_id=r.facility_id, kind="referral_post_review",
                     message="Chuyển viện cấp cứu dùng đường tắt – cần hậu kiểm", dedupe_key=f"ref-review:{r.id}"))
    else:
        need = TRANS.get((frm, to))
        if not need:
            fail(409, "BAD_TRANSITION", f"Không thể chuyển '{frm}' -> '{to}'")
        if need not in perms:
            fail(403, "FORBIDDEN", f"Bước '{frm}->{to}' cần quyền {need}")
    if body.destination:
        r.destination = body.destination
    if to in ("coordinated", "in_external_treatment") and not r.destination:
        fail(422, "DESTINATION_REQUIRED", "Cần cơ sở tiếp nhận")
    if to == "in_external_treatment":
        r.left_at = norm_dt(body.left_at) or utcnow()
    if to == "result_received":
        has_doc = db.scalars(select(MedicalDocument.id).where(MedicalDocument.referral_id == r.id,
                                                              MedicalDocument.status == "valid")).first()
        if not (body.result_note or has_doc):
            fail(422, "RESULT_REQUIRED", "Cần ghi kết quả điều trị hoặc đính kèm giấy ra viện/kết quả")
        r.result_note = body.result_note or r.result_note
    if to == "completed":
        if not (body.post_referral_plan and body.outcome):
            fail(422, "POST_PLAN_REQUIRED", "Hoàn thành chuyển viện cần kế hoạch sau chuyển viện và kết cục (outcome)")
        r.post_referral_plan, r.outcome = body.post_referral_plan, body.outcome
        if body.outcome in ("deceased", "not_returned"):
            r.needs_post_review = True   # "xử lý theo quy trình được duyệt, không đóng sai hồ sơ" (WF-06)
    if to in ("cancelled", "pending") and frm != "draft" and not body.note:
        fail(422, "NOTE_REQUIRED", "Cần nêu lý do")
    bump_version(r, body.expected_version)
    r.status = to
    _event(db, r, frm, to, user, body.note, r.left_at if to == "in_external_treatment" else None)
    audit(db, user, f"referral_{to}", "Referral", r.id, person_id=r.person_id, reason=body.note, request=request)
    _notify_status(db, r, to, user, emergency_shortcut)
    db.commit()
    return referral_out(r, user, db)


def _notify_status(db: Session, r: Referral, to: str, actor: User, shortcut: bool) -> None:
    """Thông báo theo bước chuyển viện (không nêu lý do chuyên môn)."""
    nm = person_name(db, r.person_id)
    base = dict(facility_id=r.facility_id, actor=actor, link_page="referral", link_ref=r.id, person_id=r.person_id)
    key = f"ref:{r.id}:{to}:{r.version}"
    if shortcut:
        emit(db, kind="referral.shortcut", category="referral", severity="critical", perms=("referral.approve", "report.read"),
             title="Chuyển viện cấp cứu (đi tắt) – cần hậu kiểm", plain="Một ca chuyển viện cấp cứu đã bỏ qua bước phê duyệt, cần hậu kiểm.",
             named=f"{nm}: chuyển viện cấp cứu đã bỏ qua bước phê duyệt, cần hậu kiểm.", dedupe=key, **base)
    elif to == "pending":
        emit(db, kind="referral.pending", category="referral", severity="warning" if r.urgency != "routine" else "info", perms=("referral.approve",),
             title="Đề nghị chuyển viện chờ phê duyệt", plain=f"Mức khẩn: {r.urgency}. Nơi tiếp nhận: {r.destination or 'chưa xác định'}.",
             named=f"{nm} – mức khẩn {r.urgency}, nơi tiếp nhận: {r.destination or 'chưa xác định'}.", dedupe=key, **base)
    elif to == "coordinated":
        emit(db, kind="referral.coordinated", category="referral", perms=("referral.update",), user_ids=(r.created_by,),
             title="Chuyển viện đã được điều phối – chuẩn bị bàn giao", plain=f"Nơi tiếp nhận: {r.destination or '—'}.",
             named=f"{nm} – nơi tiếp nhận: {r.destination or '—'}.", dedupe=key, **base)
    elif to == "completed" and r.outcome in ("deceased", "not_returned"):
        emit(db, kind="referral.unusual_outcome", category="referral", severity="critical", perms=("referral.approve", "report.read"),
             title="Chuyển viện kết thúc với kết cục bất thường – cần xử lý theo quy trình",
             plain="Một hồ sơ chuyển viện đã kết thúc mà người bệnh không trở lại trại; cần hậu kiểm theo quy trình được duyệt.",
             named=f"{nm}: chuyển viện kết thúc mà người bệnh không trở lại trại; cần hậu kiểm theo quy trình được duyệt.", dedupe=key, **base)
    elif to == "result_received":
        emit(db, kind="referral.result", category="referral", user_ids=(r.created_by,),
             title="Có kết quả điều trị ngoài trại – cần hoàn thành chuyển viện", plain="Đã ghi nhận kết quả, cần lập kế hoạch sau chuyển viện.",
             named=f"{nm}: đã có kết quả, cần lập kế hoạch sau chuyển viện.", dedupe=key, **base)


class NoteIn(BaseModel):
    note: str = Field(min_length=3)


@router.post("/referrals/{rid}/events", tags=["referral"])
def add_event(rid: str, body: NoteIn, request: Request, user: User = Depends(require("referral.update")),
              db: Session = Depends(get_db)):
    """Điều trị kéo dài: giữ Referral mở, ghi thêm sự kiện theo dõi."""
    r = _load(db, user, rid, request)
    if r.status not in OPEN_STATES:
        fail(409, "REFERRAL_CLOSED", "Hồ sơ đã đóng")
    _event(db, r, r.status, r.status, user, body.note)
    audit(db, user, "referral_event", "Referral", r.id, person_id=r.person_id, request=request)
    db.commit()
    return referral_out(r, user, db)


@router.post("/referrals/{rid}/post-review", tags=["referral"])
def post_review(rid: str, body: NoteIn, request: Request, user: User = Depends(require("referral.approve")),
                db: Session = Depends(get_db)):
    r = _load(db, user, rid, request)
    if not r.needs_post_review:
        fail(409, "NO_REVIEW_NEEDED", "Hồ sơ không cần hậu kiểm")
    r.needs_post_review = False
    for a in db.scalars(select(Alert).where(Alert.dedupe_key == f"ref-review:{r.id}")):
        a.status, a.resolution, a.handled_at, a.owner_id = "resolved", body.note, utcnow(), user.id
    _event(db, r, r.status, r.status, user, f"Hậu kiểm: {body.note}")
    audit(db, user, "referral_post_review", "Referral", r.id, person_id=r.person_id, reason=body.note, request=request)
    db.commit()
    return referral_out(r, user, db)


@router.get("/referrals", tags=["referral"])
def list_referrals(status: str | None = None, open_only: bool = False, user: User = Depends(require("referral.read")),
                   db: Session = Depends(get_db)):
    q = select(Referral).where(Referral.facility_id == user.facility_id).order_by(Referral.recorded_at.desc()).limit(300)
    if status:
        q = q.where(Referral.status == status)
    if open_only:
        q = q.where(Referral.status.in_(OPEN_STATES))
    out = [referral_out(r, user, db) for r in db.scalars(q)]
    if "person.read" in perms_of(user):
        from ..models import Person
        names = {p.id: p.full_name for p in db.scalars(select(Person).where(Person.id.in_([o["person_id"] for o in out] or [""])))}
        for o in out:
            o["person_name"] = names.get(o["person_id"])
    return out


@router.get("/referrals/{rid}", tags=["referral"])
def get_referral(rid: str, request: Request, user: User = Depends(require("referral.read")), db: Session = Depends(get_db)):
    r = _load(db, user, rid, request)
    audit(db, user, "view_referral", "Referral", r.id, person_id=r.person_id, request=request)
    db.commit()
    out = referral_out(r, user, db)
    if "person.read" in perms_of(user):   # tên người bệnh chỉ hiện với người có quyền xem danh tính
        out["person_name"] = person_name(db, r.person_id)
    return out
