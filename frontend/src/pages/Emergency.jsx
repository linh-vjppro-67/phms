// WF-08 – Cấp cứu: ghi nhận tối thiểu ngay, hoàn thiện hồ sơ sau (lưu cả thời điểm xảy ra và thời điểm nhập).
import { useState } from "react";
import { api } from "../api";
import Workbench from "../components/Workbench.jsx";
import { PatientPicker } from "../patient.jsx";
import { Badge, Banner, Card, Drawer, Empty, Field, Form, FormModal, KV, PageHeader, Seg, Status, fmtDT, useApp, useAct, useAuth, useLoad } from "../ui.jsx";

const localNow = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

function NewEmergency({ onClose, onDone }) {
  const act = useAct();
  const { notify } = useApp();
  const [known, setKnown] = useState(false);
  const [p, setP] = useState(null);
  const [pick, setPick] = useState(false);
  const [at, setAt] = useState(localNow());
  const late = (Date.now() - new Date(at).getTime()) > 15 * 60000;
  return (
    <>
      <FormModal title="Ghi nhận cấp cứu" danger submit="Ghi nhận & mở hồ sơ" onClose={onClose}
        onSubmit={async (d) => {
          if (known && !p) { notify("Hãy chọn người", false); return false; }
          if (!known && !d.temp_identity) { notify("Nhập mô tả nhận dạng tạm", false); return false; }
          const body = { ...(known ? { person_id: p.id } : { temp_identity: d.temp_identity }), occurred_at: new Date(at).toISOString(), location: d.location, reporter: d.reporter, description: d.description, late_entry_reason: d.late_entry_reason };
          const r = await act(() => api("POST", "/emergency-events", body), "Đã ghi nhận sự kiện cấp cứu");
          if (r?.id) onDone(r); return !!r;
        }}>
        <Banner tone="bad"><span className="sm"><b>Ưu tiên xử trí y tế.</b> Chỉ cần thông tin tối thiểu dưới đây; mọi phần còn lại bổ sung sau khi tình trạng ổn định.</span></Banner>
        <div className="seg" style={{ marginBottom: 12 }}><button type="button" className={!known ? "on" : ""} onClick={() => setKnown(false)}>Chưa rõ danh tính</button><button type="button" className={known ? "on" : ""} onClick={() => setKnown(true)}>Đã biết danh tính</button></div>
        {known ? <Field label="Người được cấp cứu" required><div className="row">{p ? <b>{p.full_name}</b> : <span className="muted">Chưa chọn</span>}<button type="button" className="btn sm" onClick={() => setPick(true)}>Chọn…</button></div></Field>
          : <Field label="Mô tả nhận dạng tạm" required hint="Hệ thống tạo hồ sơ tạm, bắt buộc đối soát danh tính trước khi đóng sự kiện"><input name="temp_identity" placeholder="Nam ~40 tuổi, buồng 5, áo số 12…" /></Field>}
        <div className="grid2">
          <Field label="Thời điểm xảy ra" required><input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} /></Field>
          <Field label="Vị trí"><input name="location" /></Field>
          <Field label="Người báo"><input name="reporter" /></Field>
        </div>
        <Field label="Mô tả ban đầu"><textarea name="description" placeholder="Ngất, co giật, khó thở…" /></Field>
        {late && <Field label="Lý do ghi nhận muộn" required hint="Sự kiện xảy ra cách hiện tại > 15 phút"><input name="late_entry_reason" required /></Field>}
      </FormModal>
      {pick && <PatientPicker onPick={setP} onClose={() => setPick(false)} />}
    </>
  );
}

