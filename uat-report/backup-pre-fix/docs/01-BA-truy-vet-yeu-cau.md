# 01 – BA: Truy vết yêu cầu → hiện thực → kiểm thử

Nguồn: *PHMS – Tài liệu phân tích nghiệp vụ & thiết kế giải pháp v1.0 (11/11/2026)*. Nhóm BA/Dev/QC.

## 1. Phân hệ Core (mục 6)
| Mã | Phân hệ | Module code | Endpoint chính | WF | Test |
|---|---|---|---|---|---|
| M01 | Hồ sơ phạm nhân | `modules/identity.py` | `/persons`, `/persons/{id}/stays`, `/stays/{id}/handover` | 01, 07 | UAT-01/08, BR-01/05, wf01, wf07 |
| M02 | Hồ sơ sức khỏe | `clinical.py` | `/persons/{id}/health-summary`, `/allergies` | 01–09 | UAT-01/09, BR-07 |
| M03 | Khám ban đầu | `clinical.py` | `/encounters` (type=initial) | 01 | wf01 |
| M04 | Khám chữa bệnh | `clinical.py`, `emergency.py` | `/encounters/*`, `/emergency-events` | 02, 08 | UAT-04/07/10 |
| M05 | Chỉ định & kê đơn | `clinical.py`, `medication.py` | `/encounters/{id}/orders`, `/medication-orders` | 02, 03 | UAT-02/10, BR-04 |
| M06 | Điều trị & cấp phát | `medication.py` | `/dispenses`, `/administrations`, `/dispense-queue` | 03, 05 | UAT-03, BR-04 |
| M07 | Khám định kỳ | `scheduling.py` | `/checkup-rounds` | 04 | wf04 |
| M08 | Bệnh lý & cảnh báo | `scheduling.py` | `/problems`, `/care-plans`, `/alerts`, `/scheduler/run` | 04, 05 | wf05 |
| M09 | Chuyển viện | `referral.py` | `/referrals`, `PATCH /referrals/{id}/status` | 06, 08 | UAT-06, wf06 |
| M10 | Báo cáo | `reports.py` | `/reports/{encounters,checkups,health-problems,dispensing,referrals,alerts}` | – | UAT-12 |
| M11 | Người dùng & phân quyền | `admin.py`, `permissions.py`, `deps.py` | `/auth/*`, `/users`, `/audit` | – | UAT-09, rbac, audit |
| M12 | Tài liệu y tế | `documents.py` | `/documents` | 06, 07, 09 | UAT-11, documents |

## 2. Business rules (mục 7.1)
| BR | Cách hiện thực |
|---|---|
| BR-01 | `person.id` UUID nội bộ; unique `(source_system, external_id)`; trùng tên+ngày sinh → API trả `409 DUPLICATE_SUSPECTED` (kèm ứng viên), chỉ tạo khi xác nhận “người khác” (`confirm_distinct`) → `pending_verification` + `duplicate_candidates`, **không tự gộp**; `/persons/{id}/verify` để đối soát; **gộp chỉ qua đề nghị + phê duyệt bốn mắt** (`/person-merges`) |
| BR-02 | Không có API DELETE; hủy = `cancelled` + lý do; Encounter hoàn tất chỉ sửa bằng **addendum**; đơn thuốc đã xác nhận chỉ **revise** (version+1) |
| BR-03 | Mọi sự kiện có `occurred_at` & `recorded_at`; không cho thời gian tương lai; cấp cứu ghi muộn >15' bắt buộc `late_entry_reason` |
| BR-04 | `DispenseEvent` chỉ tạo với đơn `confirmed/active`; tổng cấp ròng ≤ số kê; hoàn trả/hủy là sự kiện riêng tham chiếu lần cấp |
| BR-05 | Referral, Handover và CustodyStay là các máy trạng thái độc lập; HealthRecord 1:1 Person, không bị ảnh hưởng |
| BR-06 | Header `Idempotency-Key` (encounter, đơn thuốc, cấp phát, chuyển viện); cột `version` + `expected_version` → 409 |
| BR-07 | `allergy_status` = unknown/recorded/none_confirmed; summary trả `notice`; báo cáo không suy "không có" từ "chưa có" |

