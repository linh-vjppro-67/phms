// Bàn làm việc lượt khám (Encounter): dùng cho Khám ban đầu (chế độ wizard) và Khám chữa bệnh.
import { useRef, useState } from "react";
import { api } from "../api";
import { statusLabel } from "../labels";
import { usePatient } from "../patient.jsx";
import { Badge, Banner, Card, DataTable, Empty, Form, Field, Status, Stepper, Tabs, fmtDT, useApp, useAct, useAuth, useLoad } from "../ui.jsx";
import { AllergyBlock, ClinicalOrdersBlock, DiagnosisBlock, DocsPanel, PlanBlock, ProblemBlock, ReferralBlock, RxBlock, VitalsBlock } from "./blocks.jsx";

const FLOW = ["Nháp", "Đang khám", "Chờ KQ / Điều trị", "Hoàn tất"];
const flowIndex = (s) => ({ draft: 0, in_progress: 1, awaiting_results: 2, in_treatment: 2, completed: 3 }[s] ?? 0);
const WIZ = ["Tiền sử & dị ứng", "Sinh hiệu", "Khám & chẩn đoán", "Chỉ định & điều trị", "Kế hoạch theo dõi", "Hoàn tất"];

function ClinicalContext({ e }) {
  const c = e.context || { active_medications: [], open_problems: [] };
  return (
    <Card title="Thông tin lâm sàng cần thiết">
      <div className="grid3">
        <div><b className="sm">Dị ứng</b><div style={{ marginTop: 6 }}>{e.allergies.length ? e.allergies.map((a) => <div key={a.id}><Badge tone="bad">{a.substance}</Badge>{a.reaction && <span className="muted sm"> {a.reaction}</span>}</div>)
          : <Status d="allergy" v={e.allergy_status} />}</div></div>
        <div><b className="sm">Thuốc đang dùng</b><div style={{ marginTop: 6 }}>{c.active_medications.length ? c.active_medications.map((m) => <div key={m.id} className="sm">{m.drug_name} <span className="muted">· {m.dose} {m.frequency}</span></div>) : <span className="muted sm">Không có đơn đang hiệu lực</span>}</div></div>
        <div><b className="sm">Vấn đề sức khỏe đang mở</b><div style={{ marginTop: 6 }}>{c.open_problems.length ? c.open_problems.map((x) => <div key={x.id} className="sm">{x.name}{x.code && <span className="muted"> ({x.code})</span>}</div>) : <span className="muted sm">Chưa ghi nhận (không có nghĩa là không có bệnh)</span>}</div></div>
      </div>
    </Card>
  );
}

function Overview({ e, open, reload }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt } = useApp();
  const canEdit = open && has("encounter.write");
  return (
    <>
      <ClinicalContext e={e} />
      <Card title="Thông tin lượt khám">
        <dl className="kv" style={{ margin: "0 0 14px" }}>
          <dt>Loại</dt><dd><Status d="encType" v={e.type} /></dd>
          <dt>Thời điểm khám</dt><dd>{fmtDT(e.occurred_at)} <span className="muted sm">(ghi vào hệ thống: {fmtDT(e.recorded_at)})</span></dd>
          {e.late_entry_reason && <><dt>Lý do ghi muộn</dt><dd>{e.late_entry_reason}</dd></>}
          {e.completed_at && <><dt>Hoàn tất lúc</dt><dd>{fmtDT(e.completed_at)}</dd></>}
          {e.cancel_reason && <><dt>Lý do hủy</dt><dd>{e.cancel_reason}</dd></>}
        </dl>
        {canEdit ? (
          <EncounterNotes e={e} reload={reload} />
        ) : (
          <dl className="kv"><dt>Lý do khám</dt><dd>{e.reason || "—"}</dd>{e.nursing_assessment && <><dt>Đánh giá ban đầu</dt><dd style={{ whiteSpace: "pre-line" }}>{e.nursing_assessment}</dd></>}<dt>Kết luận</dt><dd style={{ whiteSpace: "pre-line" }}>{e.summary || "—"}</dd></dl>
        )}
      </Card>
      {(e.addenda.length > 0 || (e.status === "completed" && has("encounter.complete"))) && (
        <Card title="Bổ sung / điều chỉnh sau khi hoàn tất (addendum)" actions={e.status === "completed" && has("encounter.complete") && <button className="btn sm primary" onClick={async () => {
          const text = await prompt({ title: "Bổ sung hồ sơ khám", label: "Nội dung bổ sung", multiline: true, required: true });
          if (!text) return;
          const reason = await prompt({ title: "Lý do bổ sung", label: "Lý do", required: true });
          if (reason && await act(() => api("POST", `/encounters/${e.id}/addenda`, { text, reason }), "Đã thêm addendum")) reload();
        }}>+ Thêm addendum</button>}>
          <p className="muted sm" style={{ marginTop: 0 }}>Hồ sơ đã hoàn tất không bị ghi đè; mọi điều chỉnh là bản bổ sung có lý do, người thực hiện và phiên bản.</p>
          <ul className="tl">{e.addenda.map((a) => <li key={a.id}>{a.text}<small>{fmtDT(a.recorded_at)} · v{a.version_after} · Lý do: {a.reason}</small></li>)}</ul>
        </Card>
      )}
    </>
  );
}

