// M12 – Tài liệu y tế (WF-09): nguồn gốc, phiên bản, toàn vẹn, mọi lần xem/tải đều được ghi nhật ký.
import { DocsPanel } from "../components/blocks.jsx";
import { RequirePatient, usePatient } from "../patient.jsx";
import { Banner, PageHeader } from "../ui.jsx";

export default function Documents() {
  const { patient } = usePatient();
  return (
    <>
      <PageHeader title="Tài liệu y tế" sub="M12 · Giấy chuyển viện, giấy ra viện, kết quả xét nghiệm, biên bản bàn giao…" />
      <Banner tone="info"><span className="sm">Tệp được kiểm tra định dạng, quét mã độc, tính checksum và lưu mã hóa. Tài liệu đã lưu không sửa trực tiếp: dùng “Thay thế” (tạo phiên bản mới) hoặc “Không hợp lệ”.</span></Banner>
      <RequirePatient hint="Chọn người để xem và quản lý tài liệu của họ.">{patient && <DocsPanel key={patient.id} personId={patient.id} title={`Tài liệu của ${patient.name}`} />}</RequirePatient>
    </>
  );
}
