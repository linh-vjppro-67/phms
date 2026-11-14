// Các khối nghiệp vụ lâm sàng dùng lại ở nhiều màn hình (khám, hồ sơ, kê đơn...).
import { useEffect, useId, useRef, useState } from "react";
import { api, download, idem, qs, upload } from "../api";
import { DOC_TYPE, VITALS, statusLabel } from "../labels";
import { Badge, Banner, Card, DataTable, Empty, Field, Form, FormModal, Modal, Status, fmtDT, fmtDate, today, useApp, useAct, useAuth, useLoad } from "../ui.jsx";

// ------------------------------------------------------------------ dị ứng & vấn đề sức khỏe
/** Cặp ô "Tên bệnh" + "Mã ICD" liên kết HAI CHIỀU: chọn/nhập tên có trong danh mục → mã tự điền; nhập/chọn mã → tên tự điền.
 *  Vẫn cho nhập tự do (bệnh chưa có trong danh mục, mã để trống). Đọc theo name (uncontrolled) nên dùng được với <Form>/<FormModal>. */
export function IcdPair({ icd, nameField, nameLabel, nameRequired = true }) {
  const uid = useId();
  const n = useRef(null), c = useRef(null), auto = useRef({ name: false, code: false });
  const list = icd || [];
  const eq = (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase();
  const onName = (e) => {
    const m = list.find((i) => eq(i.name, e.target.value));
    if (m) { c.current.value = m.code; auto.current.code = true; }
    else if (auto.current.code) { c.current.value = ""; auto.current.code = false; }       // đổi tên sang chữ tự do → bỏ mã đã tự điền
  };
  const onCode = (e) => {
    const m = list.find((i) => eq(i.code, e.target.value));
    if (m) { n.current.value = m.name; auto.current.name = true; }
    else if (auto.current.name) { n.current.value = ""; auto.current.name = false; }
  };
  return (
    <>
      <Field label={nameLabel} required={nameRequired}>
        <input ref={n} name={nameField} list={`${uid}n`} autoComplete="off" required={nameRequired} onChange={onName} placeholder="Gõ tên hoặc chọn từ danh sách" />
      </Field>
      <datalist id={`${uid}n`}>{list.map((i) => <option key={i.id} value={i.name} label={i.code} />)}</datalist>
      <Field label="Mã ICD">
        <input ref={c} name="code" list={`${uid}c`} autoComplete="off" onChange={onCode} placeholder="Tự điền khi chọn bệnh" />
      </Field>
      <datalist id={`${uid}c`}>{list.map((i) => <option key={i.id} value={i.code} label={i.name} />)}</datalist>
    </>
  );
}

/** Cảnh báo "đã gõ nhưng chưa bấm Thêm": bọc form; onInput bật cờ, gọi done() khi lưu thành công. */
function useUnsaved() {
  const [dirty, setDirty] = useState(false);
  return { dirty, props: { onInput: () => setDirty(true) }, done: () => setDirty(false),
    badge: dirty ? <span className="badge warn" role="status">● Chưa bấm “Thêm” – nội dung này CHƯA được lưu</span> : null };
}

const ALLERGENS = ["Penicillin", "Amoxicillin", "Ampicillin", "Cephalosporin", "Sulfonamid (Cotrimoxazol)", "Aspirin", "Ibuprofen", "Diclofenac", "Paracetamol", "Tetracyclin", "Quinolon", "Macrolid",
  "Thuốc gây tê (Lidocain)", "Thuốc cản quang chứa iod", "Insulin", "Hải sản (tôm, cua)", "Cá", "Sữa", "Trứng", "Đậu phộng", "Gluten (lúa mì)", "Phấn hoa", "Bụi nhà / mạt bụi", "Lông chó mèo", "Latex (cao su)", "Nọc côn trùng (ong, kiến)", "Kim loại (Nickel)"];

export function AllergyBlock({ personId, summary, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { confirm, prompt } = useApp();
  const uns = useUnsaved();
  const c = summary?.clinical;
  if (!c) return null;
  const retract = async (a) => {
    const reason = await prompt({ title: `Gỡ dị ứng “${a.substance}”`, label: "Lý do gỡ (ghi nhầm, nhầm người bệnh…)", required: true, multiline: true,
      message: "Dị ứng sẽ bị gỡ khỏi danh sách và không còn cảnh báo khi kê đơn. Bản ghi vẫn được lưu kèm lý do và người thực hiện (không xóa hẳn)." });
    if (reason && await act(() => api("POST", `/allergies/${a.id}/retract`, { reason }), "Đã gỡ dị ứng")) reload();
  };
  return (
    <Card title="Dị ứng" actions={<Status d="allergy" v={c.allergy_status} />}>
      {c.allergies.length ? (
        <DataTable rows={c.allergies} columns={[{ h: "Chất gây dị ứng", c: (a) => <b>{a.substance}</b> }, { h: "Phản ứng", c: (a) => a.reaction || "—" },
          { h: "Mức độ", c: (a) => a.severity || "—" }, { h: "Xác nhận", c: (a) => (a.confirmed ? <Badge tone="ok">Đã xác nhận</Badge> : <Badge>Khai báo</Badge>) },
          { h: "", stop: true, c: (a) => has("encounter.write") && (!a.confirmed || has("diagnosis.write")) && <button className="btn sm" title="Gỡ khi khai sai/nhầm người (vẫn lưu dấu vết)" onClick={() => retract(a)}>Gỡ</button> }]} />
      ) : <p className="muted" style={{ marginTop: 0 }}>{c.notice}</p>}
      {has("encounter.write") && (
        <>
          <div {...uns.props}><Form className="fgrid mt" onSubmit={async (d) => { const r = await act(() => api("POST", `/persons/${personId}/allergies`, d), "Đã ghi nhận dị ứng"); if (r) { uns.done(); reload(); } return r; }}>
            <Field label="Chất gây dị ứng" required><input name="substance" list="allergens" autoComplete="off" required placeholder="Thuốc, thức ăn, môi trường…" /></Field>
            <datalist id="allergens">{ALLERGENS.map((a) => <option key={a} value={a} />)}</datalist>
            <Field label="Phản ứng"><input name="reaction" autoComplete="off" placeholder="Phát ban, khó thở…" /></Field>
            <Field label="Mức độ"><select name="severity" defaultValue=""><option value="">—</option><option>Nhẹ</option><option>Trung bình</option><option>Nặng</option></select></Field>
            <div className="fchk"><label className="chk"><input type="checkbox" name="confirmed" /> Đã xác nhận</label></div>
            <div className="fbtn"><button className="btn primary">Thêm dị ứng</button></div>
          </Form>{uns.badge}</div>
          <p className="muted sm" style={{ margin: "0 0 4px" }}><b>Đã xác nhận</b>: tick khi dị ứng đã được kiểm chứng (kết quả thử nghiệm, bệnh án cũ, từng phản ứng rõ ràng). Bỏ trống nếu chỉ là người bệnh tự khai. Cả hai loại đều gây cảnh báo khi kê đơn; mục “đã xác nhận” được ghi rõ trong cảnh báo.</p>
        </>
      )}
      {has("diagnosis.write") && c.allergy_status === "unknown" && (
        <button className="btn mt" onClick={async () => {
          if (await confirm({ message: "Xác nhận người này KHÔNG có dị ứng đã biết? Thông tin này sẽ dùng để cảnh báo khi kê đơn." }) &&
            await act(() => api("POST", `/persons/${personId}/allergy-status/none-confirmed`), "Đã xác nhận không dị ứng")) reload();
        }}>Xác nhận không có dị ứng</button>
      )}
    </Card>
  );
}

export function ProblemBlock({ personId, summary, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const uns = useUnsaved();
  const { data: icd } = useLoad(() => api("GET", "/catalogs/icd"), []);
  const c = summary?.clinical;
  if (!c) return null;
  return (
    <Card title="Vấn đề sức khỏe / bệnh mạn tính">
      <DataTable rows={c.problems} empty={<p className="muted" style={{ margin: 0 }}>Chưa ghi nhận vấn đề sức khỏe nào (không đồng nghĩa là không có bệnh).</p>}
        columns={[{ h: "Vấn đề", c: (p) => <b>{p.name}</b> }, { h: "Mã ICD", c: (p) => p.code || "—" }, { h: "Hiệu lực từ", c: (p) => fmtDate(p.effective_from) },
          { h: "Nguồn", c: (p) => p.source || "—" }, { h: "Trạng thái", c: (p) => <Status d="problem" v={p.status} /> },
          { h: "", stop: true, c: (p) => has("problem.write") && p.status === "active" && (
            <button className="btn sm" onClick={async () => {
              const note = await prompt({ title: "Kết thúc vấn đề sức khỏe", label: "Lý do/ghi chú", required: true });
              if (note && await act(() => api("POST", `/problems/${p.id}/resolve`, { note }), "Đã cập nhật")) reload();
            }}>Kết thúc</button>) }]} />
      {has("problem.write") && (
        <div {...uns.props}><Form className="fgrid mt" onSubmit={async (d) => { const r = await act(() => api("POST", `/persons/${personId}/problems`, d), "Đã ghi nhận vấn đề sức khỏe"); if (r) { uns.done(); reload(); } return r; }}>
          <IcdPair icd={icd} nameField="name" nameLabel="Tên vấn đề / bệnh" />
          <Field label="Mức xác nhận"><select name="confirmation" defaultValue="confirmed"><option value="confirmed">Đã xác nhận</option><option value="suspected">Nghi ngờ</option></select></Field>
          <div className="fbtn"><button className="btn primary">Thêm</button></div>
        </Form>{uns.badge}</div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ sinh hiệu
export function VitalsBlock({ e, open, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { notify } = useApp();
  const obs = [...e.observations].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  return (
    <Card title="Sinh hiệu & chỉ số đo">
      {open && has("observation.write") && (
        <Form onSubmit={async (d) => {
          const items = VITALS.filter((v) => d[v.key]);
          if (!items.length) { notify("Nhập ít nhất một chỉ số", false); return false; }
          let ok = true;
          for (const v of items) ok = ok && !!(await act(() => api("POST", `/encounters/${e.id}/observations`, { type: v.type, value: d[v.key], unit: v.unit, ...(d.at ? { occurred_at: d.at } : {}) })));
          if (ok) { reload(); }
          return ok;
        }}>
          <div className="grid4">
            {VITALS.map((v) => <Field key={v.key} label={`${v.type} (${v.unit})`}><input name={v.key} inputMode="decimal" /></Field>)}
            <Field label="Thời điểm đo" hint="Để trống = bây giờ"><input type="datetime-local" name="at" /></Field>
          </div>
          <button className="btn primary">Ghi nhận sinh hiệu</button>
        </Form>
      )}
      <div className="mt"><DataTable rows={obs} empty={<p className="muted">Chưa có chỉ số nào trong lượt khám này.</p>}
        columns={[{ h: "Thời điểm đo", c: (o) => fmtDT(o.occurred_at) }, { h: "Chỉ số", c: (o) => o.type }, { h: "Giá trị", c: (o) => <b>{o.value} {o.unit}</b> },
          { h: "Ghi vào hệ thống", c: (o) => <span className="muted">{fmtDT(o.recorded_at)}</span> }]} /></div>
    </Card>
  );
}

// ------------------------------------------------------------------ chẩn đoán
export function DiagnosisBlock({ e, open, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { data: icd } = useLoad(() => api("GET", "/catalogs/icd"), []);
  return (
    <Card title="Chẩn đoán">
      <DataTable rows={e.diagnoses} empty={<p className="muted" style={{ margin: 0 }}>Chưa có chẩn đoán.</p>}
        columns={[{ h: "Chẩn đoán", c: (d) => <b>{d.text}</b> }, { h: "Mã ICD", c: (d) => d.code || "—" }, { h: "Loại", c: (d) => <Badge tone={d.kind === "final" ? "ok" : "neutral"}>{d.kind === "final" ? "Chính thức" : "Sơ bộ"}</Badge> }, { h: "Ghi lúc", c: (d) => fmtDT(d.recorded_at) },
          { h: "", stop: true, c: (d) => has("problem.write") && d.kind === "final" && <button className="btn sm" title="Bệnh mạn tính/cần theo dõi lâu dài: thêm vào hồ sơ để các lần khám sau còn thấy và lập kế hoạch theo dõi" onClick={() => act(() => api("POST", `/persons/${e.person_id}/problems`, { name: d.text, ...(d.code && { code: d.code }), confirmation: "confirmed" }), "Đã thêm vào vấn đề sức khỏe")}>+ Vấn đề sức khỏe</button> }]} />
      {open && has("diagnosis.write") ? (
        <Form className="fgrid mt" onSubmit={async (d) => { const r = await act(() => api("POST", `/encounters/${e.id}/diagnoses`, d), "Đã ghi chẩn đoán"); if (r) reload(); return r; }}>
          <IcdPair icd={icd} nameField="text" nameLabel="Chẩn đoán" />
          <Field label="Loại"><select name="kind" defaultValue="preliminary"><option value="preliminary">Sơ bộ</option><option value="final">Chính thức</option></select></Field>
          <div className="fbtn"><button className="btn primary">Thêm chẩn đoán</button></div>
        </Form>
      ) : open && <p className="muted mt">Chỉ bác sĩ/y sĩ có thẩm quyền được ghi chẩn đoán.</p>}
    </Card>
  );
}

// ------------------------------------------------------------------ chỉ định xét nghiệm / thủ thuật
export function ClinicalOrdersBlock({ e, open, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  return (
    <Card title="Chỉ định xét nghiệm / thủ thuật">
      <DataTable rows={e.orders} empty={<p className="muted" style={{ margin: 0 }}>Chưa có chỉ định.</p>}
        columns={[{ h: "Loại", c: (o) => (o.kind === "lab" ? "Xét nghiệm" : "Thủ thuật") }, { h: "Nội dung", c: (o) => <b>{o.description}</b> }, { h: "Trạng thái", c: (o) => <Status d="clin" v={o.status} /> },
          { h: "Kết quả", c: (o) => o.result_text || (o.cancel_reason ? `Hủy: ${o.cancel_reason}` : "—") },
          { h: "", stop: true, c: (o) => o.status === "open" && (
            <div className="row">
              {has("observation.write") && <button className="btn sm primary" onClick={async () => {
                const t = await prompt({ title: `Kết quả: ${o.description}`, label: "Kết quả", multiline: true, required: true });
                if (t && await act(() => api("POST", `/orders/${o.id}/result`, { result_text: t }), "Đã ghi kết quả")) reload();
              }}>Nhập kết quả</button>}
              {has("order.write") && <button className="btn sm" onClick={async () => {
                const t = await prompt({ title: "Hủy chỉ định", label: "Lý do hủy", required: true });
                if (t && await act(() => api("POST", `/orders/${o.id}/cancel`, { reason: t }), "Đã hủy chỉ định")) reload();
              }}>Hủy</button>}
            </div>) }]} />
      {open && has("order.write") && (
        <Form className="grid3 mt" onSubmit={async (d) => { const r = await act(() => api("POST", `/encounters/${e.id}/orders`, d), "Đã chỉ định"); if (r) reload(); return r; }}>
          <Field label="Loại"><select name="kind" defaultValue="lab"><option value="lab">Xét nghiệm</option><option value="procedure">Thủ thuật</option></select></Field>
          <Field label="Nội dung chỉ định" required><input name="description" required placeholder="Công thức máu, X-quang phổi…" /></Field>
          <div style={{ paddingTop: 22 }}><button className="btn primary">Chỉ định</button></div>
        </Form>
      )}
      {open && e.orders.some((o) => o.status === "open") && <Banner tone="warn"><span className="sm">Còn chỉ định chờ kết quả: lượt khám chưa thể hoàn tất, hãy chuyển sang trạng thái “Chờ kết quả”.</span></Banner>}
    </Card>
  );
}

// ------------------------------------------------------------------ đơn thuốc (dùng chung Workbench + màn Kê đơn)
const ROUTES = ["uống", "tiêm bắp", "tiêm tĩnh mạch", "tiêm dưới da", "bôi ngoài da", "nhỏ mắt", "hít", "ngậm dưới lưỡi"];

export function RxCreateModal({ encounterId, onClose, onDone }) {
  const act = useAct();
  const { data: drugs } = useLoad(() => api("GET", "/catalogs/drug"), []);
  const [name, setName] = useState("");
  const item = drugs?.find((d) => d.name === name);
  const code = item?.code || "";
  const [strength, setStrength] = useState("");
  const [route, setRoute] = useState("uống");
  const pick = (v) => {                      // chọn thuốc trong danh mục → tự điền hàm lượng + đường dùng mặc định (vẫn sửa được)
    setName(v);
    const it = drugs?.find((d) => d.name === v);
    if (it?.extra?.strength) setStrength(it.extra.strength);
    if (it?.extra?.route && ROUTES.includes(it.extra.route)) setRoute(it.extra.route);
  };
  return (
    <FormModal title="Kê đơn thuốc (nháp)" wide onClose={onClose} submit="Tạo đơn nháp"
      onSubmit={async (d) => {
        const r = await act(() => api("POST", `/encounters/${encounterId}/medication-orders`, { ...d, supervised: !!d.supervised, duration_days: +d.duration_days, quantity_prescribed: +d.quantity_prescribed }, idem()), "Đã tạo đơn nháp – cần bác sĩ xác nhận");
        if (r) onDone(r); return !!r;
      }}>
      <div className="grid2">
        <Field label="Thuốc" required hint={code ? `Nhóm: ${item?.extra?.group || "—"} · mã danh mục ${code}` : `Gõ tên hoạt chất để tìm trong ${drugs?.length || 0} thuốc, hoặc nhập tên khác`}>
          <input name="drug_name" list="drugs" value={name} onChange={(e) => pick(e.target.value)} autoComplete="off" required />
        </Field>
        <datalist id="drugs">{(drugs || []).map((d) => <option key={d.id} value={d.name} label={`${d.extra?.group || ""} · ${d.code}`} />)}</datalist>
        <input type="hidden" name="drug_code" value={code} readOnly />
        <Field label="Hàm lượng"><input name="strength" placeholder="500mg" value={strength} onChange={(e) => setStrength(e.target.value)} autoComplete="off" /></Field>
        <Field label="Liều mỗi lần" required><input name="dose" defaultValue="1 viên" required /></Field>
        <Field label="Đường dùng" required><select name="route" value={route} onChange={(e) => setRoute(e.target.value)}>{ROUTES.map((r) => <option key={r}>{r}</option>)}</select></Field>
        <Field label="Tần suất" required><input name="frequency" list="freq" defaultValue="2 lần/ngày" required /></Field>
        <datalist id="freq">{["1 lần/ngày", "2 lần/ngày", "3 lần/ngày", "4 lần/ngày", "Khi cần"].map((x) => <option key={x} value={x} />)}</datalist>
        <Field label="Bắt đầu từ ngày" required><input type="date" name="start_date" defaultValue={today()} required /></Field>
        <Field label="Số ngày dùng" required><input type="number" min="1" name="duration_days" defaultValue="7" required /></Field>
        <Field label="Tổng số lượng kê" required hint="Số lượng tối đa được phép cấp phát"><input type="number" min="1" step="any" name="quantity_prescribed" defaultValue="14" required /></Field>
        <Field label=" "><label className="chk"><input type="checkbox" name="supervised" /> Cần giám sát uống thuốc</label></Field>
      </div>
      <Field label="Hướng dẫn sử dụng"><textarea name="instructions" placeholder="Uống sau ăn…" /></Field>
    </FormModal>
  );
}

/** Hook gom thao tác xác nhận / điều chỉnh / dừng đơn thuốc + modal đi kèm. */
export function useOrderActions(reload) {
  const act = useAct();
  const { notify, confirm } = useApp();
  const [m, setM] = useState(null);
  const confirmOrder = async (o) => {
    try {
      await api("POST", `/medication-orders/${o.id}/confirm`, {});
      notify("Đã xác nhận đơn thuốc"); reload();
    } catch (er) {
      if (er.data?.code === "WARNINGS_UNACKNOWLEDGED") setM({ t: "warn", o, warnings: er.data.warnings });
      else notify(er.message, false);
    }
  };
  const modals = m && (
    m.t === "warn" ? (
      <FormModal title="Cảnh báo an toàn khi kê đơn" danger submit="Vẫn xác nhận đơn" onClose={() => setM(null)}
        onSubmit={async (d) => { const r = await act(() => api("POST", `/medication-orders/${m.o.id}/confirm`, { acknowledge_warnings: true, ack_note: d.note }), "Đã xác nhận đơn thuốc"); if (r) reload(); return !!r; }}>
        <Banner tone="bad"><div><b>{m.o.drug_name}</b>{m.warnings.map((w, i) => <div key={i}>• {w.message}</div>)}</div></Banner>
        <p className="sm muted">Cảnh báo chỉ hỗ trợ, quyết định thuộc bác sĩ. Việc xác nhận và ghi chú xử lý sẽ được lưu vào nhật ký kiểm toán.</p>
        <Field label="Ghi chú xử lý (bắt buộc)" required><textarea name="note" required placeholder="Lý do vẫn kê / biện pháp theo dõi…" /></Field>
      </FormModal>
    ) : m.t === "revise" ? (
      <FormModal title={`Điều chỉnh đơn: ${m.o.drug_name}`} onClose={() => setM(null)} submit="Tạo phiên bản mới"
        onSubmit={async (d) => {
          const body = { reason: d.reason, ...(d.dose && { dose: d.dose }), ...(d.frequency && { frequency: d.frequency }), ...(d.duration_days && { duration_days: +d.duration_days }), ...(d.quantity_prescribed && { quantity_prescribed: +d.quantity_prescribed }) };
          const r = await act(() => api("POST", `/medication-orders/${m.o.id}/revise`, body), "Đã tạo bản điều chỉnh (nháp) – cần xác nhận"); if (r) reload(); return !!r;
        }}>
        <Banner tone="info"><span className="sm">Đơn đã xác nhận không sửa trực tiếp. Hệ thống tạo phiên bản mới (nháp); khi xác nhận, bản cũ được thay thế.</span></Banner>
        <div className="grid2"><Field label="Liều"><input name="dose" placeholder={m.o.dose} /></Field><Field label="Tần suất"><input name="frequency" placeholder={m.o.frequency} /></Field>
          <Field label="Số ngày"><input type="number" name="duration_days" placeholder={m.o.duration_days} /></Field><Field label="Tổng số lượng cả liệu trình" hint={m.o.dispensed_net > 0 ? `Đã gồm ${m.o.dispensed_net} đã cấp ở bản này – chỉ cấp thêm phần còn lại` : "Tổng số lượng được phép cấp"}><input type="number" step="any" name="quantity_prescribed" placeholder={m.o.quantity_prescribed} /></Field></div>
        <Field label="Lý do điều chỉnh" required><textarea name="reason" required /></Field>
      </FormModal>
    ) : (
      (
        <FormModal title={`Dừng/kết thúc đơn: ${m.o.drug_name}`} danger onClose={() => setM(null)} submit="Xác nhận"
          onSubmit={async (d) => { const r = await act(() => api("POST", `/medication-orders/${m.o.id}/stop`, d), "Đã cập nhật đơn"); if (r) reload(); return !!r; }}>
          <Field label="Kết cục" required><select name="outcome" defaultValue="stopped"><option value="stopped">Ngừng thuốc giữa chừng</option><option value="completed">Hoàn thành liệu trình</option><option value="cancelled">Hủy (chưa cấp phát)</option></select></Field>
          <Field label="Lý do" required><textarea name="reason" required /></Field>
        </FormModal>
      )
    )
  );
  const stopOrder = async (o) => {
    if (o.status === "draft") {       // đơn nháp chưa hoàn thành/chưa có hiệu lực: xóa luôn, không hỏi lý do
      if (await confirm({ title: "Xóa đơn nháp", message: `Xóa đơn nháp “${o.drug_name}”?`, okLabel: "Xóa", danger: true })
        && await act(() => api("POST", `/medication-orders/${o.id}/stop`, { outcome: "cancelled" }), "Đã xóa đơn nháp")) reload();
      return;
    }
    setM({ t: "stop", o });
  };
  return { confirmOrder, reviseOrder: (o) => setM({ t: "revise", o }), stopOrder, modals };
}

export function RxTable({ rows, actions, showPerson, empty }) {
  return (
    <DataTable rows={rows} empty={empty || <p className="muted" style={{ margin: 0 }}>Chưa có đơn thuốc.</p>}
      columns={[
        showPerson && { h: "Người bệnh", c: (o) => <b>{o.person_name}</b> },
        { h: "Thuốc", c: (o) => <><b>{o.drug_name}</b> {o.strength}{o.version > 1 && <Badge tone="info">v{o.version}</Badge>}{(o.warnings || []).map((w, i) => <div key={i}><Badge tone="bad">⚠ {w.message}</Badge></div>)}</> },
        { h: "Cách dùng", c: (o) => <span className="sm">{o.dose} · {o.route} · {o.frequency}<br />{o.duration_days} ngày từ {fmtDate(o.start_date)}</span> },
        { h: "SL kê", cls: "r", c: (o) => o.quantity_prescribed },
        { h: "Đã cấp", cls: "r", c: (o) => <>{o.dispensed_net ?? 0}{" "}<Status d="dispense" v={o.dispense_status} /></> },
        { h: "Trạng thái", c: (o) => <Status d="order" v={o.status} /> },
        actions && { h: "", stop: true, c: (o) => actions(o) },
      ].filter(Boolean)} />
  );
}

export function RxBlock({ e, open, reload }) {
  const { has } = useAuth();
  const [create, setCreate] = useState(false);
  const oa = useOrderActions(reload);
  const [totals, setTotals] = useState({});
  useEffect(() => {
    let live = true;
    Promise.all(e.medication_orders.map((o) => api("GET", `/medication-orders/${o.id}`).then((d) => [o.id, d]).catch(() => null)))
      .then((r) => live && setTotals(Object.fromEntries(r.filter(Boolean))));
    return () => (live = false);
  }, [e]);
  const rows = e.medication_orders.map((o) => ({ ...o, ...(totals[o.id] ? { dispensed_net: totals[o.id].dispensed_net, dispense_status: totals[o.id].dispense_status } : {}) }));
  return (
    <Card title="Đơn thuốc" actions={open && has("medorder.write") && <button className="btn primary sm" onClick={() => setCreate(true)}>+ Kê đơn</button>}>
      <RxTable rows={rows} actions={(o) => (
        <div className="row">
          {o.status === "draft" && has("medorder.confirm") && <button className="btn sm primary" title="Bác sĩ chốt đơn: sau đó dược sĩ mới cấp phát được; đơn đã xác nhận không sửa trực tiếp" onClick={() => oa.confirmOrder(o)}>Xác nhận</button>}
          {["confirmed", "active"].includes(o.status) && has("medorder.write") && <button className="btn sm" onClick={() => oa.reviseOrder(o)}>Điều chỉnh</button>}
          {o.status === "draft" && has("medorder.write") && <button className="btn sm" title="Xóa đơn nháp kê nhầm (chưa có hiệu lực)" onClick={() => oa.stopOrder(o)}>Xóa nháp</button>}
          {["confirmed", "active"].includes(o.status) && has("medorder.write") && <button className="btn sm" title="Ngừng thuốc đã có hiệu lực (ngừng giữa chừng, hoàn thành liệu trình)" onClick={() => oa.stopOrder(o)}>Dừng thuốc</button>}
        </div>)} />
      {!has("medorder.write") && <p className="muted sm mt">Chỉ bác sĩ/y sĩ được kê và xác nhận đơn. Cấp phát thực hiện ở tab “Cấp phát thuốc”.</p>}
      {has("medorder.write") && rows?.some?.((o) => o.status === "draft") && <p className="muted sm mt"><b>Đơn nháp</b> chưa có hiệu lực. Bác sĩ bấm <b>Xác nhận</b> để chốt đơn → dược sĩ mới cấp phát được (đơn đã xác nhận không sửa trực tiếp, dùng <b>Điều chỉnh</b>). <b>Xóa nháp</b> dùng khi kê nhầm; <b>Dừng thuốc</b> chỉ dùng cho thuốc đã xác nhận/đang dùng.</p>}
      {create && <RxCreateModal encounterId={e.id} onClose={() => setCreate(false)} onDone={reload} />}
      {oa.modals}
    </Card>
  );
}

// ------------------------------------------------------------------ kế hoạch theo dõi (problem → care plan → lịch hẹn)
export function PlanBlock({ personId, summary, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const [modal, setModal] = useState(null);
  const [editPlan, setEditPlan] = useState(null);
  const { data: plans, reload: rp } = useLoad(() => api("GET", `/persons/${personId}/care-plans`), [personId], !has("clinical.read"));
  const problems = (summary?.clinical?.problems || []).filter((p) => p.status === "active");
  const done = () => { rp(); reload?.(); };
  return (
    <Card title="Kế hoạch theo dõi & tái khám" actions={<div className="row">
      {has("careplan.write") && <button className="btn sm primary" disabled={!problems.length} title={problems.length ? "" : "Cần có vấn đề sức khỏe đang hiệu lực"} onClick={() => setModal("plan")}>+ Lập kế hoạch</button>}
      {has("schedule.write") && <button className="btn sm" onClick={() => setModal("appt")}>+ Hẹn tái khám</button>}</div>}>
      <DataTable rows={plans} empty={<p className="muted" style={{ margin: 0 }}>Chưa có kế hoạch theo dõi dài hạn.</p>}
        columns={[{ h: "Vấn đề", c: (p) => problems.concat(summary?.clinical?.problems || []).find((x) => x.id === p.problem_id)?.name || "—" }, { h: "Mục tiêu", c: (p) => p.goals },
          { h: "Chu kỳ", c: (p) => `${p.review_interval_days} ngày` }, { h: "Chỉ số cần đo", c: (p) => (p.measures || []).map((m) => `${m.name}${m.unit ? ` (${m.unit})` : ""}`).join(", ") || "—" },
          { h: "Trạng thái", c: (p) => <Status d="plan" v={p.status} /> },
          { h: "", stop: true, c: (p) => has("careplan.write") && p.status === "active" && <button className="btn sm" onClick={() => setEditPlan({ ...p, person_name: summary?.person?.full_name })}>Sửa</button> },
          { h: "", stop: true, c: (p) => has("careplan.write") && p.status === "active" && <button className="btn sm" onClick={async () => {
            const note = await prompt({ title: "Kết thúc kế hoạch theo dõi", label: "Lý do", required: true });
            if (note && await act(() => api("POST", `/care-plans/${p.id}/end`, { note }), "Đã kết thúc kế hoạch")) done();
          }}>Kết thúc</button> }]} />
      {summary?.clinical?.upcoming_appointments?.length > 0 && (
        <div className="mt"><b className="sm">Lịch sắp tới:</b> {summary.clinical.upcoming_appointments.map((a) => <Badge key={a.id} tone="info">{fmtDate(a.due_date)} · {a.kind === "care_plan" ? "theo kế hoạch" : a.kind === "periodic" ? "định kỳ" : "tái khám"}</Badge>)}</div>
      )}
      {modal === "plan" && (
        <FormModal title="Lập kế hoạch theo dõi" onClose={() => setModal(null)}
          onSubmit={async (d) => {
            const measures = (d.measures || "").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [name, unit] = l.split("|").map((x) => x.trim()); return { name, unit }; });
            const r = await act(() => api("POST", `/persons/${personId}/care-plans`, { problem_id: d.problem_id, goals: d.goals, measures, review_interval_days: +d.review_interval_days, ...(d.start_date && { start_date: d.start_date }) }), "Đã lập kế hoạch – hệ thống sẽ sinh lịch và nhắc việc");
            if (r) done(); return !!r;
          }}>
          <Field label="Vấn đề sức khỏe" required><select name="problem_id" required>{problems.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Mục tiêu theo dõi" required><textarea name="goals" required placeholder="Huyết áp < 140/90…" /></Field>
          <Field label="Chỉ số cần đo" hint="Mỗi dòng: tên | đơn vị. Ví dụ: Huyết áp tâm thu | mmHg"><textarea name="measures" /></Field>
          <div className="grid2"><Field label="Chu kỳ tái khám (ngày)" required><input type="number" min="1" name="review_interval_days" defaultValue="30" required /></Field>
            <Field label="Bắt đầu"><input type="date" name="start_date" defaultValue={today()} /></Field></div>
        </FormModal>
      )}
      {editPlan && <EditPlanModal plan={editPlan} onClose={() => setEditPlan(null)} onDone={() => { setEditPlan(null); done(); }} />}
      {modal === "appt" && (
        <FormModal title="Hẹn tái khám" onClose={() => setModal(null)}
          onSubmit={async (d) => { const r = await act(() => api("POST", "/appointments", { person_id: personId, ...d }), "Đã tạo lịch hẹn"); if (r) done(); return !!r; }}>
          <Field label="Ngày hẹn" required><input type="date" name="due_date" min={today()} required /></Field>
          <Field label="Nội dung"><textarea name="note" placeholder="Tái khám đánh giá đáp ứng điều trị…" /></Field>
        </FormModal>
      )}
    </Card>
  );
}

const measuresText = (m) => (m || []).map((x) => (x.unit ? `${x.name} | ${x.unit}` : x.name)).join("\n");
const parseMeasures = (t) => (t || "").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [name, unit] = l.split("|").map((x) => x.trim()); return { name, ...(unit && { unit }) }; });

/** Sửa kế hoạch theo dõi (WF-05 bước 5): mục tiêu, chỉ số cần đo, chu kỳ. Đổi chu kỳ sẽ dời lịch đang mở. */
export function EditPlanModal({ plan, onClose, onDone }) {
  const act = useAct();
  return (
    <FormModal title={`Sửa kế hoạch theo dõi – ${plan.person_name || ""}`} onClose={onClose} onSubmit={async (d) => {
      const r = await act(() => api("PATCH", `/care-plans/${plan.id}`, { goals: d.goals, measures: parseMeasures(d.measures), review_interval_days: +d.review_interval_days, expected_version: plan.version }), "Đã cập nhật kế hoạch");
      if (r) onDone(); return !!r;
    }}>
      {plan.problem_name && <p className="muted sm" style={{ marginTop: 0 }}>Vấn đề sức khỏe: <b>{plan.problem_name}</b></p>}
      <Field label="Mục tiêu điều trị" required><textarea name="goals" defaultValue={plan.goals} required minLength={3} /></Field>
      <Field label="Chỉ số cần đo" hint="Mỗi dòng: tên | đơn vị. Ví dụ: Huyết áp tâm thu | mmHg"><textarea name="measures" defaultValue={measuresText(plan.measures)} /></Field>
      <Field label="Chu kỳ theo dõi (ngày)" required hint="Đổi chu kỳ sẽ dời lịch theo dõi đang mở tính từ lần theo dõi gần nhất"><input type="number" name="review_interval_days" min={1} max={730} defaultValue={plan.review_interval_days} required /></Field>
    </FormModal>
  );
}

// ------------------------------------------------------------------ chuyển viện: chọn tài liệu bàn giao
/** Chọn các tài liệu HỢP LỆ của người bệnh để bàn giao kèm đề nghị chuyển viện (WF-06 bước 1). */
export function HandoverDocPicker({ personId, value, onChange }) {
  const { has } = useAuth();
  const { data, loading } = useLoad(() => api("GET", `/documents${qs({ person_id: personId })}`), [personId], !has("document.read"));
  const docs = (data || []).filter((d) => d.status === "valid");
  const toggle = (id) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);
  if (!has("document.read")) return <p className="muted sm">Bạn không có quyền xem tài liệu để chọn.</p>;
  if (loading) return <p className="muted sm">Đang tải tài liệu…</p>;
  if (!docs.length) return <p className="muted sm">Người bệnh chưa có tài liệu hợp lệ. Có thể tải lên ở tab “Tài liệu y tế” rồi chọn sau.</p>;
  return (
    <fieldset className="docpick"><legend className="sr-only">Tài liệu bàn giao kèm</legend>
      {docs.map((d) => (
        <label key={d.id} className="chk"><input type="checkbox" checked={value.includes(d.id)} onChange={() => toggle(d.id)} />
          <span><b>{d.filename}</b> <span className="muted sm">· {DOC_TYPE[d.doc_type] || d.doc_type} · v{d.version}{d.issued_date ? ` · ${fmtDate(d.issued_date)}` : ""}</span></span></label>
      ))}
    </fieldset>
  );
}

// ------------------------------------------------------------------ chuyển viện: lập đề nghị
export function ReferralCreateModal({ encounterId, personId, onClose, onDone }) {
  const act = useAct();
  const [docs, setDocs] = useState([]);
  return (
    <FormModal title="Lập đề nghị chuyển viện" onClose={onClose} submit="Lưu dự thảo"
      onSubmit={async (d) => { const r = await act(() => api("POST", `/encounters/${encounterId}/referrals`, { ...d, ...(docs.length && { handover_docs: docs }) }, idem()), "Đã lập đề nghị chuyển viện (dự thảo)"); if (r) onDone?.(r); return !!r; }}>
      <Field label="Mức khẩn" required><select name="urgency" defaultValue="routine"><option value="routine">Thường</option><option value="urgent">Khẩn</option><option value="emergency">Cấp cứu (được đi tắt, bắt buộc hậu kiểm)</option></select></Field>
      <Field label="Lý do chuyên môn" required hint="Chỉ định về y tế do bác sĩ xác định"><textarea name="reason" required minLength={5} /></Field>
      <Field label="Cơ sở tiếp nhận (dự kiến)"><input name="destination" /></Field>
      {personId && <div className="field" role="group" aria-labelledby="hdocs-l"><span id="hdocs-l">Tài liệu bàn giao kèm</span><HandoverDocPicker personId={personId} value={docs} onChange={setDocs} /><small>Chọn từ tài liệu hợp lệ của người bệnh (giấy tờ, kết quả xét nghiệm, chẩn đoán hình ảnh…)</small></div>}
    </FormModal>
  );
}

export function ReferralBlock({ e, reload, go }) {
  const { has } = useAuth();
  const [create, setCreate] = useState(false);
  return (
    <Card title="Chuyển viện" actions={e.status !== "cancelled" && has("referral.write") && <button className="btn sm primary" onClick={() => setCreate(true)}>+ Lập đề nghị chuyển viện</button>}>
      <DataTable rows={e.referrals} empty={<p className="muted" style={{ margin: 0 }}>Chưa có đề nghị chuyển viện.</p>}
        columns={[{ h: "Mức khẩn", c: (r) => <Status d="urgency" v={r.urgency} /> }, { h: "Lý do", c: (r) => r.reason }, { h: "Nơi tiếp nhận", c: (r) => r.destination || "—" }, { h: "Trạng thái", c: (r) => <Status d="referral" v={r.status} /> }]} />
      <p className="muted sm mt">Việc phê duyệt/điều phối và theo dõi điều trị ngoài trại thực hiện ở tab “Chuyển viện”. Chuyển viện không làm kết thúc đợt tiếp nhận.</p>
      {create && <ReferralCreateModal encounterId={e.id} personId={e.person_id} onClose={() => setCreate(false)} onDone={reload} />}
    </Card>
  );
}

// ------------------------------------------------------------------ tài liệu y tế
export function DocsPanel({ personId, encounterId, referralId, title = "Tài liệu y tế", compact }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const [type, setType] = useState("");
  const [up, setUp] = useState(null);
  const { data, reload } = useLoad(() => api("GET", `/documents${qs({ person_id: personId, doc_type: type })}`), [personId, type], !has("document.read"));
  const rows = (data || []).filter((d) => (!encounterId || d.encounter_id === encounterId) && (!referralId || d.referral_id === referralId));
  const { data: encs } = useLoad(() => api("GET", `/persons/${personId}/encounters`), [personId], !up || !has("clinical.read") || !!encounterId);
  return (
    <Card title={title} actions={<div className="row">
      {!compact && <select aria-label="Lọc theo loại tài liệu" value={type} onChange={(e) => setType(e.target.value)} style={{ width: "auto" }}><option value="">Tất cả loại</option>{Object.entries(DOC_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}
      {has("document.write") && <button className="btn primary sm" onClick={() => setUp({})}><span>+ Tải lên</span></button>}</div>}>
      <DataTable rows={has("document.read") ? rows : []} empty={<p className="muted" style={{ margin: 0 }}>{has("document.read") ? "Chưa có tài liệu." : "Bạn không có quyền xem tài liệu."}</p>}
        columns={[{ h: "Tệp", c: (d) => <><b>{d.filename}</b><div className="muted sm">{DOC_TYPE[d.doc_type]} · v{d.version} · {(d.size / 1024).toFixed(0)} KB</div></> },
          { h: "Nguồn / ngày phát hành", c: (d) => <span className="sm">{d.source || "—"}<br />{fmtDate(d.issued_date)}</span> }, { h: "Trạng thái", c: (d) => <Status d="doc" v={d.status} /> },
          { h: "Toàn vẹn", c: (d) => <code title={d.checksum}>{d.checksum.slice(0, 10)}…</code> },
          { h: "", stop: true, c: (d) => (
            <div className="row">
              <button className="btn sm" onClick={() => act(() => download(`/documents/${d.id}/download`, d.filename))}>Tải xuống</button>
              {has("document.write") && d.status === "valid" && <button className="btn sm" onClick={() => setUp({ replace: d })}>Thay thế</button>}
              {has("document.write") && d.status === "valid" && <button className="btn sm" onClick={async () => {
                const reason = await prompt({ title: "Đánh dấu tài liệu không hợp lệ", label: "Lý do (sai người, trùng bản…)", required: true });
                if (reason && await act(() => api("POST", `/documents/${d.id}/invalidate`, { reason }), "Đã đánh dấu không hợp lệ")) reload();
              }}>Không hợp lệ</button>}
            </div>) }]} />
      {up && (
        <FormModal title={up.replace ? `Thay thế tài liệu: ${up.replace.filename}` : "Tải tài liệu y tế"} onClose={() => setUp(null)} submit="Tải lên"
          onSubmit={async (d) => {
            if (!d.file) return false;
            const r = await act(() => up.replace
              ? upload(`/documents/${up.replace.id}/replace`, { source: d.source }, d.file)
              : upload("/documents", { doc_type: d.doc_type, person_id: personId, encounter_id: encounterId || d.encounter_id, referral_id: referralId, source: d.source, issued_date: d.issued_date }, d.file), "Đã tải lên và lưu mã hóa");
            if (r) reload(); return !!r;
          }}>
          {!up.replace && <Field label="Loại tài liệu" required><select name="doc_type" required>{Object.entries(DOC_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>}
          {!up.replace && !encounterId && !referralId && <Field label="Gắn với lượt khám" hint="Không bắt buộc – tài liệu luôn gắn với người bệnh">
            <select name="encounter_id" aria-label="Gắn với lượt khám" defaultValue=""><option value="">— Không gắn —</option>{(encs || []).map((x) => <option key={x.id} value={x.id}>{fmtDT(x.occurred_at)} · {statusLabel("encType", x.type)}</option>)}</select></Field>}
          <div className="grid2"><Field label="Nguồn phát hành"><input name="source" placeholder="Bệnh viện đa khoa…" /></Field>
            {!up.replace && <Field label="Ngày phát hành"><input type="date" name="issued_date" /></Field>}</div>
          <Field label="Tệp (PDF/PNG/JPEG, ≤ 10MB)" required><input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" required /></Field>
          <p className="muted sm">Hệ thống kiểm tra định dạng thực của tệp, quét mã độc, tính checksum và lưu bản mã hóa. Không sửa trực tiếp tệp đã lưu – dùng “Thay thế” để tạo phiên bản mới.</p>
        </FormModal>
      )}
    </Card>
  );
}
