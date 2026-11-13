# 06 – Rà soát code so với luồng nghiệp vụ

Đối chiếu mã nguồn với tài liệu thiết kế v1.0 (WF-01…09, BR-01…07, mục 8 trạng thái, mục 10.1). Mỗi mục: **lệch ở đâu → đã sửa thế nào → test**.

## A. Đã sửa
| # | Tham chiếu | Lệch trước đây | Đã sửa | Test |
|---|---|---|---|---|
| 1 | WF-04 bước 2 | Đợt khám định kỳ gom cả người **mới tiếp nhận** (chưa khám ban đầu); chưa tránh trùng lịch | Chỉ gom hồ sơ **đang quản lý**; người chưa khám ban đầu và người đã có lịch định kỳ khác đang mở vào danh sách **loại trừ có lý do** | `test_round_only_includes_managed…`, `test_wf04…` |
| 2 | BR-04, 9.4 | Cấp phát **không kiểm tra hạn dùng** của đơn (cấp được cả đơn đã hết hoặc chưa bắt đầu) | Chỉ cấp trong khoảng *ngày bắt đầu → ngày bắt đầu + số ngày – 1*; đơn hết hạn/chưa tới ngày không vào hàng đợi cấp phát | `test_dispense_only_within_order_validity_window`, `test_expired_orders_leave…` |
| 3 | WF-03 bước 6 | Không có **nhắc hết liệu trình** để bác sĩ đánh giá/tái kê | Scheduler sinh cảnh báo + thông báo khi đơn còn ≤3 ngày hoặc đã hết; **tự đóng** khi bác sĩ đã xử lý đơn; không tự đổi trạng thái đơn | `test_scheduler_reminds_once…` |
| 4 | WF-02 / mục 8 | Hoàn tất lượt khám khi còn **đơn thuốc nháp** → đơn mồ côi, không xác nhận được nữa | Chặn hoàn tất, báo rõ đơn nào | `test_cannot_complete_encounter_with_draft_medication_order` |
| 5 | BR-02 | **Hủy lượt khám** nhưng đơn thuốc/chỉ định/đề nghị chuyển viện của nó vẫn còn hiệu lực (vẫn cấp phát được) | Hủy kéo theo hủy đơn/chỉ định/đề nghị nháp (ghi lý do); **chặn** nếu đơn đã cấp phát hoặc chuyển viện đang xử lý | `test_cancel_encounter_cascades…` |
| 6 | WF-07 | Bàn giao thiếu **biên nhận** của cơ sở nhận | Cơ sở đích tạo đợt tiếp nhận mới → tự lập biên nhận (`received_at/by/stay`), báo cơ sở gửi; giao diện có bước 4 “Cơ sở nhận tiếp nhận” | `test_receiving_facility_stay_acknowledges…` |
| 7 | WF-06 ngoại lệ | Kết cục **tử vong / không trở lại** đóng như bình thường | Gắn “cần hậu kiểm”, thông báo Khẩn cho người phê duyệt và quản lý; chỉ đóng cờ khi hậu kiểm | `test_unusual_referral_outcomes…` |
| 8 | WF-02 bước 3 | Bàn làm việc không hiện **thuốc đang dùng, vấn đề sức khỏe mở** | Thẻ “Thông tin lâm sàng cần thiết” (dị ứng + thuốc + vấn đề) | `test_encounter_shows_clinical_context…` + E2E |
| 9 | Mục 10.1 | Break-glass **không có hạn thời gian** ở máy chủ và **không có màn hình** | Lượt cấp có hạn (30 phút, chỉ đọc, thu hồi được), hộp thoại trên giao diện, chip hiển thị hạn, hết hạn tự đóng hồ sơ | `test_break_glass_grant_is_time_limited…` + E2E |
| 10 | NFR-07 | Nhật ký kiểm toán của đối tượng **mới tạo** thiếu mã đối tượng *(sửa ở đợt thông báo)* | Gán mã ngay khi khởi tạo | `test_audit_events_of_new_objects…` |
| 11 | WF-07 (UI) | **Cán bộ tiếp nhận không tick được** “xác nhận điều trị đang mở” (vì không được xem chi tiết) → kẹt không bàn giao được | Luôn hiện ô xác nhận khi chi tiết bị ẩn | E2E `alignment.mjs` |
| 12 | Vận hành | CSDL tạo từ bản cũ không có cột/bảng mới | `ensure_schema()` tự thêm bảng & cột thiếu (nullable), chạy lúc khởi động | `test_schema_upgrade…` |
| 13 | UX | Sau khi cấp break-glass, hộp thoại đóng lại **bỏ chọn người bệnh** | Chỉ bỏ chọn khi người dùng Hủy | E2E `alignment.mjs` |

### Bổ sung sau đợt E2E đầy đủ (xem [02-QC-bao-cao-kiem-thu.md](02-QC-bao-cao-kiem-thu.md))
Chuỗi nhật ký đứt khi ghi đồng thời; trang Báo cáo sập khi chuyển báo cáo; nút “Xem báo cáo” không làm mới; hàng đợi cấp phát và chi tiết chuyển viện thiếu tên người bệnh; nút “Mở hồ sơ sức khỏe” hiện sai với cán bộ tiếp nhận; nhật ký tạo/sửa người dùng thiếu tên tài khoản; danh sách không tự làm mới.

