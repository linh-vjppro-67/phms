// M01 – Tiếp nhận & hồ sơ phạm nhân tham chiếu (WF-01 bước 1–3).
import { useEffect, useState } from "react";
import { ApiError, api, qs } from "../api";
import { usePatient } from "../patient.jsx";
import { Badge, Banner, Card, DataTable, Drawer, Empty, Field, FormModal, KV, Modal, PageHeader, Seg, Status, fmtDate, today, useApp, useAct, useAuth, useDebounced, useLoad } from "../ui.jsx";

/** Đối soát danh tính. Máy chủ báo nghi trùng (409 DUPLICATE_SUSPECTED) -> xem danh sách, rồi xác nhận
 *  "đây là người khác" (confirm_distinct) giống bước kiểm tra trùng khi tạo hồ sơ mới; cùng một người thì đề nghị gộp. */
export function VerifyIdentityModal({ personId, defaults = {}, title = "Đối soát danh tính", onClose, onDone }) {
  const act = useAct();
  const { notify } = useApp();
  const [draft, setDraft] = useState(defaults);
  const [cands, setCands] = useState(null);
  const send = async (body) => {
    try {
      await api("POST", `/persons/${personId}/verify`, body);
      notify("Đã xác minh danh tính"); onDone(); return true;
    } catch (e) {
      if (e instanceof ApiError && e.data.code === "DUPLICATE_SUSPECTED") { setDraft(body); setCands(e.data.candidates || []); return false; }
      await act(() => Promise.reject(e));
      return false;
    }
  };
  if (cands) return (
    <Modal title={`${title} – kiểm tra trùng hồ sơ`} onClose={onClose} wide
      footer={<><button className="btn" onClick={() => setCands(null)}>← Sửa thông tin</button><button className="btn primary" onClick={() => send({ ...draft, confirm_distinct: true })}>Đây là người khác – xác minh</button></>}>
      <Banner tone="warn"><span>Có {cands.length} hồ sơ trùng họ tên/ngày sinh vừa nhập. Hệ thống <b>không tự gộp</b>. Nếu là cùng một người, hãy hủy và dùng <b>Đề nghị gộp hồ sơ</b>.</span></Banner>
      <DataTable rows={cands} columns={[{ h: "Họ tên", c: (p) => <b>{p.full_name}</b> }, { h: "Ngày sinh", c: (p) => fmtDate(p.date_of_birth) },
        { h: "Mã nguồn", c: (p) => `${p.source_system || ""} ${p.external_id || ""}` }, { h: "Trạng thái", c: (p) => <Status d="person" v={p.status} /> }]} />
    </Modal>
  );
  return (
    <FormModal title={title} onClose={onClose} submit="Xác minh" onSubmit={send}>
      <div className="grid2">
        <Field label="Họ tên"><input name="full_name" defaultValue={draft.full_name || ""} /></Field>
        <Field label="Ngày sinh"><input type="date" name="date_of_birth" defaultValue={draft.date_of_birth || ""} /></Field>
        <Field label="Hệ thống nguồn" required><input name="source_system" defaultValue={draft.source_system || "QLPN"} required /></Field>
        <Field label="Mã nguồn" required><input name="external_id" defaultValue={draft.external_id || ""} required /></Field>
      </div>
      <Field label="Căn cứ đối soát" required><textarea name="note" required defaultValue={draft.note || ""} placeholder="Đối chiếu hồ sơ giấy/QLPN số…" /></Field>
    </FormModal>
  );
}

