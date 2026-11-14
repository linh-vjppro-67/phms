# PHMS – Prisoner Health Management System (Core MVP)

Hiện thực hóa *Tài liệu phân tích nghiệp vụ & thiết kế giải pháp sơ bộ v1.0* (gói **Core, 12 phân hệ M01–M12**, 9 luồng WF-01…09).

- **Kiến trúc**: modular monolith (mục 9) – FastAPI + SQLAlchemy 2; SQLite cho dev/test, đổi `PHMS_DB_URL` sang PostgreSQL cho vận hành.
- **Giao diện**: React 18 + Vite tại `frontend/`; bản build (`frontend/dist`) được FastAPI phục vụ tại `/`.
- **Không dùng dịch vụ ngoài/cloud**: chạy hoàn toàn trong mạng nội bộ (giả định 1.4).

## Chạy nhanh
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m app.seed                       # tạo 2 cơ sở, tài khoản mẫu, danh mục
.venv/bin/uvicorn app.main:app --reload            # API http://localhost:8000  (docs: /docs)
.venv/bin/python -m pytest -q                      # 155 test (153 + 2 bỏ qua trên SQLite) (UAT, BR, bảo mật, luồng, MFA/SSO, sao lưu…)
PHMS_TEST_DB_URL=postgresql+psycopg://user@host/db .venv/bin/python -m pytest -q   # cùng bộ test trên PostgreSQL
```
Tài khoản mẫu (mật khẩu `Phms@2026dev`): `admin`; cơ sở F01: `officer1`, `nurse1`, `doctor1`, `pharm1`, `approver1`, `manager1`; cơ sở F02: `officer2`, `nurse2`, `doctor2`, `pharm2`, `approver2`, `manager2`.

Dữ liệu demo (hư cấu, ~44 hồ sơ ở 2 trại, đi qua đúng API nghiệp vụ nên mọi quy tắc đều được áp dụng):
Bộ gọn **10 người** (mỗi người một luồng): `.venv/bin/python -m app.demo_small --reset`. Bộ đầy đủ: `.venv/bin/python -m app.demo` (chạy sau `app.seed`; DB đã có hồ sơ thì từ chối; `--reset` để **xóa hết** và tạo lại). Kịch bản chi tiết ở [docs/03-kich-ban-du-lieu-demo.md](docs/03-kich-ban-du-lieu-demo.md); hướng dẫn test từng luồng cho QC/người dùng ở [docs/04-huong-dan-test-QC-va-nguoi-dung.md](docs/04-huong-dan-test-QC-va-nguoi-dung.md); kết quả rà soát luồng ở [docs/06-ra-soat-luong-nghiep-vu.md](docs/06-ra-soat-luong-nghiep-vu.md). CSDL cũ được **tự nâng cấp lược đồ** khi khởi động.

Giao diện:
```bash
cd frontend && npm install
npm run dev      # dev: http://localhost:5173 (proxy /api -> :8000)
npm run build    # build vào dist/ -> backend phục vụ tại http://localhost:8000/
npx playwright install chromium
BASE=http://localhost:8000 npm run e2e:flows   # 8 bài E2E (luồng nghiệp vụ + bảo mật/production; tự dựng dữ liệu; chạy trên CSDL chỉ có seed)
BASE=http://localhost:8000 npm run e2e:a11y    # accessibility WCAG 2.1 A/AA (axe-core) mọi tab × mọi vai trò, sáng/tối, bàn phím
BASE=… USERS=25 MINUTES=60 npm run e2e:soak    # chạy dài: theo dõi suy giảm hiệu năng, rò rỉ bộ nhớ, chuỗi nhật ký
BASE=http://localhost:8000 npm run e2e         # smoke 13 tài khoản + các bài trên dữ liệu demo MỚI (app.demo --reset)
BASE=http://localhost:8000 npm run e2e:responsive   # điện thoại / máy tính bảng
BROWSER=firefox BASE=… node e2e/flow-intake.mjs     # đa trình duyệt: chromium (mặc định) | firefox | webkit
BASE=… USERS=100 DURATION=30 npm run e2e:load      # kiểm thử tải (dùng CSDL thử, không dùng dữ liệu thật)
```

**Vận hành:** dev/demo dùng SQLite (WAL, ~100 người dùng đồng thời); **production dùng PostgreSQL 16** (`PHMS_DB_URL=postgresql+psycopg://…`, đã kiểm chứng toàn bộ test + E2E + sao lưu/phục hồi). Khi quá tải API trả 503 + `Retry-After`.

**Production:** đọc [docs/07-van-hanh-production.md](docs/07-van-hanh-production.md) (biến môi trường, PostgreSQL, TLS, MFA, SSO, sao lưu/phục hồi, checklist go-live) và mẫu triển khai ở `deploy/`. Với `PHMS_ENV=production` ứng dụng **từ chối khởi động** nếu `PHMS_SECRET`/`PHMS_DOC_KEY` còn mặc định, tắt `/docs`, luôn gửi HSTS. **Tài khoản mẫu và mật khẩu `Phms@2026dev` chỉ để dev/demo – phải khóa/đổi trước khi dùng dữ liệu thật** (mục 5 của tài liệu 07). Sao lưu: `python -m app.backup create|verify|restore|prune`. Hoàn tất rà soát pháp lý/ATTT (mục 10.2) trước khi dùng dữ liệu thật.

## Cấu trúc
```
backend/app/
  models.py          Entity theo mục 7 (Person, CustodyStay, HealthRecord, Encounter, MedicationOrder, ...)
  permissions.py     RBAC vai trò→quyền        deps.py  ABAC theo cơ sở + break-glass
  audit.py           AuditEvent append-only + hash chain    idempotency.py  chống lưu lặp (BR-06)
  modules/           identity · clinical · medication · referral · scheduling · emergency · documents · reports · admin
backend/tests/       Bộ test QC (UAT-01…12, BR-01…07, bảo mật, workflow)
frontend/index.html  Giao diện theo vai trò
docs/                01-BA-truy-vet-yeu-cau.md · 02-QC-bao-cao-kiem-thu.md
```

