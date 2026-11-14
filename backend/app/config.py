"""Cấu hình hệ thống. Mọi giá trị nhạy cảm lấy từ biến môi trường (không hardcode ở production)."""
import os

ENV = os.getenv("PHMS_ENV", "dev").lower()          # dev | production (production: tắt /docs, bắt buộc secret riêng, HSTS)
IS_PROD = ENV == "production"
DEV_SECRET = "dev-only-secret-change-me-in-production-32b"
SECRET_KEY = os.getenv("PHMS_SECRET", DEV_SECRET)

# MFA (TOTP): vai trò bắt buộc dùng MFA, ví dụ "sysadmin,approver,manager". Rỗng = không bắt buộc (người dùng vẫn tự bật được).
MFA_REQUIRED_ROLES = {r.strip() for r in os.getenv("PHMS_MFA_REQUIRED_ROLES", "").split(",") if r.strip()}
MFA_ISSUER = os.getenv("PHMS_MFA_ISSUER", "PHMS")

# SSO OIDC (tùy chọn). Bật khi có PHMS_OIDC_ISSUER + CLIENT_ID + CLIENT_SECRET + REDIRECT_URI.
OIDC_ISSUER = os.getenv("PHMS_OIDC_ISSUER", "").rstrip("/")
OIDC_CLIENT_ID = os.getenv("PHMS_OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("PHMS_OIDC_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = os.getenv("PHMS_OIDC_REDIRECT_URI", "")          # https://<host>/api/auth/sso/callback
OIDC_USER_CLAIM = os.getenv("PHMS_OIDC_USER_CLAIM", "preferred_username")   # claim khớp với username PHMS
OIDC_ENABLED = bool(OIDC_ISSUER and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI)
# Có SSO thì có thể tắt đăng nhập mật khẩu cho người dùng (trừ sysadmin để còn đường vào khi IdP hỏng)
PASSWORD_LOGIN_DISABLED = os.getenv("PHMS_PASSWORD_LOGIN_DISABLED", "0") == "1"
DATABASE_URL = os.getenv("PHMS_DB_URL", "sqlite:///./phms.db")
TOKEN_TTL_MIN = int(os.getenv("PHMS_TOKEN_TTL_MIN", "30"))
PBKDF2_ITER = int(os.getenv("PHMS_PBKDF2_ITER", "200000"))
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

DOC_STORAGE_DIR = os.getenv("PHMS_DOC_DIR", "./storage")
DOC_ENC_KEY = os.getenv("PHMS_DOC_KEY", SECRET_KEY)  # khóa mã hóa tài liệu (derive Fernet)
MAX_UPLOAD_MB = int(os.getenv("PHMS_MAX_UPLOAD_MB", "10"))

ALERT_ESCALATE_HOURS = int(os.getenv("PHMS_ALERT_ESCALATE_HOURS", "24"))
SCHEDULER_ENABLED = os.getenv("PHMS_SCHEDULER", "1") == "1"
SCHEDULER_INTERVAL_SEC = int(os.getenv("PHMS_SCHEDULER_INTERVAL", "900"))
FUTURE_TOLERANCE_MIN = 5
LATE_ENTRY_MIN = 15

NOTIFY_RETENTION_DAYS = int(os.getenv("PHMS_NOTIFY_RETENTION_DAYS", "90"))  # xóa thông báo đã đọc/đã ẩn quá hạn
NOTIFY_MAX_AGE_DAYS = int(os.getenv("PHMS_NOTIFY_MAX_AGE_DAYS", "365"))

BREAK_GLASS_MINUTES = int(os.getenv("PHMS_BREAK_GLASS_MINUTES", "30"))   # hạn của một lần truy cập khẩn cấp
MED_COURSE_REMIND_DAYS = int(os.getenv("PHMS_MED_COURSE_REMIND_DAYS", "3"))  # nhắc trước khi hết liệu trình

# Cơ sở không có dược sĩ: cho điều dưỡng cấp phát thuốc theo y lệnh (mặc định TẮT – cấp phát là việc của dược)
NURSE_CAN_DISPENSE = os.getenv("PHMS_NURSE_CAN_DISPENSE", "0") == "1"
