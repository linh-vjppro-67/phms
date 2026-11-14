// M08 – Theo dõi bệnh lý & cảnh báo (WF-05): hộp thư cảnh báo, lịch quá hạn, kế hoạch theo dõi, vấn đề sức khỏe.
import { useState } from "react";
import { api, idem } from "../api";
import Workbench from "../components/Workbench.jsx";
import { EditPlanModal, PlanBlock, ProblemBlock } from "../components/blocks.jsx";
import { RequirePatient, usePatient } from "../patient.jsx";
import { Badge, Banner, Card, DataTable, Drawer, Empty, Field, FormModal, PageHeader, Seg, Status, Tabs, fmtDT, fmtDate, useApp, useAct, useAuth, useLoad } from "../ui.jsx";

const KIND = { appointment_overdue: "Lịch quá hạn", break_glass_review: "Truy cập khẩn cấp – cần hậu kiểm", referral_post_review: "Chuyển viện cấp cứu – cần hậu kiểm", medication_course_ending: "Đơn thuốc hết liệu trình" };

function Alerts() {
  const { has, refreshStats } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const [st, setSt] = useState("new");
  const { data, loading, reload } = useLoad(() => api("GET", "/alerts" + (st ? `?status=${st}` : "")), [st]);
  const after = () => { reload(); refreshStats(); };
  return (
    <>
      <div style={{ marginBottom: 14 }}><Seg value={st} onChange={setSt} items={[{ id: "new", label: "Mới" }, { id: "acknowledged", label: "Đã tiếp nhận" }, { id: "resolved", label: "Đã xử lý" }, { id: "", label: "Tất cả" }]} /></div>
      <Card flat>
        <DataTable rows={data} loading={loading} empty={<Empty title="Không có cảnh báo" />}
          columns={[{ h: "Phát sinh", c: (a) => fmtDT(a.created_at) }, { h: "Loại", c: (a) => KIND[a.kind] || a.kind }, { h: "Nội dung", c: (a) => a.message },
            { h: "Mức", c: (a) => (a.level > 0 ? <Badge tone="bad">Đã nâng {a.level} mức</Badge> : <span className="muted">Thường</span>) }, { h: "Trạng thái", c: (a) => <Status d="alert" v={a.status} /> },
            { h: "Kết quả xử lý", c: (a) => a.resolution || "—" },
            { h: "", c: (a) => has("alert.handle") && (
              <div className="row">
                {a.status === "new" && <button className="btn sm primary" onClick={async () => { if (await act(() => api("POST", `/alerts/${a.id}/acknowledge`), "Đã tiếp nhận – bạn là người chịu trách nhiệm")) after(); }}>Tiếp nhận</button>}
                {["new", "acknowledged"].includes(a.status) && <button className="btn sm" onClick={async () => {
                  const note = await prompt({ title: "Xử lý cảnh báo", label: "Nguyên nhân & kết quả xử lý", multiline: true, required: true });
                  if (note && await act(() => api("POST", `/alerts/${a.id}/resolve`, { note }), "Đã xử lý")) after();
                }}>Xử lý xong</button>}
              </div>) }]} />
      </Card>
    </>
  );
}