## Biến môi trường chính
| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `PHMS_DB_URL` | `sqlite:///./phms.db` | chuỗi kết nối DB |
| `PHMS_SECRET` | khóa dev | ký JWT – **bắt buộc đổi** |
| `PHMS_DOC_KEY` / `PHMS_DOC_DIR` | = SECRET / `./storage` | khóa & thư mục lưu tài liệu mã hóa |
| `PHMS_TOKEN_TTL_MIN` | 30 | hạn phiên |
| `PHMS_SCHEDULER` / `_INTERVAL` | 1 / 900s | job sinh nhắc việc, cảnh báo quá hạn, nâng mức |
| `PHMS_ALERT_ESCALATE_HOURS` | 24 | sau bao lâu cảnh báo chưa xử lý được nâng mức |
| `PHMS_ENV` | `dev` | `production`: kiểm tra cấu hình an toàn, tắt `/docs`, HSTS |
| `PHMS_MFA_REQUIRED_ROLES` | (rỗng) | vai trò bắt buộc MFA, vd `sysadmin,approver` |
| `PHMS_OIDC_*`, `PHMS_PASSWORD_LOGIN_DISABLED` | (tắt) | SSO OIDC – xem docs/07 |
| `PHMS_NURSE_CAN_DISPENSE` | 0 | cho điều dưỡng cấp phát thuốc (cơ sở không có dược sĩ) |
| `PHMS_DB_POOL` / `PHMS_DB_OVERFLOW` | 10 / 10 | cỡ pool PostgreSQL mỗi worker |
| `PHMS_TEST_DB_URL` | (SQLite bộ nhớ) | chạy pytest trên CSDL khác (PostgreSQL) |

## Các tab giao diện (mỗi tab = một phân hệ/luồng nghiệp vụ, hiển thị theo quyền)
| Nhóm | Tab | Nội dung chính |
|---|---|---|
| Tổng quan | Bảng điều khiển | KPI & việc cần làm theo vai trò, bấm để nhảy tới tab xử lý |
| Tiếp nhận | **Tiếp nhận & Hồ sơ (M01)** | Wizard tiếp nhận 3 bước (kiểm tra trùng → hồ sơ → đợt tiếp nhận), đối soát danh tính, hủy liên kết nhầm |
| | **Chuyển trại & Bàn giao (WF-07)** | Khởi tạo → tóm tắt y tế → xác nhận; cảnh báo điều trị đang mở |
| Khám chữa bệnh | **Khám ban đầu (M03)** | Danh sách chờ khám + wizard 6 bước (dị ứng → sinh hiệu → chẩn đoán → chỉ định/kê đơn → kế hoạch → hoàn tất) |
| | **Khám chữa bệnh (M04)** | Danh sách lượt khám + bàn làm việc (sinh hiệu, chẩn đoán, chỉ định, đơn thuốc, theo dõi, chuyển viện, tài liệu, addendum) |
| | **Cấp cứu (WF-08)** | Ghi nhận tối thiểu, hồ sơ tạm, diễn biến can thiệp, đối soát, đóng sự kiện |
| Thuốc | **Chỉ định & Kê đơn (M05)** | Đơn chờ xác nhận (cảnh báo dị ứng/trùng thuốc), điều chỉnh có phiên bản, dừng thuốc, chờ kết quả XN |
| | **Cấp phát thuốc (M06)** | Hàng đợi cấp phát, cấp đủ/một phần, hoàn trả/hủy, xác nhận sử dụng thuốc |
| Theo dõi | **Khám định kỳ (M07)** | Tạo đợt → sinh danh sách (loại trừ) → thực hiện → khóa đợt, tiến độ |
| | **Bệnh lý & Cảnh báo (M08)** | Hộp thư cảnh báo, lịch quá hạn, kế hoạch theo dõi, vấn đề sức khỏe |
| | **Chuyển viện (M09)** | Bảng theo trạng thái, phê duyệt/điều phối, đi tắt cấp cứu + hậu kiểm, kết quả sau viện |
| Hồ sơ | **Hồ sơ sức khỏe (M02)** | Tổng quan, dị ứng, vấn đề, thuốc, lịch sử khám, đợt tiếp nhận |
| | **Tài liệu y tế (M12)** | Tải lên, phiên bản, thay thế, đánh dấu không hợp lệ, tải xuống có audit |
| Quản lý | **Báo cáo (M10)** | 6 báo cáo dạng thẻ/bảng, xuất CSV có mục đích |
| | **Quản trị (M11)** | Người dùng (tạo, đổi vai trò, khóa, **đặt lại mật khẩu/MFA**), ma trận phân quyền, danh mục, nhật ký kiểm toán, tác vụ nền |

Bấm tên người dùng ở góc trên phải để mở **Tài khoản của tôi** (đổi mật khẩu, bật/tắt xác thực 2 lớp).

Giao diện **sáng mặc định** (không phụ thuộc chế độ tối của hệ điều hành); nút ☾/☀ ở thanh trên để đổi sáng/tối, lựa chọn được nhớ theo trình duyệt. Người đang xử lý được chọn một lần ở thanh trên cùng và dùng chung giữa các tab. **Chuông thông báo** (góc trên phải) báo việc cần xử lý theo vai trò – xem [docs/05-he-thong-thong-bao.md](docs/05-he-thong-thong-bao.md). CSDL cũ: `python -m app.notify_backfill`.
