// M06 – Cấp phát thuốc & xác nhận sử dụng (WF-03 bước 4–5). Cấp phát ≠ sử dụng: hai sự kiện riêng.
import { useState } from "react";
import { api, idem } from "../api";
import { Badge, Banner, Card, DataTable, Drawer, Empty, Field, FormModal, KV, PageHeader, Seg, Status, fmtDT, fmtDate, useAct, useAuth, useDebounced, useLoad } from "../ui.jsx";

function OrderDrawer({ id, onClose, onChanged }) {
  const { has } = useAuth();
  const act = useAct();
  const { data: o, reload } = useLoad(() => api("GET", `/medication-orders/${id}`), [id]);
  const [m, setM] = useState(null);
  if (!o) return null;
  const done = () => { reload(); onChanged(); };
  const dispenses = o.dispenses.filter((d) => d.kind === "dispense");
  return (
    <Drawer title={`${o.drug_name} ${o.strength || ""}`} onClose={onClose}>
      <div className="cols">
        <Card title="Chỉ định của bác sĩ" actions={<Status d="order" v={o.status} />}>
          <KV items={[["Cách dùng", `${o.dose} · ${o.route} · ${o.frequency}`], ["Thời gian", `${o.duration_days} ngày từ ${fmtDate(o.start_date)}`], ["Số lượng được kê", o.quantity_prescribed], ["Đã cấp (ròng)", <b key="n">{o.dispensed_net} <Status d="dispense" v={o.dispense_status} /></b>], ["Còn lại", o.remaining], ["Giám sát uống thuốc", o.supervised ? "Có" : "Không"], ["Hướng dẫn", o.instructions]]} />
          {(o.warnings || []).map((w, i) => <Banner key={i} tone="bad">{w.message}</Banner>)}
        </Card>
        <Card title="Thao tác">
          <div className="row">
            {has("dispense.write") && ["confirmed", "active"].includes(o.status) && o.remaining > 0 && <button className="btn primary" onClick={() => setM("dispense")}>Cấp thuốc</button>}
            {has("dispense.write") && dispenses.length > 0 && <button className="btn" onClick={() => setM("return")}>Hoàn trả / hủy cấp phát</button>}
            {has("admin.write") && <button className="btn" onClick={() => setM("admin")}>Ghi nhận sử dụng thuốc</button>}
          </div>
          <p className="muted sm mt">Thuốc chỉ được cấp theo đơn còn hiệu lực. “Đã cấp” không đồng nghĩa “đã uống”.</p>
        </Card>
      </div>
      <Card title="Lịch sử cấp phát" flat>
        <DataTable rows={o.dispenses} empty={<Empty title="Chưa có cấp phát" />}
          columns={[{ h: "Thời điểm", c: (d) => fmtDT(d.occurred_at) }, { h: "Loại", c: (d) => <Badge tone={d.kind === "dispense" ? "ok" : "warn"}>{d.kind === "dispense" ? "Cấp phát" : d.kind === "return" ? "Hoàn trả" : "Hủy"}</Badge> }, { h: "Số lượng", cls: "r", c: (d) => d.quantity }, { h: "Ghi nhận", c: (d) => d.kind === "dispense" ? <Status d="dispense" v={d.status} /> : "—" }, { h: "Ghi chú", c: (d) => d.note || "—" }]} />
      </Card>
      <Card title="Xác nhận sử dụng thuốc" flat>
        <DataTable rows={o.administrations} empty={<Empty title="Chưa có ghi nhận sử dụng" />}
          columns={[{ h: "Thời điểm", c: (a) => fmtDT(a.occurred_at) }, { h: "Kết quả", c: (a) => (a.administered ? <Badge tone="ok">Đã dùng</Badge> : <Badge tone="bad">Không dùng</Badge>) }, { h: "Lý do", c: (a) => a.reason || "—" }]} />
      </Card>
      {m === "dispense" && (
        <FormModal title="Cấp thuốc" onClose={() => setM(null)} submit="Ghi nhận cấp phát"
          onSubmit={async (d) => {
            const r = await act(() => api("POST", `/medication-orders/${o.id}/dispenses`, { quantity: +d.quantity, ...(d.note && { note: d.note }) }, idem()));
            if (r?.order) { act(async () => {}, r.status === "full" ? "Đã cấp đủ theo đơn" : `Cấp một phần – còn thiếu ${r.order.remaining}`); done(); } return !!r;
          }}>
          <Banner tone="info"><span className="sm">Đối chiếu đơn: <b>{o.drug_name}</b>, còn được cấp tối đa <b>{o.remaining}</b>. Số lượng thực cấp có thể khác số lượng kê.</span></Banner>
          <Field label="Số lượng thực cấp" required><input type="number" name="quantity" min="0.01" max={o.remaining} step="any" defaultValue={o.remaining} required /></Field>
          <Field label="Ghi chú"><input name="note" placeholder="Hết thuốc, cấp trước 10 viên…" /></Field>
        </FormModal>
      )}
      {m === "return" && (
        <FormModal title="Hoàn trả / hủy cấp phát" onClose={() => setM(null)} danger submit="Ghi nhận"
          onSubmit={async (d) => { const r = await act(() => api("POST", `/medication-orders/${o.id}/dispenses`, { kind: d.kind, quantity: +d.quantity, ref_dispense_id: d.ref, note: d.note }, idem()), "Đã ghi nhận"); if (r) done(); return !!r; }}>
          <Field label="Lần cấp phát liên quan" required><select name="ref" required>{dispenses.map((d) => <option key={d.id} value={d.id}>{fmtDT(d.occurred_at)} · {d.quantity}</option>)}</select></Field>
          <div className="grid2"><Field label="Loại" required><select name="kind"><option value="return">Hoàn trả</option><option value="cancel">Hủy cấp phát</option></select></Field>
            <Field label="Số lượng" required><input type="number" name="quantity" step="any" min="0.01" required /></Field></div>
          <Field label="Lý do" required><textarea name="note" required /></Field>
        </FormModal>
      )}
      {m === "admin" && (
        <FormModal title="Ghi nhận sử dụng thuốc" onClose={() => setM(null)}
          onSubmit={async (d) => { const r = await act(() => api("POST", `/medication-orders/${o.id}/administrations`, { administered: d.administered === "yes", reason: d.reason, ...(d.dispense_id && { dispense_id: d.dispense_id }) }), "Đã ghi nhận"); if (r) done(); return !!r; }}>
          <Field label="Người bệnh đã dùng thuốc?" required><select name="administered" defaultValue="yes"><option value="yes">Đã dùng</option><option value="no">Không dùng (từ chối/quên liều/đổi thuốc)</option></select></Field>
          <Field label="Lần cấp phát"><select name="dispense_id" defaultValue=""><option value="">— Không chỉ định —</option>{dispenses.map((d) => <option key={d.id} value={d.id}>{fmtDT(d.occurred_at)} · {d.quantity}</option>)}</select></Field>
          <Field label="Lý do (bắt buộc nếu không dùng)"><textarea name="reason" /></Field>
        </FormModal>
      )}
    </Drawer>
  );
}

