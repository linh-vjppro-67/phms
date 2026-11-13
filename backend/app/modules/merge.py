"""BR-01: gộp hồ sơ trùng CÓ PHÊ DUYỆT (không bao giờ tự động).

Quy trình: người có quyền person.merge.request lập đề nghị (hồ sơ nguồn -> hồ sơ giữ lại, có lý do);
người KHÁC có quyền person.merge.approve duyệt hoặc từ chối. Khi duyệt:
- mọi bản ghi gắn person_id của hồ sơ nguồn được chuyển sang hồ sơ giữ lại (đợt tiếp nhận, lượt khám, đơn thuốc, tài liệu, lịch…);
- hồ sơ sức khỏe (dị ứng, vấn đề sức khỏe) được hợp nhất;
- hồ sơ nguồn KHÔNG bị xóa: status='merged', merged_into_id trỏ về hồ sơ giữ lại (BR-02);
- nhật ký kiểm toán cũ giữ nguyên (bất biến), có thêm sự kiện gộp ghi rõ số bản ghi đã chuyển.
Chặn khi cả hai cùng có đợt tiếp nhận đang hiệu lực (sẽ tạo hai kỳ chồng nhau) – trừ hồ sơ tạm cấp cứu có kỳ tạm tại
cùng cơ sở với đợt của hồ sơ giữ lại: kỳ tạm bị hủy, lượt khám gắn sang đợt đang hiệu lực.
Chặn khi một trong hai hồ sơ đang có đợt hiệu lực tại cơ sở khác cơ sở người lập/duyệt (cơ sở đó mới có quyền gộp).
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import Base, get_db
from ..deps import active_stay, has_facility_link, person_or_404, require, require_any
from ..models import Allergy, CustodyStay, Encounter, HealthProblem, HealthRecord, Person, PersonMergeRequest, User
from ..notify import emit
from ..utils import fail, to_dict, utcnow

router = APIRouter()

# bảng có cột person_id nhưng KHÔNG chuyển: nhật ký (bất biến), thông báo (tham chiếu mềm), chính bảng đề nghị gộp
_SKIP_TABLES = {"audit_event", "notification", "person_merge_request", "health_record"}


def _out(db: Session, m: PersonMergeRequest) -> dict:
    d = to_dict(m)
    src, tgt = db.get(Person, m.source_id), db.get(Person, m.target_id)
    d["source"] = {"id": src.id, "full_name": src.full_name, "date_of_birth": str(src.date_of_birth or ""), "external_id": src.external_id,
                   "source_system": src.source_system, "status": src.status} if src else None
    d["target"] = {"id": tgt.id, "full_name": tgt.full_name, "date_of_birth": str(tgt.date_of_birth or ""), "external_id": tgt.external_id,
                   "source_system": tgt.source_system, "status": tgt.status} if tgt else None
    names = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_([x for x in (m.requested_by, m.decided_by) if x])))}
    d["requested_by_name"], d["decided_by_name"] = names.get(m.requested_by), names.get(m.decided_by)
    return d


def _may_request(db: Session, user: User, *ids: str) -> bool:
    """Người lập chỉ được đề nghị với hồ sơ mà cơ sở của mình có liên quan (có đợt tiếp nhận) hoặc do chính mình tạo."""
    for pid in ids:
        p = db.get(Person, pid)
        if p and (p.created_by == user.id or has_facility_link(db, pid, user.facility_id)):
            return True
    return False


def _active_elsewhere(db: Session, facility_id: str | None, *people: Person) -> CustodyStay | None:
    """Đợt tiếp nhận còn hiệu lực của một trong hai hồ sơ tại cơ sở KHÁC cơ sở người lập/duyệt: cơ sở đó đang quản lý
    người này, không để cơ sở khác gộp mất hồ sơ mà họ không hề biết."""
    for p in people:
        st = active_stay(db, p.id)
        if st and st.facility_id != facility_id:
            return st
    return None


def _provisional_duplicate(db: Session, src: Person, tgt: Person) -> tuple[CustodyStay, CustodyStay] | None:
    """Cả hai cùng có đợt hiệu lực – chỉ cho gộp khi đợt của hồ sơ nguồn là KỲ TẠM (cấp cứu) tại CÙNG cơ sở với đợt của
    hồ sơ giữ lại (hồ sơ tạm của người đang quản lý). Trả (kỳ tạm, đợt giữ lại) hoặc None nếu bị chặn/không áp dụng."""
    s_st, t_st = active_stay(db, src.id), active_stay(db, tgt.id)
    if s_st and t_st and s_st.provisional and s_st.facility_id == t_st.facility_id:
        return s_st, t_st
    return None


def _check_mergeable(db: Session, src: Person, tgt: Person, facility_id: str | None, status: int) -> None:
    st = _active_elsewhere(db, facility_id, src, tgt)
    if st:
        fail(status, "ACTIVE_ELSEWHERE", "Một hồ sơ đang được cơ sở khác quản lý – chỉ cơ sở đó được đề nghị/duyệt gộp",
             person_id=st.person_id, facility_id=st.facility_id)
    if active_stay(db, src.id) and active_stay(db, tgt.id) and not _provisional_duplicate(db, src, tgt):
        fail(409, "BOTH_ACTIVE", "Cả hai hồ sơ cùng có đợt tiếp nhận đang hiệu lực – cần xử lý đợt tiếp nhận trước khi gộp")


class MergeIn(BaseModel):
    source_id: str
    target_id: str
    reason: str = Field(min_length=10, description="Căn cứ cho rằng hai hồ sơ là một người")


@router.post("/person-merges", status_code=201, tags=["identity"])
def request_merge(body: MergeIn, request: Request, user: User = Depends(require("person.merge.request")),
                  db: Session = Depends(get_db)):
    if body.source_id == body.target_id:
        fail(422, "SAME_PERSON", "Hồ sơ nguồn và hồ sơ giữ lại phải khác nhau")
    src, tgt = person_or_404(db, body.source_id), person_or_404(db, body.target_id)
    if not _may_request(db, user, src.id, tgt.id):
        fail(403, "FORBIDDEN", "Cơ sở của bạn không có liên quan tới hai hồ sơ này")
    if db.scalars(select(PersonMergeRequest.id).where(
            PersonMergeRequest.status == "pending",
            or_(PersonMergeRequest.source_id.in_((src.id, tgt.id)), PersonMergeRequest.target_id.in_((src.id, tgt.id)))).limit(1)).first():
        fail(409, "MERGE_PENDING", "Một trong hai hồ sơ đang có đề nghị gộp chưa xử lý")
    _check_mergeable(db, src, tgt, user.facility_id, 403)
    m = PersonMergeRequest(source_id=src.id, target_id=tgt.id, reason=body.reason.strip(), requested_by=user.id)
    db.add(m)
    audit(db, user, "merge_requested", "PersonMergeRequest", m.id, person_id=tgt.id, request=request,
          reason=f"{src.id} -> {tgt.id}: {body.reason[:150]}")
    emit(db, kind="identity.merge_requested", category="intake", facility_id=user.facility_id, actor=user, perms=("person.merge.approve",),
         title="Đề nghị gộp hồ sơ trùng chờ duyệt", plain="Có đề nghị gộp hai hồ sơ nghi trùng cần phê duyệt.",
         named=f"Đề nghị gộp: {src.full_name} → {tgt.full_name}.", link_page="intake", link_ref=f"merge:{m.id}", dedupe=f"merge:{m.id}:req")
    db.commit()
    return _out(db, m)


@router.get("/person-merges", tags=["identity"])
def list_merges(status: str | None = None, request: Request = None, user: User = Depends(require_any("person.merge.request", "person.merge.approve")),
                db: Session = Depends(get_db)):
    q = select(PersonMergeRequest).order_by(PersonMergeRequest.requested_at.desc()).limit(200)
    if status:
        q = q.where(PersonMergeRequest.status == status)
    # phạm vi cơ sở (ABAC): chỉ thấy đề nghị do người của CƠ SỞ MÌNH lập, kể cả người duyệt
    mine = {u.id for u in db.scalars(select(User).where(User.facility_id == user.facility_id))}
    return [_out(db, m) for m in db.scalars(q) if m.requested_by in mine]


class DecideIn(BaseModel):
    approve: bool
    note: str | None = None


def _merge(db: Session, m: PersonMergeRequest, facility_id: str | None) -> dict:
    src, tgt = db.get(Person, m.source_id), db.get(Person, m.target_id)
    if src.status == "merged" or tgt.status == "merged":
        fail(409, "ALREADY_MERGED", "Một trong hai hồ sơ đã được gộp trước đó")
    _check_mergeable(db, src, tgt, facility_id, 409)      # tình trạng có thể đã đổi từ lúc lập đề nghị
    moved: dict[str, int] = {}
    dup = _provisional_duplicate(db, src, tgt)
    if dup:
        # hồ sơ tạm cấp cứu của người đang quản lý: dữ liệu khám gắn sang đợt đang hiệu lực, kỳ tạm được hủy (giữ lịch sử)
        prov, keep = dup
        moved["encounter_restayed"] = db.execute(update(Encounter).where(Encounter.stay_id == prov.id)
                                                 .values(stay_id=keep.id)).rowcount or 0
        prov.status, prov.end_date = "voided", date.today()
        prov.void_reason = f"Kỳ tạm cấp cứu trùng đợt tiếp nhận đang hiệu lực – đã gộp hồ sơ vào {tgt.id}"
    # 1) hồ sơ sức khỏe: hợp nhất (mỗi người 1 hồ sơ)
    srec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == src.id)).first()
    trec = db.scalars(select(HealthRecord).where(HealthRecord.person_id == tgt.id)).first()
    if srec and not trec:
        srec.person_id = tgt.id
        moved["health_record"] = 1
    elif srec and trec:
        moved["allergy"] = db.execute(update(Allergy).where(Allergy.record_id == srec.id).values(record_id=trec.id)).rowcount or 0
        moved["health_problem"] = db.execute(update(HealthProblem).where(HealthProblem.record_id == srec.id).values(record_id=trec.id)).rowcount or 0
        has_allergy = db.scalars(select(Allergy.id).where(Allergy.record_id == trec.id, Allergy.active.is_(True)).limit(1)).first()
        if has_allergy:
            trec.allergy_status = "recorded"
        elif "none_confirmed" in (srec.allergy_status, trec.allergy_status):
            trec.allergy_status = "none_confirmed"       # chỉ khi một bên đã xác nhận rõ ràng "không dị ứng" và không bên nào có dị ứng
    db.flush()
    # 2) mọi bảng khác có person_id
    for table in Base.metadata.sorted_tables:
        if table.name in _SKIP_TABLES or "person_id" not in table.c:
            continue
        n = db.execute(update(table).where(table.c.person_id == src.id).values(person_id=tgt.id)).rowcount or 0
        if n:
            moved[table.name] = n
    # 3) bổ sung định danh còn thiếu cho hồ sơ giữ lại (không ghi đè dữ liệu đã có)
    if not tgt.external_id and src.external_id:
        ext = (src.source_system, src.external_id)
        src.source_system = src.external_id = None
        db.flush()
        tgt.source_system, tgt.external_id = ext
    if not tgt.date_of_birth and src.date_of_birth:
        tgt.date_of_birth = src.date_of_birth
    if not tgt.gender and src.gender:
        tgt.gender = src.gender
    tgt.duplicate_candidates = [x for x in (tgt.duplicate_candidates or []) if x != src.id] or None
    src.status, src.merged_into_id, src.duplicate_candidates = "merged", tgt.id, None
    return moved


@router.post("/person-merges/{mid}/decision", tags=["identity"])
def decide_merge(mid: str, body: DecideIn, request: Request, user: User = Depends(require("person.merge.approve")),
                 db: Session = Depends(get_db)):
    m = db.get(PersonMergeRequest, mid)
    if not m:
        fail(404, "NOT_FOUND", "Không tìm thấy đề nghị gộp")
    requester = db.get(User, m.requested_by)
    if not requester or requester.facility_id != user.facility_id:
        fail(403, "FACILITY_SCOPE", "Đề nghị gộp thuộc cơ sở khác – chỉ người điều phối của cơ sở đó được xử lý")
    if m.status != "pending":
        fail(409, "NOT_PENDING", f"Đề nghị đã ở trạng thái '{m.status}'")
    if m.requested_by == user.id:
        fail(403, "FOUR_EYES", "Người lập đề nghị không được tự phê duyệt (nguyên tắc bốn mắt)")
    if not body.approve and not (body.note and len(body.note.strip()) >= 3):
        fail(422, "NOTE_REQUIRED", "Từ chối cần nêu lý do")
    m.decided_by, m.decided_at, m.decision_note = user.id, utcnow(), body.note
    if body.approve:
        m.moved = _merge(db, m, user.facility_id)
        m.status = "approved"
        audit(db, user, "persons_merged", "PersonMergeRequest", m.id, person_id=m.target_id, request=request,
              reason=f"{m.source_id} -> {m.target_id}; đã chuyển: {m.moved}")
    else:
        m.status = "rejected"
        audit(db, user, "merge_rejected", "PersonMergeRequest", m.id, person_id=m.target_id, request=request, reason=(body.note or "")[:200])
    tgt = db.get(Person, m.target_id)
    emit(db, kind="identity.merge_decided", category="intake", facility_id=None, user_ids=(m.requested_by,), actor=user,
         title="Đề nghị gộp hồ sơ đã được " + ("duyệt" if body.approve else "từ chối"),
         plain="Đề nghị gộp hồ sơ của bạn đã có kết quả.", named=f"Gộp hồ sơ → {tgt.full_name}: " + ("đã duyệt." if body.approve else f"bị từ chối ({(body.note or '')[:120]})."),
         link_page="intake", link_ref=f"merge:{m.id}", dedupe=f"merge:{m.id}:decided")
    db.commit()
    return _out(db, m)


@router.post("/person-merges/{mid}/cancel", tags=["identity"])
def cancel_merge(mid: str, request: Request, user: User = Depends(require("person.merge.request")), db: Session = Depends(get_db)):
    m = db.get(PersonMergeRequest, mid)
    if not m:
        fail(404, "NOT_FOUND", "Không tìm thấy đề nghị gộp")
    if m.requested_by != user.id:
        fail(403, "FORBIDDEN", "Chỉ người lập mới được rút đề nghị")
    if m.status != "pending":
        fail(409, "NOT_PENDING", f"Đề nghị đã ở trạng thái '{m.status}'")
    m.status, m.decided_at, m.decided_by = "cancelled", utcnow(), user.id
    audit(db, user, "merge_cancelled", "PersonMergeRequest", m.id, person_id=m.target_id, request=request)
    db.commit()
    return _out(db, m)
