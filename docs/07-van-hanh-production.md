# 07 – Triển khai & vận hành production

> Tài liệu cho người vận hành hệ thống. Tài khoản mẫu và mật khẩu mặc định (`Phms@2026dev`) **chỉ dành cho dev/demo** – xem mục 5 trước khi đưa vào sử dụng thật.

## 1. Mô hình triển khai khuyến nghị

```
Trình duyệt ──HTTPS──▶ Reverse proxy (nginx/Traefik: TLS, HSTS, giới hạn tốc độ)
                          └──HTTP──▶ PHMS (uvicorn, N worker)  ──▶ PostgreSQL 16
                                          └── thư mục tài liệu (mã hóa Fernet) ──▶ ổ đĩa riêng, được sao lưu
                       Bộ lập lịch (1 tiến trình riêng)  ──▶ cùng PostgreSQL
```

* Một gói duy nhất: backend FastAPI phục vụ luôn giao diện React đã build (`frontend/dist`).
* **PostgreSQL là cấu hình production**; SQLite chỉ dùng dev/demo/một máy nhỏ.
* Không để PHMS lộ trực tiếp ra Internet: luôn đặt sau reverse proxy có TLS.

## 2. Biến môi trường

| Biến | Bắt buộc | Mô tả |
|---|---|---|
| `PHMS_ENV=production` | ✔ | Bật chế độ production: **từ chối khởi động nếu secret yếu, nếu dùng SQLite (trừ `PHMS_ALLOW_SQLITE=1`), hoặc nếu còn tài khoản mẫu dùng mật khẩu mặc định**, tắt `/docs` `/redoc` `/openapi.json`, luôn gửi HSTS |
| `PHMS_SECRET` | ✔ | Khóa ký phiên (JWT) và mã hóa bí mật MFA. ≥ 32 ký tự ngẫu nhiên. **Đổi khóa = mọi phiên bị đăng xuất và mọi MFA phải đăng ký lại** |
| `PHMS_DOC_KEY` | ✔ | Khóa mã hóa tài liệu y tế. **Mất khóa = không đọc được tài liệu.** Giữ bản sao ở nơi an toàn, tách khỏi gói sao lưu |
| `PHMS_DB_URL` | ✔ | `postgresql+psycopg://user:pass@host:5432/phms` |
| `PHMS_DOC_DIR` | ✔ | Thư mục lưu tài liệu (mặc định `./storage`) – đặt trên ổ bền vững, có sao lưu |
| `PHMS_DB_POOL`, `PHMS_DB_OVERFLOW` | | Cỡ pool **mỗi worker** (mặc định 10 + 10). Điều kiện: (pool + overflow) × số worker < `max_connections` của PostgreSQL |
| `PHMS_TOKEN_TTL_MIN` | | Thời hạn phiên (mặc định 30 phút) |
| `PHMS_MFA_REQUIRED_ROLES` | | Vai trò bắt buộc MFA, ví dụ `sysadmin,approver,manager,doctor`. Người thuộc vai trò này phải đăng ký MFA ngay sau lần đăng nhập kế tiếp. **Khuyến nghị tối thiểu: `sysadmin`** |
| `PHMS_MFA_ISSUER` | | Tên hiện trong ứng dụng xác thực (mặc định `PHMS`) |
| `PHMS_OIDC_ISSUER`, `PHMS_OIDC_CLIENT_ID`, `PHMS_OIDC_CLIENT_SECRET`, `PHMS_OIDC_REDIRECT_URI` | | Bật SSO OIDC (mục 7). `REDIRECT_URI` = `https://<host>/api/auth/sso/callback` |
| `PHMS_OIDC_USER_CLAIM` | | Claim khớp với tên đăng nhập PHMS (mặc định `preferred_username`) |
| `PHMS_PASSWORD_LOGIN_DISABLED=1` | | Chỉ cho đăng nhập SSO (trừ `sysadmin`, để còn đường vào khi IdP hỏng) |
| `PHMS_SCHEDULER=0` | | Tắt bộ lập lịch trong worker web (khuyến nghị khi chạy nhiều worker – xem mục 4) |
| `PHMS_NURSE_CAN_DISPENSE=1` | | Cơ sở **không có dược sĩ**: cho điều dưỡng cấp phát thuốc theo y lệnh (mặc định tắt – cấp phát là việc của dược) |
| `PHMS_BOOTSTRAP_ADMIN_PASSWORD` | | Mật khẩu quản trị đầu tiên cho `python -m app.bootstrap` (bỏ trống = tự sinh, in một lần). **Xóa khỏi môi trường sau khi cài xong** |
| `PHMS_ALLOW_SQLITE=1` | | **Ngoại lệ**: cho production chạy SQLite. Chỉ điểm triển khai nhỏ, **một** worker, một máy – khóa chống tranh chấp (`lock_row`) chỉ có hiệu lực trong một tiến trình |
| `PHMS_ALLOW_SAMPLE_ACCOUNTS=1` | | **Ngoại lệ** cho môi trường đào tạo/thử nghiệm có chủ đích: cho phép còn tài khoản mẫu với mật khẩu công khai. **Không dùng với dữ liệu thật** |
| `PHMS_PBKDF2_ITER` | | Số vòng băm mật khẩu (mặc định 200.000; không đặt thấp hơn 100.000 ở production) |

