# 02 – QC: Kế hoạch & báo cáo kiểm thử

**Backend API** (pytest, SQLite in-memory, mỗi test DB mới): **114/114 đạt (SQLite và PostgreSQL 16)** (`python -m pytest -q`, ~7s) – gồm UAT-01…12, BR-01…07, bảo mật, luồng, thông báo, rà soát luồng, đồng thời nhật ký, hồi quy QC đợt 2.

**Giao diện React** (Playwright/Chromium, `frontend/e2e`) – thao tác thật trên trình duyệt, nhiều vai trò cùng lúc:

*Bộ 1 – luồng nghiệp vụ đầy đủ* (`npm run e2e:flows`; **tự dựng dữ liệu qua API**, chạy được trên CSDL chỉ có dữ liệu seed): **84 bước, tất cả đạt**
| Bài | Phân hệ / luồng | Bước | Nội dung chính |
|---|---|---|---|
| `flow-intake` | M01 · WF-01 | 11 | wizard tiếp nhận, trùng mã, trùng tên+ngày sinh, thiếu mã, đối soát, người ở trại khác, tái tiếp nhận, hủy liên kết, quyền cán bộ |
| `flow-clinical` | M04 · M05 · M06 | 18 | bàn làm việc, sinh hiệu, chẩn đoán, chỉ định → hoàn tất, addendum, hủy (có kéo theo), xung đột phiên bản 2 người; cảnh báo dị ứng/trùng thuốc, điều chỉnh v2, dừng đơn; cấp một phần/đủ, hoàn trả, ghi nhận sử dụng |
| `flow-followup` | M07 · M08 | 12 | tạo đợt, loại trừ, khám, hoãn, không thực hiện, tránh trùng lịch, khóa đợt; cảnh báo tiếp nhận/xử lý, lịch quá hạn, kế hoạch, vấn đề sức khỏe, tác vụ nền |
| `flow-referral` | M09 · WF-06 | 11 | 3 vai trò (bác sĩ → người phê duyệt → điều dưỡng): dự thảo → duyệt → rời trại → tài liệu → kết quả → hoàn thành; BV từ chối; đi tắt cấp cứu + hậu kiểm; kết cục tử vong; hủy; phân quyền |
| `flow-emergency` | WF-08 | 9 | ghi nhận tối thiểu (chưa rõ danh tính), thông báo, can thiệp, đóng sự kiện bị chặn, bổ sung hồ sơ, đối soát, đóng + lịch theo dõi, ghi muộn, người chưa có kỳ |
| `flow-handover` | WF-07 | 7 | 2 cơ sở: khởi tạo → tóm tắt → xác nhận (ack) → cơ sở nhận tiếp nhận (biên nhận); kết thúc quản lý; hồ sơ sức khỏe đi cùng người |
| `flow-docs-admin` | M12 · M10 · M11 | 16 | tải lên/tải xuống đúng nội dung, tệp độc hại/quá cỡ, thay thế, không hợp lệ; số liệu báo cáo (lượt ≠ người), xuất CSV; tạo/khóa người dùng, đổi vai trò, ma trận quyền, danh mục có phiên bản, nhật ký + toàn vẹn chuỗi, khóa tài khoản |

*Bộ 2 – dữ liệu demo* (`npm run e2e`): `smoke` (13 tài khoản mở mọi tab được phép, không lỗi), `flow` (wizard khám ban đầu), `followup` (tái khám theo kế hoạch), `notify` (thông báo), `alignment` (break-glass, thông tin lâm sàng, biên nhận) – **đều đạt**.

*Bộ 3 – đáp ứng, đa trình duyệt, tải* (đều **đạt**):
| Bài | Phạm vi | Kết quả |
|---|---|---|
| `responsive` (`npm run e2e:responsive`) | điện thoại 390×844 và máy tính bảng 820×1180, 3 vai trò: mọi tab không tràn ngang, menu thu gọn mở/đóng (nút, Esc, bấm ra ngoài), bảng thông báo/hộp thoại/ngăn kéo nằm trọn màn hình | 12 bước đạt |
| Đa trình duyệt (`BROWSER=firefox\|webkit`) | Chromium, **Firefox**, **WebKit (Safari)**: tiếp nhận, khám/kê đơn/cấp phát, cấp cứu, tài liệu & quản trị (tải tệp, ô ngày giờ) | đạt cả 3 trình duyệt |
| `load` (`npm run e2e:load`) | người dùng ảo đồng thời (cán bộ tiếp nhận, bác sĩ, điều dưỡng, dược, quản lý, quản trị) thao tác nghiệp vụ thật; kiểm tra lỗi, độ trễ, chuỗi nhật ký | xem bảng dưới |

