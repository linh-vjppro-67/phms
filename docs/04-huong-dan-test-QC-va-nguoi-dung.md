# 04 – Hướng dẫn test dành cho QC / người dùng

Tài liệu mô tả **luồng hoạt động** của hệ thống và các **kịch bản test từng bước kèm kết quả mong đợi**, dùng dữ liệu demo có sẵn.
Tên người trong ngoặc là người cụ thể có trong dữ liệu demo hiện tại (nạp bởi `python -m app.demo`).

---
## 1. Chuẩn bị

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload      # mở http://localhost:8000   (Swagger: /docs)
```
- Đăng nhập bằng tài khoản ở mục 2. Phiên hết hạn sau 30 phút. Sai mật khẩu 5 lần → khóa 15 phút.
- **Làm mới dữ liệu** sau khi test: dừng server → `.venv/bin/python -m app.demo --reset` (xóa hết, tạo lại).
- Cần kiểm tra API/giới hạn mà giao diện chặn sẵn: mở `/docs` → nút **Authorize** → dán token (lấy từ `POST /api/auth/login`).
- Một số dữ liệu trong DB có thể do chính bạn tạo lúc thử trước đó (ví dụ phiếu bàn giao “QĐ số 01” của Ngô Quốc Tài), không phải demo.

## 2. Tài khoản (mật khẩu chung `Phms@2026dev`)
| Tài khoản | Vai trò | Thấy các tab |
|---|---|---|
| `officer1` / `officer2` | Cán bộ tiếp nhận (Trại 1 / 2) | Bảng điều khiển, Tiếp nhận & Hồ sơ, Chuyển trại. **Không thấy dữ liệu lâm sàng** |
| `nurse1` / `nurse2` | Điều dưỡng | 13 tab nghiệp vụ (trừ Báo cáo, Quản trị) |
| `doctor1` / `doctor2` | Bác sĩ | Như điều dưỡng + được chẩn đoán, kê/xác nhận đơn, hoàn tất khám, lập chuyển viện, kế hoạch theo dõi |
| `pharm1` / `pharm2` | Nhân viên dược | Cấp phát thuốc, Kê đơn (chỉ xem), Khám chữa bệnh (xem), Hồ sơ SK |
| `approver1` / `approver2` | Người phê duyệt/điều phối | Chuyển viện (không thấy lý do chuyên môn), Chuyển trại (xác nhận) |
| `manager1` / `manager2` | Quản lý y tế | Khám định kỳ, Bệnh lý & Cảnh báo, Chuyển viện, Báo cáo (không thấy chi tiết người bệnh) |
| `admin` | Quản trị hệ thống | Quản trị (người dùng, phân quyền, danh mục, nhật ký). **Không xem bệnh án** |

Trại 1 (F01) và Trại 2 (F02) **cách ly dữ liệu**: người dùng trại này không mở được hồ sơ của trại kia.

## 3. Luồng tổng thể (vòng đời một người)

```
 TIẾP NHẬN ──► KHÁM BAN ĐẦU ──► QUẢN LÝ / THEO DÕI ──────────────────────────► CHUYỂN TRẠI / KẾT THÚC
 officer      doctor+nurse      ├─ Khám định kỳ theo đợt (manager tạo đợt)        officer khởi tạo
 • kiểm tra   wizard 6 bước:    ├─ Bệnh mạn tính: kế hoạch → lịch → cảnh báo       nurse soạn tóm tắt y tế
   trùng      dị ứng → sinh     ├─ Khám phát sinh ──► chỉ định XN ─► kê đơn        officer/approver xác nhận
 • tạo hồ sơ  hiệu → chẩn đoán  │        │                  │          │            ► hồ sơ SK giữ nguyên,
 • mở kỳ giam → chỉ định/kê đơn │        └─ vượt khả năng ─► CHUYỂN VIỆN             trại mới tiếp nhận kỳ mới
   giữ        → kế hoạch →      │           doctor lập → approver duyệt →
              hoàn tất          │           nurse bàn giao → kết quả → doctor hoàn tất
              (→ "Đang quản lý")└─ CẤP CỨU (bất kỳ lúc nào): ghi nhận tối thiểu → bổ sung sau → đối soát → đóng
 THUỐC: bác sĩ kê & xác nhận ► dược cấp phát (đủ/một phần/hoàn trả) ► điều dưỡng ghi nhận ĐÃ DÙNG (3 sự kiện riêng)
 XUYÊN SUỐT: phân quyền theo vai trò + cơ sở · nhật ký kiểm toán · tài liệu y tế · báo cáo
