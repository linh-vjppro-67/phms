"""PHMS – ứng dụng lõi (modular monolith, mục 9 tài liệu thiết kế)."""
import asyncio
import contextlib
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .db import Base, SessionLocal, engine
from .migrate import ensure_schema
from .modules import admin, clinical, documents, emergency, identity, medication, referral, merge, notifications, reports, scheduling, sso, worklists

log = logging.getLogger("phms")
FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")  # npm run build


async def _scheduler_loop():
    while True:
        await asyncio.sleep(config.SCHEDULER_INTERVAL_SEC)
        try:
            with SessionLocal() as db:
                log.info("scheduler: %s", scheduling.run_scheduler(db))
        except Exception:  # noqa: BLE001
            log.exception("scheduler failed")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema(engine)
    _check_no_sample_accounts()
    task = asyncio.create_task(_scheduler_loop()) if config.SCHEDULER_ENABLED else None
    yield
    if task:
        task.cancel()


def _check_production_config():
    """Production: từ chối khởi động với cấu hình không an toàn (secret mặc định, khóa tài liệu mặc định)."""
    if not config.IS_PROD:
        return
    problems = []
    if config.SECRET_KEY == config.DEV_SECRET or len(config.SECRET_KEY) < 32:
        problems.append("PHMS_SECRET phải được đặt riêng, tối thiểu 32 ký tự")
    if config.DOC_ENC_KEY in (config.DEV_SECRET, config.SECRET_KEY):
        problems.append("PHMS_DOC_KEY phải được đặt riêng và khác PHMS_SECRET (tách khóa ký phiên khỏi khóa mã hóa tài liệu)")
    if config.PBKDF2_ITER < 100_000:
        problems.append("PHMS_PBKDF2_ITER quá thấp")
    if config.DATABASE_URL.startswith("sqlite") and os.getenv("PHMS_ALLOW_SQLITE") != "1":
        problems.append("production phải dùng PostgreSQL (PHMS_DB_URL=postgresql+psycopg://…): SQLite không an toàn khi chạy nhiều worker/nhiều máy. "
                        "Chỉ điểm triển khai nhỏ, MỘT worker, mới được đặt PHMS_ALLOW_SQLITE=1")
    if config.DOC_ENC_KEY == config.DEV_SECRET:
        problems.append("PHMS_DOC_KEY không được dùng khóa mặc định")
    if problems:
        raise RuntimeError("Cấu hình production không an toàn: " + "; ".join(problems))


def _check_no_sample_accounts():
    """Production: từ chối chạy nếu còn tài khoản mẫu với mật khẩu mặc định đã công khai (dùng `python -m app.bootstrap` thay vì seed).
    Môi trường đào tạo/thử nghiệm có chủ đích mới được đặt PHMS_ALLOW_SAMPLE_ACCOUNTS=1."""
    if not config.IS_PROD or os.getenv("PHMS_ALLOW_SAMPLE_ACCOUNTS") == "1":
        return
    from sqlalchemy import select
    from .models import User
    from .security import verify_password
    from .seed import DEFAULT_PASSWORD, USERS
    names = {u[0] for u in USERS}
    with SessionLocal() as db:
        bad = [u.username for u in db.scalars(select(User).where(User.username.in_(names)))
               if verify_password(DEFAULT_PASSWORD, u.password_hash)]
    if bad:
        raise RuntimeError("Cấu hình production không an toàn: còn tài khoản mẫu dùng mật khẩu mặc định công khai (" + ", ".join(sorted(bad)) +
                           "). Đặt lại mật khẩu hoặc vô hiệu hóa các tài khoản này; khởi tạo hệ thống mới bằng `python -m app.bootstrap`.")


_check_production_config()
# Production: tắt tài liệu API tương tác (/docs, /redoc, /openapi.json)
app = FastAPI(title="PHMS – Prisoner Health Management System", version="1.0.0", lifespan=lifespan,
              docs_url=None if config.IS_PROD else "/docs", redoc_url=None if config.IS_PROD else "/redoc",
              openapi_url=None if config.IS_PROD else "/openapi.json")

