"""Mô hình dữ liệu PHMS – bám mục 7 tài liệu thiết kế (business entities).

Quy ước:
- BR-03: sự kiện có occurred_at (thực tế) và recorded_at (ghi vào hệ thống).
- BR-02: không xóa vật lý bản ghi đã xác nhận; dùng trạng thái hủy/điều chỉnh.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint, event)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .utils import name_key, uid, utcnow


@event.listens_for(Base, "init", propagate=True)
def _assign_id_on_init(target, args, kwargs):
    """Gán khóa chính ngay khi tạo đối tượng để nhật ký kiểm toán/thông báo luôn có mã đối tượng
    (nếu để default lúc flush thì `obj.id` còn None khi truyền vào audit())."""
    if "id" in target.__table__.c and kwargs.get("id") is None:
        kwargs["id"] = uid()


def _pk():
    return mapped_column(String(36), primary_key=True, default=uid)


def _fk(target: str, nullable: bool = False, **kw):
    return mapped_column(String(36), ForeignKey(target), nullable=nullable, **kw)


# ----------------------------------------------------------------- M11 người dùng / tổ chức
class Facility(Base):
    __tablename__ = "facility"
    id: Mapped[str] = _pk()
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[str] = _pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    facility_id: Mapped[str | None] = _fk("facility.id", nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mfa_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)  # nullable để nâng cấp DB cũ; None = tắt
    mfa_secret: Mapped[str | None] = mapped_column(String(300), nullable=True)   # mã hóa (Fernet), không lưu thô
    mfa_pending_secret: Mapped[str | None] = mapped_column(String(300), nullable=True)  # đang đăng ký, chưa xác nhận
    mfa_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)    # chống dùng lại mã TOTP
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CatalogItem(Base):
    """Danh mục có phiên bản (thuốc, ICD, đơn vị đo) – không hardcode vào biểu mẫu."""
    __tablename__ = "catalog_item"
    __table_args__ = (UniqueConstraint("catalog", "code", "version"),)
    id: Mapped[str] = _pk()
    catalog: Mapped[str] = mapped_column(String(32))  # drug | icd | unit
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# ----------------------------------------------------------------- M01 hồ sơ phạm nhân tham chiếu
class Person(Base):
    __tablename__ = "person"
    __table_args__ = (UniqueConstraint("source_system", "external_id", name="uq_person_external"),)
    id: Mapped[str] = _pk()  # BR-01: person_id nội bộ bất biến
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    name_key: Mapped[str | None] = mapped_column(String(220), nullable=True, index=True)   # tên không dấu/chữ thường – tự cập nhật theo full_name
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending_verification")  # | verified
    duplicate_candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)  # đã gộp vào hồ sơ này (status=merged)
    created_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PersonMergeRequest(Base):
    """BR-01: gộp hồ sơ trùng KHÔNG tự động – cần đề nghị (người lập) và phê duyệt (người khác, bốn mắt)."""
    __tablename__ = "person_merge_request"
    id: Mapped[str] = _pk()
    source_id: Mapped[str] = _fk("person.id", index=True)    # hồ sơ bị gộp (sẽ ở trạng thái merged)
    target_id: Mapped[str] = _fk("person.id", index=True)    # hồ sơ giữ lại
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending | approved | rejected | cancelled
    requested_by: Mapped[str] = _fk("app_user.id")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    moved: Mapped[dict | None] = mapped_column(JSON, nullable=True)      # thống kê số bản ghi đã chuyển sang hồ sơ giữ lại


class CustodyStay(Base):
    __tablename__ = "custody_stay"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id", index=True)
    facility_id: Mapped[str] = _fk("facility.id", index=True)
    status: Mapped[str] = mapped_column(String(24), default="received")
    # received -> managed -> transferred | ended ; voided (hủy liên kết nhầm)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    initial_exam_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Handover(Base):
    """WF-07: bàn giao khi chuyển trại / kết thúc quản lý."""
    __tablename__ = "handover"
    id: Mapped[str] = _pk()
    stay_id: Mapped[str] = _fk("custody_stay.id", index=True)
    person_id: Mapped[str] = _fk("person.id")
    kind: Mapped[str] = mapped_column(String(16))  # transfer | release
    from_facility_id: Mapped[str] = _fk("facility.id")
    to_facility_id: Mapped[str | None] = _fk("facility.id", nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | confirmed | cancelled
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    open_items: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    initiated_by: Mapped[str] = _fk("app_user.id")
    summary_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    confirmed_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # biên nhận của cơ sở đích (WF-07): lập khi cơ sở nhận tạo đợt tiếp nhận mới cho người này
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    received_stay_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- M02 hồ sơ sức khỏe
class HealthRecord(Base):
    __tablename__ = "health_record"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id", unique=True)  # 1 Person – 1 HealthRecord
    allergy_status: Mapped[str] = mapped_column(String(16), default="unknown")
    # unknown | recorded | none_confirmed  (BR-07: chưa có dữ liệu ≠ không có bệnh)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Allergy(Base):
    __tablename__ = "allergy"
    id: Mapped[str] = _pk()
    record_id: Mapped[str] = _fk("health_record.id", index=True)
    substance: Mapped[str] = mapped_column(String(200))
    reaction: Mapped[str | None] = mapped_column(String(300), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    inactive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)      # gỡ vì ghi nhầm (BR-02: không xóa vật lý)
    inactive_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    inactive_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recorded_by: Mapped[str] = _fk("app_user.id")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HealthProblem(Base):
    __tablename__ = "health_problem"
    id: Mapped[str] = _pk()
    record_id: Mapped[str] = _fk("health_record.id", index=True)
    person_id: Mapped[str] = _fk("person.id", index=True)
    name: Mapped[str] = mapped_column(String(300))
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | resolved
    confirmation: Mapped[str] = mapped_column(String(16), default="confirmed")  # suspected | confirmed
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_by: Mapped[str] = _fk("app_user.id")
    facility_id: Mapped[str | None] = _fk("facility.id", nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- M03/M04 khám
class Encounter(Base):
    __tablename__ = "encounter"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id", index=True)
    stay_id: Mapped[str | None] = _fk("custody_stay.id", nullable=True)
    facility_id: Mapped[str] = _fk("facility.id", index=True)
    type: Mapped[str] = mapped_column(String(16))  # initial | periodic | ad_hoc | emergency
    status: Mapped[str] = mapped_column(String(20), default="draft")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(12), nullable=True)  # routine | urgent | emergent (WF-02: phân loại ưu tiên khi nhận yêu cầu khám)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)                  # kết luận khám & hướng xử trí – CHỈ người có quyền khám ghi
    nursing_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)       # đánh giá ban đầu của điều dưỡng (ghi nhận, không phải kết luận)
    appointment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # tham chiếu mềm tránh vòng FK
    practitioner_id: Mapped[str | None] = _fk("app_user.id", nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    late_entry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    created_by: Mapped[str] = _fk("app_user.id")


class EncounterAddendum(Base):
    __tablename__ = "encounter_addendum"
    id: Mapped[str] = _pk()
    encounter_id: Mapped[str] = _fk("encounter.id", index=True)
    text: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    version_after: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[str] = _fk("app_user.id")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Observation(Base):
    __tablename__ = "observation"
    id: Mapped[str] = _pk()
    encounter_id: Mapped[str] = _fk("encounter.id", index=True)
    person_id: Mapped[str] = _fk("person.id", index=True)
    type: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(200))
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="manual")
    measured_by: Mapped[str] = _fk("app_user.id")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Diagnosis(Base):
    __tablename__ = "diagnosis"
    id: Mapped[str] = _pk()
    encounter_id: Mapped[str] = _fk("encounter.id", index=True)
    person_id: Mapped[str] = _fk("person.id", index=True)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(16), default="preliminary")  # preliminary | final
    diagnosed_by: Mapped[str] = _fk("app_user.id")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ClinicalOrder(Base):
    """Chỉ định xét nghiệm / thủ thuật."""
    __tablename__ = "clinical_order"
    id: Mapped[str] = _pk()
    encounter_id: Mapped[str] = _fk("encounter.id", index=True)
    person_id: Mapped[str] = _fk("person.id", index=True)
    kind: Mapped[str] = mapped_column(String(16))  # lab | procedure
    description: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resulted | cancelled
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_by: Mapped[str] = _fk("app_user.id")
    resulted_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resulted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ----------------------------------------------------------------- M05/M06 thuốc
class MedicationOrder(Base):
    __tablename__ = "medication_order"
    id: Mapped[str] = _pk()
    encounter_id: Mapped[str] = _fk("encounter.id", index=True)
    person_id: Mapped[str] = _fk("person.id", index=True)
    facility_id: Mapped[str] = _fk("facility.id")
    drug_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    drug_name: Mapped[str] = mapped_column(String(200))
    strength: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dose: Mapped[str] = mapped_column(String(64))
    route: Mapped[str] = mapped_column(String(32))
    frequency: Mapped[str] = mapped_column(String(64))
    start_date: Mapped[date] = mapped_column(Date)
    duration_days: Mapped[int] = mapped_column(Integer)
    quantity_prescribed: Mapped[float] = mapped_column(Float)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    supervised: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # draft -> confirmed -> active -> completed | stopped | cancelled ; superseded (bản cũ khi điều chỉnh)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_order_id: Mapped[str | None] = _fk("medication_order.id", nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    warning_ack_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_by: Mapped[str] = _fk("app_user.id")
    confirmed_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DispenseEvent(Base):
    """Sự kiện cấp phát thực tế – KHÁC chỉ định (BR-04)."""
    __tablename__ = "dispense_event"
    id: Mapped[str] = _pk()
    order_id: Mapped[str] = _fk("medication_order.id", index=True)
    kind: Mapped[str] = mapped_column(String(12), default="dispense")  # dispense | return | cancel
    ref_dispense_id: Mapped[str | None] = _fk("dispense_event.id", nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="partial")  # partial | full (lúc ghi)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispensed_by: Mapped[str] = _fk("app_user.id")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdministrationEvent(Base):
    """Xác nhận dùng / không dùng thuốc – KHÁC cấp phát."""
    __tablename__ = "administration_event"
    id: Mapped[str] = _pk()
    order_id: Mapped[str] = _fk("medication_order.id", index=True)
    dispense_id: Mapped[str | None] = _fk("dispense_event.id", nullable=True)
    administered: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # bắt buộc nếu không dùng
    confirmed_by: Mapped[str] = _fk("app_user.id")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- M09 chuyển viện
class Referral(Base):
    __tablename__ = "referral"
    id: Mapped[str] = _pk()
    encounter_id: Mapped[str] = _fk("encounter.id", index=True)
    person_id: Mapped[str] = _fk("person.id", index=True)
    facility_id: Mapped[str] = _fk("facility.id", index=True)
    urgency: Mapped[str] = mapped_column(String(12), default="routine")  # routine | urgent | emergency
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    destination: Mapped[str | None] = mapped_column(String(200), nullable=True)
    handover_docs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_referral_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)  # returned | deceased | not_returned
    shortcut_used: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_post_review: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = _fk("app_user.id")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReferralEvent(Base):
    __tablename__ = "referral_event"
    id: Mapped[str] = _pk()
    referral_id: Mapped[str] = _fk("referral.id", index=True)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = _fk("app_user.id")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- M07/M08 lịch, kế hoạch, cảnh báo
class CarePlan(Base):
    __tablename__ = "care_plan"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id", index=True)
    problem_id: Mapped[str] = _fk("health_problem.id")
    facility_id: Mapped[str] = _fk("facility.id")
    goals: Mapped[str] = mapped_column(Text)
    measures: Mapped[list | None] = mapped_column(JSON, nullable=True)
    review_interval_days: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | ended
    version: Mapped[int] = mapped_column(Integer, default=1)
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible_user_id: Mapped[str | None] = _fk("app_user.id", nullable=True)
    created_by: Mapped[str] = _fk("app_user.id")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CheckupRound(Base):
    __tablename__ = "checkup_round"
    id: Mapped[str] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    facility_id: Mapped[str] = _fk("facility.id")
    due_date: Mapped[date] = mapped_column(Date)
    criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | open | locked
    excluded: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = _fk("app_user.id")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Appointment(Base):
    __tablename__ = "appointment"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id", index=True)
    facility_id: Mapped[str] = _fk("facility.id", index=True)
    kind: Mapped[str] = mapped_column(String(16))  # periodic | follow_up | care_plan
    care_plan_id: Mapped[str | None] = _fk("care_plan.id", nullable=True)
    round_id: Mapped[str | None] = _fk("checkup_round.id", nullable=True)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    # scheduled -> due -> completed | postponed | not_done   (quá hạn = thuộc tính tính toán)
    assignee_id: Mapped[str | None] = _fk("app_user.id", nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_encounter_id: Mapped[str | None] = _fk("encounter.id", nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (Index("ix_alert_dedupe", "dedupe_key"),)
    id: Mapped[str] = _pk()
    person_id: Mapped[str | None] = _fk("person.id", nullable=True, index=True)
    facility_id: Mapped[str | None] = _fk("facility.id", nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(500))
    dedupe_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | acknowledged | resolved | closed
    level: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[str | None] = _fk("app_user.id", nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ----------------------------------------------------------------- cấp cứu
class EmergencyEvent(Base):
    __tablename__ = "emergency_event"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id")
    facility_id: Mapped[str] = _fk("facility.id")
    encounter_id: Mapped[str | None] = _fk("encounter.id", nullable=True)
    temp_identity: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reporter: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | closed
    timeline: Mapped[list | None] = mapped_column(JSON, default=list)
    late_entry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_by: Mapped[str | None] = _fk("app_user.id", nullable=True)
    created_by: Mapped[str] = _fk("app_user.id")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- M12 tài liệu
class MedicalDocument(Base):
    __tablename__ = "medical_document"
    id: Mapped[str] = _pk()
    person_id: Mapped[str] = _fk("person.id", index=True)
    encounter_id: Mapped[str | None] = _fk("encounter.id", nullable=True)
    referral_id: Mapped[str | None] = _fk("referral.id", nullable=True)
    stay_id: Mapped[str | None] = _fk("custody_stay.id", nullable=True)
    facility_id: Mapped[str] = _fk("facility.id")
    doc_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))  # SHA-256 của bản gốc
    storage_key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    replaces_id: Mapped[str | None] = _fk("medical_document.id", nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="valid")  # valid | superseded | invalid
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str] = _fk("app_user.id")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- kiểm toán + idempotency
class AuditEvent(Base):
    """Append-only, có hash chain để phát hiện sửa đổi (NFR-07)."""
    __tablename__ = "audit_event"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), default=uid, unique=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    object_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    person_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(16), default="success")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


@event.listens_for(AuditEvent, "before_update")
def _audit_no_update(*_):
    raise RuntimeError("AuditEvent là append-only: không được sửa")


@event.listens_for(AuditEvent, "before_delete")
def _audit_no_delete(*_):
    raise RuntimeError("AuditEvent là append-only: không được xóa")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (UniqueConstraint("key", "user_id", "path"),)
    id: Mapped[str] = _pk()
    key: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[str] = mapped_column(String(36))
    path: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------- thông báo (mỗi người dùng một hộp thư)
class Notification(Base):
    """Fan-out khi ghi: mỗi người nhận một bản ghi. Nội dung tối thiểu, không chứa chi tiết lâm sàng (need-to-know)."""
    __tablename__ = "notification"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),
                      Index("ix_notification_user_seq", "user_id", "seq"))
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), default=uid, unique=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("app_user.id"), index=True)
    category: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | warning | critical
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link_page: Mapped[str | None] = mapped_column(String(32), nullable=True)
    link_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    person_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    facility_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NotificationPref(Base):
    __tablename__ = "notification_pref"
    __table_args__ = (UniqueConstraint("user_id", "category"),)
    id: Mapped[str] = _pk()
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("app_user.id"), index=True)
    category: Mapped[str] = mapped_column(String(24))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class BreakGlassGrant(Base):
    """Truy cập khẩn cấp ngoài phạm vi cơ sở (mục 10.1): bắt buộc lý do, CÓ HẠN THỜI GIAN, hậu kiểm, chỉ đọc."""
    __tablename__ = "break_glass_grant"
    id: Mapped[str] = _pk()
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("app_user.id"), index=True)
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("person.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditHead(Base):
    """Hàng khóa duy nhất để TUẦN TỰ HÓA việc nối chuỗi băm nhật ký: giao dịch nào ghi nhật ký trước phải UPDATE hàng này
    (giữ khóa tới khi commit) rồi mới đọc bản ghi cuối -> không thể có hai bản ghi cùng nối vào một bản ghi cha."""
    __tablename__ = "audit_head"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    counter: Mapped[int] = mapped_column(Integer, default=0)


@event.listens_for(Person, "before_insert")
@event.listens_for(Person, "before_update")
def _person_name_key(_, __, target):
    target.name_key = name_key(target.full_name)