```

**Bốn nguyên tắc nên soi khi test** (đây là “điểm ăn tiền” của thiết kế):
1. **Một người – một hồ sơ sức khỏe**, bất kể bao nhiêu đợt tiếp nhận / trại.
2. **Đã xác nhận thì không ghi đè**: sửa bằng addendum / phiên bản mới, có lý do và người làm.
3. **Kê đơn ≠ cấp phát ≠ sử dụng**: ba bước, ba người, ba bản ghi.
4. **Tách quyết định chuyên môn (bác sĩ) khỏi hành chính (duyệt, điều phối)**; cấp cứu không bị chặn bởi thủ tục.

Cách dùng chung: chọn **“Chọn người xử lý”** ở thanh trên cùng một lần – người đó dùng chung cho các tab Hồ sơ sức khỏe, Tài liệu… Việc đang chờ hiện ở **chuông thông báo** góc trên bên phải (menu bên trái không còn số). Số liệu tổng quan xem ở *Bảng điều khiển*.

---
## 4. Kịch bản test

Ký hiệu: **TK** = tài khoản · **✔** = kết quả mong đợi.

### A. Tiếp nhận & Hồ sơ (M01) – `officer1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| A1 | Tab *Tiếp nhận* → **+ Tiếp nhận mới** → nhập họ tên “Nguyễn Văn Test”, ngày sinh, mã `PN-26-9001` → *Kiểm tra & tiếp tục* → *Tạo hồ sơ mới* → *Xác nhận tiếp nhận* | Hồ sơ “Đã xác minh”; xuất hiện ở “Đang quản lý”, cột Khám ban đầu = “Chưa hoàn tất”; nurse/doctor thấy người này trong tab *Khám ban đầu* |
| A2 | Như A1 nhưng nhập mã `PN-26-0015` (đã thuộc Phan Ngọc Dũng) | Bước 2 liệt kê hồ sơ trùng. Bấm “Đây là người khác – tạo hồ sơ mới” → **lỗi “Đã tồn tại hồ sơ cùng mã nguồn”** |
| A3 | Nhập họ tên **Lê Minh Tuấn**, ngày sinh **02/02/1990**, mã mới | Hiện 2 hồ sơ nghi trùng. Vẫn tạo mới → hồ sơ mới **“Chờ đối soát”**, không bị tự gộp |
| A4 | Tạo không có mã | Hồ sơ “Chờ đối soát”. Nhập mã mà xóa “hệ thống nguồn” → báo lỗi 2 trường phải đi cùng nhau |
| A5 | Tab *Chờ đối soát danh tính* → **Đinh Minh Vinh** → *Đối soát* → hệ thống nguồn `QLPN`, mã `PN-26-9002`, căn cứ | Chuyển “Đã xác minh”. Thử mã đã có (`PN-26-0015`) → lỗi “cần quy trình gộp có phê duyệt” |
| A6 | *+ Tiếp nhận mới* với tên **Lý Xuân Phong** → *Dùng hồ sơ này* | Báo “đang ở cơ sở khác”; bấm tiếp nhận → **lỗi “đang trong một đợt tiếp nhận”** (phải chuyển trại trước) |
| A7 *(UAT-01)* | *Tra cứu hồ sơ* → **Trần Trọng Tài** (đã mãn hạn) → *+ Tiếp nhận kỳ mới* → *Mở hồ sơ sức khỏe* | Có **2 đợt tiếp nhận**, lịch sử khám cũ còn nguyên, **không** tạo hồ sơ sức khỏe mới |
| A8 | Với người vừa tạo ở A1 → *Hủy liên kết* (nhập lý do) | Đợt tiếp nhận “Đã hủy liên kết”. Với người đã có lượt khám (Phan Ngọc Dũng sau B1) → **lỗi “đã có dữ liệu lâm sàng”** |
| A9 | Tra cứu **Võ Thanh Sơn** | Hồ sơ chưa có đợt tiếp nhận nào (đăng ký xong chưa tiếp nhận) |

### B. Khám ban đầu (M03) – `doctor1`, `nurse1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| B1 | `doctor1` → *Khám ban đầu* → *Chờ khám* → **Phan Ngọc Dũng** → *Bắt đầu khám*. Đi đủ 6 bước: (1) *Xác nhận không có dị ứng* → (2) nhập mạch/HA/nhiệt độ → *Ghi nhận sinh hiệu* → (3) lưu tóm tắt + thêm chẩn đoán → (4) *+ Kê đơn* rồi *Xác nhận* → (5) *+ Hẹn tái khám* → (6) kiểm tra danh sách → *Hoàn tất khám ban đầu* | Lượt khám “Hoàn tất”; ở *Tiếp nhận* đợt tiếp nhận chuyển **“Đang quản lý”**; người đó sang tab “Đã hoàn tất” |
| B2 | Bước 6 khi chưa nhập sinh hiệu/chẩn đoán | Checklist hiện dấu “!” nhưng **không chặn** (chỉ chặn nếu còn chỉ định chờ kết quả) |
| B3 | `nurse1` làm lại wizard ở người khác | Không ghi được chẩn đoán (có ghi chú “chỉ bác sĩ”); bước 6 chỉ có thông báo, **không có nút Hoàn tất** |
| B4 | Mở **Lê Minh Cường** (*Đang khám dở*, đã có sinh hiệu) và **Lý Công Trung** (*Nháp*) → Tiếp tục | Dữ liệu cũ giữ nguyên, làm tiếp được |
| B5 | `/docs` → `POST /api/encounters` loại `initial` cho người đã khám ban đầu | **409** “Đợt tiếp nhận này đã có lượt khám ban đầu” |

### C. Khám chữa bệnh (M04) – `doctor1`, `nurse1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| C1 | *Khám chữa bệnh* → **+ Lượt khám mới** → chọn người → loại “Phát sinh” → nhập lý do | Mở bàn làm việc, trạng thái “Đang khám”. Tab *Sinh hiệu* để trống mọi ô → báo “Nhập ít nhất một chỉ số” |
| C2 *(UAT-04)* | Mở lượt khám của **Bùi Hữu Nghĩa** (Chờ kết quả: công thức máu + sốt rét) → *Hoàn tất khám* | **Lỗi “Còn chỉ định chưa có kết quả”**. Nhập kết quả cả 2 chỉ định → *Hoàn tất khám* thành công |
| C3 *(UAT-10)* | Lượt khám đã hoàn tất: thử sửa tóm tắt / thêm sinh hiệu | Không cho (lượt đã khóa). Tab *Tổng quan* → **+ Thêm addendum** (nội dung + lý do) → hiện trong dòng thời gian, phiên bản tăng |
| C4 | Hủy một lượt khám | Bắt buộc nhập lý do; sau đó không đổi trạng thái được nữa (xem lượt “đã hủy” của **Hồ Công Bình**) |
| C5 | Mở **cùng một lượt khám ở 2 trình duyệt** (doctor1 và nurse1) → cả hai sửa “Tóm tắt” rồi *Lưu* | Người lưu sau nhận **“Dữ liệu đã được người khác thay đổi”** (không ghi đè âm thầm) |
| C6 | Xem bảng sinh hiệu | Có 2 mốc: *Thời điểm đo* và *Ghi vào hệ thống* |

