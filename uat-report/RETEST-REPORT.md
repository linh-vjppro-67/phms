# Báo cáo sửa lỗi & kiểm thử lại (Retest) – PHMS

| | |
|---|---|
| Ngày | 14/11/2026 |
| Tiếp nối | [UAT-REPORT.md](UAT-REPORT.md) (13/11/2026: 156 ca, 143 PASS / 11 FAIL / 2 BLOCKED, khuyến nghị NO-GO). **Báo cáo đó giữ nguyên làm mốc "trước khi sửa".** |
| Được phép sửa mã | Có – người dùng cho phép sửa các lỗi/vướng mắc phát hiện trong UAT (14/11) |
| Sao lưu mã gốc | `uat-report/backup-pre-fix/` (app, src, docs trước khi sửa; thư mục không có git) |
| Dữ liệu thật | Không đụng tới: MD5 `backend/phms.db` trước/sau = `b652e8ad645a4e062537a8f0caaf0c63`; máy chủ cổng 8000 của người dùng không bị dừng/đổi |
| Trạng thái | **Báo cáo của người kiểm thử – chưa phải kết luận chấp nhận UAT/Go-Live.** Quyết định thuộc người có thẩm quyền |

## 1. Kết quả tóm tắt

| Phép kiểm | Trước sửa | Sau sửa |
|---|---|---|
| UAT 156 ca trên staging (SQLite) | 143 PASS · 11 FAIL · 2 BLOCKED | **157/157 PASS** (156 ca + 1 ca mới EXP-10b) |
| BG-02b (mới): hết hạn break-glass thật, cấu hình 1 phút, chờ quá hạn | chưa kiểm được | **PASS** (cấp 1,0 phút; trước hạn 200; sau hạn 403 `FACILITY_SCOPE`, `active=false`) |
| Test tự động (pytest) trên SQLite tệp | 139 pass | **153 pass, 2 skip** |
| Test tự động trên **PostgreSQL 16 thật** | chưa chạy | **155 pass, 0 skip** |
| Tranh chấp trên PostgreSQL + 4 worker (`race-pg.mjs`) | chưa chạy | khám ban đầu 5 lần×8 yêu cầu → luôn **1×201 + 7×409**; confirm/revise/duyệt ×6 → đúng **1** thành công, đúng 1 sự kiện |
| Test hồi quy mới có bắt được lỗi cũ không | – | **Có**: chạy bộ test hồi quy mới (12 test ở thời điểm kiểm; nay là 14) trên mã gốc → fail (3 khám ban đầu trùng, 4/4 confirm cùng thành công…); trên mã mới → pass |
| Production-like (PostgreSQL, `PHMS_ENV=production`, 4 worker) | chưa chạy | khởi động OK; `/docs` 404; HSTS+CSP; đăng nhập tài khoản mẫu 401; admin bootstrap bị buộc đổi mật khẩu |

Bằng chứng: `retest/evidence/` (`results.after-fix.json`, `results.before-fix.json`, `results.bg02b.json`, `race-pg.txt`, `logs/<ID>.txt` từng ca, `shots/`, `changed-tcs.md`). Kịch bản chạy lại: `scripts/` (đã cập nhật; thêm `bg02b.mjs`, `race-pg.mjs`, `uat-server2.sh`).

## 2. Từng lỗi: nguyên nhân gốc → cách sửa → bằng chứng

| Mã | Mức | Nguyên nhân gốc | Sửa | Ca kiểm chứng |
|---|---|---|---|---|
| **DEF-01** | Critical | `documents.py` dùng `ensure_clinical_access` (quyền *đọc*) cho tải lên/thay thế/vô hiệu hóa, nên người đang break-glass ghi được tài liệu | Thêm `deps.ensure_not_break_glass_only`: ghi tài liệu cần **thuộc cơ sở có quan hệ quản lý** (break-glass → 403 `BREAKGLASS_READ_ONLY`, có nhật ký từ chối). Không đòi đợt tiếp nhận đang hiệu lực, để cơ sở cũ vẫn đính chính tài liệu của mình. Kèm: `replace` kiểm quyền **trước** khi lộ trạng thái tài liệu; `invalidate` tài liệu đã không hợp lệ → 409 (không ghi đè lý do cũ) | BG-03, test `test_def01_*` |
| **DEF-02** | High | `create_encounter` kiểm tra "đã có khám ban đầu" rồi mới ghi, không khóa | `lock_row(CustodyStay)` + kiểm tra lại trạng thái đợt trước khi kiểm tra trùng. Yêu cầu đến sau nhận 409 `INITIAL_EXISTS`. Không thêm ràng buộc unique ở DB (tránh migration trên dữ liệu thật) | EXP-01 (5 lần), DC-12, `race-pg` |
| **DEF-03** | Medium | Thiếu khóa ở xác nhận đơn, điều chỉnh đơn, dừng đơn, đổi trạng thái chuyển viện, nhận/xử lý cảnh báo | `lock_row` trước khi đọc điều kiện ở: `confirm_order`, `revise_order`, `stop_order`, `referral.change_status`, `ack_alert`, `resolve_alert`. Người đến sau nhận 409 như các lần gọi tuần tự | EXP-24, 24b, 25, 25c, `race-pg` |
| **DEF-04** | Medium | `create_referral` không kiểm tra trạng thái lượt khám | Lượt khám `cancelled` → 409 `ENCOUNTER_CANCELLED`. Lượt khám đã hoàn tất vẫn cho lập (chưa có yêu cầu chặn) | EXP-23, DC-09 |

