"""Bộ dữ liệu demo GỌN: 10 người, mỗi người đại diện cho một luồng nghiệp vụ, dễ theo dõi khi test/trình bày.
Dữ liệu HƯ CẤU, tạo qua đúng API nghiệp vụ (đúng phân quyền, máy trạng thái, có nhật ký) – xem app/demo.py.

  python -m app.demo_small --reset      # XÓA toàn bộ dữ liệu hiện có (tài khoản mẫu được tạo lại) rồi nạp 10 người

| # | Người | Luồng để test |
|---|---|---|
| 1 | Lê Quốc Bảo | Mới tiếp nhận, CHỜ khám ban đầu |
| 2 | Phạm Minh Tuấn | Đang khám ban đầu dở (đã đo sinh hiệu, chưa chẩn đoán) |
| 3 | Hoàng Văn Nam | Khỏe mạnh; vừa khám cảm cúm, đã cấp thuốc và ghi nhận dùng |
| 4 | Đỗ Văn Cường | Tăng huyết áp: dị ứng Aspirin, 2 thuốc giám sát, kế hoạch theo dõi, LỊCH QUÁ HẠN |
| 5 | Vũ Đình Khoa | Đái tháo đường: kế hoạch theo dõi, thuốc cấp phát MỘT PHẦN |
| 6 | Bùi Hữu Lộc | Lao phổi: phác đồ 4 thuốc, giám sát dùng thuốc, có lần KHÔNG dùng |
| 7 | Ngô Thanh Sơn | Chuyển viện đang CHỜ PHÊ DUYỆT |
| 8 | Đặng Văn Hải | Chuyển trại sang Trại 2: tóm tắt y tế đã soạn, CHỜ XÁC NHẬN |
| 9 | Trịnh Văn Dũng | CẤP CỨU đang mở, hồ sơ KHÔNG có mã → chờ đối soát danh tính (cán bộ tiếp nhận được báo) |
| 10 | Lý Thị Hoa | Đơn thuốc: 1 đơn đã xác nhận CHỜ CẤP PHÁT, 1 đơn NHÁP chờ bác sĩ xác nhận |
"""
import argparse
import sys

from sqlalchemy import func, select

from .db import Base, SessionLocal, engine
from .demo import Demo, ago, dstr
from .drug_data import DRUGS_VN
from .main import app  # noqa: F401  (đảm bảo mô hình được nạp)
from .migrate import ensure_schema
from .models import Alert, Appointment, CustodyStay, EmergencyEvent, Encounter, Handover, MedicalDocument, MedicationOrder, Person, Referral
from .seed import seed


def drug(name: str) -> dict:
    d = next(x for x in DRUGS_VN if x["name"] == name)
    return dict(code=d["code"], name=d["name"], strength=d["extra"].get("strength"))


