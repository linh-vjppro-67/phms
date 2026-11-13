// M10 – Báo cáo & chỉ số quản trị: số liệu tổng hợp, không có định danh, lọc theo cơ sở.
import { useState } from "react";
import { api, download, qs } from "../api";
import { Badge, Banner, Card, DataTable, Empty, Field, PageHeader, Progress, useApp, useAct, useAuth, useLoad } from "../ui.jsx";
import { statusLabel } from "../labels";

const REPORTS = [
  ["encounters", "Tình hình khám chữa bệnh", "Số lượt khám theo loại; đếm lượt khác đếm người."],
  ["checkups", "Khám sức khỏe định kỳ", "Đến hạn, hoàn thành, hoãn, chưa khám, quá hạn."],
  ["health-problems", "Quản lý bệnh lý", "Số người có vấn đề sức khỏe đang hiệu lực theo nhóm bệnh."],
  ["dispensing", "Cấp phát thuốc", "Số đơn đã xác nhận, cấp đủ/một phần, số lượt cấp phát."],
  ["referrals", "Chuyển viện", "Theo trạng thái, thời gian xử lý, ca chưa có kết quả."],
  ["alerts", "Theo dõi & cảnh báo", "Lịch quá hạn, cảnh báo chưa xử lý, thời gian xử lý theo vai trò."],
];
const Tile = ({ n, label, tone }) => <div className="kpi" style={{ cursor: "default", borderLeftColor: tone ? `var(--${tone})` : undefined }}><b>{n ?? "—"}</b><span>{label}</span></div>;
const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const Map = ({ title, data, label = (k) => k, head = "Nhóm", val = "Số lượng" }) => (
  <Card title={title} flat><DataTable rows={Object.entries(data || {}).map(([k, v], i) => ({ id: i, k, v }))} empty={<Empty title="Không có dữ liệu" />} columns={[{ h: head, c: (r) => label(r.k) }, { h: val, cls: "r", c: (r) => <b>{r.v}</b> }]} /></Card>
);

const VIEW = {
  encounters: (d) => (
    <>
      <div className="kpis"><Tile n={d.total_encounters} label="Tổng số lượt khám" /><Tile n={d.total_distinct_persons} label="Số người đã khám" tone="ok" /><Tile n={d.cancelled_encounters} label="Lượt khám đã hủy" /></div>
      <Card title="Theo loại lượt khám" flat><DataTable rows={Object.entries(d.by_type).map(([k, v]) => ({ id: k, k, ...v }))} empty={<Empty title="Chưa có lượt khám" />}
        columns={[{ h: "Loại", c: (r) => statusLabel("encType", r.k) }, { h: "Số lượt", cls: "r", c: (r) => <b>{r.encounter_count}</b> }, { h: "Số người", cls: "r", c: (r) => r.distinct_person_count }]} /></Card>
      <p className="muted sm">{d.definition}</p>
    </>
  ),
  checkups: (d) => (
    <>
      <div className="kpis"><Tile n={d.total_due} label="Tổng đến hạn" /><Tile n={d.completed} label="Đã hoàn thành" tone="ok" /><Tile n={d.pending} label="Chưa khám" /><Tile n={d.overdue} label="Quá hạn" tone={d.overdue ? "bad" : ""} /><Tile n={d.postponed} label="Hoãn" /><Tile n={d.not_done} label="Không thực hiện" /></div>
      <Card title={`Tỷ lệ hoàn thành: ${pct(d.completion_rate)}`}><Progress value={d.completion_rate} /></Card>
    </>
  ),
  "health-problems": (d) => <><Map title="Người có vấn đề sức khỏe đang hiệu lực" head="Nhóm bệnh" val="Số người" data={d.active_by_problem} /><p className="muted sm">{d.note}</p></>,
  dispensing: (d) => (
    <>
      <div className="kpis"><Tile n={d.confirmed_orders} label="Đơn đã xác nhận" /><Tile n={d.fully_dispensed} label="Cấp đủ" tone="ok" /><Tile n={d.partially_dispensed} label="Cấp một phần" tone="warn" /><Tile n={d.not_dispensed} label="Chưa cấp" /><Tile n={d.dispense_events} label="Lượt cấp phát" /></div>
      <p className="muted sm">{d.note}</p>
    </>
  ),
  referrals: (d) => (
    <>
      <div className="kpis"><Tile n={d.total} label="Tổng đề nghị chuyển viện" /><Tile n={d.without_result} label="Đang điều trị, chưa có kết quả" tone="warn" /><Tile n={d.needs_post_review} label="Cần hậu kiểm" tone={d.needs_post_review ? "bad" : ""} /><Tile n={d.avg_hours_to_departure ?? "—"} label="Giờ trung bình đến khi rời trại" /></div>
      <Map title="Theo trạng thái" head="Trạng thái" label={(k) => statusLabel("referral", k)} data={d.by_status} />
    </>
  ),
  alerts: (d) => (
    <>
      <div className="kpis"><Tile n={d.overdue_appointments} label="Lịch quá hạn" tone={d.overdue_appointments ? "bad" : ""} /><Tile n={d.unresolved_alerts} label="Cảnh báo chưa xử lý" tone={d.unresolved_alerts ? "warn" : ""} /></div>
      <Map title="Thời gian xử lý trung bình theo vai trò (giờ)" head="Vai trò" val="Giờ" data={d.avg_handle_hours_by_role} />
    </>
  ),
};

export default function Reports() {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const [name, setName] = useState("encounters");
  const [f, setF] = useState({ date_from: "", date_to: "" });
  const [applied, setApplied] = useState(f);
  const { data, loading } = useLoad(() => api("GET", `/reports/${name}${qs(applied)}`), [name, applied]);
  const exportCsv = async () => {
    const purpose = await prompt({ title: "Xuất dữ liệu", label: "Mục đích / căn cứ xuất (được ghi nhật ký)", required: true });
    if (purpose) act(() => download(`/reports/${name}${qs({ ...applied, format: "csv", purpose })}`, `${name}.csv`), "Đã xuất CSV");
  };
  return (
    <>
      <PageHeader title="Báo cáo & Thống kê" sub="M10 · Chỉ hiển thị số liệu tổng hợp của cơ sở bạn; không có định danh người bệnh." />
      <div className="split">
        <div>{REPORTS.map(([id, t, sub]) => (
          <div key={id} className="kcard" style={{ borderColor: name === id ? "var(--brand)" : undefined, background: name === id ? "var(--soft)" : undefined }} onClick={() => setName(id)}><b>{t}</b><div className="muted sm">{sub}</div></div>))}</div>
        <div>
          <Card><div className="row" style={{ alignItems: "end" }}>
            <Field label="Từ ngày"><input type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></Field>
            <Field label="Đến ngày"><input type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></Field>
            <div style={{ marginBottom: 12 }}><button className="btn primary" onClick={() => setApplied({ ...f })}>Xem báo cáo</button></div>
            {has("report.export") && <div className="right" style={{ marginBottom: 12 }}><button className="btn" onClick={exportCsv}>Xuất CSV</button></div>}
          </div>
            {data && <p className="muted sm" style={{ margin: 0 }}>Kỳ báo cáo: {data.date_from} → {data.date_to}</p>}</Card>
          {data && data.report === name ? VIEW[name](data.data) : <Card><Empty title="Đang tính toán…" /></Card>}   {/* không vẽ báo cáo mới bằng số liệu của báo cáo cũ */}
        </div>
      </div>
    </>
  );
}