function Overdue() {
  const { has, refreshStats } = useAuth();
  const act = useAct();
  const [view, setView] = useState("overdue");
  const [m, setM] = useState(null);
  const [enc, setEnc] = useState(null);
  const { data, loading, reload } = useLoad(() => api("GET", "/appointments?limit=500"), []);
  const days = (d) => Math.floor((Date.now() - new Date(d)) / 864e5);
  const open = (data || []).filter((a) => ["scheduled", "due"].includes(a.status) && a.kind !== "periodic");
  const rows = view === "overdue" ? open.filter((a) => a.overdue) : open;
  const after = () => { reload(); refreshStats(); };
  const examine = async (a) => {
    const e = await act(() => api("POST", "/encounters", { person_id: a.person_id, type: "periodic", appointment_id: a.id, reason: a.kind === "care_plan" ? "Tái khám theo kế hoạch theo dõi bệnh mạn tính" : "Tái khám theo hẹn" }, idem()));
    if (!e?.id) return;
    await act(() => api("POST", `/encounters/${e.id}/transition`, { to: "in_progress" }));
    after(); setEnc(e.id);
  };
  return (
    <>
      <Banner tone="info"><span className="sm">“Quá hạn” là thuộc tính tính toán (đến hạn nhưng chưa thực hiện). Bấm <b>Khám</b> để thực hiện tái khám: hoàn tất lượt khám sẽ đóng lịch này và tự sinh lịch kỳ kế tiếp theo kế hoạch. Lịch của đợt khám định kỳ xử lý ở tab “Khám định kỳ”.</span></Banner>
      <div style={{ marginBottom: 14 }}><Seg value={view} onChange={setView} items={[{ id: "overdue", label: `Quá hạn (${open.filter((a) => a.overdue).length})` }, { id: "open", label: `Tất cả lịch đang mở (${open.length})` }]} /></div>
      <Card flat>
        <DataTable rows={rows} loading={loading} empty={<Empty title="Không có lịch" />}
          columns={[{ h: "Người", c: (a) => <b>{a.person_name || a.person_id.slice(0, 8)}</b> }, { h: "Loại", c: (a) => (a.kind === "care_plan" ? "Theo kế hoạch bệnh mạn tính" : "Tái khám") }, { h: "Hạn", c: (a) => fmtDate(a.due_date) },
            { h: "Tình trạng", c: (a) => (a.overdue ? <Badge tone="bad">Trễ {days(a.due_date)} ngày</Badge> : <Status d="appt" v={a.status} />) }, { h: "Ghi chú", c: (a) => <span className="sm">{a.note || ""}</span> },
            { h: "", cls: "r", c: (a) => (
              <div className="row" style={{ justifyContent: "flex-end" }}>
                {has("encounter.examine") && <button className="btn sm primary" onClick={() => examine(a)}>Khám</button>}
                {has("schedule.write") && <button className="btn sm" onClick={() => setM({ a, to: "postponed" })}>Hoãn</button>}
                {has("schedule.write") && <button className="btn sm" onClick={() => setM({ a, to: "not_done" })}>Không thực hiện</button>}
              </div>) }]} />
      </Card>
      {m && (
        <FormModal title={m.to === "postponed" ? "Hoãn lịch" : "Không thực hiện"} onClose={() => setM(null)}
          onSubmit={async (d) => { const r = await act(() => api("POST", `/appointments/${m.a.id}/status`, { to: m.to, ...d }), "Đã cập nhật"); if (r) after(); return !!r; }}>
          <Field label="Lý do" required><textarea name="reason" required /></Field>
          {m.to === "postponed" && <Field label="Hẹn lại ngày"><input type="date" name="new_due_date" /></Field>}
        </FormModal>
      )}
      {enc && <Drawer title="Tái khám" onClose={() => { setEnc(null); after(); }}><Workbench id={enc} onChanged={after} /></Drawer>}
    </>
  );
}

function Plans() {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const [edit, setEdit] = useState(null);
  const { data, loading, reload } = useLoad(() => api("GET", "/care-plans"), []);
  return (
    <Card flat>
      <DataTable rows={data} loading={loading} empty={<Empty title="Chưa có kế hoạch theo dõi đang hoạt động">Lập kế hoạch ở tab “Theo dõi người đang chọn” hoặc trong lượt khám.</Empty>}
        columns={[{ h: "Người", c: (p) => <b>{p.person_name}</b> }, { h: "Vấn đề", c: (p) => p.problem_name }, { h: "Mục tiêu", c: (p) => <span className="sm">{p.goals}</span> }, { h: "Chu kỳ", c: (p) => `${p.review_interval_days} ngày` },
          { h: "Lần theo dõi tới", c: (p) => <>{fmtDate(p.next_due)} {p.overdue && <Badge tone="bad">Quá hạn</Badge>}</> },
          { h: "", c: (p) => has("careplan.write") && <div className="row"><button className="btn sm" onClick={() => setEdit(p)}>Sửa</button><button className="btn sm" onClick={async () => { const note = await prompt({ title: "Kết thúc kế hoạch", label: "Lý do", required: true }); if (note && await act(() => api("POST", `/care-plans/${p.id}/end`, { note }), "Đã kết thúc")) reload(); }}>Kết thúc</button></div> }]} />
      {edit && <EditPlanModal plan={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </Card>
  );
}

function Mine() {
  const { summary, patient, refresh } = usePatient();
  return (
    <RequirePatient hint="Chọn người để xem và cập nhật vấn đề sức khỏe, lập kế hoạch theo dõi.">
      {summary && <><ProblemBlock personId={patient.id} summary={summary} reload={refresh} /><PlanBlock personId={patient.id} summary={summary} reload={refresh} /></>}
    </RequirePatient>
  );
}

export default function Chronic() {
  const { has, stats } = useAuth();
  const [tab, setTab] = useState("alerts");
  return (
    <>
      <PageHeader title="Bệnh lý & Cảnh báo" sub="M08 · Mỗi bệnh lý dài hạn có kế hoạch và người chịu trách nhiệm; mọi nhắc việc/cảnh báo có trạng thái, người xử lý và thời gian xử lý." />
      <Tabs value={tab} onChange={setTab} items={[{ id: "alerts", label: "Cảnh báo", count: stats.new_alerts }, { id: "overdue", label: "Lịch tái khám & quá hạn", count: stats.overdue_appointments },
        has("clinical.read") && { id: "plans", label: "Kế hoạch theo dõi" }, has("clinical.read") && { id: "mine", label: "Theo dõi người đang chọn" }]} />
      {tab === "alerts" && <Alerts />}{tab === "overdue" && <Overdue />}{tab === "plans" && <Plans />}{tab === "mine" && <Mine />}
    </>
  );
}
