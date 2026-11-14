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


def test_small_demo_has_ten_people_each_covering_a_flow():
    from app import demo_small
    from app.models import Person
    demo_small.run(reset=True)
    with SessionLocal() as s:
        names = {p.full_name: p for p in s.scalars(select(Person))}
        assert len(names) == 10
        stays = {n: s.scalars(select(CustodyStay).where(CustodyStay.person_id == p.id)).first().status for n, p in names.items()}
        assert stays["Lê Quốc Bảo"] == "received" and stays["Đỗ Văn Cường"] == "managed"             # chờ khám ban đầu / đang quản lý
        assert names["Trịnh Văn Dũng"].status == "pending_verification"                              # cấp cứu, chờ đối soát
        assert s.scalars(select(EmergencyEvent)).one().status == "open"
        assert s.scalars(select(Referral)).one().status == "pending"
        assert s.scalars(select(Handover)).one().status == "pending"
        st = {o.status for o in s.scalars(select(MedicationOrder))}
        assert {"draft", "active"} <= st                                                             # có đơn nháp và đơn đang hiệu lực
        assert s.scalar(select(func.count()).select_from(Alert).where(Alert.kind == "overdue")) >= 1 or s.scalar(select(func.count()).select_from(Alert)) >= 1