### D. Chỉ định & Kê đơn (M05) – `doctor1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| D1 *(UAT-02)* | Tạo lượt khám cho **Trần Thanh Quân** (dị ứng Amoxicillin) → kê *Amoxicillin 500mg* → đơn nháp có nhãn đỏ ⚠ → *Xác nhận* | Hộp “Cảnh báo an toàn”: **bắt buộc ghi chú xử lý** mới xác nhận được. `admin` → Nhật ký có `medication_warning_acknowledged` |
| D2 | **Bùi Ngọc Hùng** (dị ứng Aspirin) kê “Aspirin 81mg” | Cảnh báo dị ứng (khớp theo tên chất) |
| D3 | **Bùi Hữu Lộc** kê thêm *Amlodipine 5mg* | Cảnh báo **trùng đơn đang hiệu lực** |
| D4 | `nurse1` vào *Chỉ định & Kê đơn* | Chỉ xem: **không có** nút Kê/Xác nhận/Điều chỉnh. `doctor1` xác nhận đơn nháp Ibuprofen của **Hồ Công Bình** |
| D5 | Đơn đã xác nhận → *Điều chỉnh* (đổi liều + lý do) → xác nhận bản mới (mẫu: Bùi Ngọc Hùng) | Bản mới v2; bản cũ **“Đã thay bằng bản mới”**; không có nút sửa trực tiếp đơn đã xác nhận |
| D6 | *Dừng* một đơn (chọn kết cục + lý do). Với đơn đã cấp thuốc chọn “Hủy” | “Ngừng/Hoàn thành” được; “Hủy” bị chặn vì đã cấp phát |
| D7 | Seg *Chờ kết quả XN/thủ thuật* | Danh sách lượt khám đang chờ; bấm mở để nhập kết quả |

### E. Cấp phát thuốc (M06) – `pharm1`, `nurse1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| E1 *(UAT-03)* | *Hàng đợi* → **Hoàng Ngọc Khánh – Omeprazole 0/14** → *Cấp thuốc* số lượng **10** | Thông báo “**Cấp một phần – còn thiếu 4**”; trạng thái “Cấp một phần”; mục *Xác nhận sử dụng* vẫn **trống** (không tự thành “đã dùng”). Cấp tiếp 4 → “Đã cấp đủ”, biến khỏi hàng đợi |
| E2 | Thử cấp quá số còn lại | Ô nhập chặn >tối đa; qua `/docs` (`POST /api/medication-orders/{id}/dispenses`) → **409 OVER_DISPENSE** |
| E3 | Mở **Nguyễn Đình Trung** (Cetirizine) | Lịch sử có dòng **Hoàn trả 4**; thử hoàn trả quá số đã cấp → 409 |
| E4 | `nurse1` → *Ghi nhận sử dụng thuốc* trên đơn **chưa cấp** (Omeprazole trước E1) | Lỗi “Chưa có cấp phát”. Trên đơn đã cấp: chọn *Không dùng* mà bỏ trống lý do → lỗi; có lý do → ghi được (mẫu: Bùi Hữu Lộc có vài lần không dùng) |
| E5 | `pharm1` | **Không có** nút ghi nhận sử dụng, không sửa được chỉ định |
| E6 | Đơn nháp (Ibuprofen của Hồ Công Bình) | **Không** nằm trong hàng đợi cấp phát |

### F. Khám định kỳ (M07) – `manager1`, `nurse1`, `doctor1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| F1 *(UAT-05)* | `nurse1` mở đợt **Quý 4/2026** | Chỉ nhiệm vụ của Trại 1. `doctor2` chỉ thấy đợt “Trại 2” |
| F2 | Một nhiệm vụ → **Khám** → ghi sinh hiệu → (doctor1) *Hoàn tất khám* | Nhiệm vụ “Hoàn tất”, **thanh tiến độ tăng** |
| F3 | *Hoãn* (lý do + ngày hẹn mới) / *Không thực hiện* (lý do) | Hoãn sinh lịch mới; không cho thiếu lý do |
| F4 | Tab *Loại trừ* | Có lý do: “Đang điều trị ngoài trại”, “Đang chờ chuyển trại”, “Chưa hoàn tất khám ban đầu”, “Đã có lịch khám định kỳ khác đang mở” (nurse thấy tên; manager chỉ thấy mã rút gọn) |
| F5 | `manager1` → *+ Tạo đợt khám* (ngày hạn) | Báo số nhiệm vụ sinh ra / số loại trừ. **Chỉ người đang quản lý (đã khám ban đầu)** có nhiệm vụ; người mới tiếp nhận bị loại trừ với lý do “Chưa hoàn tất khám ban đầu”; người đã có lịch định kỳ khác đang mở bị loại “tránh trùng lịch” |
| F6 | `manager1` → *Khóa đợt & chốt kết quả* | Người chưa khám ghi **“Không thực hiện”** (không bỏ sót); đợt “Đã khóa”, không thao tác thêm |

### G. Bệnh lý & Cảnh báo (M08) – `nurse1`, `doctor1`, `manager1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| G1 | Tab *Cảnh báo* → **Tiếp nhận** một cảnh báo → **Xử lý xong** (nhập kết quả) | Có người chịu trách nhiệm + thời điểm xử lý; tiếp nhận lần 2 bị chặn. Có sẵn cảnh báo “đã nâng mức 1” |
| G2 *(sửa mới)* | Tab *Lịch tái khám & quá hạn* → dòng **Đinh Minh Phong** (trễ) → **Khám** → ghi sinh hiệu → *Hoàn tất khám* | Lịch cũ **biến khỏi danh sách quá hạn** (còn 3 dòng); ở *Tất cả lịch đang mở* xuất hiện **lịch kỳ kế tiếp** (cách hôm nay đúng “chu kỳ” ngày) |
| G3 | Cùng tab: *Hoãn* / *Không thực hiện* | Phải nhập lý do |
| G4 | Tab *Kế hoạch theo dõi* | Danh sách kế hoạch + “lần theo dõi tới” + nhãn quá hạn; *Kết thúc* kế hoạch → lịch mở bị đóng |
| G5 | Tab *Theo dõi người đang chọn* (chọn người trước) | Thêm vấn đề sức khỏe, lập kế hoạch (cần có vấn đề đang hiệu lực) |
| G6 | `admin` → Quản trị → *Tác vụ nền* → **Chạy ngay** | Hiện số liệu đã xử lý; chạy lại **không sinh cảnh báo trùng** (hệ thống cũng tự chạy mỗi 15 phút) |