def run(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    ensure_schema(engine)
    with SessionLocal() as s:
        seed(s)
        if s.scalar(select(func.count()).select_from(Person)):
            sys.exit("DB đã có hồ sơ. Dùng --reset nếu muốn XÓA hết và tạo lại.")
    D = Demo()
    f2 = D.f["F02"]
    print("• Tạo 10 người…")

    # 1) mới tiếp nhận, chờ khám ban đầu
    D.person(name="Lê Quốc Bảo", since=0)

    # 2) đang khám ban đầu dở
    p2 = D.person(name="Phạm Minh Tuấn", since=1)
    D.initial_exam(p2, 0, "normal", only_vitals=True)

    # 3) khỏe mạnh + cảm cúm vừa khám, đã cấp thuốc
    p3 = D.person(name="Hoàng Văn Nam", since=20)
    D.initial_exam(p3, 19, "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")], summary="Sức khỏe bình thường, đủ điều kiện lao động.")
    e = D.enc("doctor1", p3["id"], "ad_hoc", "Sổ mũi, đau họng, sốt nhẹ 2 ngày", ago(days=1))
    D.vitals("nurse1", e["id"], p3["id"], "fever", ago(days=1))
    D.dx("doctor1", e["id"], "J06", "Nhiễm khuẩn hô hấp trên cấp")
    D.patch("doctor1", f"/api/encounters/{e['id']}", {"summary": "Cảm cúm thông thường. Hạ sốt, nghỉ ngơi, uống nhiều nước, theo dõi."})
    o = D.rx("doctor1", e["id"], code="PARA500", name="Paracetamol 500mg", dose="1 viên", freq="3 lần/ngày", days=3, qty=9, start=1, strength="500mg", note="Uống khi sốt > 38,5 °C")
    D.dispense_course("pharm1", o, 1, per=9)
    D.administer("nurse1", o, days=1)
    D.done("doctor1", e["id"])

    # 4) tăng huyết áp (dị ứng Aspirin, 2 thuốc giám sát, lịch theo dõi QUÁ HẠN)
    p4 = D.person(name="Đỗ Văn Cường", since=121, prof="htn")
    drugs = [dict(code="AMLO5", name="Amlodipine 5mg", dose="1 viên", freq="1 lần/ngày", days=180, qty=180, start=120, supervised=True, strength="5mg", note="Uống buổi sáng"),
             dict(code="LOSA50", name="Losartan 50mg", dose="1 viên", freq="1 lần/ngày", days=180, qty=180, start=120, supervised=True, strength="50mg")]
    _, orders = D.initial_exam(p4, 120, "htn", [("Aspirin", "Khó thở, co thắt phế quản", "Nặng")], [("I10", "Tăng huyết áp vô căn")], drugs,
                               summary="Tăng huyết áp độ 2, chưa điều trị trước đây. Khởi trị, hẹn tái khám theo kế hoạch.")
    for o in orders:
        D.dispense_course("pharm1", o, 120)
    D.administer("nurse1", orders[0])
    D.problem_plan("doctor1", p4, "Tăng huyết áp vô căn", "I10", "Huyết áp < 140/90 mmHg", [("Huyết áp tâm thu", "mmHg"), ("Huyết áp tâm trương", "mmHg")], 14, 23, 119)
    D.follow_up("doctor1", "nurse1", p4, 60, "htn")
    D.follow_up("doctor1", "nurse1", p4, 30, "htn_ok")
    D.prof[p4["id"]] = "htn_ok"

    # 5) đái tháo đường, thuốc cấp phát một phần
    p5 = D.person(name="Vũ Đình Khoa", since=91, prof="dm")
    drugs = [dict(code="MET850", name="Metformin 850mg", dose="1 viên", freq="2 lần/ngày", days=120, qty=240, start=90, strength="850mg", note="Uống sau ăn"),
             dict(code="GLIC30", name="Gliclazide 30mg", dose="1 viên", freq="1 lần/ngày", days=120, qty=120, start=90, strength="30mg")]
    _, orders = D.initial_exam(p5, 90, "dm", None, [("E11", "Đái tháo đường típ 2")], drugs, summary="Đái tháo đường típ 2 phát hiện khi tiếp nhận, đường huyết lúc đói 11,8 mmol/L. Khởi trị, chế độ ăn, theo dõi đường huyết.")
    D.dispense_course("pharm1", orders[0], 90)
    D.post("pharm1", f"/api/medication-orders/{orders[1]['id']}/dispenses", {"quantity": 30, "occurred_at": ago(30)})       # mới cấp 30/120: còn thiếu
    D.problem_plan("doctor1", p5, "Đái tháo đường típ 2", "E11", "HbA1c < 7%, đường huyết đói 4,4–7,2 mmol/L", [("Đường huyết", "mmol/L"), ("Cân nặng", "kg")], 30, 12, 89)
    D.follow_up("doctor1", "nurse1", p5, 40, "dm")
    D.prof[p5["id"]] = "dm_ok"

    # 6) lao phổi, phác đồ 4 thuốc, giám sát
    p6 = D.person(name="Bùi Hữu Lộc", since=61, prof="tb")
    tb = [dict(code="RIFA150", name="Rifampicin 150mg", dose="3 viên", freq="1 lần/ngày", days=120, qty=360, start=60, supervised=True, strength="150mg", note="Uống lúc đói, trước ăn 1 giờ"),
          dict(code="INH100", name="Isoniazid 100mg", dose="3 viên", freq="1 lần/ngày", days=120, qty=360, start=60, supervised=True, strength="100mg")]
    for nm in ("Pyrazinamid 500mg", "Ethambutol 400mg"):
        d = drug(nm)
        tb.append(dict(code=d["code"], name=d["name"], dose="3 viên" if "Pyr" in nm else "2 viên", freq="1 lần/ngày", days=120, qty=360 if "Pyr" in nm else 240, start=60, supervised=True, strength=d["strength"]))
    _, orders = D.initial_exam(p6, 60, "tb", None, [("A15", "Lao phổi")], tb, summary="Ho kéo dài > 3 tuần, sụt cân. AFB(+). Lao phổi mới, bắt đầu phác đồ 2 tháng tấn công, giám sát uống thuốc trực tiếp.")
    for o in orders:
        D.dispense_course("pharm1", o, 60, per=30)
    D.administer("nurse1", orders[0], days=6)                                       # có 1 lần KHÔNG dùng (có lý do)
    D.problem_plan("doctor1", p6, "Lao phổi", "A15", "Âm hóa đờm sau 2 tháng", [("Cân nặng", "kg"), ("Nhiệt độ", "°C")], 30, 5, 59)

    # 7) chuyển viện chờ phê duyệt
    p7 = D.person(name="Ngô Thanh Sơn", since=40)
    D.initial_exam(p7, 39, "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")])
    e = D.enc("doctor1", p7["id"], "ad_hoc", "Nổi hạch cổ 2 tuần, không đau", ago(days=2))
    D.vitals("nurse1", e["id"], p7["id"], "normal", ago(days=2))
    D.dx("doctor1", e["id"], "R50", "Sốt kéo dài kèm hạch cổ", "preliminary")
    D.referral("doctor1", e["id"], p7["id"], "urgent", "Hạch cổ nghi lao hạch/u, cần sinh thiết", "Bệnh viện Ung bướu tỉnh", "pending")
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_treatment"})

    # 8) chuyển trại: đã soạn tóm tắt, chờ xác nhận
    p8 = D.person(name="Đặng Văn Hải", since=50)
    D.initial_exam(p8, 49, "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")], summary="Sức khỏe bình thường.")
    D.handover("officer1", "nurse1", p8["stay"]["id"], "transfer", "Điều chuyển theo quyết định số 215/QĐ-TG", to=f2,
               summary="Sức khỏe ổn định, khám ban đầu bình thường, không bệnh mạn tính, không dị ứng, không đơn thuốc đang dùng. Hồ sơ sức khỏe giữ nguyên khi chuyển trại.")

    # 9) cấp cứu đang mở, hồ sơ KHÔNG có mã → chờ đối soát danh tính
    p9 = D.person(name="Trịnh Văn Dũng", since=3, code=False)
    ev = D.post("nurse1", "/api/emergency-events", {"person_id": p9["id"], "occurred_at": ago(minutes=5), "location": "Buồng 4, khu B", "reporter": "Quản giáo Nguyễn Văn Thắng",
                                                   "description": "Ngã từ giường tầng, đau đầu, buồn nôn"})
    for act in ("Cho nằm yên, cố định cổ, đo dấu hiệu sinh tồn", "Đánh giá tri giác (GCS 15), không chảy máu", "Báo bác sĩ, theo dõi mỗi 15 phút"):
        D.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": act, "performer": "Điều dưỡng 1"})
    D.vitals("nurse1", ev["encounter_id"], p9["id"], "normal", ago(minutes=3), only=["Mạch", "Huyết áp tâm thu", "Huyết áp tâm trương", "SpO2"])

    # 10) đơn thuốc: 1 đã xác nhận chờ cấp phát + 1 nháp
    p10 = D.person(name="Lý Thị Hoa", female=True, since=45)
    D.initial_exam(p10, 44, "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")])
    e = D.enc("doctor1", p10["id"], "ad_hoc", "Đau thượng vị, ợ chua sau ăn 1 tuần", ago(hours=3))
    D.vitals("nurse1", e["id"], p10["id"], "normal", ago(hours=3))
    D.dx("doctor1", e["id"], "K29", "Viêm dạ dày")
    D.rx("doctor1", e["id"], code="OMEP20", name="Omeprazole 20mg", dose="1 viên", freq="1 lần/ngày", days=14, qty=14, start=0, strength="20mg", note="Uống trước ăn sáng 30 phút")     # đã xác nhận, chờ cấp phát
    D.rx("doctor1", e["id"], code="IBU400", name="Ibuprofen 400mg", dose="1 viên", freq="2 lần/ngày", days=5, qty=10, start=0, strength="400mg", confirm=False)                  # nháp

    print("• Đợt khám định kỳ, tác vụ nền…")
    D.round("manager1", "doctor1", "nurse1", "Khám sức khỏe định kỳ Quý 4/2026", 12, complete_n=2, days_range=(0, 2))
    D.post("admin", "/api/scheduler/run")
    D.post("admin", "/api/scheduler/run?escalate_after_hours=0")
    for u in ("officer1", "nurse1", "doctor1", "pharm1", "approver1", "manager1"):
        for cat in ("intake", "medication"):
            D.post(u, f"/api/notifications/read-all?category={cat}")

    with SessionLocal() as s:
        cnt = lambda m: s.scalar(select(func.count()).select_from(m))  # noqa: E731
        print("\n=== Xong ===")
        print(f"Hồ sơ: {cnt(Person)} · Đợt tiếp nhận: {cnt(CustodyStay)} · Lượt khám: {cnt(Encounter)} · Đơn thuốc: {cnt(MedicationOrder)} · Chuyển viện: {cnt(Referral)} · Cấp cứu: {cnt(EmergencyEvent)} · "
              f"Bàn giao: {cnt(Handover)} · Lịch hẹn: {cnt(Appointment)} · Cảnh báo: {cnt(Alert)} · Tài liệu: {cnt(MedicalDocument)}")
    print("Đăng nhập (mật khẩu Phms@2026dev): admin · officer1 nurse1 doctor1 pharm1 approver1 manager1 (Trại 1) · officer2 nurse2 doctor2 pharm2 approver2 manager2 (Trại 2)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Dữ liệu demo gọn: 10 người")
    ap.add_argument("--reset", action="store_true", help="XÓA toàn bộ dữ liệu hiện có rồi tạo lại")
    run(ap.parse_args().reset)