function Checklist({ e }) {
  const items = [
    [e.observations.length > 0, "Đã ghi nhận sinh hiệu"],
    [e.diagnoses.length > 0, "Đã có chẩn đoán"],
    [e.allergy_status !== "unknown", "Đã ghi nhận tình trạng dị ứng"],
    [!e.orders.some((o) => o.status === "open"), "Không còn chỉ định chờ kết quả"],
    [!e.medication_orders.some((o) => o.status === "draft"), "Không còn đơn thuốc nháp chưa xác nhận"],
  ];
  return <Card title="Kiểm tra trước khi hoàn tất">{items.map(([ok, t]) => <div key={t} className="chk"><Badge tone={ok ? "ok" : "warn"}>{ok ? "✓" : "!"}</Badge> {t}</div>)}
    <p className="muted sm">Mục cảnh báo (!) không chặn nghiệp vụ, trừ khi còn chỉ định chờ kết quả.</p></Card>;
}

/** Lý do khám + tóm tắt: lưu bằng nút Lưu HOẶC tự lưu khi rời khỏi ô (tránh mất chữ khi bấm "Tiếp tục" mà quên Lưu). */
function EncounterNotes({ e, reload }) {
  const act = useAct();
  const { has } = useAuth();
  const examiner = has("encounter.examine");
  const form = useRef(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);        // chặn lưu chồng (rời ô rồi bấm Lưu liền) – tránh xung đột phiên bản
  const save = async (silent) => {
    if (inflight.current) return;
    const f = form.current.elements;
    const body = { reason: f.reason.value.trim(), nursing_assessment: f.nursing_assessment.value.trim(), expected_version: e.version };
    if (examiner) body.summary = f.summary.value.trim();            // kết luận khám chỉ người có quyền khám ghi
    if (body.reason === (e.reason || "") && body.nursing_assessment === (e.nursing_assessment || "") && (!examiner || body.summary === (e.summary || ""))) { setDirty(false); return; }
    inflight.current = true; setBusy(true);
    const r = await act(() => api("PATCH", `/encounters/${e.id}`, body), silent ? "Đã tự lưu" : "Đã lưu");
    inflight.current = false; setBusy(false);
    if (r) { setDirty(false); reload(); }
  };
  return (
    <form ref={form} onSubmit={(ev) => { ev.preventDefault(); save(false); }} onBlur={(ev) => { if (dirty && ev.target.tagName === "TEXTAREA" && !busy) save(true); }}>
      <Field label="Lý do đến khám / triệu chứng chính"><textarea name="reason" defaultValue={e.reason || ""} onChange={() => setDirty(true)} /></Field>
      <Field label="Đánh giá ban đầu (điều dưỡng/ghi nhận ban đầu)"><textarea name="nursing_assessment" defaultValue={e.nursing_assessment || ""} onChange={() => setDirty(true)} placeholder="Tri giác, tình trạng chung, than phiền của người bệnh…" /></Field>
      {examiner ? <Field label="Kết luận khám & hướng xử trí (bác sĩ/y sĩ)"><textarea name="summary" defaultValue={e.summary || ""} onChange={() => setDirty(true)} style={{ minHeight: 110 }} /></Field>
        : e.summary ? <dl className="kv"><dt>Kết luận khám</dt><dd style={{ whiteSpace: "pre-line" }}>{e.summary}</dd></dl> : null}
      <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Đang lưu…" : "Lưu"}</button>
        {dirty && !busy && <span className="badge warn">● Chưa lưu – sẽ tự lưu khi bạn rời khỏi ô</span>}</div>
    </form>
  );
}