### H. Chuyển viện (M09) – `doctor1`, `approver1`, `nurse1`
Tạo mới: *Chuyển viện* → **+ Lập đề nghị** (hoặc trong bàn làm việc, tab *Chuyển viện*). Mẫu có sẵn ở mọi trạng thái: Ngô Văn Dũng (nháp), Lý Minh Kiên (chờ xử lý), Đinh Ngọc Long (đã điều phối), Bùi Hữu Lộc (đang ngoài trại), Đặng Hữu Đông (có kết quả), Đinh Đức Kiên & Vũ Văn Hải (hoàn tất), Hồ Thanh Thắng (hủy).

| # | Các bước | ✔ Kết quả |
|---|---|---|
| H1 *(UAT-06)* | Đi trọn luồng với một đề nghị mới: doctor **Gửi duyệt** → approver **Phê duyệt & điều phối** (nhập nơi tiếp nhận) → nurse **Xác nhận đã rời trại** → nurse **Ghi nhận kết quả** → doctor **Hoàn thành** | Mỗi bước hiện nút đúng người; *Lịch sử điều phối* ghi từng mốc “xảy ra / nhập”; thanh tiến độ chạy hết |
| H2 | `doctor1` thử duyệt hộ approver | **Không có nút** “Phê duyệt”; qua `/docs` → **403** |
| H3 | `approver1` mở một đề nghị | **Không thấy lý do chuyên môn/kết quả** (“ẩn theo phân quyền”) |
| H4 | Ghi nhận kết quả mà bỏ trống; hoàn thành mà thiếu kế hoạch sau viện hoặc kết cục | Bị chặn, báo thiếu |
| H5 | “BV đổi / không tiếp nhận” ở trạng thái Đã điều phối | Quay về Chờ xử lý, bắt buộc lý do, lịch sử ghi lại |
| H6 | **Cấp cứu đi tắt**: lập đề nghị mức *Cấp cứu* → nút **Chuyển viện khẩn (đi tắt)** | Sang thẳng “Đang điều trị ngoài trại”, gắn **“Cần hậu kiểm”** + sinh cảnh báo. `approver1` mở **Ngô Minh Hoà** → **Hậu kiểm** → cờ và cảnh báo được đóng |
| H7 | Mở một đề nghị → mục *Tài liệu chuyển viện* → tải PDF (nurse/doctor) | Tài liệu gắn đúng đề nghị; **approver không thấy mục tài liệu** (không có quyền) |
| H8 *(BR-05)* | Sau chuyển viện, xem *Tiếp nhận* của người đó | Đợt tiếp nhận **vẫn “Đang quản lý”** (chuyển viện ≠ chuyển trại) |

### I. Cấp cứu (WF-08) – `nurse1`, `doctor1`, `officer1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| I1 *(UAT-07)* | *Cấp cứu* → **+ Ghi nhận cấp cứu** → “Chưa rõ danh tính” + mô tả tạm, bỏ trống mọi ô còn lại → lưu | Tạo được ngay (không cần đủ hồ sơ); sinh **hồ sơ tạm “[TẠM] …”** + lượt khám cấp cứu đang mở |
| I2 | Đổi *Thời điểm xảy ra* lùi >15 phút | Hiện ô **Lý do ghi nhận muộn** bắt buộc. Thẻ sự kiện hiển thị **“Xảy ra lúc” khác “Ghi vào hệ thống”** |
| I3 | Thêm vài **can thiệp** ở thẻ sự kiện | Dòng thời gian có người thực hiện + giờ nhập |
| I4 | `doctor1` → *Đóng sự kiện* khi chưa xong | **Lỗi, liệt kê 2 điều kiện**: hồ sơ khám chưa hoàn tất; danh tính chưa đối soát |
| I5 | Hoàn thiện: *Mở hồ sơ khám cấp cứu* → chẩn đoán → hoàn tất khám. Sau đó `officer1` → *Tiếp nhận* → “Chờ đối soát” → hồ sơ [TẠM] → *Đối soát* (mã thật). Cuối cùng `doctor1` *Đóng sự kiện* (có thể hẹn theo dõi) | Đóng thành công. *(Lưu ý: nút Đối soát nằm ở tab Tiếp nhận của cán bộ – bác sĩ/điều dưỡng không đối soát danh tính.)* |
| I6 | Xem các sự kiện mẫu | Vũ Minh Dũng (cơn tăng huyết áp, đã đóng), Trần Trọng Tài (ghi muộn vì mất điện, đã đóng), Ngô Minh Hoà (đang mở, đã chuyển viện khẩn) |