## B. Các khoảng trống đã nêu ở QC đợt 2 – nay đã xử lý (QC đợt 3)
| Mục | Đã làm |
|---|---|
| Đổi/đặt lại mật khẩu (10.1) | Màn hình **Tài khoản của tôi** (đổi mật khẩu); tài khoản do quản trị tạo **bị buộc đổi ở lần đăng nhập đầu**; quản trị **Đặt lại mật khẩu** (mật khẩu tạm sinh ngẫu nhiên, hiện một lần, thu hồi mọi phiên cũ); không cho đặt trùng mật khẩu cũ. *Tài khoản mẫu cố ý KHÔNG bị ép đổi* (theo yêu cầu giữ nguyên) |
| MFA / SSO (10.1) | **MFA TOTP** (bật tự phục vụ bằng QR, chống dùng lại mã, bí mật mã hóa khi lưu, bắt buộc theo vai trò qua `PHMS_MFA_REQUIRED_ROLES`, quản trị đặt lại MFA). **SSO OIDC** (authorization code + PKCE, kiểm chữ ký/iss/aud/nonce, không tự tạo tài khoản). SSO mới kiểm với IdP giả lập |
| BR-06 idempotency | Thêm cho tạo hồ sơ, đợt tiếp nhận, sinh hiệu, chẩn đoán, chỉ định, dị ứng, vấn đề sức khỏe, kế hoạch, lịch hẹn, cấp cứu, ghi nhận dùng thuốc, đề nghị gộp. **Giao diện tự gắn `Idempotency-Key` cho mọi thao tác tạo và tự thử lại an toàn** khi mất mạng/503. Còn lại: upload tài liệu (giao diện khóa nút khi đang gửi) |
| WF-05 bước 5 | Nút **Sửa** kế hoạch theo dõi (mục tiêu, chỉ số, chu kỳ, người phụ trách) ở tab Bệnh lý & Cảnh báo và hồ sơ người bệnh; đổi chu kỳ **dời lịch đang mở**; kiểm tra phiên bản (xung đột) |
| WF-06 bước 1 | **Chọn tài liệu bàn giao** khi lập đề nghị chuyển viện và đổi lại khi chưa chuyển đi; chỉ nhận tài liệu hợp lệ của đúng người bệnh; người điều phối chỉ thấy có tài liệu, không thấy tên tệp |
| WF-02 bước 1 | Trường **Mức ưu tiên** (thường/ưu tiên/khẩn cấp) khi nhận yêu cầu khám; danh sách xếp ca khẩn lên đầu; cấp cứu tự mang mức khẩn cấp |
| BR-01 trùng hồ sơ | API **chặn tạo trùng tên + ngày sinh** (`DUPLICATE_SUSPECTED` kèm ứng viên) trừ khi xác nhận rõ "người khác"; **gộp hồ sơ có phê duyệt bốn mắt** (người lập ≠ người duyệt; chuyển toàn bộ dữ liệu; hồ sơ nguồn không bị xóa, chỉ đánh dấu *Đã gộp*; chặn khi cả hai cùng có đợt tiếp nhận đang hiệu lực) |
| Bảo mật HTTP | `Content-Security-Policy`, `Permissions-Policy`, COOP/CORP; **HSTS** khi HTTPS (hoặc production); `/docs` & `/openapi.json` **tắt ở production**; production **từ chối khởi động** nếu secret mặc định |
| Hạ tầng | Kiểm chứng PostgreSQL 16 (toàn bộ test + E2E); khóa tư vấn khi khởi tạo schema nhiều worker; sao lưu/phục hồi (`python -m app.backup`); bộ lập lịch chạy riêng (`python -m app.scheduler_cli`); soak; accessibility |

## C. Còn lệch / chưa làm (cần quyết định)
| Mục | Hiện trạng | Gợi ý |
|---|---|---|
| Dị ứng chéo | Cảnh báo theo nhóm thuốc bằng bảng cố định trong mã (`DRUG_CLASSES`: penicillin/beta-lactam, cephalosporin, sulfonamide, NSAID, quinolone, macrolide). Chưa do chuyên môn quản lý | Đưa bảng nhóm thuốc vào danh mục có phiên bản để dược sĩ cập nhật |
| MFA | Chưa có mã khôi phục dùng một lần (khôi phục qua quản trị) | Thêm recovery codes nếu khách yêu cầu |
| SSO | Chưa thử với IdP thật | Thử tích hợp khi có Keycloak/Azure AD của khách |
| Gộp hồ sơ | Không hoàn tác được sau khi duyệt (dữ liệu đã chuyển); cặp cùng có đợt tiếp nhận đang hiệu lực phải xử lý kỳ trước | Quyết định nghiệp vụ nếu cần "tách lại" |
| Chặn tốc độ theo IP | Làm ở reverse proxy (mẫu `deploy/nginx.conf`) | — |
| Alembic | Vẫn dùng bộ nâng cấp nhẹ `ensure_schema` (chỉ thêm bảng/cột nullable) | Chuyển Alembic trước khi có thay đổi schema phá vỡ |
| Container | `deploy/Dockerfile`, `docker-compose.yml` chưa build thử (Docker daemon không chạy trong môi trường kiểm thử) | Build & thử trước khi dùng |
| Soak nhiều giờ | Mới chạy 12 phút (xem 02); script hỗ trợ chạy hàng giờ (`MINUTES=…`) | Chạy qua đêm trên môi trường staging |
| Ngoài phạm vi Core | Tích hợp QLPN/FHIR, chữ ký số, offline, kho dược | Theo tài liệu thiết kế |