Mẫu đầy đủ: [`deploy/phms.env.example`](../deploy/phms.env.example).

## 3. PostgreSQL

```sql
CREATE ROLE phms LOGIN PASSWORD '…';
CREATE DATABASE phms OWNER phms ENCODING 'UTF8';
```
* Lần khởi động đầu, ứng dụng tự tạo bảng (`ensure_schema`) dưới **khóa tư vấn** nên nhiều worker khởi động cùng lúc vẫn an toàn.
* Khởi tạo hệ thống **thật** (cơ sở + quản trị viên đầu tiên + danh mục, **không** có tài khoản mẫu): `python -m app.bootstrap --facility F01="Trại giam số 1" --facility F02="Trại giam số 2"` (xem mục 5). `python -m app.seed` chỉ dành cho dev/demo và **tự từ chối chạy ở production**.
* Danh mục ICD-10 thường gặp ở Việt Nam (217 mã, tên tiếng Việt) và **292 thuốc thiết yếu** (19 nhóm điều trị, kèm hàm lượng/dạng/đường dùng; mã là mã *nội bộ PHMS*, không phải mã thuốc BHYT của Bộ Y tế – dược sĩ/hội đồng thuốc cần rà soát) có sẵn trong seed; nạp thêm vào CSDL đang chạy bằng `python -m app.catalog_import` (idempotent, chỉ thêm mã còn thiếu, **không** tạo tài khoản). Đây là bộ khởi đầu để chọn nhanh, **không thay thế** bộ ICD-10 đầy đủ của Bộ Y tế – nạp bộ đầy đủ ở Quản trị → Danh mục khi khách cung cấp.
* Sao lưu bằng `python -m app.backup` (mục 8), không chỉ `pg_dump` thủ công, vì cần kèm tệp tài liệu.

## 4. Chạy ứng dụng

```bash
# web: nhiều worker, KHÔNG chạy lập lịch
PHMS_ENV=production PHMS_SCHEDULER=0 uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    --workers 4 --proxy-headers --forwarded-allow-ips 127.0.0.1
# lập lịch: đúng MỘT tiến trình (systemd service hoặc container riêng)
PHMS_ENV=production python -m app.scheduler_cli --loop
```
Reverse proxy mẫu (TLS, HSTS, giới hạn đăng nhập): [`deploy/nginx.conf`](../deploy/nginx.conf). Proxy **phải** gửi `X-Forwarded-Proto` và `X-Forwarded-For` (ứng dụng dùng để nhận biết HTTPS và ghi IP vào nhật ký).

## 5. Tài khoản & mật khẩu – CÀI MỚI CHO KHÁCH

**Môi trường dev/demo:** tài khoản mẫu (admin, officer1…manager2; mật khẩu `Phms@2026dev`) giữ nguyên, không bị ép đổi mật khẩu, để test/QC không gián đoạn.

**Production – quy trình cài mới (không dùng tài khoản mẫu):**