**Kết quả tải** (SQLite một tệp, máy phát triển, scheduler tắt):
| Người dùng đồng thời | Yêu cầu | Thông lượng | p50 / p95 / p99 | Lỗi | Chuỗi nhật ký |
|---|---|---|---|---|---|
| 30 | ~10.000 / 30s | ~340 req/s | 30 / 198 / 778 ms | 0 | toàn vẹn (16.392 bản ghi) |
| 100 | ~9.500 / 30s | ~310 req/s | 218 / 678 / 1.807 ms | 0 | toàn vẹn (21.355 bản ghi) |

Đạt NFR-01 (p95 ≤ 3s). **Giới hạn**: SQLite chỉ ghi tuần tự nên thông lượng ghi bị chặn trên (~300 req/s); tải thật nhiều cơ sở nên dùng **PostgreSQL** (đã hỗ trợ qua `PHMS_DB_URL`, chưa thử với PostgreSQL thật). Chưa kiểm thử: tải kéo dài nhiều giờ, tải tệp lớn đồng thời, phục hồi sau sự cố/sao lưu.

## Lỗi tìm thấy khi chạy E2E đầy đủ (đã sửa)
| # | Lỗi | Hậu quả | Đã sửa |
|---|---|---|---|
| 1 | **Chuỗi băm nhật ký kiểm toán bị đứt khi nhiều người thao tác đồng thời** (hai yêu cầu cùng nối vào một bản ghi cha) | Chức năng phát hiện sửa đổi báo sai “PHÁT HIỆN SỬA ĐỔI” | Khóa tuần tự hóa việc nối chuỗi (`audit_head`); test 8 luồng song song; công cụ `app.audit_repair` nối lại chuỗi cũ |
| 2 | **Trang Báo cáo sập (trắng màn hình)** khi chuyển báo cáo khác (vẽ báo cáo mới bằng số liệu báo cáo cũ) | Mất giao diện | Chỉ vẽ khi dữ liệu đúng báo cáo; thêm ErrorBoundary toàn ứng dụng |
| 3 | Nút **“Xem báo cáo” không làm mới** khi bộ lọc không đổi | Không cập nhật được số liệu | Luôn tải lại |
| 4 | **Hàng đợi cấp phát không hiện tên người bệnh** | Dược sĩ không biết đơn của ai | API trả `person_name` |
| 5 | **Chi tiết chuyển viện không hiện tên người bệnh** | Khó nhận biết hồ sơ | API chi tiết trả tên cho người có quyền xem danh tính |
| 6 | Cán bộ tiếp nhận thấy nút **“Mở hồ sơ sức khỏe”** nhưng không có quyền (bấm bị đẩy về trang chủ) | Gây hiểu nhầm | Ẩn nút với người không có quyền lâm sàng |
| 7 | Nhật ký **tạo/sửa người dùng không ghi tên tài khoản** | Khó truy vết | Ghi tên tài khoản và thay đổi |
| 8 | Danh sách **không tự cập nhật** khi quay lại cửa sổ sau một lúc | Thấy dữ liệu cũ | Tự tải lại khi quay lại cửa sổ (>20 giây) |
| 9 | Cán bộ không tick được “điều trị đang mở” khi bàn giao; hộp thoại break-glass bỏ chọn người *(đã nêu ở docs/06)* | Kẹt luồng | Đã sửa |
| 10 | **Dưới tải cao (100 người dùng) hệ thống nghẽn 30 giây và trả lỗi HTTP 500** (cạn hồ kết nối CSDL, khóa ghi SQLite) | Mất khả dụng khi đông người | Bật WAL, nới hồ kết nối khớp số luồng, trả **503 + Retry-After** khi quá tải; sau sửa 100 người dùng: 0 lỗi, p95 678ms |
| 11 | Menu di động **không đóng khi bấm ra ngoài / nhấn Esc / bấm đúng tab đang mở** | Khó dùng trên điện thoại | Thêm lớp nền, Esc, tự đóng khi chọn tab |
| 12 | Tab **Khám định kỳ tràn ngang** trên điện thoại (lưới 1fr, dải nút lọc không xuống dòng) | Phải kéo ngang | `minmax(0,1fr)` + dải lọc tự xuống dòng; nút Đăng xuất chỉ còn biểu tượng trên màn hình nhỏ |

