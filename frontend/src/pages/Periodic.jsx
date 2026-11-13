// M07 – Khám sức khỏe định kỳ (WF-04): tạo đợt → sinh danh sách (loại trừ) → thực hiện → khóa → báo cáo.
import { useState } from "react";
import { api, idem } from "../api";
import Workbench from "../components/Workbench.jsx";
import { Badge, Banner, Card, DataTable, Drawer, Empty, Field, FormModal, PageHeader, Progress, Seg, Status, Tabs, fmtDate, today, useApp, useAct, useAuth, useLoad } from "../ui.jsx";

const Stat = ({ n, label, tone }) => <div className="kpi" style={{ cursor: "default", borderLeftColor: tone === "bad" ? "var(--bad)" : tone === "ok" ? "var(--ok)" : undefined }}><b style={{ fontSize: 22 }}>{n}</b><span>{label}</span></div>;

function RoundDetail({ id, reloadList }) {
  const { has, refreshStats } = useAuth();
  const act = useAct();
  const { confirm } = useApp();
  const [tab, setTab] = useState("tasks");
  const [filter, setFilter] = useState("");
  const [enc, setEnc] = useState(null);
  const [m, setM] = useState(null);
  const { data: r, reload: r1 } = useLoad(() => api("GET", `/checkup-rounds/${id}`), [id]);
  const { data: tasks, reload: r2 } = useLoad(() => api("GET", `/appointments?round_id=${id}&limit=500`), [id]);
  const reload = () => { r1(); r2(); reloadList(); refreshStats(); };
  if (!r) return null;
  const st = r.stats;
  const rows = (tasks || []).filter((t) => !filter || (filter === "overdue" ? t.overdue : t.status === filter));
  const examine = async (t) => {
    const e = await act(() => api("POST", "/encounters", { person_id: t.person_id, type: "periodic", appointment_id: t.id, reason: `Khám định kỳ – ${r.name}` }, idem()));
    if (!e?.id) return;
    await act(() => api("POST", `/encounters/${e.id}/transition`, { to: "in_progress" }));
    reload(); setEnc(e.id);
  };
  return (
    <>
      <Card title={<>{r.name} <Status d="round" v={r.status} /></>} actions={has("checkup.manage") && r.status !== "locked" && <button className="btn" onClick={async () => {
        if (await confirm({ title: "Khóa đợt khám", message: `Người chưa khám (${st.pending}) sẽ được ghi nhận “không thực hiện”. Không thể hoàn tác.`, danger: true, okLabel: "Khóa đợt" }) && await act(() => api("POST", `/checkup-rounds/${id}/lock`), "Đã khóa đợt khám")) reload();
      }}>Khóa đợt & chốt kết quả</button>}>
        <p className="muted sm" style={{ marginTop: 0 }}>Hạn hoàn thành: <b>{fmtDate(r.due_date)}</b></p>
        <div className="row" style={{ marginBottom: 6 }}><b>Tiến độ {st.total ? Math.round((st.completion_rate || 0) * 100) : 0}%</b><span className="muted sm">{st.completed}/{st.total} đã khám</span></div>
        <Progress value={st.completion_rate} />
        <div className="kpis mt" style={{ marginBottom: 0 }}>
          <Stat n={st.total} label="Tổng nhiệm vụ" /><Stat n={st.completed} label="Đã hoàn thành" tone="ok" /><Stat n={st.pending} label="Chưa khám" /><Stat n={st.overdue} label="Quá hạn" tone={st.overdue ? "bad" : ""} />
          <Stat n={st.postponed} label="Hoãn" /><Stat n={st.not_done} label="Không thực hiện" /><Stat n={st.excluded_count} label="Loại trừ khỏi đợt" /><Stat n={st.new_problems_detected} label="Vấn đề SK mới phát hiện" />
        </div>
      </Card>
      <Tabs value={tab} onChange={setTab} items={[{ id: "tasks", label: "Danh sách khám", count: st.total }, { id: "excl", label: "Loại trừ", count: st.excluded_count }]} />
      {tab === "tasks" ? (
        <Card flat>
          <div className="toolbar"><Seg value={filter} onChange={setFilter} items={[{ id: "", label: "Tất cả" }, { id: "overdue", label: "Quá hạn" }, { id: "scheduled", label: "Chưa khám" }, { id: "completed", label: "Đã khám" }, { id: "postponed", label: "Hoãn" }, { id: "not_done", label: "Không thực hiện" }]} /></div>
          <DataTable rows={rows} empty={<Empty title="Không có nhiệm vụ" />}
            columns={[{ h: "Người", c: (t) => <b>{t.person_name || t.person_id.slice(0, 8)}</b> }, { h: "Hạn", c: (t) => <>{fmtDate(t.due_date)} {t.overdue && <Badge tone="bad">Quá hạn</Badge>}</> }, { h: "Trạng thái", c: (t) => <><Status d="appt" v={t.status} />{t.status_reason && <div className="muted sm">{t.status_reason}</div>}</> },
              { h: "", cls: "r", c: (t) => ["scheduled", "due"].includes(t.status) && r.status !== "locked" && (
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  {has("encounter.write") && <button className="btn sm primary" onClick={() => examine(t)}>Khám</button>}
                  {has("schedule.write") && <button className="btn sm" onClick={() => setM({ t, to: "postponed" })}>Hoãn</button>}
                  {has("schedule.write") && <button className="btn sm" onClick={() => setM({ t, to: "not_done" })}>Không thực hiện</button>}
                </div>) }]} />
        </Card>
      ) : (
        <Card flat><DataTable rows={(r.excluded || []).map((x, i) => ({ ...x, id: i }))} empty={<Empty title="Không có trường hợp loại trừ" />}
          columns={[{ h: "Người", c: (x) => <b>{x.person_name || x.person_id.slice(0, 8)}</b> }, { h: "Lý do loại trừ", c: (x) => x.reason }]} /></Card>
      )}
      {m && (
        <FormModal title={m.to === "postponed" ? "Hoãn khám" : "Ghi nhận không thực hiện"} onClose={() => setM(null)}
          onSubmit={async (d) => { const r2_ = await act(() => api("POST", `/appointments/${m.t.id}/status`, { to: m.to, reason: d.reason, ...(d.new_due_date && { new_due_date: d.new_due_date }) }), "Đã cập nhật"); if (r2_) reload(); return !!r2_; }}>
          <Field label="Lý do" required hint="Ví dụ: đang lao động ngoài trại, đang điều trị ngoại viện…"><textarea name="reason" required /></Field>
          {m.to === "postponed" && <Field label="Hẹn lại vào ngày" hint="Hệ thống tạo lịch mới"><input type="date" name="new_due_date" min={today()} /></Field>}
        </FormModal>
      )}
      {enc && <Drawer title="Khám định kỳ" onClose={() => { setEnc(null); reload(); }}><Workbench id={enc} onChanged={reload} /></Drawer>}
    </>
  );
}

