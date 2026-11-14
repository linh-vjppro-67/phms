# 05 – Hệ thống thông báo

## Nguyên tắc thiết kế
- **Gửi đúng người**: người dùng đang hoạt động, **có quyền liên quan** và **thuộc đúng cơ sở**. Không tự báo cho người thực hiện. Mỗi người một hộp thư riêng (truy vấn luôn ràng buộc `user_id`, chống truy cập chéo).
- **Riêng tư (need-to-know)**: nội dung chỉ nêu *việc cần làm*; **tên người bệnh chỉ hiện với người có quyền xem danh tính** (`person.read`); **không bao giờ** nêu chẩn đoán/lý do chuyên môn. Thông báo của trình duyệt/hệ điều hành chỉ hiện tiêu đề chung.
- **Nguyên tử**: ghi cùng giao dịch với sự kiện gốc. **Không trùng**: khóa khử trùng lặp theo từng người (`dedupe_key`), nên scheduler/retry không sinh thêm.
- **Nhóm bắt buộc** (Cấp cứu, Bảo mật) không thể tắt; các nhóm còn lại người dùng tự bật/tắt.
- **Lưu giữ**: thông báo đã đọc/đã ẩn quá 90 ngày và mọi thông báo quá 365 ngày bị xóa tự động (`PHMS_NOTIFY_RETENTION_DAYS`, `PHMS_NOTIFY_MAX_AGE_DAYS`), chạy cùng tác vụ nền.
- **Chuyển phát**: giao diện hỏi định kỳ `GET /api/notifications/poll?after_seq=` (20 giây khi tab đang mở, 60 giây khi ẩn, tự lùi khi lỗi, hỏi ngay khi quay lại tab). Không dùng kênh luôn mở nên chạy ổn qua proxy.

## Ma trận sự kiện → người nhận
| Sự kiện | Mức | Nhóm | Người nhận (cùng cơ sở) | Mở tới |
|---|---|---|---|---|
| Ghi nhận cấp cứu | Khẩn | Cấp cứu | nurse, doctor (trừ người ghi) | Cấp cứu |
| Cấp cứu chưa rõ danh tính | Cảnh báo | Cấp cứu | officer (quyền `person.write`) | Tiếp nhận → hồ sơ tạm |
| Chuyển viện gửi duyệt | Thông tin / Cảnh báo (nếu khẩn) | Chuyển viện | approver | Chuyển viện → đúng hồ sơ |
| Chuyển viện cấp cứu đi tắt | Khẩn | Chuyển viện | approver, manager | Chuyển viện → đúng hồ sơ |
| Chuyển viện đã điều phối | Thông tin | Chuyển viện | bác sĩ lập đề nghị, nurse | Chuyển viện |
| Có kết quả điều trị ngoài trại | Thông tin | Chuyển viện | bác sĩ lập đề nghị | Chuyển viện |
| Có kết quả xét nghiệm/thủ thuật | Thông tin | Thuốc & XN | bác sĩ đã chỉ định | Khám chữa bệnh → đúng lượt khám |
| Đơn thuốc đã xác nhận | Thông tin | Thuốc & XN | pharmacist, nurse (quyền `dispense.write`) | Cấp phát → đúng đơn |
| Khởi tạo bàn giao | Cảnh báo | Chuyển trại | nurse, doctor (soạn tóm tắt) | Chuyển trại |
| Đã có tóm tắt y tế | Thông tin | Chuyển trại | officer, approver (xác nhận) | Chuyển trại |
| Bàn giao đã xác nhận | Cảnh báo | Chuyển trại | officer **của cơ sở nhận** | Tiếp nhận → người đó |
| Người mới tiếp nhận | Thông tin | Tiếp nhận | nurse, doctor | Khám ban đầu |
| Lịch quá hạn (scheduler) | Cảnh báo | Lịch & cảnh báo | nurse, doctor, manager (+ người phụ trách) | Bệnh lý & Cảnh báo |
| Cảnh báo bị nâng mức | Khẩn | Lịch & cảnh báo | manager (+ người phụ trách) | Bệnh lý & Cảnh báo |
| Đợt khám định kỳ mới | Thông tin | Lịch & cảnh báo | nurse, doctor | Khám định kỳ → đúng đợt |
| Truy cập khẩn cấp (break-glass) | Khẩn | Bảo mật | manager của người xem, **admin** | Cảnh báo / Quản trị |
| Đơn thuốc sắp/đã hết liệu trình | Thông tin / Cảnh báo (đã hết) | Thuốc & XN | bác sĩ kê đơn + người có quyền kê đơn | Chỉ định & Kê đơn → đúng đơn |
| Cơ sở đích đã tiếp nhận (biên nhận bàn giao) | Thông tin | Chuyển trại | officer/approver **của cơ sở gửi** | Chuyển trại |
| Chuyển viện kết thúc với kết cục bất thường (tử vong / không trở lại) | Khẩn | Chuyển viện | approver, manager | Chuyển viện → đúng hồ sơ |
| Tài khoản bị khóa | Cảnh báo | Bảo mật | admin | Quản trị |

## API (đều chỉ trả dữ liệu của chính người đăng nhập)
`GET /api/notifications` (lọc `unread`, `category`, phân trang `before_seq`) · `GET /api/notifications/poll?after_seq=` · `POST /api/notifications/{id}/read` · `POST /api/notifications/read-all[?category=]` · `POST /api/notifications/{id}/dismiss` · `GET|PUT /api/notifications/preferences`.

## Dữ liệu có sẵn
- Bản demo mới (`python -m app.demo --reset`) tự sinh thông báo; các nhóm số lượng lớn (tiếp nhận, đơn chờ cấp phát) được đánh dấu đã đọc, chỉ việc cần xử lý còn chưa đọc.
- CSDL cũ (tạo trước khi có thông báo): chạy `python -m app.notify_backfill` – chỉ bổ sung cho **việc đang mở**, chạy lại an toàn.