export default function Workbench({ id, wizard, onChanged }) {
  const { has } = useAuth();
  const act = useAct();
  const { prompt, confirm } = useApp();
  const { refresh } = usePatient();
  const { data: e, reload: rl } = useLoad(() => api("GET", `/encounters/${id}`), [id]);
  const { data: sum, reload: rs } = useLoad(() => api("GET", `/persons/${e.person_id}/health-summary`), [e?.person_id], !e);
  const [tab, setTab] = useState("overview");
  const [step, setStep] = useState(0);
  if (!e) return <Card><Empty title="Đang tải lượt khám…" /></Card>;

  const open = !["completed", "cancelled"].includes(e.status);
  const reload = () => { rl(); rs(); onChanged?.(); refresh?.(); };
  const to = async (status) => {
    const body = { to: status, expected_version: e.version };
    if (status === "cancelled") { body.reason = await prompt({ title: "Hủy lượt khám", label: "Lý do hủy", required: true }); if (!body.reason) return; }
    if (status === "completed" && !(await confirm({ title: "Hoàn tất lượt khám", message: "Sau khi hoàn tất, hồ sơ không thể sửa trực tiếp (chỉ bổ sung bằng addendum). Tiếp tục?" }))) return;
    if (await act(() => api("POST", `/encounters/${e.id}/transition`, body), status === "completed" ? "Đã hoàn tất lượt khám" : "Đã cập nhật trạng thái")) reload();
  };

  const common = { e, open, reload };
  const personId = e.person_id;
  const header = (
    <Card className="wb-head">
      <div className="row" style={{ marginBottom: 12 }}>
        <div><div style={{ fontSize: 18, fontWeight: 700 }}>{e.person_name}</div><div className="muted sm">{e.person_external_id} · bắt đầu {fmtDT(e.occurred_at)}</div></div>
        <Status d="encType" v={e.type} />{e.status === "cancelled" ? <Status d="enc" v="cancelled" /> : <Status d="enc" v={e.status} />}
        <div className="right row">
          {open && e.status === "draft" && has("encounter.examine") && <button className="btn primary" onClick={() => to("in_progress")}>Bắt đầu khám</button>}
          {open && e.status !== "draft" && has("encounter.examine") && e.status !== "awaiting_results" && <button className="btn" onClick={() => to("awaiting_results")}>Chờ kết quả</button>}
          {open && e.status !== "draft" && has("encounter.examine") && e.status !== "in_treatment" && <button className="btn" onClick={() => to("in_treatment")}>Chuyển điều trị</button>}
          {open && e.status !== "draft" && has("encounter.complete") && !wizard && <button className="btn primary" onClick={() => to("completed")}>Hoàn tất khám</button>}
          {open && (has("encounter.examine") || (has("encounter.write") && e.status === "draft")) && <button className="btn" onClick={() => to("cancelled")}>Hủy lượt khám</button>}
        </div>
      </div>
      {e.status !== "cancelled" && <Stepper steps={FLOW} current={flowIndex(e.status) + (e.status === "completed" ? 1 : 0)} />}
      {e.allergy_status === "recorded" && e.allergies.length > 0
        ? <Banner tone="bad"><b>DỊ ỨNG:</b> {e.allergies.map((a) => `${a.substance}${a.reaction ? ` (${a.reaction})` : ""}`).join("; ")}</Banner>
        : e.allergy_status === "unknown" && open && <Banner tone="warn">Chưa ghi nhận thông tin dị ứng – hãy hỏi và ghi nhận trước khi kê đơn.</Banner>}
      {e.status === "draft" && <Banner tone="info">{has("encounter.examine") ? "Lượt khám đang ở trạng thái nháp. Bấm “Bắt đầu khám” để ghi nhận." : "Yêu cầu khám đang chờ bác sĩ/y sĩ. Bạn có thể đo sinh hiệu và ghi đánh giá ban đầu."}</Banner>}
    </Card>
  );

  if (wizard) {
    const blocks = [
      <><AllergyBlock personId={personId} summary={sum} reload={reload} /><ProblemBlock personId={personId} summary={sum} reload={reload} /></>,
      <VitalsBlock {...common} />,
      <><Overview {...common} /><DiagnosisBlock {...common} /></>,
      <><ClinicalOrdersBlock {...common} /><RxBlock {...common} /></>,
      <PlanBlock personId={personId} summary={sum} reload={reload} />,
      <><Checklist e={e} />{open && has("encounter.complete") ? (
        <Card><p style={{ marginTop: 0 }}>Hoàn tất khám ban đầu sẽ chuyển đợt tiếp nhận sang <b>“Đang quản lý”</b>.</p>
          <button className="btn primary" disabled={e.status === "draft"} onClick={() => to("completed")}>Hoàn tất khám ban đầu</button></Card>
      ) : open ? <Banner tone="info">Bác sĩ/y sĩ có thẩm quyền sẽ xác nhận kết quả đánh giá ban đầu.</Banner> : <Banner tone="ok">Khám ban đầu đã hoàn tất.</Banner>}</>,
    ];
    return (
      <>
        {header}
        <Stepper steps={WIZ} current={step} onStep={setStep} />
        {blocks[step]}
        <div className="row mt">
          <button className="btn" disabled={step === 0} onClick={() => setStep(step - 1)}>← Quay lại</button>
          <button className="btn primary right" disabled={step === WIZ.length - 1} onClick={() => setStep(step + 1)}>Tiếp tục →</button>
        </div>
      </>
    );
  }

  const tabs = [
    { id: "overview", label: "Tổng quan" }, { id: "vitals", label: "Sinh hiệu", count: e.observations.length }, { id: "dx", label: "Chẩn đoán", count: e.diagnoses.length },
    { id: "orders", label: "Chỉ định XN/thủ thuật", count: e.orders.length }, { id: "rx", label: "Đơn thuốc", count: e.medication_orders.length },
    { id: "plan", label: "Theo dõi & tái khám" }, { id: "referral", label: "Chuyển viện", count: e.referrals.length }, has("document.read") && { id: "docs", label: "Tài liệu" },
  ];
  return (
    <>
      {header}
      <Tabs items={tabs} value={tab} onChange={setTab} />
      {tab === "overview" && <><Overview {...common} /><Checklist e={e} /></>}
      {tab === "vitals" && <VitalsBlock {...common} />}
      {tab === "dx" && <DiagnosisBlock {...common} />}
      {tab === "orders" && <ClinicalOrdersBlock {...common} />}
      {tab === "rx" && <RxBlock {...common} />}
      {tab === "plan" && <><AllergyBlock personId={personId} summary={sum} reload={reload} /><ProblemBlock personId={personId} summary={sum} reload={reload} /><PlanBlock personId={personId} summary={sum} reload={reload} /></>}
      {tab === "referral" && <ReferralBlock e={e} reload={reload} />}
      {tab === "docs" && <DocsPanel personId={personId} encounterId={e.id} title="Tài liệu của lượt khám" compact />}
    </>
  );
}