export default function Periodic({ focus }) {
  const { has } = useAuth();
  const act = useAct();
  const { notify } = useApp();
  const { data: rounds, reload } = useLoad(() => api("GET", "/checkup-rounds"), []);
  const [sel, setSel] = useState(focus || null);
  const [nw, setNw] = useState(false);
  const cur = sel || rounds?.[0]?.id;
  return (
    <>
      <PageHeader title="Khám sức khỏe định kỳ" sub="M07 · Mỗi đợt tự sinh danh sách theo hồ sơ ĐANG QUẢN LÝ (đã khám ban đầu); loại trừ người đang ở bệnh viện, chờ chuyển trại, chưa khám ban đầu hoặc đã có lịch khác – mọi trường hợp loại trừ đều được ghi lý do; không bỏ sót người chưa khám."
        actions={has("checkup.manage") && <button className="btn primary" onClick={() => setNw(true)}>+ Tạo đợt khám</button>} />
      <div className="split">
        <div>
          {!rounds?.length ? <Card><Empty title="Chưa có đợt khám định kỳ" /></Card> : rounds.map((r) => (
            <div key={r.id} className="kcard" style={{ borderColor: cur === r.id ? "var(--brand)" : undefined, background: cur === r.id ? "var(--soft)" : undefined }} onClick={() => setSel(r.id)}>
              <div className="row"><b>{r.name}</b><span className="right"><Status d="round" v={r.status} /></span></div>
              <div className="muted sm" style={{ margin: "4px 0 8px" }}>Hạn {fmtDate(r.due_date)} · {r.stats.completed}/{r.stats.total} đã khám{r.stats.overdue > 0 && <> · <span style={{ color: "var(--bad)" }}>{r.stats.overdue} quá hạn</span></>}</div>
              <Progress value={r.stats.completion_rate} />
            </div>
          ))}
        </div>
        <div>{cur ? <RoundDetail key={cur} id={cur} reloadList={reload} /> : null}</div>
      </div>
      {nw && (
        <FormModal title="Tạo đợt khám định kỳ" onClose={() => setNw(false)} submit="Tạo đợt & sinh danh sách"
          onSubmit={async (d) => {
            const r = await act(() => api("POST", "/checkup-rounds", { name: d.name, due_date: d.due_date, ...(d.min && { min_days_since_last_periodic: +d.min }) }));
            if (r?.id) { notify(`Đã sinh ${r.tasks_created} nhiệm vụ khám, loại trừ ${r.excluded.length} trường hợp`); setSel(r.id); reload(); } return !!r;
          }}>
          <Field label="Tên đợt" required><input name="name" required placeholder="Khám định kỳ Quý 4/2026" /></Field>
          <Field label="Hạn hoàn thành" required><input type="date" name="due_date" min={today()} required /></Field>
          <Field label="Bỏ qua người đã khám định kỳ trong vòng (ngày)" hint="Để trống = đưa tất cả người đang quản lý vào đợt"><input type="number" name="min" min="0" /></Field>
          <Banner tone="info"><span className="sm">Tự động loại trừ: người đang điều trị ngoài trại (chuyển viện) và người đang chờ chuyển trại.</span></Banner>
        </FormModal>
      )}
    </>
  );
}
