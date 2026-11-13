// WF-07 – Chuyển trại & kết thúc kỳ quản lý: khởi tạo → tóm tắt y tế → xác nhận bàn giao.
import { useState } from "react";
import { api } from "../api";
import { Badge, Banner, Card, Empty, Field, FormModal, PageHeader, Seg, Status, Stepper, fmtDT, useAct, useAuth, useLoad } from "../ui.jsx";

const OPEN_LABEL = { open_encounters: "lượt khám đang mở", open_clinical_orders: "chỉ định chờ kết quả", active_medication_orders: "đơn thuốc đang hiệu lực", open_appointments: "lịch hẹn mở", open_referrals: "chuyển viện chưa hoàn tất" };
const OpenItems = ({ items }) => {
  const list = Object.entries(items || {}).filter(([, v]) => v > 0);
  return list.length ? <div className="row">{list.map(([k, v]) => <Badge key={k} tone="warn">{v} {OPEN_LABEL[k]}</Badge>)}</div> : <Badge tone="ok">Không còn điều trị/lịch đang mở</Badge>;
};

export default function Handover() {
  const { has, user } = useAuth();
  const act = useAct();
  const [view, setView] = useState("pending");
  const [m, setM] = useState(null);
  const { data: raw, reload } = useLoad(() => api("GET", "/handovers" + (view === "all" ? "" : `?status=${view === "receipt" ? "confirmed" : view}`)), [view]);
  const data = view === "receipt" ? (raw || []).filter((h) => h.kind === "transfer" && !h.received_at) : raw;
  const { data: facs } = useLoad(() => api("GET", "/facilities"), []);
  const { data: stays } = useLoad(() => api("GET", "/stays?status=active"), [], m?.t !== "new");
  const fn = (id) => facs?.find((f) => f.id === id)?.name || "—";
  const canSummary = has("handover.summary"), canConfirm = has("handover.confirm");

  return (
    <>
      <PageHeader title="Chuyển trại & Bàn giao" sub="WF-07 · Chuyển trại không làm mất hồ sơ sức khỏe; chỉ thay đổi đơn vị chịu trách nhiệm."
        actions={has("handover.initiate") && <button className="btn primary" onClick={() => setM({ t: "new" })}>+ Khởi tạo bàn giao</button>} />
      <div style={{ marginBottom: 14 }}><Seg value={view} onChange={setView} items={[{ id: "pending", label: "Chờ xác nhận" }, { id: "receipt", label: "Chờ cơ sở nhận tiếp nhận" }, { id: "confirmed", label: "Đã bàn giao" }, { id: "all", label: "Tất cả" }]} /></div>
      {!data?.length && <Card><Empty title="Không có phiếu bàn giao" /></Card>}
      {data?.map((h) => {
        const hasReceipt = h.kind === "transfer";   // chuyển trại có thêm bước "cơ sở đích tiếp nhận" (biên nhận)
        const cur = h.status === "confirmed" ? (hasReceipt ? (h.received_at ? 4 : 3) : 3) : h.summary || h.has_summary ? 2 : 1;
        return (
          <Card key={h.id} title={<>{h.person_name} <Badge tone={h.kind === "transfer" ? "info" : "neutral"}>{h.kind === "transfer" ? "Chuyển trại" : "Kết thúc quản lý"}</Badge> <Badge tone={h.direction === "out" ? "warn" : "ok"}>{h.direction === "out" ? "Chuyển đi" : "Tiếp nhận đến"}</Badge></>}
            actions={h.status === "confirmed" && h.kind === "transfer" && !h.received_at ? <Badge tone="warn">Chờ cơ sở nhận tiếp nhận</Badge> : <Status d="handover" v={h.status} />}>
            <p className="sm muted" style={{ marginTop: 0 }}>{fn(h.from_facility_id)} {h.to_facility_id ? `→ ${fn(h.to_facility_id)}` : "→ ra khỏi diện quản lý"} · khởi tạo {fmtDT(h.recorded_at)} · Lý do: {h.reason}</p>
            <Stepper steps={hasReceipt ? ["Khởi tạo", "Tóm tắt y tế", "Xác nhận bàn giao", "Cơ sở nhận tiếp nhận"] : ["Khởi tạo", "Tóm tắt y tế", "Xác nhận bàn giao"]} current={cur} />
            {h.open_items && <div style={{ marginBottom: 10 }}><b className="sm">Điều trị đang mở: </b><OpenItems items={h.open_items} /></div>}
            {h.summary ? <div className="banner info" style={{ whiteSpace: "pre-line" }}>{h.summary}</div>
              : h.has_summary ? <Banner tone="ok">Bộ phận y tế đã lập tóm tắt bàn giao (nội dung chỉ hiển thị cho nhân viên y tế).</Banner>
                : h.status === "pending" && <Banner tone="warn">Chưa có tóm tắt y tế – chưa thể xác nhận bàn giao.</Banner>}
            {h.status === "pending" && h.direction === "out" && (
              <div className="row">
                {canSummary && <button className="btn" onClick={() => setM({ t: "summary", h })}>{h.summary ? "Sửa tóm tắt y tế" : "Soạn tóm tắt y tế"}</button>}
                {canConfirm && <button className="btn primary" onClick={() => setM({ t: "confirm", h })}>Xác nhận bàn giao</button>}
              </div>
            )}
            {h.received_at && <Banner tone="ok">Cơ sở nhận đã tiếp nhận lúc {fmtDT(h.received_at)} (biên nhận hoàn tất).</Banner>}
            {h.status === "confirmed" && h.kind === "transfer" && !h.received_at && h.direction === "in" && <Banner tone="warn">Cần tiếp nhận: tạo đợt tiếp nhận mới cho người này ở tab “Tiếp nhận & Hồ sơ” – hệ thống tự lập biên nhận.</Banner>}
            {h.status === "confirmed" && h.kind === "transfer" && !h.received_at && h.direction === "out" && <p className="sm muted">Đã bàn giao, đang chờ cơ sở nhận tiếp nhận.</p>}
          </Card>
        );
      })}

      {m?.t === "new" && (
        <FormModal title="Khởi tạo bàn giao" onClose={() => setM(null)} submit="Khởi tạo"
          onSubmit={async (d) => { const r = await act(() => api("POST", `/stays/${d.stay_id}/handover`, { kind: d.kind, reason: d.reason, ...(d.to_facility_id && { to_facility_id: d.to_facility_id }) }), "Đã khởi tạo phiếu bàn giao"); if (r) reload(); return !!r; }}>
          <Field label="Người" required><select name="stay_id" required defaultValue=""><option value="" disabled>— Chọn —</option>{(stays || []).map((s) => <option key={s.id} value={s.id}>{s.person_name} ({s.person_external_id || "chưa có mã"})</option>)}</select></Field>
          <Field label="Hình thức" required><select name="kind" defaultValue="transfer" onChange={(e) => setM({ t: "new", kind: e.target.value })}><option value="transfer">Chuyển sang trại khác</option><option value="release">Kết thúc quản lý (mãn hạn/ra khỏi diện)</option></select></Field>
          {m.kind !== "release" && <Field label="Cơ sở đích" required><select name="to_facility_id" required defaultValue=""><option value="" disabled>— Chọn —</option>{(facs || []).filter((f) => f.id !== user.facility_id).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>}
          <Field label="Căn cứ / lý do" required><textarea name="reason" required minLength={3} placeholder="Quyết định số…" /></Field>
        </FormModal>
      )}
      {m?.t === "summary" && (
        <FormModal title={`Tóm tắt y tế bàn giao – ${m.h.person_name}`} wide onClose={() => setM(null)}
          onSubmit={async (d) => { const r = await act(() => api("PUT", `/handovers/${m.h.id}/summary`, d), "Đã lưu tóm tắt bàn giao"); if (r) reload(); return !!r; }}>
          <div style={{ marginBottom: 10 }}><b className="sm">Điều trị đang mở: </b><OpenItems items={m.h.open_items} /></div>
          <Field label="Thông tin cần tiếp tục chăm sóc" required hint="Bệnh đang theo dõi, thuốc đang dùng, lịch tái khám, dị ứng, lưu ý đặc biệt…"><textarea name="summary" required minLength={10} defaultValue={m.h.summary || ""} style={{ minHeight: 200 }} /></Field>
        </FormModal>
      )}
      {m?.t === "confirm" && (
        <FormModal title={`Xác nhận bàn giao – ${m.h.person_name}`} onClose={() => setM(null)} submit="Xác nhận đã bàn giao"
          onSubmit={async (d) => { const r = await act(() => api("POST", `/handovers/${m.h.id}/confirm`, { acknowledge_open_items: !!d.ack, receiver_name: d.receiver_name }), "Đã xác nhận bàn giao"); if (r) reload(); return !!r; }}>
          <Banner tone="info"><span className="sm">Sau khi xác nhận: đợt tiếp nhận tại đơn vị này kết thúc, lịch hẹn đang mở bị hoãn. <b>Hồ sơ sức khỏe được giữ nguyên.</b></span></Banner>
          {m.h.open_items ? <OpenItems items={m.h.open_items} /> : <p className="muted sm" style={{ margin: 0 }}>Cán bộ quản lý không xem được chi tiết điều trị; bộ phận y tế đã lập tóm tắt bàn giao.</p>}
          {(!m.h.open_items || Object.values(m.h.open_items).some((v) => v > 0)) && <label className="chk mt"><input type="checkbox" name="ack" /> Tôi xác nhận các điều trị/lịch đang mở (nếu có) đã được bàn giao</label>}
          <Field label="Người/đơn vị nhận bàn giao"><input name="receiver_name" /></Field>
        </FormModal>
      )}
    </>
  );
}
