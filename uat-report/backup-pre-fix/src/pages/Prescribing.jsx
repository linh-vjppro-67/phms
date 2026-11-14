// M05 – Chỉ định & kê đơn (WF-02 bước 5, WF-03 bước 1–3).
import { useState } from "react";
import { api } from "../api";
import Workbench from "../components/Workbench.jsx";
import { RxCreateModal, RxTable, useOrderActions } from "../components/blocks.jsx";
import { PatientPicker } from "../patient.jsx";
import { Banner, Card, DataTable, Drawer, Empty, Field, Modal, PageHeader, Seg, Status, fmtDT, useAuth, useLoad } from "../ui.jsx";

const GROUPS = { pending: "draft", active: "confirmed,active", closed: "completed,stopped,cancelled,superseded", all: "" };

function NewRx({ onClose, onDone }) {
  const [p, setP] = useState(null);
  const [pick, setPick] = useState(true);
  const [enc, setEnc] = useState(null);
  const { data: encs } = useLoad(() => api("GET", `/persons/${p.id}/encounters`), [p?.id], !p);
  const editable = (encs || []).filter((e) => ["draft", "in_progress", "awaiting_results", "in_treatment"].includes(e.status));
  if (enc) return <RxCreateModal encounterId={enc} onClose={onClose} onDone={onDone} />;
  return (
    <>
      <Modal title="Kê đơn mới – chọn lượt khám" onClose={onClose}>
        <Field label="Người bệnh"><div className="row">{p ? <b>{p.full_name}</b> : <span className="muted">Chưa chọn</span>}<button className="btn sm" onClick={() => setPick(true)}>{p ? "Đổi" : "Chọn…"}</button></div></Field>
        {p && (editable.length ? <DataTable rows={editable} onRow={(e) => setEnc(e.id)} columns={[{ h: "Lượt khám đang mở", c: (e) => fmtDT(e.occurred_at) }, { h: "Loại", c: (e) => <Status d="encType" v={e.type} /> }, { h: "Trạng thái", c: (e) => <Status d="enc" v={e.status} /> }, { h: "", c: () => <button className="btn sm primary">Kê đơn</button> }]} />
          : <Banner tone="warn">Người này chưa có lượt khám đang mở. Hãy tạo lượt khám ở tab “Khám chữa bệnh” trước.</Banner>)}
      </Modal>
      {pick && <PatientPicker onPick={setP} onClose={() => setPick(false)} title="Chọn người bệnh" />}
    </>
  );
}

export default function Prescribing() {
  const { has, refreshStats } = useAuth();
  const [view, setView] = useState("pending");
  const [nw, setNw] = useState(false);
  const [open, setOpen] = useState(null);
  const { data, loading, reload } = useLoad(() => api("GET", `/medication-orders?status=${GROUPS[view] || ""}`), [view], view === "lab");
  const wait = useLoad(() => api("GET", "/encounters?status=awaiting_results"), [view], view !== "lab");
  const after = () => { reload(); wait.reload(); refreshStats(); };
  const oa = useOrderActions(after);
  return (
    <>
      <PageHeader title="Chỉ định & Kê đơn" sub="M05 · Bác sĩ chỉ định và xác nhận đơn; đơn đã xác nhận bị khóa – điều chỉnh bằng phiên bản mới. Cảnh báo dị ứng/đơn trùng chỉ hỗ trợ quyết định."
        actions={has("medorder.write") && <button className="btn primary" onClick={() => setNw(true)}>+ Kê đơn mới</button>} />
      <div style={{ marginBottom: 14 }}><Seg value={view} onChange={setView} items={[{ id: "pending", label: "Chờ xác nhận" }, { id: "active", label: "Đang hiệu lực" }, { id: "closed", label: "Đã kết thúc" }, { id: "lab", label: "Chờ kết quả XN/thủ thuật" }, { id: "all", label: "Tất cả đơn" }]} /></div>
      <Card flat>
        {view === "lab" ? (
          <DataTable rows={wait.data} loading={wait.loading} onRow={(e) => setOpen(e.id)} empty={<Empty title="Không có lượt khám nào đang chờ kết quả" />}
            columns={[{ h: "Thời điểm", c: (e) => fmtDT(e.occurred_at) }, { h: "Người bệnh", c: (e) => <b>{e.person_name}</b> }, { h: "Loại", c: (e) => <Status d="encType" v={e.type} /> }, { h: "", c: () => <button className="btn sm primary">Nhập kết quả</button> }]} />
        ) : (
          <RxTable rows={data} showPerson empty={<Empty title={loading ? "Đang tải…" : "Không có đơn thuốc"} />}
            actions={(o) => (
              <div className="row">
                {o.status === "draft" && has("medorder.confirm") && <button className="btn sm primary" onClick={() => oa.confirmOrder(o)}>Xác nhận</button>}
                {["confirmed", "active"].includes(o.status) && has("medorder.write") && <button className="btn sm" onClick={() => oa.reviseOrder(o)}>Điều chỉnh</button>}
                {o.status === "draft" && has("medorder.write") && <button className="btn sm" title="Xóa đơn nháp kê nhầm (chưa có hiệu lực)" onClick={() => oa.stopOrder(o)}>Xóa nháp</button>}
                {["confirmed", "active"].includes(o.status) && has("medorder.write") && <button className="btn sm" title="Ngừng thuốc đã có hiệu lực" onClick={() => oa.stopOrder(o)}>Dừng thuốc</button>}
                <button className="btn sm ghost" onClick={() => setOpen(o.encounter_id)}>Lượt khám</button>
              </div>)} />
        )}
      </Card>
      {oa.modals}
      {nw && <NewRx onClose={() => { setNw(false); after(); }} onDone={after} />}
      {open && <Drawer title="Lượt khám" onClose={() => { setOpen(null); after(); }}><Workbench id={open} onChanged={after} /></Drawer>}
    </>
  );
}