## 3. Quyết định thiết kế của nhóm (chỗ tài liệu để mở)
| # | Quyết định | Lý do / liên quan câu hỏi |
|---|---|---|
| D1 | Chỉ hỗ trợ **phạm nhân** (không tạm giữ/tạm giam) | Giả định 1.4, Q01 |
| D2 | **Break-glass** là *lượt cấp có hạn do máy chủ quản lý* (`POST /persons/{id}/break-glass`, mặc định 30 phút, **chỉ đọc**, lý do ≥10 ký tự, có hộp thoại trên giao diện; header `X-Break-Glass-Reason` vẫn tạo lượt cấp có hạn); ghi audit + Alert + thông báo hậu kiểm | Mục 10.1 "do khách hàng phê duyệt" – cần xác nhận chính sách |
| D3 | Kho dược **không** có nhập-xuất-tồn; chỉ ghi nhận cấp phát | Q06, WF-03 ("không giả lập tồn kho") |
| D4 | Truy cập lâm sàng = người dùng thuộc cơ sở từng có đợt tiếp nhận với người đó (kể cả lịch sử); chuyển trại → cơ sở đích truy cập sau khi tạo kỳ tiếp nhận mới | Mục 10.1 ABAC; Q02 |
| D5 | Cấp cứu tạo **hồ sơ tạm** + đợt tiếp nhận `provisional`; đóng sự kiện chỉ khi hồ sơ hoàn tất **và** danh tính đã đối soát | WF-08 |
| D6 | Gộp 2 hồ sơ trùng: **đã làm** theo quy trình đề nghị → người khác duyệt (bốn mắt) → chuyển toàn bộ dữ liệu, hồ sơ nguồn giữ lại ở trạng thái `merged`; không hoàn tác; chặn khi cả hai cùng có đợt tiếp nhận đang hiệu lực | BR-01, rủi ro 13.3; Q02/Q03 cần khách xác nhận quy trình |
| D7 | Chuyển viện khẩn (`urgency=emergency`) được **đi tắt** tới `in_external_treatment`, đặt `needs_post_review` + Alert; người duyệt hậu kiểm | Mục 8 "đường tắt, lưu hậu kiểm" |
| D8 | Người điều phối (approver/manager) xem Referral **không có** lý do/kết quả lâm sàng | Mục 3.1 tách quyết định chuyên môn – hành chính |
| D9 | Xuất CSV cần quyền `report.export` + nêu mục đích, có audit; không có xuất hàng loạt hồ sơ | Mục 10.1 |
| D10 | Tài liệu: chỉ PDF/PNG/JPEG (kiểm magic bytes), ≤10MB, mã hóa Fernet khi lưu, SHA-256, hook quét mã độc (`scan_bytes`) | WF-09 |

## 4. Chưa thuộc Core / cần quyết định (mục 13.2)
Q01–Q10 vẫn mở. Hiện chưa có: tích hợp HIS/EMR/LIS/QLPN (chỉ có `source_system+external_id`), ký số, offline, kho dược, FHIR, phê duyệt gộp hồ sơ, SSO/LDAP, phân loại cấp độ ATTT, RPO/RTO. Các mục này nên chốt tại workshop đầu tiên (13.4).

## Bổ sung (QC đợt 3) – mục 10.1 bảo mật & vận hành
| Yêu cầu | Hiện thực |
|---|---|
| Quản lý mật khẩu | Đổi mật khẩu tự phục vụ; tài khoản mới bị buộc đổi lần đầu; quản trị đặt lại (mật khẩu tạm một lần); khóa sau 5 lần sai; chính sách độ mạnh; thu hồi phiên khi đổi |
| MFA cho vai trò đặc quyền | TOTP RFC 6238 (`PHMS_MFA_REQUIRED_ROLES`), chống dùng lại mã, bí mật mã hóa khi lưu |
| SSO | OIDC authorization code + PKCE (`modules/sso.py`), không tự tạo tài khoản; **mới kiểm bằng IdP giả lập** |
| Bảo vệ truyền tải/ứng dụng | CSP, HSTS, Permissions-Policy, COOP/CORP, `/docs` tắt ở production, từ chối khởi động nếu secret mặc định |
| BR-06 | Idempotency-Key cho mọi API tạo bản ghi nghiệp vụ; giao diện tự gắn khóa và thử lại an toàn |
| WF-02 ưu tiên · WF-05 sửa kế hoạch · WF-06 tài liệu bàn giao | `Encounter.priority`; `PATCH /care-plans/{id}` (dời lịch theo chu kỳ); `Referral.handover_docs` (kiểm đúng người, tài liệu hợp lệ) |
| NFR-03 sao lưu/phục hồi | `python -m app.backup` (SQLite + PostgreSQL + tài liệu mã hóa, bản kê SHA-256, tự kiểm sau phục hồi) |
| NFR-01/02 hiệu năng · tính sẵn sàng | Đã kiểm: tải 30–100 người dùng, soak 12 phút trên PostgreSQL (xem 02) |
| Khả năng tiếp cận | WCAG 2.1 A/AA (axe-core) mọi tab × mọi vai trò, sáng/tối; bàn phím, focus hộp thoại, vùng `<main>`, liên kết bỏ qua điều hướng |
