"""RBAC (mục 10.1): vai trò -> quyền. ABAC (cơ sở/quan hệ điều trị) xử lý ở access.py.

Nguyên tắc: tách quyết định chuyên môn (bác sĩ) và hành chính (approver/cán bộ);
sysadmin KHÔNG có clinical.read (không mặc định đọc bệnh án).
"""

NURSE = {
    "person.read", "clinical.read", "encounter.write", "observation.write", "dispense.write",
    "admin.write", "schedule.read", "schedule.write", "alert.handle", "handover.initiate",
    "handover.summary", "document.read", "document.write", "emergency.write",
    "referral.read", "referral.update", "breakglass", "catalog.read",
}
DOCTOR = NURSE | {
    "diagnosis.write", "encounter.complete", "order.write", "medorder.write", "medorder.confirm",
    "referral.write", "problem.write", "careplan.write", "emergency.close",
}

ROLE_PERMS: dict[str, set[str]] = {
    "custody_officer": {"person.read", "person.write", "stay.write", "handover.initiate",
                        "handover.confirm", "catalog.read", "person.merge.request"},
    "nurse": NURSE,
    "doctor": DOCTOR,
    "pharmacist": {"person.read", "clinical.read", "dispense.write", "catalog.read"},
    "approver": {"person.read", "referral.read", "referral.approve", "referral.update",
                 "handover.confirm", "catalog.read", "person.merge.approve"},
    "manager": {"report.read", "report.export", "checkup.manage", "schedule.read",
                "alert.handle", "referral.read", "catalog.read"},
    "sysadmin": {"user.manage", "audit.read", "catalog.write", "catalog.read", "scheduler.run"},
}

ROLES = set(ROLE_PERMS)


def perms_of(user) -> set[str]:
    return ROLE_PERMS.get(user.role, set())
