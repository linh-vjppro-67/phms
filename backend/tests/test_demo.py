"""Bộ dữ liệu demo phải chạy trọn kịch bản qua API (nếu một quy tắc nghiệp vụ đổi, demo sẽ hỏng và test này báo)."""
from sqlalchemy import func, select

from app import demo
from app.db import SessionLocal
from app.models import Alert, CustodyStay, Encounter, EmergencyEvent, Handover, MedicationOrder, Referral


def test_demo_runs_and_covers_all_flows():
    demo.run(reset=True)
    with SessionLocal() as s:
        grp = lambda col: {k: v for k, v in s.execute(select(col, func.count()).group_by(col)).all()}  # noqa: E731
        assert set(grp(Referral.status)) == {"draft", "pending", "coordinated", "in_external_treatment", "result_received", "completed", "cancelled"}
        assert set(grp(Handover.status)) == {"pending", "confirmed"}
        assert set(grp(EmergencyEvent.status)) == {"open", "closed"}
        assert {"received", "managed", "transferred", "ended"} <= set(grp(CustodyStay.status))
        assert {"active", "draft", "completed", "stopped", "superseded"} <= set(grp(MedicationOrder.status))
        assert {"awaiting_results", "in_treatment", "completed", "cancelled"} <= set(grp(Encounter.status))
        assert s.scalar(select(func.count()).select_from(Referral).where(Referral.needs_post_review.is_(True))) == 1
        assert s.scalar(select(func.count()).select_from(Alert).where(Alert.level > 0)) >= 1
