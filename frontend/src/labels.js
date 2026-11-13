// Nhãn tiếng Việt + màu cho từng loại trạng thái nghiệp vụ.
const D = {
  enc: { draft: ["Nháp", "neutral"], in_progress: ["Đang khám", "info"], awaiting_results: ["Chờ kết quả", "warn"], in_treatment: ["Đang điều trị", "info"], completed: ["Hoàn tất", "ok"], cancelled: ["Đã hủy", "neutral"] },
  encType: { initial: ["Khám ban đầu", "info"], periodic: ["Khám định kỳ", "neutral"], ad_hoc: ["Khám phát sinh", "neutral"], emergency: ["Cấp cứu", "bad"] },
  order: { draft: ["Chờ xác nhận", "warn"], confirmed: ["Đã xác nhận", "info"], active: ["Đang hiệu lực", "ok"], completed: ["Hoàn tất", "neutral"], stopped: ["Đã ngừng", "neutral"], cancelled: ["Đã hủy", "neutral"], superseded: ["Đã thay bằng bản mới", "neutral"] },
  dispense: { none: ["Chưa cấp", "neutral"], partial: ["Cấp một phần", "warn"], full: ["Đã cấp đủ", "ok"] },
  clin: { open: ["Chờ kết quả", "warn"], resulted: ["Đã có kết quả", "ok"], cancelled: ["Đã hủy", "neutral"] },
  appt: { scheduled: ["Đã lên lịch", "neutral"], due: ["Đến hạn", "info"], completed: ["Hoàn tất", "ok"], postponed: ["Hoãn", "warn"], not_done: ["Không thực hiện", "bad"] },
  referral: { draft: ["Dự thảo", "neutral"], pending: ["Chờ xử lý", "warn"], coordinated: ["Đã điều phối", "info"], in_external_treatment: ["Đang điều trị ngoài trại", "bad"], result_received: ["Đã có kết quả", "info"], completed: ["Hoàn tất", "ok"], cancelled: ["Đã hủy", "neutral"] },
  urgency: { routine: ["Thường", "neutral"], urgent: ["Khẩn", "warn"], emergency: ["Cấp cứu", "bad"] },
  stay: { received: ["Mới tiếp nhận", "warn"], managed: ["Đang quản lý", "ok"], transferred: ["Đã chuyển trại", "neutral"], ended: ["Đã kết thúc", "neutral"], voided: ["Đã hủy liên kết", "neutral"] },
  handover: { pending: ["Chờ xác nhận", "warn"], confirmed: ["Đã bàn giao", "ok"], cancelled: ["Đã hủy", "neutral"] },
  alert: { new: ["Mới", "bad"], acknowledged: ["Đã tiếp nhận", "warn"], resolved: ["Đã xử lý", "ok"], closed: ["Đã đóng", "neutral"] },
  round: { draft: ["Nháp", "neutral"], open: ["Đang thực hiện", "info"], locked: ["Đã khóa", "ok"] },
  priority: { routine: ["Thường", "neutral"], urgent: ["Ưu tiên", "warn"], emergent: ["Khẩn cấp", "bad"] },
  person: { verified: ["Đã xác minh", "ok"], pending_verification: ["Chờ đối soát", "warn"], merged: ["Đã gộp", "neutral"] },
  doc: { valid: ["Hợp lệ", "ok"], superseded: ["Đã có bản thay thế", "neutral"], invalid: ["Không hợp lệ", "bad"] },
  event: { open: ["Đang mở", "bad"], closed: ["Đã đóng", "ok"] },
  problem: { active: ["Đang hiệu lực", "warn"], resolved: ["Đã khỏi/kết thúc", "ok"] },
  allergy: { unknown: ["Chưa ghi nhận", "warn"], recorded: ["Có dị ứng", "bad"], none_confirmed: ["Đã xác nhận không dị ứng", "ok"] },
  plan: { active: ["Đang theo dõi", "info"], ended: ["Đã kết thúc", "neutral"] },
  result: { success: ["Thành công", "ok"], denied: ["Bị từ chối", "bad"], error: ["Lỗi", "bad"] },
};
export const statusLabel = (d, v) => D[d]?.[v]?.[0] ?? v ?? "";
export const statusTone = (d, v) => D[d]?.[v]?.[1] ?? "neutral";

