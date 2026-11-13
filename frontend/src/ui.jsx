import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import { statusLabel, statusTone } from "./labels";

export const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);
export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

// ---------------------------------------------------------------- định dạng
export const fmtDT = (d) => (d ? new Date(d.endsWith?.("Z") || /[+-]\d\d:\d\d$/.test(d) ? d : d + "Z").toLocaleString("vi-VN", { hour12: false, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
export const fmtDate = (d) => (d ? String(d).slice(0, 10).split("-").reverse().join("/") : "—");
export const today = () => new Date().toISOString().slice(0, 10);
export const short = (id) => (id ? String(id).slice(0, 8) : "");

// ---------------------------------------------------------------- icon
const P = {
  home: "M3 11l9-8 9 8M5 9.5V20h14V9.5", users: "M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M21 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8", activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  pill: "M10.5 20.5l10-10a4.95 4.95 0 1 0-7-7l-10 10a4.95 4.95 0 1 0 7 7zM8.5 8.5l7 7", calendar: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0", swap: "M17 3l4 4-4 4M3 11V9a2 2 0 0 1 2-2h16M7 21l-4-4 4-4M21 13v2a2 2 0 0 1-2 2H3",
  alert: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01", file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8",
  chart: "M3 3v18h18M7 15l4-4 3 3 5-6", shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  plus: "M12 5v14M5 12h14", x: "M18 6L6 18M6 6l12 12", check: "M20 6L9 17l-5-5", menu: "M3 6h18M3 12h18M3 18h18", logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  clip: "M9 2h6a1 1 0 0 1 1 1v2H8V3a1 1 0 0 1 1-1zM8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2M9 13l2 2 4-4",
  truck: "M1 3h15v13H1zM16 8h4l3 3v5h-7zM5.5 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18.5 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3", upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z", cross: "M9 3h6v6h6v6h-6v6H9v-6H3V9h6z",
  heart: "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z", back: "M19 12H5M12 19l-7-7 7-7",
};
export const Icon = ({ n, size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[n]} /></svg>
);

// ---------------------------------------------------------------- khối giao diện cơ bản
export const Badge = ({ tone = "neutral", children }) => <span className={`badge ${tone}`}>{children}</span>;
export const Status = ({ d, v }) => (v ? <Badge tone={statusTone(d, v)}>{statusLabel(d, v)}</Badge> : null);
export const Card = ({ title, actions, children, flat, className = "" }) => (
  <section className={`card ${flat ? "flat" : ""} ${className}`}>
    {title && <div className="ch">{title}{actions && <div className="sp">{actions}</div>}</div>}
    <div className="cb">{children}</div>
  </section>
);
export const PageHeader = ({ title, sub, actions }) => (
  <div className="ph"><div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>{actions && <div className="acts">{actions}</div>}</div>
);
export const Empty = ({ title, children, action }) => (
  <div className="empty"><b>{title}</b>{children}{action}</div>
);
export const Banner = ({ tone = "info", children }) => <div className={`banner ${tone}`}>{children}</div>;
export const Field = ({ label, required, hint, children }) => (
  <label className="field"><span>{label}{required && <i className="req"> *</i>}</span>{children}{hint && <small>{hint}</small>}</label>
);
export const KV = ({ items }) => (
  <dl className="kv" style={{ margin: 0 }}>{items.filter(Boolean).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{v ?? "—"}</dd></div>)}</dl>
);
export const Progress = ({ value }) => <div className="progress"><div style={{ width: `${Math.round((value || 0) * 100)}%` }} /></div>;

export function Tabs({ items, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {items.filter(Boolean).map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? "on" : ""} onClick={() => onChange(t.id)}>
          {t.label}{t.count != null && <span className="n">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
export const Seg = ({ items, value, onChange }) => (
  <div className="seg">{items.map((i) => <button key={i.id} className={value === i.id ? "on" : ""} onClick={() => onChange(i.id)}>{i.label}</button>)}</div>
);
export function Stepper({ steps, current, onStep }) {
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <div key={s} className={`step ${i < current ? "done" : ""} ${i === current ? "cur" : ""} ${onStep ? "click" : ""}`} onClick={() => onStep?.(i)}>
          <i>{i < current ? "✓" : i + 1}</i>{s}
        </div>
      ))}
    </div>
  );
}

/** columns: [{h, c:(row)=>node, cls}] */
export function DataTable({ columns, rows, onRow, empty, loading }) {
  if (loading && !rows) return <div className="empty">Đang tải…</div>;
  if (!rows?.length) return empty || <Empty title="Không có dữ liệu" />;
  return (
    <div className="tblwrap" tabIndex={0} role="region" aria-label="Bảng dữ liệu (cuộn bằng phím mũi tên)">
      <table className="tbl">
        <thead><tr>{columns.map((c, i) => <th key={i} className={c.cls}>{c.h || <span className="sr-only">Thao tác</span>}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={r.id ?? ri} className={onRow ? "click" : ""} onClick={() => onRow?.(r)}
              {...(onRow ? { tabIndex: 0, onKeyDown: (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); onRow(r); } } } : {})}>
              {columns.map((c, i) => <td key={i} className={c.cls} onClick={c.stop ? (e) => e.stopPropagation() : undefined}>{c.c(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- modal / drawer / form
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const dialogStack = [];   // chỉ hộp thoại trên cùng nhận phím Esc và giữ focus

/** Quản lý focus cho hộp thoại/ngăn kéo: focus vào trong khi mở, Tab quay vòng trong hộp thoại, Esc chỉ đóng lớp trên cùng, trả focus về phần tử đã mở. */
function useDialog(ref, onClose) {
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const el = ref.current, opener = document.activeElement, id = Symbol("dlg");
    dialogStack.push(id);
    const items = () => [...el.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
    if (!el.contains(document.activeElement)) {
      const list = items();
      (el.querySelector("[autofocus]") || list.find((x) => !x.closest("header")) || list[0] || el).focus({ preventScroll: true });
    }
    const key = (e) => {
      if (dialogStack[dialogStack.length - 1] !== id) return;
      if (e.key === "Escape") { e.stopPropagation(); close.current(); return; }
      if (e.key !== "Tab") return;
      const f = items();
      if (!f.length) { e.preventDefault(); el.focus(); return; }
      const first = f[0], last = f[f.length - 1], cur = document.activeElement;
      if (e.shiftKey && (cur === first || !el.contains(cur))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (cur === last || !el.contains(cur))) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("keydown", key, true);
      const i = dialogStack.indexOf(id); if (i >= 0) dialogStack.splice(i, 1);
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
    };
  }, [ref]);
}

export function Modal({ title, onClose, children, footer, wide }) {
  const ref = useRef(null);
  useDialog(ref, onClose);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header role="none">{title}<button className="btn ghost sm" onClick={onClose} aria-label="Đóng"><Icon n="x" /></button></header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}
export function Drawer({ title, onClose, children, actions }) {
  const ref = useRef(null);
  useDialog(ref, onClose);
  return (
    <div className="drawer-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header role="none"><button className="btn sm" onClick={onClose}><Icon n="back" size={15} /> Quay lại</button><h2>{title}</h2>{actions}</header>
        <div className="body">{children}</div>
      </div>
    </div>
  );
}
/** Form trong modal. onSubmit(data) trả truthy -> đóng. Input đọc theo thuộc tính name (uncontrolled). */
export function FormModal({ title, onClose, onSubmit, submit = "Lưu", danger, wide, children, extra }) {
  const [busy, setBusy] = useState(false);
  const id = useRef("f" + Math.random().toString(36).slice(2)).current;
  const go = async (e) => {
    e.preventDefault();
    const data = {};
    [...e.currentTarget.elements].forEach((el) => {
      if (!el.name) return;
      if (el.type === "checkbox") { if (el.checked) data[el.name] = true; return; }
      if (el.type === "file") { if (el.files[0]) data[el.name] = el.files[0]; return; }
      const v = el.value.trim();
      if (v !== "") data[el.name] = v;
    });
    setBusy(true);
    try { if (await onSubmit(data)) onClose(); } finally { setBusy(false); }
  };
  return (
    <Modal title={title} onClose={onClose} wide={wide}
      footer={<>{extra}<button type="button" className="btn" onClick={onClose}>Hủy</button><button className={`btn ${danger ? "danger" : "primary"}`} form={id} disabled={busy}>{busy ? "Đang lưu…" : submit}</button></>}>
      <form id={id} onSubmit={go}>{children}</form>
    </Modal>
  );
}

/** Form nội tuyến (không modal). onSubmit(data) trả truthy -> reset form. */
export function Form({ onSubmit, children, className, keep }) {
  const [busy, setBusy] = useState(false);
  return (
    <form onSubmit={async (e) => {
      e.preventDefault();
      const f = e.currentTarget, data = {};
      [...f.elements].forEach((el) => {
        if (!el.name) return;
        if (el.type === "checkbox") { if (el.checked) data[el.name] = true; return; }
        const v = el.value.trim();
        if (v !== "") data[el.name] = v;
      });
      setBusy(true);
      try { if ((await onSubmit(data)) && !keep) f.reset(); } finally { setBusy(false); }
    }}>
      <fieldset className={className} disabled={busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>{children}</fieldset>
    </form>
  );
}

// ---------------------------------------------------------------- toast + hộp thoại xác nhận/nhập
export function Overlays({ children }) {
  const [toast, setToast] = useState(null);
  const [dlg, setDlg] = useState(null);
  const timer = useRef();
  const notify = useCallback((msg, ok = true) => {
    setToast({ msg, ok });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 5000);
  }, []);
  const prompt = useCallback((o) => new Promise((res) => setDlg({ kind: "prompt", res, ...o })), []);
  const confirm = useCallback((o) => new Promise((res) => setDlg({ kind: "confirm", res, ...o })), []);
  const done = (v) => { dlg.res(v); setDlg(null); };
  return (
    <AppCtx.Provider value={{ notify, prompt, confirm }}>
      {children}
      {toast && <div className="toast" role="status" style={{ background: toast.ok ? "#15803d" : "#b91c1c" }}>{toast.msg}</div>}
      {dlg && (
        <Modal title={dlg.title || (dlg.kind === "confirm" ? "Xác nhận" : "Nhập thông tin")} onClose={() => done(dlg.kind === "confirm" ? false : null)}
          footer={<><button className="btn" onClick={() => done(dlg.kind === "confirm" ? false : null)}>Hủy</button>
            <button className={`btn ${dlg.danger ? "danger" : "primary"}`} form="dlgform">{dlg.okLabel || "Đồng ý"}</button></>}>
          <form id="dlgform" onSubmit={(e) => { e.preventDefault(); done(dlg.kind === "confirm" ? true : e.currentTarget.elements.v.value.trim() || null); }}>
            {dlg.message && <div style={{ whiteSpace: "pre-line", marginBottom: 10 }}>{dlg.message}</div>}
            {dlg.kind === "prompt" && (
              <Field label={dlg.label} required={dlg.required}>
                {dlg.multiline ? <textarea name="v" defaultValue={dlg.defaultValue} autoFocus required={dlg.required} /> : <input name="v" defaultValue={dlg.defaultValue} autoFocus required={dlg.required} />}
              </Field>
            )}
          </form>
        </Modal>
      )}
    </AppCtx.Provider>
  );
}

// ---------------------------------------------------------------- hook gọi API
export function useAct() {
  const { notify } = useApp();
  return useCallback(async (fn, okMsg) => {
    try {
      const r = await fn();
      if (okMsg) notify(okMsg);
      return r ?? true;
    } catch (e) {
      if (!(e instanceof ApiError)) { notify("Không kết nối được máy chủ", false); return undefined; }
      const extra = [e.data.warnings?.map((w) => w.message), e.data.problems, e.data.errors?.map((x) => `${x.field}: ${x.message}`)].flat().filter(Boolean);
      notify(e.message + (extra.length ? " – " + extra.join("; ") : ""), false);
      return undefined;
    }
  }, [notify]);
}

/** useLoad(fn, deps, skip) -> {data, reload, loading}. Lỗi hiện toast; giữ dữ liệu cũ khi tải lại. */
export function useLoad(fn, deps = [], skip = false) {
  const act = useAct();
  const [data, setData] = useState();
  const [loading, setLoading] = useState(!skip);
  const [n, setN] = useState(0);
  const seq = useRef(0);
  const loadedAt = useRef(0);
  // quay lại cửa sổ/tab sau >20 giây -> tự tải lại để không hiển thị dữ liệu cũ (không ảnh hưởng ô đang nhập)
  useEffect(() => {
    if (skip) return;
    const wake = () => { if (!document.hidden && Date.now() - loadedAt.current > 20000) setN((x) => x + 1); };
    window.addEventListener("focus", wake); document.addEventListener("visibilitychange", wake);
    return () => { window.removeEventListener("focus", wake); document.removeEventListener("visibilitychange", wake); };
  }, [skip]);
  useEffect(() => {
    if (skip) { setData(undefined); setLoading(false); return; }
    loadedAt.current = Date.now();
    const my = ++seq.current;
    setLoading(true);
    act(fn).then((d) => { if (my === seq.current) { setData(d === true ? undefined : d); setLoading(false); } });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n, skip]);
  return { data, loading, reload: useCallback(() => setN((x) => x + 1), []) };
}

export const useDebounced = (v, ms = 300) => {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
};

// ---------------------------------------------------------------- giao diện sáng/tối (mặc định SÁNG, không theo hệ điều hành)
const THEME_KEY = "phms_theme";
export const getTheme = () => { try { return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light"; } catch { return "light"; } };
export const applyTheme = (t) => { document.documentElement.dataset.theme = t; try { localStorage.setItem(THEME_KEY, t); } catch { /* bỏ qua */ } };
export function ThemeToggle() {
  const [t, setT] = useState(getTheme());
  return (
    <button className="btn icon" aria-label={t === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"} title={t === "dark" ? "Giao diện sáng" : "Giao diện tối"}
      onClick={() => { const n = t === "dark" ? "light" : "dark"; applyTheme(n); setT(n); }}><Icon n={t === "dark" ? "sun" : "moon"} /></button>
  );
}