const PAGE = 30;
const norm = (t) => String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").toLowerCase();

/** Danh sách đơn gom theo NGƯỜI BỆNH, trong mỗi người chia theo từng ĐỢT KÊ ĐƠN (lượt khám). Có tìm kiếm, thu gọn/mở rộng, phân trang theo người. */
function GroupedOrders({ rows, loading, onOpen, empty }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [openSet, setOpenSet] = useState({});          // person_id -> true/false (mặc định theo số lượng)
  const [shown, setShown] = useState(PAGE);
  if (loading && !rows) return <div className="empty">Đang tải…</div>;
  const key = norm(dq);
  const list = (rows || []).filter((o) => !key || norm(o.person_name).includes(key) || norm(o.drug_name).includes(key));
  const byPerson = new Map();
  for (const o of list) { if (!byPerson.has(o.person_id)) byPerson.set(o.person_id, { id: o.person_id, name: o.person_name, orders: [] }); byPerson.get(o.person_id).orders.push(o); }
  const groups = [...byPerson.values()].map((g) => {
    const enc = new Map();
    for (const o of g.orders) { const k = o.encounter_id || o.id; if (!enc.has(k)) enc.set(k, { id: k, at: o.recorded_at, orders: [] }); const e = enc.get(k); e.orders.push(o); if (o.recorded_at < e.at) e.at = o.recorded_at; }
    return { ...g, courses: [...enc.values()].sort((a, b) => (a.at < b.at ? 1 : -1)), missing: g.orders.reduce((t, o) => t + (o.remaining || 0), 0) };
  }).sort((a, b) => b.missing - a.missing || a.name.localeCompare(b.name, "vi"));
  const isOpen = (g) => openSet[g.id] ?? (key ? true : groups.length <= 5);   // ít người/đang tìm: mở sẵn; nhiều người: thu gọn
  const setAll = (v) => setOpenSet(Object.fromEntries(groups.map((g) => [g.id, v])));
  return (
    <>
      <div className="row" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
        <input className="search" placeholder="Tìm theo tên người bệnh hoặc tên thuốc…" aria-label="Tìm đơn thuốc" value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} style={{ maxWidth: 360 }} />
        <span className="muted sm">{groups.length} người · {list.length} đơn</span>
        <span className="right row"><button className="btn sm" onClick={() => setAll(true)}>Mở tất cả</button><button className="btn sm" onClick={() => setAll(false)}>Thu gọn tất cả</button></span></div>
      {!groups.length ? empty : groups.slice(0, shown).map((g) => (
        <div key={g.id} className="ogroup">
          <button className="ohead" aria-expanded={isOpen(g)} onClick={() => setOpenSet({ ...openSet, [g.id]: !isOpen(g) })}>
            <span className="ocaret" aria-hidden="true">{isOpen(g) ? "▾" : "▸"}</span>
            <b>{g.name}</b>
            <span className="muted sm">{g.orders.length} đơn · {g.courses.length} đợt kê</span>
            <span className="right">{g.missing > 0 ? <Badge tone="warn">Còn thiếu {g.missing}</Badge> : <Badge tone="ok">Đã cấp đủ</Badge>}</span>
          </button>
          {isOpen(g) && g.courses.map((c) => (
            <div key={c.id} className="ocourse">
              <div className="muted sm" style={{ padding: "6px 16px" }}>Đợt kê ngày <b>{fmtDate(c.at)}</b> · {c.orders.length} thuốc</div>
              <DataTable rows={c.orders} onRow={(o) => onOpen(o.id)}
                columns={[{ h: "Thuốc", c: (o) => <>{o.drug_name} {o.supervised && <Badge tone="info">Giám sát</Badge>}</> }, { h: "Cách dùng", c: (o) => <span className="sm">{o.dose} · {o.frequency}</span> },
                  { h: "Kê", cls: "r", c: (o) => o.quantity_prescribed }, { h: "Đã cấp", cls: "r", c: (o) => o.dispensed_net }, { h: "Còn thiếu", cls: "r", c: (o) => <b>{o.remaining}</b> },
                  { h: "Cấp phát", c: (o) => <Status d="dispense" v={o.dispense_status} /> }, { h: "", c: () => <button className="btn sm primary">Mở</button> }]} />
            </div>
          ))}
        </div>
      ))}
      {groups.length > shown && <div style={{ padding: 14, textAlign: "center" }}><button className="btn" onClick={() => setShown(shown + PAGE)}>Xem thêm {Math.min(PAGE, groups.length - shown)} người ({groups.length - shown} người còn lại)</button></div>}
    </>
  );
}