### J. Chuyển trại & Bàn giao (WF-07) – `officer1`, `nurse1`, `officer2`, `doctor2`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| J1 *(UAT-08)* | `officer1` → **+ Khởi tạo bàn giao** (chọn người, “Chuyển sang trại khác”, Trại 2, lý do) | Phiếu “Chờ xác nhận”, thanh tiến độ ở bước 2 |
| J2 | `officer1` bấm **Xác nhận bàn giao** ngay | **Lỗi “Chưa có tóm tắt y tế”** (duy trì trạng thái chờ) |
| J3 | `nurse1` → **Soạn tóm tắt y tế** | Phiếu sang bước 3; `officer1` chỉ thấy “đã có tóm tắt”, **không đọc được nội dung** |
| J4 | `officer1` xác nhận khi người còn điều trị/lịch mở (mẫu **Dương Ngọc Nghĩa**) | Hiện các chỉ số “đang mở”, **phải tick xác nhận** mới được xác nhận |
| J5 | Sau khi xác nhận | Đợt tiếp nhận ở Trại 1 “Đã chuyển trại”; lịch hẹn mở bị hoãn. `officer2` thấy phiếu “Tiếp nhận đến” → tạo **kỳ mới** ở Trại 2 → `doctor2` mở hồ sơ thấy **toàn bộ lịch sử** (mẫu **Lý Xuân Phong**, Ngô Quốc Tài) |
| J6 | Hình thức *Kết thúc quản lý* | Kỳ “Đã kết thúc”, không xóa dữ liệu (mẫu Trần Trọng Tài) |
| J7 | Tạo bàn giao thứ 2 cho cùng một người khi phiếu cũ còn chờ | **Lỗi “Đã có phiếu bàn giao đang chờ”** |

### K. Hồ sơ sức khỏe & Tài liệu (M02, M12) – `doctor1`, `nurse1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| K1 | Chọn người → *Hồ sơ sức khỏe*: các tab Tổng quan / Dị ứng & vấn đề / Thuốc / Lịch sử khám / Kế hoạch / Đợt tiếp nhận | Người chưa ghi dị ứng hiện **“Chưa ghi nhận”** (khác “đã xác nhận không dị ứng”); mục trống ghi “chưa có dữ liệu”, không suy ra “không bệnh” |
| K2 | *Tài liệu y tế* → **+ Tải lên** một PDF/PNG/JPG hợp lệ | Có dòng mới, có mã toàn vẹn (checksum); *Tải xuống* mở lại được đúng tệp |
| K3 | Tải tệp `.txt` đổi tên thành `.pdf`; tệp >10 MB; tệp `.exe` | Bị chặn (“Chỉ chấp nhận PDF/PNG/JPEG”, quá dung lượng) – hệ thống kiểm tra **nội dung thật**, không tin đuôi tệp |
| K4 | *Thay thế* một tài liệu; *Không hợp lệ* một tài liệu | Bản mới v2, bản cũ “Đã có bản thay thế”; bản sai “Không hợp lệ” kèm lý do – **không xóa/sửa tệp gốc** |
| K5 | `admin` → Nhật ký | Có `document_uploaded`, `document_download`… với người thực hiện |

### L. Báo cáo (M10) – `manager1` *(thử thêm `manager2` để so sánh trại)*
| # | Các bước | ✔ Kết quả |
|---|---|---|
| L1 *(UAT-12)* | *Tình hình khám chữa bệnh* → Xem báo cáo (mặc định 30 ngày) | Hiện **Số lượt khám** và **Số người đã khám** riêng (một người có thể nhiều lượt). Đối chiếu với danh sách ở tab *Khám chữa bệnh* |
| L2 | Đổi khoảng ngày / báo cáo khác (định kỳ, bệnh lý, cấp phát, chuyển viện, cảnh báo) | Số liệu thay đổi; “Cấp phát” có ghi chú *số đơn ≠ số lần uống* |
| L3 | **Xuất CSV** | Bắt buộc nhập mục đích; có tệp CSV; `admin` → Nhật ký có `report_exported` |
| L4 | So `manager1` với `manager2` | Số liệu **chỉ của cơ sở mình** |
| L5 | `nurse1` thử vào báo cáo | Không có tab; qua `/docs` → **403** |

### M. Phân quyền, bảo mật, nhật ký – nhiều tài khoản
| # | Các bước | ✔ Kết quả |
|---|---|---|
| M1 *(UAT-09)* | `officer1` mở một người trong *Tiếp nhận* | Chỉ thấy danh tính + đợt tiếp nhận; **không có** tab/chi tiết lâm sàng; gõ thẳng `#/record` hoặc `#/exam` → quay về tab được phép. Qua `/docs` gọi `GET /api/encounters/{id}` → **403** |
| M2 | `admin` | Chỉ có Quản trị; gọi API hồ sơ sức khỏe → 403 (không đọc bệnh án) |
| M3 | `doctor2` thử mở hồ sơ người Trại 1 (ví dụ qua `/docs`: `GET /api/persons/{id}/health-summary`) | **403 “ngoài phạm vi cơ sở”**; sự kiện `access_denied` vào nhật ký |
| M4 | Truy cập khẩn cấp (*break-glass*) – xem mục **O1–O3** | Có hộp thoại nhập lý do, quyền **chỉ đọc**, **tự hết hạn** (30 phút), sinh cảnh báo hậu kiểm |
| M5 | Đăng nhập sai 5 lần liên tiếp | **Khóa 15 phút** (mã 423) |
| M6 | Quản trị → Người dùng: tạo tài khoản (mật khẩu yếu bị từ chối: ≥10 ký tự, có hoa/thường/số), khóa/mở, đổi vai trò | Áp dụng ngay; tài khoản bị khóa/đổi quyền **mất phiên đang dùng** |
| M7 | Quản trị → *Ma trận phân quyền* | Đối chiếu từng vai trò với bảng mục 2; *sysadmin không có “Xem dữ liệu lâm sàng”* |
| M8 | Quản trị → *Nhật ký kiểm toán* → lọc theo người/hành động → **Kiểm tra toàn vẹn chuỗi** | “Chuỗi nhật ký toàn vẹn”. Dữ liệu demo có sẵn 4+ sự kiện bị từ chối và 1 break-glass |
| M9 | Quản trị → *Danh mục* → thêm/cập nhật một thuốc | Sinh **phiên bản mới**, bản cũ giữ; mục mới dùng được khi kê đơn. Kê mã thuốc không có trong danh mục (qua API) → 422 |