export const ROLE_LABEL = {
  custody_officer: "Cán bộ tiếp nhận", nurse: "Điều dưỡng", doctor: "Bác sĩ", pharmacist: "Nhân viên dược",
  approver: "Người phê duyệt/điều phối", manager: "Quản lý y tế", sysadmin: "Quản trị hệ thống",
};
export const OUTCOME = { returned: "Đã trở lại trại", deceased: "Tử vong", not_returned: "Không trở lại" };
export const DOC_TYPE = { referral_letter: "Giấy chuyển viện", discharge_summary: "Giấy ra viện", lab_result: "Kết quả xét nghiệm", imaging: "Chẩn đoán hình ảnh", handover: "Biên bản bàn giao", consent: "Cam kết/đồng ý", other: "Khác" };
export const VITALS = [
  { type: "Mạch", unit: "lần/phút", key: "pulse" }, { type: "Huyết áp tâm thu", unit: "mmHg", key: "sys" },
  { type: "Huyết áp tâm trương", unit: "mmHg", key: "dia" }, { type: "Nhiệt độ", unit: "°C", key: "temp" },
  { type: "SpO2", unit: "%", key: "spo2" }, { type: "Nhịp thở", unit: "lần/phút", key: "rr" },
  { type: "Cân nặng", unit: "kg", key: "weight" }, { type: "Chiều cao", unit: "cm", key: "height" },
  { type: "Đường huyết", unit: "mmol/L", key: "glu" },
];
export const PERM_LABEL = {
  "person.read": "Xem danh tính", "person.write": "Tạo/đối soát hồ sơ", "person.merge.request": "Đề nghị gộp hồ sơ trùng", "person.merge.approve": "Duyệt gộp hồ sơ trùng", "stay.write": "Xác nhận tiếp nhận",
  "clinical.read": "Xem dữ liệu lâm sàng", "encounter.write": "Ghi lượt khám", "observation.write": "Ghi sinh hiệu/kết quả",
  "diagnosis.write": "Chẩn đoán", "encounter.complete": "Hoàn tất khám / addendum", "order.write": "Chỉ định XN/thủ thuật",
  "medorder.write": "Kê đơn", "medorder.confirm": "Xác nhận đơn thuốc", "dispense.write": "Cấp phát thuốc", "admin.write": "Ghi nhận dùng thuốc",
  "referral.read": "Xem chuyển viện", "referral.write": "Lập/hoàn tất chuyển viện", "referral.update": "Cập nhật điều phối", "referral.approve": "Phê duyệt chuyển viện",
  "problem.write": "Vấn đề sức khỏe", "careplan.write": "Kế hoạch theo dõi", "schedule.read": "Xem lịch/cảnh báo", "schedule.write": "Quản lý lịch hẹn",
  "alert.handle": "Xử lý cảnh báo", "checkup.manage": "Quản lý đợt khám định kỳ", "handover.initiate": "Khởi tạo bàn giao", "handover.summary": "Tóm tắt y tế bàn giao",
  "handover.confirm": "Xác nhận bàn giao", "document.read": "Xem tài liệu", "document.write": "Tải/sửa tài liệu", "emergency.write": "Ghi nhận cấp cứu",
  "emergency.close": "Đóng sự kiện cấp cứu", "report.read": "Xem báo cáo", "report.export": "Xuất dữ liệu", "user.manage": "Quản lý người dùng",
  "audit.read": "Xem nhật ký kiểm toán", "catalog.write": "Sửa danh mục", "catalog.read": "Xem danh mục", "scheduler.run": "Chạy tác vụ nền", "breakglass": "Truy cập khẩn cấp",
};
