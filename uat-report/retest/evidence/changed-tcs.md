| NAV-pharm | Menu của Dược chỉ gồm các phân hệ được phép (đối chiếu 04-§2) | FAIL | PASS | [log](retest/evidence/logs/NAV-pharm.txt) |
| BG-02 | Vai trò không có quyền 'breakglass' (dược, cán bộ) không được truy cập khẩn (phần hết hạn: xem BG-02b) | BLOCKED | PASS | [log](retest/evidence/logs/BG-02.txt) |
| SEC-05 | Cấu hình PRODUCTION (từ chối khởi động khi cấu hình không an toàn; tắt /docs; HSTS luôn bật; không còn tài kho | BLOCKED | PASS | [log](retest/evidence/logs/SEC-05.txt) |
| EXP-01 | 6 yêu cầu ĐỒNG THỜI tạo khám ban đầu cho cùng một đợt tiếp nhận: chỉ 1 thành công (không nhân đôi lượt khám ba | FAIL | PASS | [log](retest/evidence/logs/EXP-01.txt) |
| EXP-10 | Tra cứu danh tính liên cơ sở: chỉ vai trò cần đối soát trùng (cán bộ tiếp nhận) mới tìm được người của cơ sở k | FAIL | PASS | [log](retest/evidence/logs/EXP-10.txt) |
| EXP-10b | Tình huống khẩn cấp: người có quyền break-glass tìm được người NGOÀI cơ sở chỉ bằng ĐÚNG mã nguồn, thông tin t | (mới) | PASS | [log](retest/evidence/logs/EXP-10b.txt) |
| EXP-23 | Không ghi thêm chẩn đoán / chỉ định / đơn thuốc / đề nghị chuyển viện vào lượt khám đã HỦY (BR-02: hủy = đóng, | FAIL | PASS | [log](retest/evidence/logs/EXP-23.txt) |
| BG-03 | Break-glass là CHỈ ĐỌC (mục 10.1/D2): người ngoài cơ sở đang có lượt break-glass không được tải lên / thay thế | FAIL | PASS | [log](retest/evidence/logs/BG-03.txt) |
| EXP-24 | 3 yêu cầu đồng thời XÁC NHẬN cùng một đơn thuốc nháp: chỉ 1 thành công, không nhân đôi nhật ký/thông báo cấp p | FAIL | PASS | [log](retest/evidence/logs/EXP-24.txt) |
| EXP-24b | 3 yêu cầu đồng thời ĐIỀU CHỈNH cùng một đơn đã xác nhận: chỉ 1 phiên bản mới (không sinh nhiều bản nháp v2 son | FAIL | PASS | [log](retest/evidence/logs/EXP-24b.txt) |
| EXP-25 | 3 người cùng duyệt MỘT đề nghị chuyển viện: chỉ 1 thao tác thành công, lịch sử điều phối không ghi trùng bước | FAIL | PASS | [log](retest/evidence/logs/EXP-25.txt) |
| EXP-25c | 3 người cùng tiếp nhận MỘT cảnh báo: chỉ 1 người trở thành người chịu trách nhiệm (không 2 người cùng 'nhận') | FAIL | PASS | [log](retest/evidence/logs/EXP-25c.txt) |
| DC-09 | Hồ sơ chuyển viện đang mở không thuộc lượt khám đã hủy; chuyển viện completed luôn có kế hoạch & kết cục | FAIL | PASS | [log](retest/evidence/logs/DC-09.txt) |
| DC-12 | Mỗi đợt tiếp nhận chỉ có tối đa 1 lượt khám ban đầu không bị hủy (WF-01, B5) | FAIL | PASS | [log](retest/evidence/logs/DC-12.txt) |
| BG-02b | Quyền truy cập khẩn cấp TỰ HẾT HẠN: sau khi quá hạn, hồ sơ ngoài cơ sở bị đóng lại (cấu hình 1 phút để kiểm th | (mới) | PASS | [log](retest/evidence/logs/BG-02b.txt) |