function IntakeWizard({ onClose, onDone }) {
  const act = useAct();
  const { notify } = useApp();
  const [step, setStep] = useState(0);
  const [id, setId] = useState({ source_system: "QLPN" });
  const [cands, setCands] = useState([]);
  const [person, setPerson] = useState(null);
  const [stay, setStay] = useState({ start_date: today(), source_ref: "" });
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setId({ ...id, [k]: e.target.value });

  const check = async () => {
    if (!id.full_name || id.full_name.trim().length < 2) return setMsg("Nhập họ tên (tối thiểu 2 ký tự)");
    if (!id.external_id && id.source_system) { id.source_system = ""; setId({ ...id, source_system: "" }); }   // chưa có mã -> bỏ hệ thống nguồn mặc định
    if (!id.external_id !== !id.source_system) return setMsg("Mã nguồn và hệ thống nguồn phải đi cùng nhau");
    setMsg(null);
    const [byName, byCode] = await Promise.all([api("GET", "/persons" + qs({ q: id.full_name })), id.external_id ? api("GET", "/persons" + qs({ external_id: id.external_id })) : []]).catch(() => [[], []]);
    const all = [...byCode, ...byName.filter((p) => !byCode.find((x) => x.id === p.id))];
    setCands(all);
    setStep(1);
  };
  const create = async () => {
    const body = Object.fromEntries(Object.entries(id).filter(([, v]) => v));
    if (!body.external_id) delete body.source_system;
    if (cands.length) body.confirm_distinct = true;           // người dùng đã xem danh sách nghi trùng và xác nhận đây là người khác
    try {
      const r = await api("POST", "/persons", body);
      notify("Đã tạo hồ sơ"); setPerson(r); setStep(2);
    } catch (e) {
      if (e instanceof ApiError && e.data.code === "DUPLICATE_SUSPECTED") { setCands(e.data.candidates); notify("Máy chủ phát hiện hồ sơ nghi trùng – hãy kiểm tra lại danh sách", false); }
      else notify(e instanceof ApiError ? e.message : "Không kết nối được máy chủ", false);
    }
  };
  const makeStay = async () => {
    const r = await act(() => api("POST", `/persons/${person.id}/stays`, { start_date: stay.start_date, ...(stay.source_ref && { source_ref: stay.source_ref }) }), "Đã xác nhận tiếp nhận mới");
    if (r?.id) { setStep(3); onDone(person, r); }
  };
  const titles = ["1. Thông tin định danh", "2. Kiểm tra trùng hồ sơ", "3. Đợt tiếp nhận", "Hoàn tất"];
  return (
    <Modal title={`Tiếp nhận mới – ${titles[step]}`} onClose={onClose} wide
      footer={step === 0 ? <><button className="btn" onClick={onClose}>Hủy</button><button className="btn primary" onClick={check}>Kiểm tra & tiếp tục</button></>
        : step === 1 ? <><button className="btn" onClick={() => setStep(0)}>← Sửa thông tin</button><button className="btn primary" onClick={create}>{cands.length ? "Đây là người khác – tạo hồ sơ mới" : "Tạo hồ sơ mới"}</button></>
          : step === 2 ? <><button className="btn" onClick={onClose}>Để sau</button><button className="btn primary" onClick={makeStay}>Xác nhận tiếp nhận</button></>
            : <button className="btn primary" onClick={onClose}>Đóng</button>}>
      {step === 0 && (
        <>
          {msg && <Banner tone="bad">{msg}</Banner>}
          <div className="grid2">
            <Field label="Họ và tên" required><input value={id.full_name || ""} onChange={set("full_name")} autoFocus /></Field>
            <Field label="Ngày sinh"><input type="date" value={id.date_of_birth || ""} onChange={set("date_of_birth")} /></Field>
            <Field label="Giới tính"><select value={id.gender || ""} onChange={set("gender")}><option value="">—</option><option value="Nam">Nam</option><option value="Nữ">Nữ</option></select></Field>
            <Field label="Hệ thống nguồn" hint="Hệ thống đã cấp mã (mặc định QLPN). Chưa có mã thì bỏ qua cả hai ô"><input value={id.source_system || ""} onChange={set("source_system")} /></Field>
            <Field label="Mã phạm nhân (mã nguồn)" hint="Thiếu mã → hồ sơ chờ đối soát danh tính"><input value={id.external_id || ""} onChange={set("external_id")} /></Field>
          </div>
        </>
      )}
      {step === 1 && (
        cands.length ? (
          <>
            <Banner tone="warn">Có {cands.length} hồ sơ giống thông tin vừa nhập. Hệ thống <b>không tự gộp</b> – hãy kiểm tra để tránh tạo trùng.</Banner>
            <DataTable rows={cands} columns={[{ h: "Họ tên", c: (p) => <b>{p.full_name}</b> }, { h: "Ngày sinh", c: (p) => fmtDate(p.date_of_birth) }, { h: "Mã nguồn", c: (p) => `${p.source_system || ""} ${p.external_id || ""}` },
              { h: "Tại cơ sở", c: (p) => (p.facility_stay_status ? <Status d="stay" v={p.facility_stay_status} /> : p.active_elsewhere ? <Badge tone="info">Cơ sở khác</Badge> : "—") },
              { h: "", c: (p) => <button className="btn sm primary" onClick={() => { setPerson(p); setStep(2); }}>Dùng hồ sơ này</button> }]} />
          </>
        ) : <Banner tone="ok">Không tìm thấy hồ sơ trùng. Có thể tạo hồ sơ mới.</Banner>
      )}
      {step === 2 && (
        <>
          <Banner tone="info"><span><b>{person.full_name}</b> · {person.source_system} {person.external_id} · <Status d="person" v={person.status} /></span></Banner>
          {person.facility_stay_status && ["received", "managed"].includes(person.facility_stay_status) ? <Banner tone="warn">Người này đã có đợt tiếp nhận đang hiệu lực tại cơ sở. Không cần tiếp nhận lại.</Banner>
            : person.active_elsewhere ? <Banner tone="bad">Người này đang trong đợt tiếp nhận ở cơ sở khác – cần hoàn tất chuyển trại trước.</Banner> : (
              <div className="grid2">
                <Field label="Ngày bắt đầu đợt tiếp nhận" required><input type="date" value={stay.start_date} onChange={(e) => setStay({ ...stay, start_date: e.target.value })} /></Field>
                <Field label="Số/ngày quyết định tiếp nhận"><input value={stay.source_ref} onChange={(e) => setStay({ ...stay, source_ref: e.target.value })} /></Field>
              </div>)}
          <p className="muted sm">Nếu người này đã có hồ sơ sức khỏe, hệ thống dùng lại hồ sơ đó – không tạo hồ sơ sức khỏe mới.</p>
        </>
      )}
      {step === 3 && <Banner tone="ok">Đã tiếp nhận <b>{person.full_name}</b>. Bước tiếp theo: khám ban đầu (tab “Khám ban đầu”).</Banner>}
    </Modal>
  );
}

