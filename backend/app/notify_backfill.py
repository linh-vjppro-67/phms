"""Bổ sung thông báo cho dữ liệu ĐÃ CÓ (tạo trước khi có hệ thống thông báo). Không xóa/sửa dữ liệu, chạy lại an toàn
(cùng dedupe_key với thông báo sinh trực tiếp). Chỉ tạo cho các việc ĐANG MỞ và cần hành động.
Chạy:  python -m app.notify_backfill
"""
from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .migrate import ensure_schema
from .models import Alert, EmergencyEvent, Handover, Person, Referral
from .notify import emit, person_name


def run() -> dict:
    ensure_schema(engine)
    n = {"emergency": 0, "referral": 0, "handover": 0, "alert": 0}
    with SessionLocal() as db:
        for ev in db.scalars(select(EmergencyEvent).where(EmergencyEvent.status == "open")):
            pn = person_name(db, ev.person_id)
            desc = (ev.description or "").strip()
            n["emergency"] += emit(db, kind="emergency.created", category="emergency", severity="critical", facility_id=ev.facility_id, perms=("emergency.write",),
                                   title=f"CẤP CỨU{': ' + ev.location if ev.location else ''}", plain=desc or "Có sự cố y tế khẩn cấp, cần có mặt xử trí.",
                                   named=f"{pn} – {desc}" if desc else pn, link_page="emergency", link_ref=ev.id, person_id=ev.person_id, dedupe=f"emg:{ev.id}")
            p = db.get(Person, ev.person_id)
            if p and p.is_temporary and p.status != "verified":
                n["emergency"] += emit(db, kind="emergency.identity", category="emergency", severity="warning", facility_id=ev.facility_id, perms=("person.write",),
                                       title="Hồ sơ tạm từ cấp cứu cần đối soát danh tính", plain="Có người cấp cứu chưa rõ danh tính, cần đối soát với nguồn dữ liệu gốc.",
                                       link_page="intake", link_ref=ev.person_id, person_id=ev.person_id, dedupe=f"emg:{ev.id}:identity")
        for r in db.scalars(select(Referral)):
            nm = person_name(db, r.person_id)
            base = dict(facility_id=r.facility_id, link_page="referral", link_ref=r.id, person_id=r.person_id)
            if r.needs_post_review:
                n["referral"] += emit(db, kind="referral.shortcut", category="referral", severity="critical", perms=("referral.approve", "report.read"),
                                      title="Chuyển viện cấp cứu (đi tắt) – cần hậu kiểm", plain="Một ca chuyển viện cấp cứu đã bỏ qua bước phê duyệt, cần hậu kiểm.",
                                      named=f"{nm}: chuyển viện cấp cứu đã bỏ qua bước phê duyệt, cần hậu kiểm.", dedupe=f"ref:{r.id}:in_external_treatment:{r.version}", **base)
            elif r.status == "pending":
                n["referral"] += emit(db, kind="referral.pending", category="referral", severity="warning" if r.urgency != "routine" else "info", perms=("referral.approve",),
                                      title="Đề nghị chuyển viện chờ phê duyệt", plain=f"Mức khẩn: {r.urgency}. Nơi tiếp nhận: {r.destination or 'chưa xác định'}.",
                                      named=f"{nm} – mức khẩn {r.urgency}, nơi tiếp nhận: {r.destination or 'chưa xác định'}.", dedupe=f"ref:{r.id}:pending:{r.version}", **base)
            elif r.status == "result_received":
                n["referral"] += emit(db, kind="referral.result", category="referral", user_ids=(r.created_by,),
                                      title="Có kết quả điều trị ngoài trại – cần hoàn thành chuyển viện", plain="Đã ghi nhận kết quả, cần lập kế hoạch sau chuyển viện.",
                                      named=f"{nm}: đã có kết quả, cần lập kế hoạch sau chuyển viện.", dedupe=f"ref:{r.id}:result_received:{r.version}", **base)
        for h in db.scalars(select(Handover).where(Handover.status == "pending")):
            what = "chuyển trại" if h.kind == "transfer" else "kết thúc quản lý"
            nm = person_name(db, h.person_id)
            if h.summary:
                n["handover"] += emit(db, kind="handover.ready", category="handover", facility_id=h.from_facility_id, perms=("handover.confirm",),
                                      title="Phiếu bàn giao sẵn sàng xác nhận", plain="Bộ phận y tế đã lập tóm tắt, chờ xác nhận bàn giao.",
                                      named=f"{nm}: đã có tóm tắt y tế, chờ xác nhận bàn giao.", link_page="handover", link_ref=h.id, person_id=h.person_id, dedupe=f"ho:{h.id}:ready")
            else:
                n["handover"] += emit(db, kind="handover.initiated", category="handover", severity="warning", facility_id=h.from_facility_id, perms=("handover.summary",),
                                      title="Cần soạn tóm tắt y tế bàn giao", plain=f"Có phiếu {what} đang chờ bộ phận y tế lập tóm tắt.",
                                      named=f"{nm}: phiếu {what} đang chờ bộ phận y tế lập tóm tắt.", link_page="handover", link_ref=h.id, person_id=h.person_id, dedupe=f"ho:{h.id}:init")
        for a in db.scalars(select(Alert).where(Alert.status.in_(("new", "acknowledged")))):
            if a.kind == "break_glass_review":
                n["alert"] += emit(db, kind="security.break_glass", category="security", severity="critical", facility_id=a.facility_id, perms=("report.read",),
                                   title="Truy cập khẩn cấp (break-glass) cần hậu kiểm", plain=a.message, link_page="chronic", person_id=a.person_id, dedupe=a.dedupe_key)
            elif a.kind == "appointment_overdue":
                n["alert"] += emit(db, kind="schedule.overdue", category="schedule", severity="warning", facility_id=a.facility_id, perms=("alert.handle",),
                                   title="Lịch quá hạn cần xử lý", plain=a.message, named=f"{person_name(db, a.person_id)}: {a.message}", link_page="chronic",
                                   person_id=a.person_id, dedupe=f"alert:{a.id}:new")
                if a.level:
                    n["alert"] += emit(db, kind="schedule.escalated", category="schedule", severity="critical", facility_id=a.facility_id, perms=("report.read",),
                                       title=f"Cảnh báo chưa xử lý đã nâng mức {a.level}", plain=a.message, link_page="chronic", person_id=a.person_id,
                                       dedupe=f"alert:{a.id}:esc:{a.level}")
        db.commit()
    return n


if __name__ == "__main__":
    print("Đã tạo thông báo cho việc đang mở:", run())