1. Chuẩn bị `deploy/phms.env` từ [`phms.env.example`](../deploy/phms.env.example): `PHMS_ENV=production`, `PHMS_SECRET`, `PHMS_DOC_KEY` (hai khóa **khác nhau**), `PHMS_DB_URL` (PostgreSQL), `PHMS_MFA_REQUIRED_ROLES=sysadmin` (nên thêm `approver,manager`). Ứng dụng **từ chối khởi động** nếu thiếu/yếu.
2. Khởi tạo: `docker compose -f deploy/docker-compose.yml --env-file deploy/phms.env run --rm bootstrap --facility F01="Tên cơ sở 1" [--facility F02="Tên cơ sở 2"]` (hoặc `python -m app.bootstrap …`). Lệnh tạo cơ sở, danh mục và **một** quản trị viên `admin` (bắt buộc đổi mật khẩu + đăng ký MFA ở lần đầu). Chạy lại nhiều lần an toàn, không ghi đè.
3. Đăng nhập `admin` → đổi mật khẩu → đăng ký MFA → ở *Quản trị → Người dùng* tạo tài khoản thật (cán bộ tiếp nhận, điều dưỡng, bác sĩ, dược, người điều phối, quản lý; người mới bị buộc đổi mật khẩu lần đầu). Tạo **ít nhất 2 quản trị viên**.
4. Nếu môi trường production cũ còn tài khoản mẫu (vd. đã chạy `app.seed` trước đây): ứng dụng sẽ **từ chối khởi động** và nêu tên các tài khoản đó. Đặt lại mật khẩu hoặc vô hiệu hóa chúng (bằng công cụ quản trị CSDL hoặc tạm đặt `PHMS_ALLOW_SAMPLE_ACCOUNTS=1` để đăng nhập `admin` xử lý rồi bỏ biến này).
5. Quên mật khẩu: quản trị dùng nút **Đặt lại mật khẩu** (mật khẩu tạm hiện một lần, người dùng bị buộc đổi ở lần đăng nhập kế tiếp, mọi phiên cũ bị thu hồi). Mất thiết bị MFA: **Đặt lại MFA** (chỉ sau khi xác minh đúng người). Mọi thao tác đều ghi nhật ký.
6. Chính sách mật khẩu: ≥ 10 ký tự, có chữ hoa/thường/số, khác mật khẩu cũ; khóa 15 phút sau 5 lần sai (kể cả sai OTP) và báo cho quản trị.

Đăng nhập hiện dùng **tài khoản + mật khẩu (+ MFA)**. SSO là tùy chọn, bật sau (mục 7), không cần cho lần go-live đầu.

## 6. MFA (TOTP, RFC 6238)

* Người dùng tự bật ở *Tài khoản của tôi → Xác thực 2 lớp* (quét QR hoặc nhập khóa), dùng được mọi ứng dụng TOTP.
* Mỗi mã chỉ dùng một lần (chống phát lại); chấp nhận lệch ±30 giây.
* Bí mật MFA được **mã hóa** (Fernet, dẫn xuất từ `PHMS_SECRET`) khi lưu CSDL.
* Vai trò bắt buộc MFA không tự tắt được. Chưa có mã khôi phục dùng một lần: quy trình khôi phục là quản trị **Đặt lại MFA**.

## 7. SSO (OpenID Connect)

1. Đăng ký ứng dụng ở IdP (Keycloak, Azure AD, Okta…) với redirect URI `https://<host>/api/auth/sso/callback`, luồng *authorization code* (+PKCE), scope `openid profile email`.
2. Đặt 4 biến `PHMS_OIDC_*`. Màn hình đăng nhập tự hiện nút **Đăng nhập bằng SSO**.
3. PHMS **không tự tạo tài khoản**: danh tính từ IdP (claim `PHMS_OIDC_USER_CLAIM`) phải khớp một tài khoản PHMS đang hoạt động; vai trò/cơ sở/quyền vẫn do PHMS quản lý. Không khớp → từ chối và ghi nhật ký `sso_failed`.
4. `id_token` được kiểm chữ ký (JWKS), `iss`, `aud`, hạn dùng, `nonce`; `state` ràng buộc qua cookie `HttpOnly`.
5. MFA của người dùng SSO do IdP đảm nhiệm. Muốn bắt buộc SSO: `PHMS_PASSWORD_LOGIN_DISABLED=1` (vẫn giữ `sysadmin` đăng nhập bằng mật khẩu + MFA làm đường dự phòng).

> **Trạng thái kiểm chứng:** luồng SSO được kiểm tra bằng IdP giả lập (đúng/sai `state`, `nonce`, chữ ký, `aud`, tài khoản lạ). **Chưa kiểm chứng với IdP thật của khách hàng** – cần thử tích hợp khi có IdP.

## 8. Sao lưu & phục hồi

