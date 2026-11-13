// M02 – Hồ sơ sức khỏe cá nhân: một người – một hồ sơ xuyên suốt các đợt tiếp nhận.
import { useState } from "react";
import { api } from "../api";
import Workbench from "../components/Workbench.jsx";
import { AllergyBlock, DocsPanel, PlanBlock, ProblemBlock, RxTable } from "../components/blocks.jsx";
import { RequirePatient, SafetyBanner, usePatient } from "../patient.jsx";
import { Badge, Card, DataTable, Drawer, Empty, KV, PageHeader, Status, Tabs, fmtDT, fmtDate, useAuth, useLoad } from "../ui.jsx";

export default function Record() {
  const { has } = useAuth();
  const { patient, summary, refresh } = usePatient();
  const [tab, setTab] = useState("overview");
  const [open, setOpen] = useState(null);
  const pid = patient?.id;
  const meds = useLoad(() => api("GET", `/persons/${pid}/medication-orders`), [pid, tab], !pid || tab !== "meds");
  const encs = useLoad(() => api("GET", `/persons/${pid}/encounters`), [pid, tab], !pid || tab !== "history");
  const c = summary?.clinical;
  const p = summary?.person;
  return (
    <>
      <PageHeader title="Hồ sơ sức khỏe" sub="M02 · Một người – một hồ sơ sức khỏe, giữ nguyên khi chuyển trại hoặc tái tiếp nhận. “Chưa có dữ liệu” không có nghĩa là “không có bệnh”." />
      <RequirePatient hint="Chọn người ở thanh trên cùng để xem hồ sơ sức khỏe.">
        {!summary ? <Card><Empty title="Đang tải hồ sơ…" /></Card> : (
          <>
            <SafetyBanner summary={summary} />
            <Tabs value={tab} onChange={setTab} items={[{ id: "overview", label: "Tổng quan" }, { id: "alg", label: "Dị ứng & vấn đề sức khỏe", count: c ? c.allergies.length + c.problems.length : null }, { id: "meds", label: "Thuốc" },
              { id: "history", label: "Lịch sử khám", count: c?.recent_encounters.length }, { id: "plan", label: "Kế hoạch theo dõi" }, { id: "stays", label: "Đợt tiếp nhận", count: summary.stays.length }, has("document.read") && { id: "docs", label: "Tài liệu" }]} />
            {tab === "overview" && c && (
              <div className="cols">
                <Card title="Thông tin cá nhân"><KV items={[["Họ tên", p.full_name], ["Ngày sinh", fmtDate(p.date_of_birth)], ["Giới tính", p.gender], ["Mã nguồn", `${p.source_system || ""} ${p.external_id || ""}`], ["Danh tính", <Status key="s" d="person" v={p.status} />], ["Dị ứng", <Status key="a" d="allergy" v={c.allergy_status} />]]} /></Card>
                <Card title="Đang điều trị / theo dõi">
                  <KV items={[["Vấn đề sức khỏe", c.problems.filter((x) => x.status === "active").map((x) => x.name).join(", ") || "Chưa ghi nhận"], ["Thuốc đang hiệu lực", c.active_medications.map((m) => m.drug_name).join(", ") || "Không"], ["Chuyển viện đang mở", c.open_referrals.length], ["Lịch sắp tới", c.upcoming_appointments.length ? c.upcoming_appointments.map((a) => fmtDate(a.due_date)).join(", ") : "Không"]]} />
                </Card>
                <Card title="Lượt khám gần đây" flat><DataTable rows={c.recent_encounters.slice(0, 5)} onRow={(e) => setOpen(e.id)} columns={[{ h: "Thời điểm", c: (e) => fmtDT(e.occurred_at) }, { h: "Loại", c: (e) => <Status d="encType" v={e.type} /> }, { h: "Trạng thái", c: (e) => <Status d="enc" v={e.status} /> }]} /></Card>
              </div>
            )}
            {tab === "alg" && <><AllergyBlock personId={pid} summary={summary} reload={refresh} /><ProblemBlock personId={pid} summary={summary} reload={refresh} /></>}
            {tab === "meds" && <Card flat><RxTable rows={meds.data} empty={<Empty title="Chưa có đơn thuốc" />} /></Card>}
            {tab === "history" && <Card flat><DataTable rows={encs.data} onRow={(e) => setOpen(e.id)} empty={<Empty title="Chưa có lượt khám" />} columns={[{ h: "Thời điểm", c: (e) => fmtDT(e.occurred_at) }, { h: "Loại", c: (e) => <Status d="encType" v={e.type} /> }, { h: "Trạng thái", c: (e) => <Status d="enc" v={e.status} /> }, { h: "Lý do", c: (e) => e.reason || "—" }, { h: "Ghi vào hệ thống", c: (e) => <span className="muted">{fmtDT(e.recorded_at)}</span> }]} /></Card>}
            {tab === "plan" && <PlanBlock personId={pid} summary={summary} reload={refresh} />}
            {tab === "stays" && <Card flat><DataTable rows={summary.stays} columns={[{ h: "Từ ngày", c: (s) => fmtDate(s.start_date) }, { h: "Đến ngày", c: (s) => fmtDate(s.end_date) }, { h: "Trạng thái", c: (s) => <><Status d="stay" v={s.status} />{s.provisional && <Badge tone="warn">Tạm</Badge>}</> }, { h: "Khám ban đầu", c: (s) => fmtDT(s.initial_exam_completed_at) }]} /></Card>}
            {tab === "docs" && <DocsPanel personId={pid} />}
          </>
        )}
      </RequirePatient>
      {open && <Drawer title="Lượt khám" onClose={() => { setOpen(null); refresh(); }}><Workbench id={open} onChanged={refresh} /></Drawer>}
    </>
  );
}
