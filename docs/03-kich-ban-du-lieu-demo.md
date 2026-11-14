# 03 – Kịch bản dữ liệu demo

## Bộ dữ liệu GỌN: 10 người (`python -m app.demo_small --reset`)
Dùng khi cần dữ liệu ít, dễ theo dõi (bộ đầy đủ ~44 hồ sơ ở bên dưới). **`--reset` xóa toàn bộ dữ liệu hiện có** (tài khoản mẫu được tạo lại, mật khẩu `Phms@2026dev`). Mỗi người đại diện một luồng:

| # | Người | Luồng để test | Đăng nhập thử |
|---|---|---|---|
| 1 | Lê Quốc Bảo | Mới tiếp nhận, **chờ khám ban đầu** | `doctor1` → Khám ban đầu |
| 2 | Phạm Minh Tuấn | **Đang khám ban đầu dở** (đã đo sinh hiệu) | `doctor1` |
| 3 | Hoàng Văn Nam | Khỏe mạnh; vừa khám cảm cúm, thuốc đã cấp + ghi nhận dùng; **đơn sắp hết liệu trình** | `nurse1`, `pharm1` |
| 4 | Đỗ Văn Cường | Tăng huyết áp, **dị ứng Aspirin**, 2 thuốc giám sát, kế hoạch theo dõi, **lịch quá hạn** | `nurse1` (cảnh báo), `doctor1` |
| 5 | Vũ Đình Khoa | Đái tháo đường, kế hoạch theo dõi, **thuốc cấp phát một phần** | `pharm1` |
| 6 | Bùi Hữu Lộc | **Lao phổi**, phác đồ 4 thuốc, giám sát dùng thuốc (có lần *không dùng*) | `nurse1` → Cấp phát → Giám sát |
| 7 | Ngô Thanh Sơn | **Chuyển viện chờ phê duyệt** | `approver1` → Chuyển viện |
| 8 | Đặng Văn Hải | **Chuyển trại** sang Trại 2, tóm tắt đã soạn, **chờ xác nhận** | `officer1` → Chuyển trại |
| 9 | Trịnh Văn Dũng | **Cấp cứu đang mở**, hồ sơ **không mã** → chờ đối soát (cán bộ tiếp nhận có thông báo) | `officer1` đối soát → `doctor1` đóng sự kiện |
| 10 | Lý Thị Hoa | **Đơn đã xác nhận chờ cấp phát** + **đơn nháp** (thử Xác nhận / Xóa nháp) | `pharm1`, `doctor1` |

Ngoài ra có một đợt khám định kỳ Quý 4 đang chạy (manager1) và các cảnh báo do tác vụ nền sinh ra. Muốn đối soát người số 9 để thử đóng cấp cứu: hệ thống nguồn `QLPN`, mã thử `TEST-0001`.

---


Toàn bộ là **dữ liệu hư cấu** (tên, mã phạm nhân PN-26-xxxx, số quyết định, bệnh viện, PDF). Được tạo bằng `python -m app.demo` qua chính API nghiệp vụ nên đúng phân quyền, máy trạng thái và có nhật ký kiểm toán. Mốc thời gian tính theo ngày chạy; xảy ra trong quá khứ thì lưu `occurred_at` lùi, còn `recorded_at` là lúc nạp dữ liệu (giống “nhập bổ sung”).

## Quy mô (Trại 1 = F01, Trại 2 = F02)
~44 hồ sơ · 45 đợt tiếp nhận · ~84 lượt khám · 23 đơn thuốc · 10 chuyển viện · 5 sự kiện cấp cứu · 5 phiếu bàn giao · 3 đợt khám định kỳ · 8 tài liệu PDF xem được · >1100 bản ghi nhật ký.