## Ma trận UAT (mục 12.2)
| UAT | Test | Kết quả |
|---|---|---|
| 01 Không trùng HealthRecord khi tái tiếp nhận | `test_uat01_…` | ✔ |
| 02 Cảnh báo dị ứng, bác sĩ quyết định + ghi nhận | `test_uat02_…` | ✔ |
| 03 Cấp 10/30 = "cấp một phần", không thành "đã dùng" | `test_uat03_…` | ✔ |
| 04 Order mở → Encounter không kết thúc sai | `test_uat04_…` | ✔ |
| 05 Danh sách lịch đúng phạm vi cơ sở | `test_uat05_…` | ✔ |
| 06 Chuyển viện → mốc, kết quả, kế hoạch sau viện | `test_uat06_…` | ✔ |
| 07 Cấp cứu ghi tối thiểu, bổ sung sau, timestamp riêng | `test_uat07_…`, `07b` | ✔ |
| 08 Chuyển trại: kỳ đổi trạng thái, HealthRecord còn | `test_uat08_…` | ✔ |
| 09 Cán bộ quản lý không thấy lâm sàng (UI **và** API) | `test_uat09_…` + smoke UI | ✔ API; UI: officer chỉ có 3 tab, không có tab lâm sàng |
| 10 Sửa hồ sơ đã xác nhận → addendum/version + audit | `test_uat10_…` | ✔ |
| 11 Tài liệu: kiểm quyền + audit xem/tải | `test_uat11_…` | ✔ |
| 12 Báo cáo: lượt ≠ người, lọc đúng cơ sở | `test_uat12_…` | ✔ |

## Phạm vi test bổ sung
- **BR-01…07**: `test_rules_security.py` (trùng mã nguồn, tên+DOB, hủy có lý do, occurred/recorded, cấp quá lượng/hoàn trả, idempotency & version conflict, "chưa có dữ liệu ≠ không có").
- **Bảo mật**: khóa tài khoản sau 5 lần sai, thu hồi phiên khi đổi mật khẩu, chính sách mật khẩu, RBAC mẫu, cách ly cơ sở, break-glass, hash-chain audit phát hiện sửa DB trực tiếp, upload (sai magic bytes, EICAR, quá cỡ, path traversal, mã hóa, phát hiện hỏng checksum), xuất CSV cần mục đích.
- **Luồng**: `test_workflows.py` – khám ban đầu → managed, void stay, đợt khám định kỳ (loại trừ đang ở BV/chờ chuyển trại, khóa đợt, tỷ lệ), bệnh mạn tính + scheduler + nâng mức cảnh báo, hoãn lịch, chuyển viện (nhảy bước, BV từ chối, đường tắt cấp cứu), kết thúc quản lý, cấp cứu người chưa rõ danh tính, danh mục có phiên bản.

## Lỗi/điều chỉnh tìm thấy khi test (đã sửa)
1. Header `X-Break-Glass-Reason` chứa tiếng Việt không hợp lệ theo chuẩn HTTP → server nay **URL-decode** header, client phải `encodeURIComponent`.
2. Scheduler cũ nâng mức cảnh báo ngay trong lần chạy tạo ra nó (so sánh thời gian) → hành vi hiện tại: nâng mức ở các lần chạy sau (test đã phản ánh).

## QC độc lập đợt 2 (kiểm tra lại toàn hệ thống)
**Cách làm:** CSDL thử riêng (seed-only và demo), không dùng `phms.db`; chạy lại toàn bộ test hiện có rồi tự viết 2 bộ “đục” (quyền theo vai trò trên API, ID bất thường, dữ liệu đầu vào xấu, token/mật khẩu, dị ứng/tương tác, vòng đời đơn thuốc, khóa lạc quan, idempotency, máy trạng thái chuyển viện, break-glass).

**Kết quả hồi quy:** pytest 82/82 · E2E 7 luồng nghiệp vụ + responsive đạt · 5 bộ demo (smoke/flow/followup/notify/alignment) đạt · Firefox & WebKit (nhận hồ sơ, khám–kê đơn–cấp phát, chuyển viện, bàn giao) đạt · tải 30 người dùng: p95 210 ms, 0 lỗi, chuỗi nhật ký toàn vẹn (6.750 sự kiện).