const MERGE_ST = { pending: ["Chờ duyệt", "warn"], approved: ["Đã gộp", "ok"], rejected: ["Từ chối", "bad"], cancelled: ["Đã rút", "neutral"] };
const PCard = ({ p, label }) => p ? (
  <Card title={label}><KV items={[["Họ tên", p.full_name], ["Ngày sinh", fmtDate(p.date_of_birth)], ["Mã nguồn", `${p.source_system || ""} ${p.external_id || ""}`.trim() || "—"], ["Trạng thái", <Status key="s" d="person" v={p.status} />]]} /></Card>) : null;

/** Đề nghị gộp: chọn hồ sơ giữ lại trong các hồ sơ nghi trùng. KHÔNG gộp ngay – chờ người điều phối duyệt. */
function MergeRequestModal({ person, onClose, onDone }) {
  const act = useAct();
  const { data: cands } = useLoad(() => Promise.all((person.duplicate_candidates || []).map((id) => api("GET", `/persons/${id}`).catch(() => null))).then((r) => r.filter((x) => x && x.status !== "merged")), [person.id]);
  const [pick, setPick] = useState(null);
  const [keep, setKeep] = useState("other");
  const other = cands?.find((c) => c.id === pick);
  return (
    <FormModal title="Đề nghị gộp hồ sơ trùng" onClose={onClose} wide submit="Gửi đề nghị"
      onSubmit={async (d) => {
        if (!other) return false;
        const [source, target] = keep === "other" ? [person, other] : [other, person];
        const r = await act(() => api("POST", "/person-merges", { source_id: source.id, target_id: target.id, reason: d.reason }), "Đã gửi đề nghị – chờ người điều phối duyệt");
        if (r) onDone(); return !!r;
      }}>
      <Banner tone="info"><span className="sm">Gộp <b>không tự động</b>: người khác có thẩm quyền sẽ duyệt. Khi duyệt, toàn bộ dữ liệu của hồ sơ bị gộp chuyển sang hồ sơ giữ lại; hồ sơ bị gộp vẫn được lưu để truy vết.</span></Banner>
      <h4 style={{ margin: "12px 0 6px" }}>Chọn hồ sơ trùng với {person.full_name}</h4>
      {!cands ? <p className="muted">Đang tải…</p> : !cands.length ? <Empty title="Không còn hồ sơ trùng để gộp" /> : (
        <DataTable rows={cands} columns={[{ h: "", c: (c) => <input type="radio" name="pick" checked={pick === c.id} onChange={() => setPick(c.id)} aria-label={`Chọn ${c.full_name} ${c.external_id || ""}`} /> }, { h: "Họ tên", c: (c) => <b>{c.full_name}</b> }, { h: "Ngày sinh", c: (c) => fmtDate(c.date_of_birth) }, { h: "Mã nguồn", c: (c) => `${c.source_system || ""} ${c.external_id || "(chưa có mã)"}` }, { h: "Danh tính", c: (c) => <Status d="person" v={c.status} /> }]} />
      )}
      {other && (
        <div style={{ marginTop: 12 }}>
          <Field label="Hồ sơ nào được GIỮ LẠI?">
            <select value={keep} onChange={(e) => setKeep(e.target.value)}>
              <option value="other">Giữ hồ sơ đã chọn ({other.external_id || "chưa có mã"}) – gộp hồ sơ đang mở vào đó</option>
              <option value="this">Giữ hồ sơ đang mở – gộp hồ sơ đã chọn vào đây</option>
            </select>
          </Field>
          <Field label="Căn cứ cho rằng là một người" required hint="Tối thiểu 10 ký tự. Ví dụ: đối chiếu ảnh/vân tay/quyết định tạm giam…"><textarea name="reason" required minLength={10} /></Field>
        </div>
      )}
    </FormModal>
  );
}

