// M04 – Quản lý khám chữa bệnh: danh sách lượt khám + bàn làm việc.
import { useState } from "react";
import { api, qs, idem } from "../api";
import Workbench from "../components/Workbench.jsx";
import { PatientPicker, usePatient } from "../patient.jsx";
import { Banner, Card, DataTable, Drawer, Empty, Field, FormModal, PageHeader, Seg, Status, fmtDT, useAct, useApp, useAuth, useLoad } from "../ui.jsx";

function NewEncounter({ onClose, onCreated }) {
  const act = useAct();
  const { notify } = useApp();
  const { patient: ctx } = usePatient();
  const [p, setP] = useState(ctx ? { id: ctx.id, full_name: ctx.name } : null);
  const [pick, setPick] = useState(false);
  return (
    <>
      <FormModal title="Lượt khám mới" onClose={onClose} submit="Tạo & bắt đầu khám"
        onSubmit={async (d) => {
          if (!p) { notify("Hãy chọn người cần khám", false); return false; }
          const e = await act(() => api("POST", "/encounters", { person_id: p.id, type: d.type, reason: d.reason, priority: d.priority || "routine", ...(d.occurred_at && { occurred_at: d.occurred_at }), ...(d.late_entry_reason && { late_entry_reason: d.late_entry_reason }) }, idem()));
          if (!e?.id) return false;
          await act(() => api("POST", `/encounters/${e.id}/transition`, { to: "in_progress" }));
          onCreated(e.id); return true;
        }}>
        <Field label="Người khám" required>
          <div className="row">{p ? <b>{p.full_name}</b> : <span className="muted">Chưa chọn</span>}<button type="button" className="btn sm" onClick={() => setPick(true)}>{p ? "Đổi" : "Chọn người…"}</button></div>
        </Field>
        <Field label="Loại lượt khám" required><select name="type" defaultValue="ad_hoc"><option value="ad_hoc">Khám phát sinh (theo yêu cầu/triệu chứng)</option><option value="periodic">Khám định kỳ</option></select></Field>
        <Field label="Mức ưu tiên" hint="Phân loại khi nhận yêu cầu khám – ca khẩn được xếp lên đầu danh sách"><select name="priority" defaultValue="routine"><option value="routine">Thường</option><option value="urgent">Ưu tiên (cần khám sớm trong ngày)</option><option value="emergent">Khẩn cấp (cần xử trí ngay)</option></select></Field>
        <Field label="Lý do đến khám / triệu chứng"><textarea name="reason" /></Field>
        <Banner tone="info"><span className="sm">Khám ban đầu thực hiện ở tab “Khám ban đầu”; cấp cứu ở tab “Cấp cứu”.</span></Banner>
      </FormModal>
      {pick && <PatientPicker onPick={setP} onClose={() => setPick(false)} title="Chọn người cần khám" />}
    </>
  );
}

export default function Encounters({ focus }) {
  const { has, refreshStats } = useAuth();
  const { patient } = usePatient();
  const [view, setView] = useState("open");
  const [type, setType] = useState("");
  const [onlyMine, setOnlyMine] = useState(false);
  const [open, setOpen] = useState(focus || null);
  const [nw, setNw] = useState(false);
  const { data, loading, reload } = useLoad(() => api("GET", "/encounters" + qs({ open_only: view === "open", status: view === "wait" ? "awaiting_results" : view === "done" ? "completed" : "", type })), [view, type]);
  const rows = (data || []).filter((e) => !onlyMine || e.person_id === patient?.id);
  return (
    <>
      <PageHeader title="Khám chữa bệnh" sub="M04 · Mỗi lần khám là một lượt (Encounter) riêng: người khám, thời gian, chẩn đoán, chỉ định, kết quả."
        actions={has("encounter.write") && <button className="btn primary" onClick={() => setNw(true)}>+ Lượt khám mới</button>} />
      <div className="row" style={{ marginBottom: 14 }}>
        <Seg value={view} onChange={setView} items={[{ id: "open", label: "Đang thực hiện" }, { id: "wait", label: "Chờ kết quả" }, { id: "done", label: "Đã hoàn tất" }, { id: "all", label: "Tất cả" }]} />
        <select aria-label="Lọc theo loại lượt khám" value={type} onChange={(e) => setType(e.target.value)} style={{ width: "auto" }}><option value="">Mọi loại</option><option value="initial">Khám ban đầu</option><option value="periodic">Định kỳ</option><option value="ad_hoc">Phát sinh</option><option value="emergency">Cấp cứu</option></select>
        {patient && <label className="chk"><input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /> Chỉ {patient.name}</label>}
      </div>
      <Card flat>
        <DataTable rows={rows} loading={loading} onRow={(e) => setOpen(e.id)} empty={<Empty title="Không có lượt khám phù hợp" />}
          columns={[{ h: "Ưu tiên", c: (e) => (e.priority && e.priority !== "routine" ? <Status d="priority" v={e.priority} /> : <span className="muted">—</span>) }, { h: "Thời điểm", c: (e) => fmtDT(e.occurred_at) }, { h: "Người bệnh", c: (e) => <b>{e.person_name}</b> }, { h: "Loại", c: (e) => <Status d="encType" v={e.type} /> },
            { h: "Trạng thái", c: (e) => <Status d="enc" v={e.status} /> }, { h: "Lý do khám", c: (e) => <span className="sm">{e.reason || "—"}</span> }]} />
      </Card>
      {open && <Drawer title="Lượt khám" onClose={() => { setOpen(null); reload(); refreshStats(); }}><Workbench id={open} onChanged={reload} /></Drawer>}
      {nw && <NewEncounter onClose={() => setNw(false)} onCreated={(id) => { reload(); setOpen(id); }} />}
    </>
  );
}