export default function Pharmacy({ focus }) {
  const { has, refreshStats } = useAuth();
  const [view, setView] = useState(has("dispense.write") ? "queue" : "super");
  const [open, setOpen] = useState(focus || null);
  const queue = useLoad(() => api("GET", "/dispense-queue"), [], !has("dispense.write") || view !== "queue");
  const orders = useLoad(() => api("GET", "/medication-orders?status=confirmed,active,completed,stopped"), [view], view === "queue");
  const reload = () => { queue.reload(); orders.reload(); refreshStats(); };
  const rows = view === "queue" ? queue.data : view === "super" ? orders.data?.filter((o) => o.supervised && o.dispensed_net > 0 && ["confirmed", "active"].includes(o.status)) : orders.data;
  return (
    <>
      <PageHeader title="Cấp phát thuốc" sub="M06 · Đối chiếu đơn, ghi nhận thực cấp (đủ/một phần), hoàn trả/hủy có lý do, và xác nhận việc dùng thuốc khi cần giám sát." />
      <div style={{ marginBottom: 14 }}><Seg value={view} onChange={setView} items={[has("dispense.write") && { id: "queue", label: "Hàng đợi cấp phát" }, { id: "super", label: "Giám sát dùng thuốc" }, { id: "hist", label: "Tất cả đơn" }].filter(Boolean)} /></div>
      <Card flat>
        <GroupedOrders rows={rows} loading={view === "queue" ? queue.loading : orders.loading} onOpen={setOpen} empty={<Empty title={view === "queue" ? "Không có đơn nào cần cấp phát" : "Không có dữ liệu"} />} />
      </Card>
      {open && <OrderDrawer id={open} onClose={() => { setOpen(null); reload(); }} onChanged={reload} />}
    </>
  );
}