---
### P. Mật khẩu & xác thực 2 lớp – `admin` + một tài khoản MỚI do bạn tạo *(đừng dùng tài khoản mẫu để thử MFA/đổi mật khẩu)*
| # | Các bước | ✔ Kết quả |
|---|---|---|
| P1 | `admin` → Quản trị → Người dùng → **+ Tạo người dùng** (vai trò Điều dưỡng, Trại 1, mật khẩu ban đầu hợp lệ). Đăng nhập bằng tài khoản đó | Hiện màn hình **“Đổi mật khẩu lần đầu”**, chưa vào được hệ thống. Nhập mật khẩu mới yếu/không khớp → báo lỗi. Đổi đúng → vào Bảng điều khiển |
| P2 | Bấm tên ở góc trên phải → **Tài khoản của tôi** → Đổi mật khẩu (nhập sai mật khẩu cũ rồi nhập đúng) | Sai → báo “Mật khẩu cũ không đúng” **và không bị đăng xuất**; đúng → “Đã đổi mật khẩu”, phiên cũ ở máy khác bị thu hồi |
| P3 | Tab **Xác thực 2 lớp** → Bật → quét QR (hoặc nhập khóa) bằng Google/Microsoft Authenticator → nhập mã 6 số. Đăng xuất, đăng nhập lại | Sau mật khẩu, hệ thống **đòi mã 6 số**; mã sai bị từ chối; mã đã dùng không dùng lại được; sai 5 lần → khóa 15 phút |
| P4 | `admin` → Người dùng → **Đặt lại MFA** cho tài khoản trên | Tài khoản đăng nhập lại chỉ bằng mật khẩu; có nhật ký `mfa_reset` |
| P5 | `admin` → **Đặt lại mật khẩu** | Hiện **mật khẩu tạm một lần** (đóng rồi không xem lại được). Mật khẩu cũ vô hiệu; đăng nhập bằng mật khẩu tạm → bị buộc đổi |
| P6 | (Cấu hình) đặt `PHMS_MFA_REQUIRED_ROLES=approver`, đăng nhập `approver1` | Bị buộc đăng ký MFA trước khi dùng; không tự tắt MFA được |

### Q. Gộp hồ sơ trùng có phê duyệt – `officer1`, `approver1` *(cần dữ liệu demo mới: có sẵn cặp “Phạm Quốc Khánh”)*
| # | Các bước | ✔ Kết quả |
|---|---|---|
| Q1 | `officer1` → Tiếp nhận → *Chờ đối soát danh tính* → mở hồ sơ “Phạm Quốc Khánh” (không mã) → **Đề nghị gộp hồ sơ** | Thấy hồ sơ nghi trùng (có mã PN). Chọn hồ sơ giữ lại, nhập căn cứ ≥10 ký tự → “Đã gửi đề nghị” |
| Q2 | Tab **Đề nghị gộp hồ sơ** (cùng tài khoản) → mở đề nghị | Trạng thái **Chờ duyệt**; **không có nút Duyệt** (bốn mắt), chỉ có *Rút đề nghị* |
| Q3 | `approver1` → chuông thông báo → bấm “Đề nghị gộp hồ sơ trùng chờ duyệt” (hoặc Tiếp nhận → Đề nghị gộp hồ sơ) → xem 2 hồ sơ → **Duyệt & gộp** (xác nhận) | “Đã gộp hồ sơ”; liệt kê số bản ghi đã chuyển; `officer1` nhận thông báo kết quả. Hồ sơ bị gộp ở trạng thái **Đã gộp**, không còn trong tra cứu, **không tạo được kỳ mới**; dữ liệu nằm ở hồ sơ giữ lại. Từ chối thì bắt buộc nêu lý do |
| Q4 | Thử tạo mới một hồ sơ cùng họ tên + ngày sinh (Tiếp nhận mới) | Bước 2 cảnh báo trùng; chỉ tạo được khi bấm “Đây là người khác”. Qua API không kèm xác nhận → 409 `DUPLICATE_SUSPECTED` |

### R. Ưu tiên khám, tài liệu bàn giao chuyển viện, sửa kế hoạch – `doctor1`, `approver1`, `nurse1`
| # | Các bước | ✔ Kết quả |
|---|---|---|
| R1 | `doctor1` → Khám chữa bệnh → **+ Lượt khám mới** → chọn *Mức ưu tiên* = Khẩn cấp | Ca xuất hiện **đầu danh sách** kèm nhãn “Khẩn cấp”; cấp cứu luôn ở mức này |
| R2 | `doctor1` → Chuyển viện → Lập đề nghị → tick tài liệu ở mục **Tài liệu bàn giao kèm** → Lưu; mở chi tiết → **Chọn tài liệu** để đổi | Hiện đúng tài liệu đã chọn; chỉ đổi được khi chưa chuyển đi. Tài liệu của người khác/bản đã bị thay thế bị từ chối |
| R3 | `approver1` mở cùng đề nghị | Thấy **có** tài liệu (loại, phiên bản) nhưng **không thấy tên tệp**, không có nút sửa |
| R4 | `doctor1` → Bệnh lý & Cảnh báo → *Kế hoạch theo dõi* → **Sửa** (đổi chu kỳ 14→30 ngày, mục tiêu, chỉ số) | Cập nhật; **lịch theo dõi đang mở dời theo chu kỳ mới**; `nurse1` không có nút Sửa; hai người sửa cùng lúc → báo xung đột phiên bản |

### S. Sao lưu & phục hồi – quản trị hạ tầng *(dòng lệnh, trên CSDL thử)*
| # | Các bước | ✔ Kết quả |
|---|---|---|
| S1 | `python -m app.backup create --out ./backups` rồi `verify <gói> --check-docs` | Gói `.tar.gz` quyền 0600; `ok:true`; thống kê khớp CSDL |
| S2 | `restore <gói> --db-url … --storage-dir …` sang nơi **khác** | Tự kiểm: chuỗi nhật ký toàn vẹn, mọi tài liệu giải mã & khớp checksum; chạy ứng dụng trên bản phục hồi đọc được dữ liệu, ghi mới được |
| S3 | Sửa 1 byte trong gói rồi `verify`/`restore` | **Từ chối** (sai SHA-256) |