**Lỗi thật phát hiện & đã sửa (có test hồi quy `tests/test_qc_regression.py`):**
| # | Mức | Lỗi | Sửa |
|---|---|---|---|
| Q1 | Cao | Dị ứng Penicillin nhưng kê Amoxicillin **không cảnh báo** (chỉ so khớp chuỗi tên) | Cảnh báo theo nhóm thuốc (`DRUG_CLASSES`); vẫn buộc xác nhận kèm lý do |
| Q2 | TB | Sinh hiệu vô lý được ghi nhận: Mạch “abc”, Mạch 500, Nhiệt độ 99 °C | Chỉ số đã biết phải là số và trong ngưỡng sinh lý khả dĩ (`OBS_NOT_NUMERIC`/`OBS_OUT_OF_RANGE`); chấp nhận dấu phẩy thập phân |
| Q3 | TB | Ngày sinh tương lai (2999) và 1800 được chấp nhận | Hợp lệ từ 1900 đến hôm nay (tạo, đối soát) |
| Q4 | Thấp | Đổi mật khẩu cho phép đặt trùng mật khẩu cũ | Từ chối `SAME_PASSWORD` |

**Đã kiểm và đạt (không có lỗi):** 401 khi thiếu/sai token ở 10 API; ma trận quyền đọc (admin/audit/users chỉ quản trị); cách ly cơ sở (health-summary, tạo lượt khám, referral → 403); ID rác → 404 không 5xx; tên 5.000 ký tự/rỗng → 422; SQLi qua tên và `q` không lỗi; nhảy bước trạng thái lượt khám/chuyển viện bị chặn; lượt khám đã hoàn tất khóa (409, dùng addendum); cấp phát: đơn nháp/quá số lượng/0/âm/đơn đã dừng bị chặn; sửa trực tiếp đơn đã xác nhận bị chặn; dừng thuốc bắt buộc lý do; sai `expected_version` → 409; Idempotency-Key trùng trả cùng kết quả, khác nội dung → 422; break-glass: lý do ngắn bị từ chối, chỉ ĐỌC (ghi bị chặn), có nhật ký; PUT/PATCH/DELETE nhật ký → 404/405; đổi mật khẩu thu hồi token cũ.

**Chập chờn ghi nhận:** `flow-docs-admin` K4 hết thời gian chờ 1 lần trong 5 lần chạy (tức 1/5) khi chạy ngay sau các bộ khác; chạy lại 4 lần liên tiếp đều đạt, **chưa tái hiện** – theo dõi, chưa xác định nguyên nhân.

**Sự cố quy trình của QC (đã khắc phục, nêu để minh bạch):** lệnh dựng CSDL thử lần đầu lỗi dây chuyền nên máy chủ thử trỏ nhầm `backend/phms.db` thật; E2E/probe chạy vào đó và để lại 38 hồ sơ thử. Đã sao lưu bản nhiễm ra ngoài, **seed lại về trạng thái sạch** (13 tài khoản, 0 hồ sơ, chuỗi nhật ký ok). Tệp tài liệu mồ côi trong `storage/` đã dọn.

## QC đợt 3 – hoàn thiện production (yêu cầu: làm hết các khoảng trống còn lại, giữ nguyên tài khoản/mật khẩu mẫu)
**Đã làm & kiểm chứng:** đổi/đặt lại mật khẩu + buộc đổi lần đầu · MFA TOTP · SSO OIDC · CSP/HSTS/tắt `/docs`/chặn cấu hình yếu · idempotency toàn bộ API tạo bản ghi (giao diện tự gắn khóa + thử lại) · chặn tạo trùng + **gộp hồ sơ có phê duyệt bốn mắt** · mức ưu tiên yêu cầu khám · chọn tài liệu bàn giao chuyển viện · sửa kế hoạch theo dõi · PostgreSQL · sao lưu/phục hồi · soak · accessibility. Chi tiết: [06](06-ra-soat-luong-nghiep-vu.md) mục B, vận hành: [07](07-van-hanh-production.md).

| Hạng mục | Kết quả |
|---|---|
| pytest | **114/114** trên SQLite **và** PostgreSQL 16 (gồm test MFA RFC 6238, SSO giả lập, gộp hồ sơ, sao lưu/phục hồi, đồng thời nhật ký) |
| E2E trên SQLite | 8 bài luồng (gồm `flow-security`: 13 bước mới) + responsive + accessibility + 5 bài demo: **đạt** |
| E2E trên PostgreSQL | 8 bài luồng **đạt** |
| Khởi động production 4 worker trên PostgreSQL trống | Đạt (khóa tư vấn chống đua tạo schema); secret mặc định bị từ chối; `/docs` 404; có HSTS |
| Nâng cấp DB cũ | DB phiên bản trước tự thêm bảng/cột mới, dữ liệu và chuỗi nhật ký nguyên vẹn, người dùng cũ không bị ép đổi mật khẩu |
| Sao lưu → phục hồi (PostgreSQL) | Gói 46 hồ sơ/955 nhật ký/12 tài liệu → phục hồi sang CSDL + thư mục khác: chuỗi băm đúng, **12/12 tài liệu giải mã & khớp checksum**, ghi mới được. Gói bị sửa 1 byte → từ chối; gói có đường dẫn độc hại → từ chối |
| **Soak PostgreSQL** | 26 người dùng ảo × **12 phút**, ~235.000 yêu cầu, ~330 req/s: **0 lỗi**; p95 23→30 ms; RSS 126→108 MB (không rò rỉ); chuỗi nhật ký 186.158 sự kiện toàn vẹn |
| Accessibility | axe-core WCAG 2.1 A/AA: đăng nhập + mọi tab × 7 vai trò + hộp thoại/ngăn kéo, **sáng và tối**: 0 lỗi serious/critical; bàn phím (Tab, focus trong hộp thoại, Esc, trả focus) đạt |