function MergeDecision({ m, onClose, onDone }) {
  const act = useAct();
  const { has, user } = useAuth();
  const mine = m.requested_by === user.id;
  const { prompt, confirm } = useApp();
  const promptNote = () => prompt({ title: "Từ chối đề nghị gộp", label: "Lý do từ chối", required: true, multiline: true });
  const run = async (approve) => {
    let note = null;
    if (approve) { if (!(await confirm({ title: "Duyệt gộp hồ sơ", message: `Gộp “${m.source.full_name}” vào “${m.target.full_name}”?\nToàn bộ đợt tiếp nhận, lượt khám, đơn thuốc, tài liệu… của hồ sơ bị gộp sẽ chuyển sang hồ sơ giữ lại. Không thể hoàn tác.`, okLabel: "Duyệt & gộp" }))) return; }
    else { note = await promptNote(); if (!note) return; }
    const r = await act(() => api("POST", `/person-merges/${m.id}/decision`, { approve, note }), approve ? "Đã gộp hồ sơ" : "Đã từ chối đề nghị");
    if (r) onDone();
  };
  const [lbl, tone] = MERGE_ST[m.status] || [m.status, "neutral"];
  return (
    <Modal title="Đề nghị gộp hồ sơ" onClose={onClose} wide
      footer={m.status === "pending" ? (has("person.merge.approve") && !mine ? <><button className="btn danger" onClick={() => run(false)}>Từ chối</button><button className="btn primary" onClick={() => run(true)}>Duyệt & gộp</button></>
        : mine ? <button className="btn" onClick={async () => { if (await act(() => api("POST", `/person-merges/${m.id}/cancel`), "Đã rút đề nghị")) onDone(); }}>Rút đề nghị</button> : null) : null}>
      <p style={{ marginTop: 0 }}><Badge tone={tone}>{lbl}</Badge> Lập bởi <b>{m.requested_by_name}</b> · {fmtDate(m.requested_at)}</p>
      <div className="cols"><PCard p={m.source} label="Hồ sơ BỊ GỘP (sẽ ngừng dùng)" /><PCard p={m.target} label="Hồ sơ GIỮ LẠI" /></div>
      <Card title="Căn cứ"><p style={{ margin: 0, whiteSpace: "pre-line" }}>{m.reason}</p></Card>
      {m.status === "pending" && mine && <Banner tone="info">Bạn là người lập đề nghị nên không được tự duyệt (nguyên tắc bốn mắt). Chờ người điều phối xử lý.</Banner>}
      {m.status === "approved" && <Banner tone="ok"><span className="sm">Đã chuyển: {Object.entries(m.moved || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "không có dữ liệu"} · duyệt bởi {m.decided_by_name}</span></Banner>}
      {m.status === "rejected" && <Banner tone="bad"><span className="sm">Bị từ chối bởi {m.decided_by_name}: {m.decision_note}</span></Banner>}
    </Modal>
  );
}

function MergeQueue({ focusId }) {
  const { data, reload, loading } = useLoad(() => api("GET", "/person-merges"), []);
  const [open, setOpen] = useState(null);
  const sel = data?.find((m) => m.id === open);
  useEffect(() => { if (focusId && data?.some((m) => m.id === focusId)) setOpen(focusId); }, [focusId, data]);
  return (
    <>
      <DataTable rows={data} loading={loading} onRow={(m) => setOpen(m.id)} empty={<Empty title="Không có đề nghị gộp hồ sơ">Đề nghị được lập từ hồ sơ nghi trùng (tab “Chờ đối soát danh tính” → mở hồ sơ).</Empty>}
        columns={[{ h: "Hồ sơ bị gộp", c: (m) => <b>{m.source?.full_name}</b> }, { h: "→ Giữ lại", c: (m) => m.target?.full_name }, { h: "Lập bởi", c: (m) => m.requested_by_name }, { h: "Ngày", c: (m) => fmtDate(m.requested_at) },
          { h: "Trạng thái", c: (m) => { const [l, t] = MERGE_ST[m.status] || [m.status, "neutral"]; return <Badge tone={t}>{l}</Badge>; } }]} />
      {sel && <MergeDecision m={sel} onClose={() => setOpen(null)} onDone={() => { setOpen(null); reload(); }} />}
    </>
  );
}

function PersonDrawer({ id, onClose, onChanged }) {
  const { has, go } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const { select } = usePatient();
  const { data: p, reload: r1 } = useLoad(() => api("GET", `/persons/${id}`), [id]);
  const { data: stays, reload: r2 } = useLoad(() => api("GET", `/persons/${id}/stays`), [id]);
  const [m, setM] = useState(null);
  const reload = () => { r1(); r2(); onChanged(); };
  if (!p) return null;
  const active = stays?.find((s) => ["received", "managed"].includes(s.status));
  return (
    <Drawer title={p.full_name} onClose={onClose} actions={has("clinical.read") && <button className="btn primary" onClick={() => { select(p); onClose(); go("record"); }}>Mở hồ sơ sức khỏe</button>}>
      {p.status === "merged" && <Banner tone="info"><span>Hồ sơ này <b>đã được gộp</b> vào hồ sơ khác; toàn bộ dữ liệu nay nằm ở hồ sơ giữ lại. <button className="btn sm" onClick={() => go("intake", p.merged_into_id)}>Mở hồ sơ giữ lại</button></span></Banner>}
      {p.status !== "verified" && p.status !== "merged" && <Banner tone="warn"><span>Danh tính <b>chưa được đối soát</b>{p.is_temporary ? " (hồ sơ tạm từ cấp cứu)" : ""}. {has("person.write") && "Hãy đối soát với nguồn dữ liệu gốc."}</span></Banner>}
      <div className="cols">
        <Card title="Danh tính" actions={has("person.write") && p.status !== "verified" && <button className="btn sm primary" onClick={() => setM("verify")}>Đối soát</button>}>
          <KV items={[["Họ tên", p.full_name], ["Ngày sinh", fmtDate(p.date_of_birth)], ["Giới tính", p.gender], ["Hệ thống nguồn", p.source_system], ["Mã nguồn", p.external_id], ["Trạng thái", <Status key="s" d="person" v={p.status} />]]} />
          {p.duplicate_candidates?.length > 0 && p.status !== "merged" && <Banner tone="warn"><span className="sm">Nghi trùng với {p.duplicate_candidates.length} hồ sơ khác (cùng họ tên + ngày sinh). Cần đối soát, không tự gộp.{has("person.merge.request") && <> <button className="btn sm" onClick={() => setM("merge")}>Đề nghị gộp hồ sơ</button></>}</span></Banner>}
        </Card>
        <Card title="Đợt tiếp nhận" actions={has("stay.write") && !active && <button className="btn sm primary" onClick={() => setM("stay")}>+ Tiếp nhận kỳ mới</button>} flat>
          <DataTable rows={stays} columns={[{ h: "Từ ngày", c: (s) => fmtDate(s.start_date) }, { h: "Đến ngày", c: (s) => fmtDate(s.end_date) }, { h: "Trạng thái", c: (s) => <><Status d="stay" v={s.status} />{s.provisional && <Badge tone="warn">Tạm</Badge>}</> },
            { h: "", c: (s) => has("stay.write") && s.status === "received" && <button className="btn sm" onClick={async () => {
              const reason = await prompt({ title: "Hủy liên kết đợt tiếp nhận (nhập nhầm người)", label: "Lý do", required: true });
              if (reason && await act(() => api("POST", `/stays/${s.id}/void`, { reason }), "Đã hủy liên kết")) reload();
            }}>Hủy liên kết</button> }]} />
        </Card>
      </div>
      {m === "verify" && (
        <VerifyIdentityModal personId={id} onClose={() => setM(null)} onDone={() => { setM(null); reload(); }}
          defaults={p.is_temporary ? { date_of_birth: p.date_of_birth } : { full_name: p.full_name, date_of_birth: p.date_of_birth, source_system: p.source_system, external_id: p.external_id }} />
      )}
      {m === "merge" && <MergeRequestModal person={p} onClose={() => setM(null)} onDone={() => { setM(null); reload(); }} />}
      {m === "stay" && (
        <FormModal title="Xác nhận tiếp nhận mới" onClose={() => setM(null)}
          onSubmit={async (d) => { const r = await act(() => api("POST", `/persons/${id}/stays`, d), "Đã tiếp nhận"); if (r) reload(); return !!r; }}>
          <Field label="Ngày bắt đầu" required><input type="date" name="start_date" defaultValue={today()} required /></Field>
          <Field label="Số/ngày quyết định tiếp nhận"><input name="source_ref" /></Field>
        </FormModal>
      )}
    </Drawer>
  );
}

export default function Intake({ focus }) {
  const { has } = useAuth();
  const { go } = useAuth();
  const isMergeFocus = focus?.startsWith("merge:");
  const canMerge = has("person.merge.request") || has("person.merge.approve");
  const [view, setView] = useState(isMergeFocus ? "merge" : "active");
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [wiz, setWiz] = useState(false);
  const [open, setOpen] = useState(focus && !isMergeFocus ? focus : null);
  const stays = useLoad(() => api("GET", "/stays?status=active"), [view], view !== "active");
  const pending = useLoad(() => api("GET", "/persons?status=pending_verification"), [view], view !== "pending");
  const all = useLoad(() => api("GET", "/persons" + qs({ q: dq })), [view, dq], view !== "all");
  const reload = () => { stays.reload(); pending.reload(); all.reload(); };
  const idCols = (idKey) => [
    { h: "Họ tên", c: (r) => <b>{r.full_name || r.person_name}</b> }, { h: "Mã nguồn", c: (r) => r.person_external_id ?? `${r.source_system || ""} ${r.external_id || ""}` },
  ];
  return (
    <>
      <PageHeader title="Tiếp nhận & Hồ sơ" sub="M01 · Quản lý định danh và đợt tiếp nhận. Một người – một hồ sơ sức khỏe, dù tiếp nhận nhiều lần."
        actions={has("person.write") && <button className="btn primary" onClick={() => setWiz(true)}>+ Tiếp nhận mới</button>} />
      <div className="row" style={{ marginBottom: 14 }}>
        <Seg value={view} onChange={setView} items={[{ id: "active", label: "Đang quản lý tại cơ sở" }, { id: "pending", label: "Chờ đối soát danh tính" }, { id: "all", label: "Tra cứu hồ sơ" }, ...(canMerge ? [{ id: "merge", label: "Đề nghị gộp hồ sơ" }] : [])]} />
        {view === "all" && <input className="search" placeholder="Tìm theo họ tên…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />}
      </div>
      <Card flat>
        {view === "active" && <DataTable rows={stays.data} loading={stays.loading} onRow={(s) => setOpen(s.person_id)} empty={<Empty title="Chưa có ai trong diện quản lý">Bấm “Tiếp nhận mới” để bắt đầu.</Empty>}
          columns={[...idCols(), { h: "Ngày tiếp nhận", c: (s) => fmtDate(s.start_date) }, { h: "Đợt tiếp nhận", c: (s) => <><Status d="stay" v={s.status} />{s.provisional && <Badge tone="warn">Tạm</Badge>}</> },
            { h: "Khám ban đầu", c: (s) => (s.needs_initial_exam ? <Badge tone="warn">Chưa hoàn tất</Badge> : <Badge tone="ok">Đã hoàn tất</Badge>) }]} />}
        {view === "pending" && <DataTable rows={pending.data} loading={pending.loading} onRow={(p) => setOpen(p.id)} empty={<Empty title="Không có hồ sơ chờ đối soát" />}
          columns={[...idCols(), { h: "Ngày sinh", c: (p) => fmtDate(p.date_of_birth) }, { h: "Ghi chú", c: (p) => (p.is_temporary ? <Badge tone="bad">Hồ sơ tạm cấp cứu</Badge> : p.duplicate_candidates ? <Badge tone="warn">Nghi trùng</Badge> : <Badge>Thiếu mã nguồn</Badge>) }]} />}
        {view === "all" && <DataTable rows={all.data} loading={all.loading} onRow={(p) => setOpen(p.id)} empty={<Empty title="Không tìm thấy hồ sơ" />}
          columns={[...idCols(), { h: "Ngày sinh", c: (p) => fmtDate(p.date_of_birth) }, { h: "Danh tính", c: (p) => <Status d="person" v={p.status} /> },
            { h: "Tại cơ sở này", c: (p) => (p.facility_stay_status ? <Status d="stay" v={p.facility_stay_status} /> : p.active_elsewhere ? <Badge tone="info">Cơ sở khác</Badge> : <span className="muted">—</span>) }]} />}
        {view === "merge" && <MergeQueue focusId={isMergeFocus ? focus.slice(6) : null} />}
      </Card>
      {wiz && <IntakeWizard onClose={() => { setWiz(false); reload(); }} onDone={() => reload()} />}
      {open && <PersonDrawer id={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </>
  );
}