## 3. Yêu cầu đã chốt với người dùng

**REQ-01 – dược sĩ và tab "Tiếp nhận & Hồ sơ".** Quyết định: làm theo thực hành của các EMR (dược sĩ được tra cứu bệnh nhân để cấp thuốc, nhưng không đăng ký/nhập viện). Kết quả: giữ tab ở chế độ **chỉ tra cứu**; backend vốn không cấp `person.write` nên không ghi được; ca NAV-pharm nay còn kiểm **không có nút** Tiếp nhận mới / Đối soát / Đề nghị gộp. Đã sửa `docs/04` §2.
> Lưu ý trung thực: tôi không tra cứu tài liệu của từng hãng EMR trong phiên này; quyết định dựa trên hiểu biết chung về thực hành EMR và chỉ thị của người dùng. BA nên xác nhận lại với khách hàng.

**REQ-02 – tra cứu danh tính liên cơ sở (phương án b).** Chỉ vai trò có `person.write` (cán bộ tiếp nhận) tra liên cơ sở. Vai trò khác chỉ tìm/mở người có đợt tiếp nhận (không bị hủy) tại cơ sở mình, **hoặc hồ sơ do người của cơ sở mình lập** (để người điều phối vẫn thấy hồ sơ vừa lập chưa có đợt), hoặc đang có break-glass còn hạn. Áp dụng cho cả `GET /persons` và `GET /persons/{id}`.

**Hệ quả tôi phải xử lý thêm (ngoài yêu cầu, cần người dùng biết):** luồng break-glass trên giao diện đi qua "tìm người → chọn → hộp thoại khẩn cấp". Nếu chặn tìm kiếm hoàn toàn thì bác sĩ cơ sở khác **không có cách nào tìm người đang cần cấp cứu**. Giải pháp: người có quyền `breakglass` tìm được người ngoài cơ sở **chỉ khi gõ đúng toàn bộ mã nguồn** (không theo tên, không theo mã một phần, không có ngày sinh), chỉ trả thông tin tối thiểu, mỗi lần tra cứu ghi nhật ký `person_lookup_out_of_scope`; mở hồ sơ vẫn bắt buộc break-glass. Ca EXP-10b kiểm điều này. Nếu bạn muốn chặt hơn (bỏ hẳn tra cứu theo mã), chỉ cần xóa một khối lệnh trong `identity.search_persons`, nhưng khi đó cần một quy trình khác để cấp cứu người lạ cơ sở.

## 4. Đưa lên production – đã làm gì