**Lỗi phát hiện khi kiểm tính năng mới (đã sửa):**
| # | Mức | Lỗi |
|---|---|---|
| R1 | Cao | Người điều phối cơ sở A **xem/duyệt được đề nghị gộp hồ sơ của cơ sở B** (tự rà soát) → giới hạn theo cơ sở người lập; có test |
| R2 | TB | Nhập sai mật khẩu cũ → giao diện hiểu 401 là hết phiên và **tự đăng xuất** → chỉ đăng xuất khi mã lỗi là phiên không hợp lệ |
| R3 | TB | Bộ chọn tài liệu dùng nhãn lồng nhau: bấm một ô làm bật/tắt nhầm ô đầu |
| R4 | TB | Production cho phép dùng chung khóa ký phiên và khóa mã hóa tài liệu → bắt buộc `PHMS_DOC_KEY` riêng |
| R5 | TB | Accessibility: tương phản màu (nhãn nhóm, mã phân hệ, huy hiệu đỏ; chế độ tối), không có vùng `<main>`/liên kết bỏ qua, hộp thoại không tên và **không giữ focus**, Esc đóng **cả** hộp thoại lẫn ngăn kéo bên dưới, ô chọn không nhãn, bảng/bảng Kanban cuộn không dùng được bằng bàn phím, hàng bấm được không focus được, thông báo có nút lồng nhau |
| R6 | Thấp | Nhiều worker khởi động cùng lúc có thể đua tạo schema trên PostgreSQL → khóa tư vấn |
| R7 | Thấp | Test M1 chập chờn (chờ nhầm toast cũ) → chờ trạng thái thật |

**Điều chưa kiểm chứng / còn lại (trung thực):** SSO với IdP thật · build container (`deploy/Dockerfile`, compose chưa chạy vì Docker daemon không có) · soak **nhiều giờ** (mới 12 phút; script chạy được hàng giờ) · pentest/rà soát pháp lý · đọc màn hình thật (mới kiểm bằng axe + bàn phím) · mã khôi phục MFA.
**Lưu ý quy trình:** ở đợt 2 QC từng chạy nhầm lên `phms.db`; đợt này mọi lần chạy đều dùng CSDL riêng và đã xác nhận `phms.db` còn seed-only.

## Rủi ro / khoảng trống kiểm thử còn lại
| Mức | Nội dung |
|---|---|
| Cao | Chưa pentest, chưa rà soát pháp lý/ATTT; JWT HS256 + secret từ env, chưa có SSO/MFA cho vai trò đặc quyền (mục 10.1) |
| Cao | Chỉ chạy SQLite; **chưa kiểm chứng PostgreSQL** (cấp phát/idempotency/chuỗi nhật ký dưới race thật cần chạy lại) |
| TB | Chưa test accessibility (đọc màn hình, bàn phím toàn diện); Firefox/WebKit mới phủ 4 luồng chính |
| TB | Chưa test sao lưu/phục hồi (NFR-03) và soak nhiều giờ; nhật ký hash-chain chỉ *phát hiện*, không *ngăn* người có quyền DB |
| TB | Các khoảng trống chức năng còn mở xem [06 mục B](06-ra-soat-luong-nghiep-vu.md) (màn hình đổi mật khẩu, sửa kế hoạch, chọn tài liệu bàn giao, ưu tiên khi nhận yêu cầu khám, gộp hồ sơ trùng có duyệt…) |
| Thấp | Chưa có migration Alembic – hiện dùng bộ nâng cấp nhẹ `ensure_schema`; cần trước khi vận hành |
| Ngoài phạm vi Core | Tích hợp QLPN/FHIR/chữ ký số/offline/kho dược (tài liệu xếp ngoài Core) |
