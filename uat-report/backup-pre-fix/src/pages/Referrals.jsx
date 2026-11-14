// M09 – Chuyển viện (WF-06): bảng theo trạng thái; quyết định y khoa (bác sĩ) tách khỏi duyệt/điều phối (người phê duyệt).
import { useState } from "react";
import { api } from "../api";
import { DocsPanel, HandoverDocPicker, ReferralCreateModal } from "../components/blocks.jsx";
import { PatientPicker } from "../patient.jsx";
import { DOC_TYPE, OUTCOME } from "../labels";
import { Badge, Banner, Card, DataTable, Drawer, Empty, Field, FormModal, KV, Modal, PageHeader, Seg, Status, Stepper, fmtDT, useApp, useAct, useAuth, useLoad } from "../ui.jsx";

const COLS = ["draft", "pending", "coordinated", "in_external_treatment", "result_received"];
const STEPS = ["draft", "pending", "coordinated", "in_external_treatment", "result_received", "completed"];
const STEP_LABEL = ["Dự thảo", "Chờ xử lý", "Đã điều phối", "Điều trị ngoài trại", "Có kết quả", "Hoàn tất"];
const localNow = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

function Detail({ id, onClose, onChanged }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const { data: r, reload } = useLoad(() => api("GET", `/referrals/${id}`), [id]);
  const [m, setM] = useState(null);
  if (!r) return null;
  const done = () => { reload(); onChanged(); };
  const patch = (body, ok) => act(() => api("PATCH", `/referrals/${r.id}/status`, { ...body, expected_version: r.version }), ok).then((x) => { if (x) done(); return !!x; });
  const emergencyShortcut = r.urgency === "emergency" && ["draft", "pending", "coordinated"].includes(r.status) && (has("referral.write") || has("referral.update"));
  const btn = (label, key, primary) => <button className={`btn ${primary ? "primary" : ""}`} onClick={() => setM(key)}>{label}</button>;
  return (
    <Drawer title={`Chuyển viện${r.person_name ? ` – ${r.person_name}` : ""}`} onClose={onClose} actions={<Status d="urgency" v={r.urgency} />}>
      {r.status === "cancelled" ? <Banner tone="warn">Đề nghị chuyển viện đã bị hủy.</Banner> : <Stepper steps={STEP_LABEL} current={Math.max(0, STEPS.indexOf(r.status)) + (r.status === "completed" ? 1 : 0)} />}
      {r.needs_post_review && <Banner tone="warn"><div style={{ flex: 1 }}><b>{r.shortcut_used ? "Chuyển viện cấp cứu đã dùng đường tắt – cần hậu kiểm." : `Kết thúc với kết cục “${OUTCOME[r.outcome] || r.outcome}” – cần xác nhận theo quy trình được duyệt.`}</b></div>{has("referral.approve") && <button className="btn sm primary" onClick={async () => { const note = await prompt({ title: "Hậu kiểm chuyển viện cấp cứu", label: "Kết luận hậu kiểm", required: true }); if (note && await act(() => api("POST", `/referrals/${r.id}/post-review`, { note }), "Đã hậu kiểm")) done(); }}>Hậu kiểm</button>}</Banner>}
      <div className="cols">
        <Card title="Thông tin chuyển viện">
          <KV items={[["Trạng thái", <Status key="s" d="referral" v={r.status} />], ["Lý do chuyên môn", r.clinical_hidden ? <span key="h" className="muted">Ẩn theo phân quyền (chỉ nhân viên y tế)</span> : r.reason], ["Cơ sở tiếp nhận", r.destination], ["Rời trại lúc", r.left_at && fmtDT(r.left_at)], !r.clinical_hidden && ["Kết quả điều trị", r.result_note], !r.clinical_hidden && ["Kế hoạch sau chuyển viện", r.post_referral_plan], r.outcome && ["Kết cục", OUTCOME[r.outcome]]]} />
        </Card>
        <Card title="Thao tác">
          <div className="row">
            {r.status === "draft" && has("referral.write") && btn("Gửi duyệt/điều phối", "submit", true)}
            {r.status === "pending" && has("referral.approve") && btn("Phê duyệt & điều phối", "approve", true)}
            {r.status === "coordinated" && has("referral.update") && btn("Xác nhận đã rời trại", "depart", true)}
            {r.status === "coordinated" && has("referral.update") && btn("BV đổi / không tiếp nhận", "back")}
            {r.status === "in_external_treatment" && has("referral.update") && btn("Ghi nhận kết quả điều trị", "result", true)}
            {["in_external_treatment", "result_received", "coordinated"].includes(r.status) && has("referral.update") && <button className="btn" onClick={async () => { const note = await prompt({ title: "Ghi nhận diễn biến", label: "Nội dung", multiline: true, required: true }); if (note && await act(() => api("POST", `/referrals/${r.id}/events`, { note }), "Đã ghi nhận")) done(); }}>Ghi nhận diễn biến</button>}
            {r.status === "result_received" && has("referral.write") && btn("Hoàn thành chuyển viện", "complete", true)}
            {emergencyShortcut && <button className="btn danger" onClick={() => setM("shortcut")}>Chuyển viện khẩn (đi tắt)</button>}
            {["draft", "pending", "coordinated"].includes(r.status) && has("referral.write") && btn("Hủy", "cancel")}
          </div>
          <p className="muted sm mt">Chuyển viện không làm kết thúc đợt tiếp nhận. Hồ sơ sức khỏe của người bệnh được giữ nguyên.</p>
        </Card>
      </div>
      <Card title="Tài liệu bàn giao kèm" actions={["draft", "pending", "coordinated"].includes(r.status) && has("referral.write") && has("document.read") && <button className="btn sm" onClick={() => setM("docs")}>Chọn tài liệu</button>}>
        {r.handover_docs_detail?.length ? <ul className="tl">{r.handover_docs_detail.map((d) => <li key={d.id}><b>{d.filename || DOC_TYPE[d.doc_type] || "Tài liệu"}</b> <small>{DOC_TYPE[d.doc_type] || d.doc_type} · v{d.version}{d.status !== "valid" && " · không còn hiệu lực"}</small></li>)}</ul>
          : <p className="muted sm" style={{ margin: 0 }}>Chưa chọn tài liệu bàn giao kèm.</p>}
      </Card>
      <Card title="Lịch sử điều phối">
        <ul className="tl">{r.events.map((e) => <li key={e.id}><b>{e.from_status && e.from_status !== e.to_status ? `${STEP_LABEL[STEPS.indexOf(e.from_status)] || e.from_status} → ` : ""}{e.to_status === "cancelled" ? "Đã hủy" : STEP_LABEL[STEPS.indexOf(e.to_status)] || e.to_status}</b>{e.note ? ` – ${e.note}` : ""}<small>Xảy ra {fmtDT(e.occurred_at)} · nhập {fmtDT(e.recorded_at)}</small></li>)}</ul>
      </Card>
      {has("document.read") && <DocsPanel personId={r.person_id} referralId={r.id} title="Tài liệu chuyển viện (giấy ra viện, kết quả…)" compact />}

      {m === "docs" && <HandoverDocsModal r={r} onClose={() => setM(null)} onDone={() => { setM(null); done(); }} />}
      {m === "submit" && <Modal title="Gửi duyệt" onClose={() => setM(null)} footer={<><button className="btn" onClick={() => setM(null)}>Hủy</button><button className="btn primary" onClick={async () => { if (await patch({ to: "pending" }, "Đã gửi duyệt")) setM(null); }}>Gửi</button></>}>Gửi đề nghị cho người có thẩm quyền duyệt/điều phối?</Modal>}
      {m === "approve" && <FormModal title="Phê duyệt & điều phối" onClose={() => setM(null)} onSubmit={(d) => patch({ to: "coordinated", destination: d.destination, note: d.note }, "Đã điều phối")}><Field label="Cơ sở tiếp nhận" required><input name="destination" defaultValue={r.destination || ""} required /></Field><Field label="Ghi chú điều phối"><textarea name="note" /></Field></FormModal>}
      {m === "depart" && <FormModal title="Xác nhận rời trại" onClose={() => setM(null)} onSubmit={(d) => patch({ to: "in_external_treatment", destination: d.destination, left_at: new Date(d.left_at).toISOString(), note: d.note }, "Đã ghi nhận rời trại")}><Field label="Cơ sở tiếp nhận" required><input name="destination" defaultValue={r.destination || ""} required /></Field><Field label="Thời điểm rời trại" required><input type="datetime-local" name="left_at" defaultValue={localNow()} required /></Field><Field label="Ghi chú bàn giao"><textarea name="note" /></Field></FormModal>}
      {m === "back" && <FormModal title="Bệnh viện đổi / không tiếp nhận" onClose={() => setM(null)} onSubmit={(d) => patch({ to: "pending", destination: d.destination, note: d.note }, "Đã cập nhật điều phối")}><Field label="Lý do" required><textarea name="note" required /></Field><Field label="Cơ sở tiếp nhận mới"><input name="destination" /></Field></FormModal>}
      {m === "result" && <FormModal title="Kết quả điều trị ngoài trại" onClose={() => setM(null)} onSubmit={(d) => patch({ to: "result_received", result_note: d.result_note }, "Đã ghi nhận kết quả")}><Field label="Kết quả điều trị / diễn biến" required hint="Hoặc đính kèm giấy ra viện ở mục tài liệu phía dưới rồi ghi tóm tắt"><textarea name="result_note" required /></Field></FormModal>}
      {m === "complete" && <FormModal title="Hoàn thành chuyển viện" onClose={() => setM(null)} onSubmit={(d) => patch({ to: "completed", post_referral_plan: d.plan, outcome: d.outcome }, "Đã hoàn thành chuyển viện")}><Field label="Kết cục" required><select name="outcome" defaultValue="returned">{Object.entries(OUTCOME).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field><Field label="Kế hoạch sau chuyển viện" required hint="Thuốc, theo dõi, tái khám…"><textarea name="plan" required /></Field></FormModal>}
      {m === "cancel" && <FormModal title="Hủy đề nghị chuyển viện" danger onClose={() => setM(null)} onSubmit={(d) => patch({ to: "cancelled", note: d.note }, "Đã hủy")}><Field label="Lý do" required><textarea name="note" required /></Field></FormModal>}
      {m === "shortcut" && <FormModal title="Chuyển viện khẩn – đi tắt" danger submit="Xác nhận chuyển" onClose={() => setM(null)} onSubmit={(d) => patch({ to: "in_external_treatment", destination: d.destination, left_at: new Date(d.left_at).toISOString(), note: d.note }, "Đã chuyển khẩn – chờ hậu kiểm")}>
        <Banner tone="bad"><span className="sm">Trường hợp cấp cứu được bỏ qua bước phê duyệt để không cản trở xử trí; hệ thống bắt buộc hậu kiểm sau đó.</span></Banner>
        <Field label="Cơ sở tiếp nhận" required><input name="destination" defaultValue={r.destination || ""} required /></Field><Field label="Thời điểm rời trại" required><input type="datetime-local" name="left_at" defaultValue={localNow()} required /></Field><Field label="Ghi chú"><textarea name="note" /></Field></FormModal>}
    </Drawer>
  );
}

function HandoverDocsModal({ r, onClose, onDone }) {
  const act = useAct();
  const [docs, setDocs] = useState(r.handover_docs || []);
  return (
    <FormModal title="Tài liệu bàn giao kèm" onClose={onClose} onSubmit={async () => { const x = await act(() => api("PUT", `/referrals/${r.id}/handover-docs`, { handover_docs: docs }), "Đã cập nhật tài liệu bàn giao"); if (x) onDone(); return !!x; }}>
      <HandoverDocPicker personId={r.person_id} value={docs} onChange={setDocs} />
    </FormModal>
  );
}

function NewReferral({ onClose, onDone }) {
  const [p, setP] = useState(null);
  const [pick, setPick] = useState(true);
  const [enc, setEnc] = useState(null);
  const { data: encs } = useLoad(() => api("GET", `/persons/${p.id}/encounters`), [p?.id], !p);
  const rows = (encs || []).filter((e) => !["cancelled"].includes(e.status));
  if (enc) return <ReferralCreateModal encounterId={enc} personId={p?.id} onClose={onClose} onDone={onDone} />;
  return (
    <>
      <Modal title="Lập đề nghị chuyển viện – chọn lượt khám" onClose={onClose}>
        <Field label="Người bệnh"><div className="row">{p ? <b>{p.full_name}</b> : <span className="muted">Chưa chọn</span>}<button className="btn sm" onClick={() => setPick(true)}>{p ? "Đổi" : "Chọn…"}</button></div></Field>
        {p && <DataTable rows={rows} onRow={(e) => setEnc(e.id)} empty={<Banner tone="warn">Chưa có lượt khám nào.</Banner>} columns={[{ h: "Lượt khám", c: (e) => fmtDT(e.occurred_at) }, { h: "Trạng thái", c: (e) => <Status d="enc" v={e.status} /> }, { h: "", c: () => <button className="btn sm primary">Chọn</button> }]} />}
      </Modal>
      {pick && <PatientPicker onPick={setP} onClose={() => setPick(false)} title="Chọn người bệnh" />}
    </>
  );
}

export default function Referrals({ focus }) {
  const { has, refreshStats } = useAuth();
  const [view, setView] = useState("open");
  const [urg, setUrg] = useState("");
  const [open, setOpen] = useState(focus || null);
  const [nw, setNw] = useState(false);
  const { data, reload } = useLoad(() => api("GET", "/referrals"), []);
  const after = () => { reload(); refreshStats(); };
  const rows = (data || []).filter((r) => !urg || r.urgency === urg);
  const closed = rows.filter((r) => ["completed", "cancelled"].includes(r.status));
  return (
    <>
      <PageHeader title="Chuyển viện" sub="M09 · Bác sĩ xác định chỉ định y tế; người có thẩm quyền phê duyệt/điều phối; nhân viên y tế bàn giao tài liệu và theo dõi kết quả sau chuyển viện."
        actions={has("referral.write") && <button className="btn primary" onClick={() => setNw(true)}>+ Lập đề nghị chuyển viện</button>} />
      <div className="row" style={{ marginBottom: 14 }}>
        <Seg value={view} onChange={setView} items={[{ id: "open", label: "Đang xử lý" }, { id: "closed", label: `Đã đóng (${closed.length})` }]} />
        <select aria-label="Lọc theo mức khẩn" value={urg} onChange={(e) => setUrg(e.target.value)} style={{ width: "auto" }}><option value="">Mọi mức khẩn</option><option value="emergency">Cấp cứu</option><option value="urgent">Khẩn</option><option value="routine">Thường</option></select>
      </div>
      {view === "open" ? (
        <div className="board" tabIndex={0} role="region" aria-label="Bảng chuyển viện theo trạng thái (cuộn ngang bằng phím mũi tên)">
          {COLS.map((c) => {
            const items = rows.filter((r) => r.status === c);
            return (
              <div key={c} className="col"><h3>{STEP_LABEL[STEPS.indexOf(c)]}<span>{items.length}</span></h3>
                {items.map((r) => (
                  <div key={r.id} className="kcard" onClick={() => setOpen(r.id)}>
                    <div className="row"><Status d="urgency" v={r.urgency} />{r.needs_post_review && <Badge tone="warn">Hậu kiểm</Badge>}</div>
                    <div style={{ margin: "6px 0 2px" }}><b>{r.person_name || `Hồ sơ ${r.id.slice(0, 6)}`}</b></div>
                    <div className="muted sm">{r.destination || "Chưa có nơi tiếp nhận"}</div>
                    <div className="muted sm">{fmtDT(r.recorded_at)}</div>
                  </div>))}
                {!items.length && <div className="muted sm" style={{ textAlign: "center", padding: 12 }}>—</div>}
              </div>
            );
          })}
        </div>
      ) : (
        <Card flat><DataTable rows={closed} onRow={(r) => setOpen(r.id)} empty={<Empty title="Chưa có hồ sơ đã đóng" />}
          columns={[{ h: "Người", c: (r) => <b>{r.person_name || r.id.slice(0, 8)}</b> }, { h: "Nơi tiếp nhận", c: (r) => r.destination || "—" }, { h: "Kết cục", c: (r) => OUTCOME[r.outcome] || "—" }, { h: "Trạng thái", c: (r) => <Status d="referral" v={r.status} /> }, { h: "Ghi nhận", c: (r) => fmtDT(r.recorded_at) }]} /></Card>
      )}
      {open && <Detail id={open} onClose={() => setOpen(null)} onChanged={after} />}
      {nw && <NewReferral onClose={() => setNw(false)} onDone={(r) => { after(); setOpen(r.id); }} />}
    </>
  );
}