function EventCard({ ev, onOpen, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const [m, setM] = useState(null);
  return (
    <Card title={<>{ev.person_name} {ev.person_status === "pending_verification" && <Badge tone="bad">Danh tính tạm – cần đối soát</Badge>}</>} actions={<Status d="event" v={ev.status} />}>
      <KV items={[["Xảy ra lúc", fmtDT(ev.occurred_at)], ["Ghi vào hệ thống", fmtDT(ev.recorded_at)], ev.late_entry_reason && ["Lý do ghi muộn", ev.late_entry_reason], ["Vị trí / người báo", `${ev.location || "—"} / ${ev.reporter || "—"}`], ["Hồ sơ khám", ev.encounter_status ? <Status d="enc" v={ev.encounter_status} /> : "—"], ["Mô tả", ev.description]]} />
      <h3 style={{ margin: "14px 0 8px", fontSize: 14 }}>Diễn biến & can thiệp</h3>
      {ev.timeline?.length ? <ul className="tl">{ev.timeline.map((t, i) => <li key={i}>{t.action}<small>{fmtDT(t.occurred_at)} · {t.performer} <span title="thời điểm nhập">(nhập {fmtDT(t.recorded_at)})</span></small></li>)}</ul> : <p className="muted sm">Chưa ghi nhận can thiệp.</p>}
      {ev.status === "open" && (
        <>
          <Form className="row" onSubmit={async (d) => { const r = await act(() => api("POST", `/emergency-events/${ev.id}/interventions`, d), "Đã ghi nhận"); if (r) reload(); return r; }}>
            <input name="action" placeholder="Can thiệp (sơ cứu, ép tim, thở oxy…)" style={{ flex: 1, minWidth: 220 }} required />
            <input name="performer" placeholder="Người thực hiện" style={{ width: 180 }} />
            <button className="btn">Ghi nhận</button>
          </Form>
          <div className="row mt">
            <button className="btn primary" onClick={() => onOpen(ev.encounter_id)}>Mở hồ sơ khám cấp cứu</button>
            {ev.person_status === "pending_verification" && has("person.write") && <button className="btn" onClick={() => setM("verify")}>Đối soát danh tính</button>}
            {has("emergency.close") && <button className="btn" onClick={() => setM("close")}>Đóng sự kiện</button>}
          </div>
        </>
      )}
      {m === "verify" && (
        <FormModal title="Đối soát danh tính (hồ sơ tạm)" onClose={() => setM(null)} submit="Xác minh"
          onSubmit={async (d) => { const r = await act(() => api("POST", `/persons/${ev.person_id}/verify`, d), "Đã xác minh danh tính"); if (r) reload(); return !!r; }}>
          <div className="grid2"><Field label="Họ tên"><input name="full_name" /></Field><Field label="Ngày sinh"><input type="date" name="date_of_birth" /></Field>
            <Field label="Hệ thống nguồn" required><input name="source_system" defaultValue="QLPN" required /></Field><Field label="Mã nguồn" required><input name="external_id" required /></Field></div>
          <Field label="Căn cứ đối soát" required><textarea name="note" required /></Field>
        </FormModal>
      )}
      {m === "close" && (
        <FormModal title="Đóng sự kiện cấp cứu" onClose={() => setM(null)} submit="Đóng sự kiện"
          onSubmit={async (d) => { const r = await act(() => api("POST", `/emergency-events/${ev.id}/close`, d), "Đã đóng sự kiện"); if (r) reload(); return !!r; }}>
          <Banner tone="info"><span className="sm">Chỉ đóng được khi hồ sơ khám đã hoàn tất và danh tính đã đối soát.</span></Banner>
          <Field label="Kết luận / ghi chú" required><textarea name="note" required /></Field>
          <Field label="Hẹn theo dõi sau cấp cứu"><input type="date" name="follow_up_date" /></Field>
        </FormModal>
      )}
    </Card>
  );
}

export default function Emergency() {
  const { refreshStats } = useAuth();
  const [view, setView] = useState("open");
  const [nw, setNw] = useState(false);
  const [open, setOpen] = useState(null);
  const { data, reload } = useLoad(() => api("GET", `/emergency-events?status=${view}`), [view]);
  const after = () => { reload(); refreshStats(); };
  return (
    <>
      <PageHeader title="Cấp cứu" sub="WF-08 · Không có bước nhập liệu hay phê duyệt nào cản trở xử trí y tế khẩn; hồ sơ hoàn thiện và kiểm toán được sau sự kiện."
        actions={<button className="btn danger" onClick={() => setNw(true)}>+ Ghi nhận cấp cứu</button>} />
      <div style={{ marginBottom: 14 }}><Seg value={view} onChange={setView} items={[{ id: "open", label: "Đang mở" }, { id: "closed", label: "Đã đóng" }]} /></div>
      {!data?.length ? <Card><Empty title={view === "open" ? "Không có sự kiện cấp cứu đang mở" : "Chưa có sự kiện đã đóng"} /></Card>
        : <div className="cols">{data.map((ev) => <EventCard key={ev.id} ev={ev} onOpen={setOpen} reload={after} />)}</div>}
      {nw && <NewEmergency onClose={() => setNw(false)} onDone={(ev) => { after(); setOpen(ev.encounter_id); }} />}
      {open && <Drawer title="Hồ sơ khám cấp cứu" onClose={() => { setOpen(null); after(); }}><Workbench id={open} onChanged={after} /></Drawer>}
    </>
  );
}