### N. Thông báo – mọi tài khoản (xem thêm [05-he-thong-thong-bao.md](05-he-thong-thong-bao.md))
Mở **hai trình duyệt/cửa sổ ẩn danh** (một người thao tác, một người nhận) để thấy thông báo đến trực tiếp (tối đa ~20 giây, hoặc bấm sang tab khác rồi quay lại để nhận ngay).
| # | Các bước | ✔ Kết quả |
|---|---|---|
| N1 | Menu bên trái | **Không còn số** màu cam; chuông ở góc trên phải có số chưa đọc |
| N2 | `nurse1` mở chuông | Danh sách nhóm “Hôm nay / Trước đó”, dòng chưa đọc có chấm + chữ đậm, mức **Khẩn** có viền đỏ; tab *Chưa đọc* chỉ liệt kê chưa đọc |
| N3 | Bấm một thông báo | Tự **đánh dấu đã đọc** (số giảm 1) và **mở đúng nơi cần xử lý** (vd chuyển viện → mở đúng hồ sơ; đơn thuốc → mở đúng đơn; lượt khám → mở đúng lượt) |
| N4 | `doctor1` ghi nhận **cấp cứu** → `nurse1` (cùng trại) | Trong ≤20 giây: chuông chuyển **đỏ**, số tăng, hiện toast “🔔 CẤP CỨU…”, tiêu đề tab thành “(n) PHMS…”. `doctor1` (người ghi) **không** nhận; `doctor2`/`nurse2` (trại khác) **không** nhận |
| N5 | `doctor1` gửi duyệt một đề nghị chuyển viện | `approver1` nhận “chờ phê duyệt” (có tên người bệnh, **không có** lý do chuyên môn). Đề nghị mức *Cấp cứu* đi tắt → `approver1` **và** `manager1` nhận mức Khẩn; `manager1` **không thấy tên** người bệnh |
| N6 | `nurse1` nhập kết quả xét nghiệm | **Chỉ bác sĩ đã chỉ định** nhận “Có kết quả…” |
| N7 | `doctor1` xác nhận đơn thuốc | `pharm1` (và `nurse1`) nhận “Đơn thuốc mới chờ cấp phát”; `doctor1` không nhận |
| N8 | Bàn giao: `officer1` khởi tạo → `nurse1` soạn tóm tắt → `officer1` xác nhận | Lần lượt: `nurse1` nhận “cần soạn tóm tắt” → `officer1`/`approver1` nhận “sẵn sàng xác nhận” → `officer2` (trại nhận) nhận “có người chuyển đến” |
| N9 | Đăng nhập sai 5 lần một tài khoản; hoặc dùng break-glass (mục M4) | `admin` nhận “tài khoản bị khóa”/“truy cập khẩn cấp”; break-glass còn báo `manager` của người xem |
| N10 | Chuông → ⚙ **Cài đặt** | Bật/tắt từng nhóm (lưu bền sau khi tải lại); **Cấp cứu** và **Bảo mật** bị khóa (Bắt buộc). Tắt “Thuốc & xét nghiệm” → không còn nhận loại này |
| N11 | **Đọc tất cả**; nút **×** ẩn một thông báo | Số về 0, tiêu đề tab hết “(n)”; thông báo bị ẩn không hiện lại |
| N12 | `officer1` mở chuông | Chỉ thấy việc của cán bộ (đối soát, bàn giao…), **không có nội dung lâm sàng** |
| N13 | Chuông → ⚙ → bật **Thông báo trên trình duyệt**, chuyển sang tab khác rồi tạo sự kiện cấp cứu từ tài khoản khác | Có thông báo hệ điều hành chỉ ghi tiêu đề chung (**không có tên người bệnh**) |
| N14 | `/docs` (đăng nhập `doctor1`): `POST /api/notifications/{id}/read` với `id` thông báo của `nurse1` | **404** (không đọc được hộp thư người khác) |