for mod in (notifications, worklists, sso, merge, admin, identity, clinical, medication, referral, scheduling, emergency, documents, reports):
    app.include_router(mod.router, prefix="/api")


@app.exception_handler(StarletteHTTPException)
async def http_exc(_: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)}
    return JSONResponse({"error": detail}, status_code=exc.status_code)


def _vi_msg(e: dict) -> str:
    """Việt hóa thông báo kiểm tra dữ liệu của pydantic để người dùng cuối hiểu được."""
    t, ctx = e.get("type", ""), e.get("ctx") or {}
    if t == "string_too_short":
        return f"cần tối thiểu {ctx.get('min_length')} ký tự"
    if t == "string_too_long":
        return f"tối đa {ctx.get('max_length')} ký tự"
    if t == "missing":
        return "bắt buộc nhập"
    if t in ("greater_than", "greater_than_equal"):
        return f"phải lớn hơn{' hoặc bằng' if t.endswith('equal') else ''} {ctx.get('gt', ctx.get('ge'))}"
    if t in ("less_than", "less_than_equal"):
        return f"phải nhỏ hơn{' hoặc bằng' if t.endswith('equal') else ''} {ctx.get('lt', ctx.get('le'))}"
    if t == "string_pattern_mismatch":
        return "giá trị không hợp lệ"
    if t.startswith(("int_", "float_")):
        return "phải là số"
    if t.startswith(("date", "datetime")):
        return "ngày/giờ không hợp lệ"
    if t == "value_error":
        return str(e.get("msg", "")).replace("Value error, ", "")
    return e.get("msg", "không hợp lệ")


@app.exception_handler(RequestValidationError)
async def validation_exc(_: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": _vi_msg(e)} for e in exc.errors()]
    return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "Dữ liệu không hợp lệ", "errors": errs}},
                        status_code=422)


@app.exception_handler(IntegrityError)
async def integrity_conflict(_: Request, exc: IntegrityError):
    """Hai người cùng tạo một dữ liệu duy nhất (cùng mã, cùng đợt…): trả 409 dễ hiểu thay vì lỗi 500; dữ liệu không bị nhân đôi nhờ ràng buộc CSDL."""
    log.warning("integrity conflict: %s", str(exc.orig)[:160])
    return JSONResponse({"error": {"code": "CONFLICT", "message": "Dữ liệu này vừa được người khác tạo hoặc thay đổi – hãy tải lại rồi thử lại"}}, status_code=409)


@app.exception_handler(SATimeoutError)
async def pool_timeout(_: Request, exc: SATimeoutError):
    return JSONResponse({"error": {"code": "BUSY", "message": "Hệ thống đang quá tải, vui lòng thử lại sau ít giây"}},
                        status_code=503, headers={"Retry-After": "3"})


@app.exception_handler(OperationalError)
async def db_busy(_: Request, exc: OperationalError):
    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
        return JSONResponse({"error": {"code": "BUSY", "message": "Cơ sở dữ liệu đang bận, vui lòng thử lại sau ít giây"}},
                            status_code=503, headers={"Retry-After": "3"})
    raise exc


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cache-Control", "no-store")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if not request.url.path.startswith(("/docs", "/redoc")):     # trang Swagger (chỉ dev) cần tải tài nguyên ngoài
        resp.headers.setdefault("Content-Security-Policy", CSP)
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    if https or config.IS_PROD:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


@app.get("/api/health", tags=["ops"])
def health():
    return {"status": "ok"}


@app.get("/api/health/ready", tags=["ops"])
def ready():
    """Sẵn sàng phục vụ: kiểm tra kết nối CSDL (dùng cho load balancer/giám sát). Không lộ chi tiết lỗi."""
    from sqlalchemy import text
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        log.exception("readiness check failed")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ready"}


if os.path.isdir(FRONTEND):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(FRONTEND, "index.html"))