| Hạng mục | Thay đổi |
|---|---|
| Khởi tạo không dùng tài khoản mẫu | Lệnh mới `python -m app.bootstrap --facility MÃ="Tên" …`: tạo cơ sở, danh mục, **một** quản trị viên (bắt buộc đổi mật khẩu; mật khẩu từ `PHMS_BOOTSTRAP_ADMIN_PASSWORD` hoặc sinh ngẫu nhiên in một lần). Chạy lại an toàn. Có dịch vụ `bootstrap` trong `docker-compose.yml` |
| Chặn cấu hình nguy hiểm khi khởi động | Production **từ chối chạy** nếu: secret/khóa tài liệu mặc định hoặc trùng nhau; dùng SQLite (trừ `PHMS_ALLOW_SQLITE=1`, chỉ cho điểm nhỏ một worker – vì `lock_row` chỉ có tác dụng trong một tiến trình); còn tài khoản mẫu dùng mật khẩu công khai (trừ `PHMS_ALLOW_SAMPLE_ACCOUNTS=1` cho môi trường đào tạo). `python -m app.seed` tự từ chối ở production |
| Dev/demo | **Không đổi**: tài khoản mẫu và mật khẩu `Phms@2026dev` giữ nguyên, không bị ép đổi (test `test_seeded_accounts_are_not_forced_to_change_password` vẫn pass) |
| Giám sát | `GET /api/health/ready` (kiểm tra CSDL, 503 khi lỗi); Dockerfile/compose dùng nó làm healthcheck |
| Đóng gói | `requirements.txt` chỉ còn phụ thuộc chạy; `requirements-dev.txt` (pytest, httpx). Thêm `.dockerignore` (trước đây `COPY frontend/` có thể kéo `node_modules` của máy dev đè lên bản cài trong image, và đưa dữ liệu/tệp thừa vào ngữ cảnh build) |
| Tài liệu | `docs/07` (mục 2, 3, 5, 9, 11, 12), `docs/04` (§2, O1), `deploy/phms.env.example`, README |

## 5. Còn lại / giới hạn – nói thẳng

1. **Chưa build được image Docker**: Docker daemon không chạy trong phiên. `docker compose config` hợp lệ; Dockerfile chưa chạy thật. Hãy chạy `docker compose -f deploy/docker-compose.yml build` trước khi giao.
2. **Chưa kiểm TLS/nginx thật** (`deploy/nginx.conf` chưa qua `nginx -t`) và hạ tầng của khách (sao lưu ra ngoài máy chủ, diễn tập phục hồi trên môi trường của họ). Các kiểm tra production ở đây chạy trên máy cục bộ (HTTP, PostgreSQL cục bộ).
3. **SSO chưa dùng**, theo chỉ đạo: đăng nhập tài khoản + mật khẩu (+ MFA) như hiện tại. Luồng SSO chỉ được test với IdP giả lập.
4. **Nhận cảnh báo đồng thời** chưa thử riêng trên PostgreSQL (DB seed không có cảnh báo); đã kiểm ở EXP-25c trên SQLite và dùng cùng cơ chế `lock_row` đã chứng minh trên PostgreSQL cho confirm/revise/duyệt.
5. **Thay đổi hành vi cần thông báo cho khách/QC**: (a) tài liệu đã không hợp lệ gọi `invalidate` lần nữa → 409; (b) người dùng cơ sở khác không còn tìm thấy người theo tên (kể cả khi trước đây dùng để mời hội chẩn); (c) production không chạy với SQLite hoặc tài khoản mẫu.
6. **Chưa sửa vì không có yêu cầu**: không thêm ràng buộc unique cho khám ban đầu ở DB; không đổi cơ chế `Idempotency-Key`; không kiểm tải/chịu tải lại.
7. **Việc do người dùng/khách làm trước go-live**: tạo `phms.env` thật (khóa riêng, `PHMS_MFA_REQUIRED_ROLES`), chạy bootstrap, tạo tài khoản thật, cấu hình sao lưu, chọn người ký chấp nhận UAT.

## 6. Điều kiện Go-Live (đề xuất, người có thẩm quyền quyết định)

- [x] DEF-01…04 đã sửa và retest đạt (staging SQLite + PostgreSQL 4 worker)
- [x] REQ-01/02 đã chốt và triển khai, có test
- [x] BG-02 (hết hạn) và SEC-05 (production) được kiểm với kết quả PASS
- [ ] Build image Docker + `nginx -t` + TLS trên máy chủ đích
- [ ] Chạy `app.bootstrap` trên PostgreSQL thật của khách, đổi mật khẩu admin, bật MFA, tạo ≥ 2 quản trị viên
- [ ] Diễn tập sao lưu/phục hồi trên hạ tầng của khách (`app.backup verify --check-docs`)
- [ ] BA xác nhận lại REQ-01/REQ-02 và cơ chế tra cứu khẩn cấp theo mã với khách hàng
- [ ] Người có thẩm quyền ký UAT Accepted

**Khuyến nghị của người kiểm thử:** các lỗi đã nêu ở UAT 13/11 đã được khắc phục và kiểm chứng; không còn lỗi mở nào trong 158 ca. Điều kiện NO-GO trước đây về mặt chức năng đã được gỡ; các mục chưa đánh dấu ở trên là việc hạ tầng/vận hành cần hoàn tất trước khi dùng dữ liệu thật.