## Tình huống để thử, theo tab
| Tab | Thử gì | Dữ liệu có sẵn |
|---|---|---|
| Tiếp nhận (M01) | Chờ đối soát, trùng hồ sơ | 3 hồ sơ chờ đối soát: **hai người trùng tên + ngày sinh “Lê Minh Tuấn”** (không tự gộp), 1 người **thiếu mã nguồn**, 1 hồ sơ tạm từ cấp cứu; 1 hồ sơ chưa có đợt tiếp nhận |
| Khám ban đầu (M03) | Wizard 6 bước | 5 người **chờ khám**, 1 lượt **nháp**, 1 lượt **đang khám dở** (mới có sinh hiệu) |
| Khám chữa bệnh (M04) | Bàn làm việc, addendum | Lượt khám ở đủ trạng thái: đang khám, chờ kết quả (xét nghiệm sốt), đang điều trị, hoàn tất, **đã hủy có lý do** |
| Kê đơn (M05) | Cảnh báo dị ứng, điều chỉnh | Người **dị ứng Amoxicillin** được kê Amoxicillin → cảnh báo, bác sĩ ghi nhận xử lý; 1 đơn **nháp chờ xác nhận**; 1 đơn **điều chỉnh liều (v2)** – bản cũ “đã thay thế”; đơn hoàn thành, đơn ngừng |
| Cấp phát (M06) | Cấp đủ/một phần, hoàn trả, giám sát | Hàng đợi có đơn **chưa cấp** và **cấp một phần**; 1 lần **hoàn trả** có lý do; thuốc lao/tăng huyết áp có **giám sát uống thuốc** (gồm vài lần “không dùng” kèm lý do) |
| Khám định kỳ (M07) | Đợt khóa & đợt đang chạy | Đợt **Quý 3 (đã khóa)**: đã khám/hoãn/không thực hiện; đợt **Quý 4 (đang chạy)** ở cả 2 trại, có người **bị loại trừ** (đang ở bệnh viện / chờ chuyển trại) |
| Bệnh lý & Cảnh báo (M08) | Hộp thư, nâng mức | 5 người tăng huyết áp, 3 đái tháo đường, 2 lao phổi, có **kế hoạch theo dõi**; vài lịch **quá hạn**; cảnh báo: 1 đã xử lý, 1 đã tiếp nhận, 2 mới **đã nâng mức**; cảnh báo hậu kiểm chuyển viện cấp cứu và truy cập khẩn cấp |
| Chuyển viện (M09) | Đủ 7 trạng thái | Nháp, chờ xử lý (x2), đã điều phối, đang điều trị ngoài trại, có kết quả, hoàn tất (x2, có giấy chuyển viện/giấy ra viện), hủy; 1 ca **cấp cứu đi tắt chờ hậu kiểm** |
| Cấp cứu (WF-08) | Ghi nhận tối thiểu | 2 sự kiện **đang mở** (1 đau ngực → chuyển viện khẩn, 1 chưa rõ danh tính); 3 đã đóng, gồm **ghi muộn vì mất điện** và ca **chưa rõ danh tính → đối soát → đóng** |
| Chuyển trại (WF-07) | Đủ bước | Chờ tóm tắt; đã có tóm tắt chờ xác nhận (còn điều trị mở); **F01→F02 đã bàn giao** và khám tiếp ở F02 (cùng hồ sơ); **F02→F01**; kết thúc quản lý (mãn hạn) |
| Hồ sơ SK (M02) / Tài liệu (M12) | Lịch sử, tải PDF | Mỗi người có sinh hiệu theo thời gian; người chuyển trại giữ nguyên lịch sử ở cả 2 trại |
| Báo cáo (M10) | Số liệu có ý nghĩa | Có dữ liệu cho cả 6 báo cáo ở 2 trại |
| Quản trị (M11) | Nhật ký | 4 sự kiện **bị từ chối** (quyền, cơ sở, đăng nhập sai), 1 **break-glass** (bác sĩ Trại 2 xem hồ sơ Trại 1 kèm lý do) |

## Gợi ý đăng nhập nhanh để xem từng luồng
- `doctor1` / `nurse1`: khám, kê đơn, cấp cứu, theo dõi · `pharm1`: hàng đợi cấp phát · `approver1`: duyệt chuyển viện & hậu kiểm
- `officer1`: tiếp nhận, đối soát, bàn giao · `manager1`: đợt khám, cảnh báo, báo cáo · `admin`: người dùng, nhật ký
- `doctor2`/`officer2`…: xem cách ly dữ liệu giữa hai trại; thử xem hồ sơ Trại 1 để thấy từ chối.

## Giới hạn cần biết khi thử
- Cảnh báo dị ứng **chỉ khớp theo tên chất** (vd dị ứng “Amoxicillin” mới cảnh báo khi kê Amoxicillin). **Chưa có nhóm thuốc/dị ứng chéo** (penicillin ↔ amoxicillin) – cần danh mục hoạt chất/nhóm thuốc nếu muốn.
- Số lượng thuốc là số đơn vị trừu tượng (viên/gói), chưa quản lý tồn kho (ngoài phạm vi Core).