### O. Các điểm đã rà soát cho khớp luồng (xem [06-ra-soat-luong-nghiep-vu.md](06-ra-soat-luong-nghiep-vu.md))
| # | Các bước | ✔ Kết quả |
|---|---|---|
| O1 *(10.1)* | `doctor2` → *Chọn người xử lý* → tìm **Bùi Hữu Lộc** (đang ở Trại 1) → chọn | Hiện hộp thoại **“Truy cập khẩn cấp (break-glass)”**; bấm Hủy → không chọn người nào |
| O2 | Nhập lý do <10 ký tự; rồi lý do hợp lệ → xác nhận | Lý do ngắn bị chặn. Hợp lệ: thẻ người hiện nhãn đỏ **“Truy cập khẩn cấp (chỉ đọc) đến HH:MM”**; xem được *Hồ sơ sức khỏe*, *Lịch sử khám* |
| O3 | Cùng phiên, thử ghi dữ liệu cho người đó (sinh hiệu, đơn thuốc…) / chờ quá hạn | Mọi thao tác **ghi** bị từ chối (chỉ đọc). Hết hạn → hồ sơ tự đóng, truy cập lại bị chặn. `manager2` và `admin` nhận thông báo **Khẩn**; có cảnh báo hậu kiểm ở tab *Bệnh lý & Cảnh báo* |
| O4 *(WF-04)* | `manager1` tạo đợt khám khi có người mới tiếp nhận | Người mới **không** có nhiệm vụ, nằm ở tab *Loại trừ* với lý do “Chưa hoàn tất khám ban đầu” |
| O5 *(BR-04)* | Kê và xác nhận một đơn có **ngày bắt đầu trong quá khứ**, số ngày ngắn đã hết (qua `/docs` hoặc sửa ngày) → `pharm1` cấp thuốc | Lỗi **“Đơn đã hết liệu trình”**; đơn không còn trong *Hàng đợi cấp phát*; đơn bắt đầu ở tương lai thì chưa cấp được |
| O6 *(WF-03 bước 6)* | `admin` → Tác vụ nền → Chạy ngay, khi có đơn sắp hết (≤3 ngày) hoặc đã hết liệu trình (mẫu: Amlodipine ở Trại 2; Metformin của một người tiểu đường ở Trại 1) | Bác sĩ nhận cảnh báo + thông báo “Đơn thuốc sắp/đã hết liệu trình”; không trùng khi chạy lại; sau khi bác sĩ **Dừng/Hoàn thành/Điều chỉnh** đơn, cảnh báo tự đóng ở lần chạy sau |
| O7 | Mở lượt khám có **đơn thuốc nháp** → *Hoàn tất khám* | **Lỗi “Còn đơn thuốc nháp chưa xác nhận”** – phải xác nhận hoặc dừng đơn trước |
| O8 | Lượt khám có đơn/chỉ định/đề nghị chuyển viện nháp → *Hủy lượt khám* (nhập lý do) | Hủy thành công và **các đơn, chỉ định, đề nghị nháp bị hủy theo**. Nếu đơn **đã cấp phát** hoặc chuyển viện **đang xử lý** → bị chặn |
| O9 *(WF-02 bước 3)* | Mở bất kỳ lượt khám nào (vd **Bùi Ngọc Hùng**) | Có thẻ **“Thông tin lâm sàng cần thiết”**: dị ứng, thuốc đang dùng, vấn đề sức khỏe đang mở |
| O10 *(WF-07)* | `officer1` xác nhận bàn giao (vd **Dương Ngọc Nghĩa**) → tab *Chờ cơ sở nhận tiếp nhận*; sau đó `officer2` tạo đợt tiếp nhận cho người đó | Phiếu có bước thứ 4 “Cơ sở nhận tiếp nhận”; khi cơ sở đích tạo kỳ mới, phiếu hiện **“biên nhận hoàn tất”** và cơ sở gửi nhận thông báo |
| O11 | `officer1` xác nhận bàn giao khi người còn điều trị mở | Có ô **tick xác nhận** (cán bộ không thấy chi tiết điều trị nhưng vẫn xác nhận được) |
| O12 *(WF-06)* | Hoàn thành một chuyển viện với kết cục **Tử vong** hoặc **Không trở lại trại** | Hồ sơ gắn **“cần hậu kiểm”**; `approver`/`manager` nhận thông báo Khẩn; chỉ đóng cờ khi người phê duyệt **Hậu kiểm** |

## 5. Ánh xạ UAT (mục 12.2 tài liệu thiết kế) → nơi test trên giao diện
UAT-01 → A7 · UAT-02 → D1 · UAT-03 → E1 · UAT-04 → C2 · UAT-05 → F1 · UAT-06 → H1 · UAT-07 → I1–I5 · UAT-08 → J1–J5 · UAT-09 → M1 · UAT-10 → C3, D5 · UAT-11 → K2, K5 · UAT-12 → L1.

## 6. Những điều CHƯA có / hành vi cố ý – đừng báo nhầm là lỗi
- **Tài khoản mẫu giữ nguyên** (mật khẩu chung, không bị ép đổi, không MFA) để test không gián đoạn. Muốn thử đổi mật khẩu/MFA/đặt lại: **tạo tài khoản mới** ở Quản trị (mục P). Trước khi dùng thật xem [07-van-hanh-production.md](07-van-hanh-production.md) mục 5.
- **Gộp hồ sơ không tự động** (cố ý): phải có đề nghị và người khác duyệt (mục Q); đã gộp thì không hoàn tác.
- **Cảnh báo dị ứng có nhóm thuốc cố định** (penicillin/beta-lactam, cephalosporin, sulfonamide, NSAID, quinolone, macrolide): dị ứng Penicillin → cảnh báo khi kê Amoxicillin (“cùng nhóm”). Nhóm thuốc khác ngoài danh sách chưa được phủ.
- **SSO**: chỉ bật khi cấu hình IdP; chưa thử với IdP thật.
- **Chưa có**: kho dược (nhập-xuất-tồn, lô, hạn), tích hợp HIS/EMR/LIS/hệ thống quản lý phạm nhân, ký số, offline, đa trại ngoài 2 trại demo, FHIR.
- Người [TẠM] từ cấp cứu và người chưa đối soát vẫn nằm trong hàng đợi *Khám ban đầu* – cố ý để không bỏ sót.
- Hồ sơ cũ của người đã chuyển trại vẫn xem được ở trại cũ (đã từng có quan hệ điều trị); trại khác (chưa từng có quan hệ) thì không, trừ khi break-glass.
- Dữ liệu demo: thời điểm lùi về quá khứ là `occurred_at`; **“Ghi vào hệ thống”** là lúc nạp dữ liệu (giống nhập bổ sung). Tổng nhiệm vụ của đợt Quý 3 gồm cả lịch sinh ra khi hoãn.
- Bản chạy demo dùng SQLite một tệp; production dùng PostgreSQL (đã kiểm chứng – xem 02 và 07). Đã có test tải, soak 12 phút, sao lưu/phục hồi và accessibility; **chưa soak nhiều giờ**.

## 7. Cách ghi nhận lỗi
Mỗi lỗi ghi: **mã kịch bản** (vd C2) · tài khoản · bước làm · kết quả mong đợi / thực tế · ảnh chụp · thời điểm (để tra `Quản trị → Nhật ký`) · mức độ (chặn nghiệp vụ / sai dữ liệu / sai quyền / giao diện).
Lỗi **sai quyền hoặc lộ dữ liệu y tế** luôn ở mức cao nhất. Thông báo lỗi trả về dạng `{error:{code,message}}` – kèm `code` khi báo lỗi.