```bash
python -m app.backup create  --out /var/backups/phms          # CSDL + tài liệu + bản kê SHA-256 (gói .tar.gz, quyền 0600)
python -m app.backup verify  /var/backups/phms/phms-backup-….tar.gz --check-docs
python -m app.backup restore /var/backups/phms/phms-backup-….tar.gz --db-url postgresql+psycopg://…/phms_restore --storage-dir /srv/phms/storage_restore
python -m app.backup prune   --out /var/backups/phms --keep 30
```
* SQLite: sao lưu trực tuyến nhất quán (không cần dừng). PostgreSQL: `pg_dump -Fc` (cần `pg_dump`/`pg_restore`; đặt `PHMS_PG_BIN` nếu không có trong PATH).
* `restore` từ chối nếu gói hỏng; từ chối ghi đè nếu đích không trống (cần `--force`); **sau phục hồi tự kiểm** chuỗi băm nhật ký, giải mã & đối chiếu checksum từng tài liệu, so số liệu với bản kê.
* Khóa `PHMS_DOC_KEY`/`PHMS_SECRET` **không nằm trong gói** – lưu riêng (kho bí mật). Gói chứa dữ liệu y tế: lưu ở nơi mã hóa, phân quyền chặt, **sao chép ra ngoài máy chủ** (3-2-1).
* Lịch gợi ý: hằng ngày + `prune --keep 30`; **diễn tập phục hồi hằng quý** sang CSDL thử rồi chạy `verify --check-docs`. Mẫu cron: [`deploy/backup-cron.example`](../deploy/backup-cron.example).

## 9. Giám sát

* `GET /api/health` (liveness, không chạm CSDL) và `GET /api/health/ready` (readiness, kiểm tra kết nối CSDL; 503 nếu không) – dùng cho load balancer/Docker healthcheck. Khi quá tải ứng dụng trả **503 + `Retry-After`** thay vì lỗi 500.
* `GET /api/audit/verify` (quyền quản trị) – nên gọi định kỳ (cron) và **cảnh báo nếu `ok:false`**: chuỗi nhật ký bị sửa/đứt.
* Nhật ký ứng dụng ra stdout (`uvicorn`, logger `phms`, `phms.scheduler`) – thu thập bằng hệ thống log của bạn.
* Thông báo bảo mật trong ứng dụng (khóa tài khoản, break-glass) tới người có quyền `audit.read`.

## 10. Nâng cấp & hoàn tác

1. `python -m app.backup create` (và kiểm `verify`).
2. Triển khai bản mới. Khi khởi động, `ensure_schema` **thêm bảng/cột nullable còn thiếu**, không xóa/đổi kiểu cột. Thay đổi cột bắt buộc/xóa cột sẽ báo lỗi và cần migration thủ công (chưa dùng Alembic).
3. Hoàn tác: triển khai lại bản cũ; nếu cần, `restore` gói ở bước 1 vào CSDL mới.

## 11. Danh sách kiểm tra bảo mật

- [ ] `PHMS_ENV=production`, secret/khóa riêng, ứng dụng khởi động được
- [ ] TLS hợp lệ ở proxy; `curl -I https://…` thấy `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options: DENY`
- [ ] `/docs` trả 404
- [ ] Khởi tạo bằng `app.bootstrap` (không có tài khoản mẫu); có ít nhất 2 quản trị viên (một dự phòng) và MFA bật cho họ
- [ ] `PHMS_DB_URL` là PostgreSQL; `PHMS_ALLOW_SQLITE` và `PHMS_ALLOW_SAMPLE_ACCOUNTS` **không** được đặt
- [ ] `/api/health/ready` trả `{"status":"ready"}`; đã thử đăng nhập tài khoản mẫu cũ (phải bị từ chối)
- [ ] PostgreSQL chỉ nghe mạng nội bộ; tài khoản DB quyền tối thiểu; sao lưu chạy và đã diễn tập phục hồi
- [ ] Giới hạn tốc độ `/api/auth/login` ở proxy (mẫu có sẵn) – ứng dụng đã khóa tài khoản sau 5 lần sai nhưng không chặn theo IP
- [ ] Cron gọi `/api/audit/verify` và cảnh báo khi lỗi

## 12. Giới hạn đã biết

* Chưa có mã khôi phục MFA dùng một lần; chưa có cảnh báo đăng nhập từ thiết bị lạ.
* Chưa chặn tốc độ theo IP trong ứng dụng (làm ở proxy).
* Nhật ký hash-chain *phát hiện* sửa đổi, không *ngăn* người có quyền ghi CSDL – cần phân quyền DB chặt và sao chép nhật ký ra hệ thống ngoài (SIEM) nếu yêu cầu cao hơn.
* Chưa có Alembic.
* Đã kiểm chứng chế độ production trên **PostgreSQL 16 thật** (153 test, 4 worker uvicorn, bootstrap, từ chối cấu hình không an toàn). **Chưa build được image Docker** (Docker daemon không chạy khi kiểm thử; `docker compose config` hợp lệ) – hãy `docker compose build` thử trước khi giao khách.
* SSO chưa thử với IdP thật (mục 7). Chưa kiểm chứng TLS/nginx thật (`nginx -t` tại máy chủ đích).
