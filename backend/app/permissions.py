"""RBAC (mục 10.1): vai trò -> quyền. ABAC (cơ sở/quan hệ điều trị) xử lý ở access.py.

Nguyên tắc: tách quyết định chuyên môn (bác sĩ) và hành chính (approver/cán bộ);
sysadmin KHÔNG có clinical.read (không mặc định đọc bệnh án).
"""

from . import config

# Điều dưỡng: tiếp đón, ghi nhận thông tin, đo sinh hiệu, chăm sóc, THỰC HIỆN y lệnh (ghi nhận đã dùng thuốc).
# KHÔNG: bắt đầu/kết luận khám, chẩn đoán, chỉ định, kê đơn (encounter.examine, diagnosis.write, order.write, medorder.*),
# và mặc định KHÔNG cấp phát thuốc (việc của dược; bật cho cơ sở không có dược sĩ bằng PHMS_NURSE_CAN_DISPENSE=1).
NURSE = {
    "person.read", "clinical.read", "encounter.write", "observation.write",
    "admin.write", "schedule.read", "schedule.write", "alert.handle", "handover.initiate",
    "handover.summary", "document.read", "document.write", "emergency.write",
    "referral.read", "referral.update", "breakglass", "catalog.read",
}
DOCTOR = NURSE | {
    "encounter.examine", "diagnosis.write", "encounter.complete", "order.write", "medorder.write", "medorder.confirm",
    "referral.write", "problem.write", "careplan.write", "emergency.close",
}

ROLE_PERMS: dict[str, set[str]] = {
    "custody_officer": {"person.read", "person.write", "stay.write", "handover.initiate",
                        "handover.confirm", "catalog.read", "person.merge.request"},
    "nurse": NURSE,
    "doctor": DOCTOR,
    # Y sĩ: khám, chẩn đoán, kê đơn trong phạm vi được giao. HIỆN quyền bằng bác sĩ; thu hẹp theo xác nhận phạm vi hành nghề của khách hàng.
    "medical_assistant": DOCTOR,
    "pharmacist": {"person.read", "clinical.read", "dispense.write", "catalog.read"},
    "approver": {"person.read", "referral.read", "referral.approve", "referral.update",
                 "handover.confirm", "catalog.read", "person.merge.approve"},
    "manager": {"report.read", "report.export", "checkup.manage", "schedule.read",
                "alert.handle", "referral.read", "catalog.read"},
    "sysadmin": {"user.manage", "audit.read", "catalog.write", "catalog.read", "scheduler.run"},
}

ROLES = set(ROLE_PERMS)


def perms_of(user) -> set[str]:
    p = ROLE_PERMS.get(user.role, set())
    if user.role == "nurse" and config.NURSE_CAN_DISPENSE:
        return p | {"dispense.write"}
    return p
