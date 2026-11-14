import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, ApiError, qs } from "./api";
import { Badge, Banner, Empty, Field, FormModal, Modal, Status, useApp, useAuth, useDebounced, useLoad } from "./ui.jsx";
import { fmtDate } from "./ui.jsx";

const Ctx = createContext(null);
export const usePatient = () => useContext(Ctx);

/** Ngữ cảnh "bệnh nhân đang xử lý" dùng chung cho các tab (chọn một lần).
 *  Người ngoài phạm vi cơ sở: hỏi lý do truy cập khẩn cấp (break-glass) – chỉ đọc, có hạn, được hậu kiểm. */
export function PatientProvider({ children }) {
  const { notify } = useApp();
  const { user } = useAuth();
  const [patient, setPatient] = useState(null);
  const [summary, setSummary] = useState(null);
  const [bg, setBg] = useState(null);            // {id, name}: đang chờ nhập lý do
  const [bgUntil, setBgUntil] = useState(null);  // hạn truy cập khẩn cấp hiện tại
  const granted = useRef(false);

  const load = useCallback(async (id) => {
    try {
      const sm = await api("GET", `/persons/${id}/health-summary`);
      setSummary(sm);
      const mine = sm.stays.some((x) => x.facility_id === user.facility_id && x.status !== "voided");
      if (!mine && !sm.clinical_hidden) { const g = await api("GET", `/persons/${id}/break-glass`).catch(() => null); setBgUntil(g?.active ? g.expires_at : null); }
      else setBgUntil(null);
    } catch (e) {
      if (e instanceof ApiError && e.data.code === "FACILITY_SCOPE" && e.data.break_glass_allowed) { setBg({ id }); return; }
      notify(e instanceof ApiError ? e.message : "Không kết nối được máy chủ", false);
      setPatient(null);
    }
  }, [notify, user.facility_id]);

  const select = useCallback((p) => { setPatient({ id: p.id, name: p.full_name }); setSummary(null); setBgUntil(null); setBg(null); load(p.id); }, [load]);
  const clear = useCallback(() => { setPatient(null); setSummary(null); setBgUntil(null); setBg(null); }, []);
  const refresh = useCallback(() => patient && load(patient.id), [patient, load]);
  useEffect(() => {   // hết hạn truy cập khẩn cấp -> tự thu hồi trên giao diện
    if (!bgUntil) return;
    const ms = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(bgUntil) ? bgUntil : bgUntil + "Z") - Date.now();
    const t = setTimeout(() => { setBgUntil(null); notify("Hết hạn truy cập khẩn cấp – hồ sơ được đóng lại", false); clear(); }, Math.max(ms, 0));
    return () => clearTimeout(t);
  }, [bgUntil, clear, notify]);

  const activeStay = summary?.stays.find((x) => ["received", "managed"].includes(x.status) && x.facility_id === user.facility_id);
  return (
    <Ctx.Provider value={{ patient, summary, activeStay, bgUntil, select, clear, refresh }}>
      {children}
      {bg && (
        <FormModal title="Truy cập khẩn cấp (break-glass)" danger submit="Xác nhận truy cập khẩn cấp"
          onClose={() => { if (granted.current) { granted.current = false; setBg(null); } else clear(); }}   // chỉ bỏ chọn khi người dùng HỦY
          onSubmit={async (d) => {
            try { await api("POST", `/persons/${bg.id}/break-glass`, { reason: d.reason }); granted.current = true; await load(bg.id); notify("Đã cấp quyền xem khẩn cấp (chỉ đọc, có thời hạn)"); return true; }
            catch (e) { notify(e instanceof ApiError ? e.message : "Lỗi kết nối", false); return false; }
          }}>
          <Banner tone="bad"><span className="sm">Hồ sơ này <b>ngoài phạm vi cơ sở của bạn</b>. Chỉ dùng trong tình huống khẩn cấp. Quyền xem <b>chỉ đọc</b>, <b>tự hết hạn sau 30 phút</b>; việc truy cập được ghi nhật ký và <b>gửi cảnh báo hậu kiểm</b> cho quản lý và quản trị hệ thống.</span></Banner>
          <Field label="Lý do truy cập khẩn cấp" required hint="Tối thiểu 10 ký tự, nêu rõ tình huống"><textarea name="reason" required minLength={10} autoFocus placeholder="Vd: nghi ngộ độc, cần tiền sử dị ứng của người sắp được chuyển đến…" /></Field>
        </FormModal>
      )}
    </Ctx.Provider>
  );
}

export function PatientPicker({ onPick, onClose, title = "Chọn người cần xử lý" }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const { data, loading } = useLoad(() => api("GET", "/persons" + qs({ q: dq })), [dq]);
  return (
    <Modal title={title} onClose={onClose} wide>
      <input autoFocus className="search" style={{ maxWidth: "100%" }} placeholder="Nhập họ tên để tìm… (người ngoài cơ sở: nhập đúng mã nguồn, chỉ dùng khi khẩn cấp)" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="tblwrap mt" style={{ maxHeight: "52vh" }} tabIndex={0} role="region" aria-label="Danh sách người (cuộn bằng phím mũi tên)">
        {!data?.length ? <Empty title={loading ? "Đang tìm…" : "Không tìm thấy hồ sơ"} /> : (
          <table className="tbl"><thead><tr><th>Họ tên</th><th>Ngày sinh</th><th>Mã nguồn</th><th>Danh tính</th><th>Tại cơ sở này</th></tr></thead>
            <tbody>{data.map((p) => (
              <tr key={p.id} className="click" tabIndex={0} onClick={() => { onPick(p); onClose(); }} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(p); onClose(); } }}>
                <td><b>{p.full_name}</b></td><td>{fmtDate(p.date_of_birth)}</td><td>{p.source_system} {p.external_id}</td>
                <td><Status d="person" v={p.status} /></td>
                <td>{p.facility_stay_status ? <Status d="stay" v={p.facility_stay_status} /> : p.active_elsewhere ? <Badge tone="info">Đang ở cơ sở khác</Badge> : <span className="muted">Chưa có đợt tiếp nhận</span>}</td>
              </tr>))}</tbody></table>
        )}
      </div>
    </Modal>
  );
}

/** Dùng ở đầu các màn hình cần bệnh nhân: nếu chưa chọn thì hiện lời mời chọn. */
export function RequirePatient({ children, hint }) {
  const { patient, select } = usePatient();
  const [open, setOpen] = useState(false);
  if (patient) return children;
  return (
    <div className="card"><Empty title="Chưa chọn người cần xử lý" action={<button className="btn primary" onClick={() => setOpen(true)}>Chọn người…</button>}>
      {hint || "Chọn một hồ sơ để bắt đầu."}</Empty>
      {open && <PatientPicker onPick={select} onClose={() => setOpen(false)} />}</div>
  );
}

/** Thanh cảnh báo an toàn người bệnh – luôn thấy dị ứng khi đang thao tác trên một hồ sơ. */
export function SafetyBanner({ summary }) {
  const c = summary?.clinical;
  if (!c) return null;
  if (c.allergy_status === "recorded" && c.allergies.length)
    return <Banner tone="bad"><b>Dị ứng:</b> {c.allergies.map((a) => `${a.substance}${a.reaction ? ` (${a.reaction})` : ""}`).join("; ")}</Banner>;
  if (c.allergy_status === "unknown") return <Banner tone="warn">Chưa ghi nhận thông tin dị ứng – hãy hỏi/ghi nhận trước khi kê đơn.</Banner>;
  return null;
}

