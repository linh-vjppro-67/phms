// Hệ thống thông báo phía giao diện: polling nhẹ, chuông + trung tâm thông báo, tùy chọn theo nhóm, thông báo trình duyệt.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, qs } from "./api";
import { Icon, useApp } from "./ui.jsx";

const Ctx = createContext(null);
export const useNotifications = () => useContext(Ctx);

const BASE_TITLE = "PHMS – Quản lý sức khỏe phạm nhân";
const POLL_VISIBLE = 20000, POLL_HIDDEN = 60000, POLL_MAX_BACKOFF = 120000;
const DESKTOP_KEY = "phms_desktop_notify";

const toUtc = (d) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(d) ? d : d + "Z");
export function timeAgo(d) {
  const s = Math.max(0, (Date.now() - toUtc(d)) / 1000);
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} ngày trước`;
  return toUtc(d).toLocaleDateString("vi-VN");
}
const isToday = (d) => toUtc(d).toDateString() === new Date().toDateString();
const sortDesc = (a) => a.sort((x, y) => y.seq - x.seq);
const merge = (prev, add) => {
  const m = new Map(prev.map((n) => [n.id, n]));
  add.forEach((n) => m.set(n.id, { ...m.get(n.id), ...n }));
  return sortDesc([...m.values()]);
};

export function NotifyProvider({ children }) {
  const { notify } = useApp();
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({ unread: 0, critical: 0 });
  const [more, setMore] = useState(null);
  const [loading, setLoading] = useState(true);
  const [desktop, setDesktop] = useState(() => localStorage.getItem(DESKTOP_KEY) === "1" && typeof Notification !== "undefined" && Notification.permission === "granted");
  const latest = useRef(0);
  const announced = useRef("");
  const fails = useRef(0);
  const desktopRef = useRef(desktop);
  desktopRef.current = desktop;

  const announce = useCallback((fresh) => {
    const crit = fresh.filter((n) => n.severity === "critical");
    crit.slice(0, 3).forEach((n) => notify(`🔔 ${n.title}`, false));
    if (fresh.length) announced.current = fresh[0].title;
    if (desktopRef.current && document.hidden) {
      // Thông báo hệ điều hành KHÔNG chứa tên/chi tiết người bệnh – chỉ tiêu đề chung.
      fresh.filter((n) => n.severity !== "info").slice(0, 3).forEach((n) => {
        const w = new Notification(n.title, { body: "Mở PHMS để xem chi tiết.", tag: n.id, icon: undefined });
        w.onclick = () => { window.focus(); location.hash = `#/${n.link_page || "dashboard"}${n.link_ref ? "/" + n.link_ref : ""}`; w.close(); };
      });
    }
  }, [notify]);

  const loadFirst = useCallback(async () => {
    try {
      const d = await api("GET", "/notifications" + qs({ limit: 30 }));
      setItems(sortDesc(d.items)); setMore(d.next_before_seq); setCounts({ unread: d.unread, critical: d.critical });
      latest.current = d.items[0]?.seq || 0;
    } finally { setLoading(false); }
  }, []);

  const tick = useCallback(async () => {
    for (let i = 0; i < 5; i++) {   // nhận hết đợt tồn (tối đa 5 x 50)
      const d = await api("GET", `/notifications/poll?after_seq=${latest.current}`);
      setCounts({ unread: d.unread, critical: d.critical });
      if (!d.items.length) return;
      latest.current = d.items[d.items.length - 1].seq;
      setItems((p) => merge(p, d.items));
      announce([...d.items].reverse());
      if (d.items.length < 50) return;
    }
  }, [announce]);

  useEffect(() => {
    let stop = false, timer;
    const schedule = (ms) => { clearTimeout(timer); if (!stop) timer = setTimeout(run, ms); };
    const run = async () => {
      try { await tick(); fails.current = 0; schedule(document.hidden ? POLL_HIDDEN : POLL_VISIBLE); }
      catch { fails.current += 1; schedule(Math.min(POLL_MAX_BACKOFF, POLL_VISIBLE * 2 ** fails.current)); }
    };
    loadFirst().then(() => schedule(POLL_VISIBLE)).catch(() => schedule(POLL_VISIBLE));
    const wake = () => { if (!document.hidden) run(); };
    window.addEventListener("focus", wake); window.addEventListener("online", wake); document.addEventListener("visibilitychange", wake);
    return () => { stop = true; clearTimeout(timer); window.removeEventListener("focus", wake); window.removeEventListener("online", wake); document.removeEventListener("visibilitychange", wake); };
  }, [tick, loadFirst]);

  useEffect(() => { document.title = counts.unread > 0 ? `(${counts.unread > 99 ? "99+" : counts.unread}) ${BASE_TITLE}` : BASE_TITLE; return () => { document.title = BASE_TITLE; }; }, [counts.unread]);

  const apply = (id, patch) => setItems((p) => p.map((n) => (n.id === id ? { ...n, ...patch } : n)));
  const markRead = useCallback(async (n) => {
    if (n.read_at) return;
    apply(n.id, { read_at: new Date().toISOString() });
    setCounts((c) => ({ unread: Math.max(0, c.unread - 1), critical: Math.max(0, c.critical - (n.severity === "critical" ? 1 : 0)) }));
    try { const r = await api("POST", `/notifications/${n.id}/read`); setCounts({ unread: r.unread, critical: r.critical }); } catch { loadFirst(); }
  }, [loadFirst]);
  const readAll = useCallback(async () => {
    const r = await api("POST", "/notifications/read-all");
    setItems((p) => p.map((n) => ({ ...n, read_at: n.read_at || new Date().toISOString() }))); setCounts({ unread: r.unread, critical: r.critical });
  }, []);
  const dismiss = useCallback(async (n) => {
    setItems((p) => p.filter((x) => x.id !== n.id));
    try { const r = await api("POST", `/notifications/${n.id}/dismiss`); setCounts({ unread: r.unread, critical: r.critical }); } catch { loadFirst(); }
  }, [loadFirst]);
  const loadMore = useCallback(async () => {
    if (!more) return;
    const d = await api("GET", "/notifications" + qs({ limit: 30, before_seq: more }));
    setItems((p) => merge(p, d.items)); setMore(d.next_before_seq);
  }, [more]);
  const loadUnread = useCallback(async () => {
    const d = await api("GET", "/notifications" + qs({ unread: true, limit: 100 }));
    setItems((p) => merge(p, d.items)); setCounts({ unread: d.unread, critical: d.critical });
  }, []);

  const toggleDesktop = useCallback(async () => {
    if (typeof Notification === "undefined") return notify("Trình duyệt này không hỗ trợ thông báo hệ thống", false);
    if (desktop) { localStorage.removeItem(DESKTOP_KEY); return setDesktop(false); }
    const p = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    if (p === "granted") { localStorage.setItem(DESKTOP_KEY, "1"); setDesktop(true); notify("Đã bật thông báo trên trình duyệt (không hiển thị tên người bệnh)"); }
    else notify("Bạn đã chặn thông báo trên trình duyệt. Hãy cho phép trong cài đặt trang.", false);
  }, [desktop, notify]);

  const value = useMemo(() => ({ items, counts, more, loading, desktop, markRead, readAll, dismiss, loadMore, loadUnread, toggleDesktop, announced }),
    [items, counts, more, loading, desktop, markRead, readAll, dismiss, loadMore, loadUnread, toggleDesktop]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="sr-only" role="status" aria-live="polite">{counts.unread > 0 ? `Bạn có ${counts.unread} thông báo chưa đọc. Mới nhất: ${announced.current}` : ""}</div>
    </Ctx.Provider>
  );
}

const SEV = { critical: "bad", warning: "warn", info: "info" };

function Item({ n, onOpen }) {
  const { dismiss } = useNotifications();
  return (
    <div className={`nitem ${SEV[n.severity]} ${n.read_at ? "" : "unread"}`} onClick={() => onOpen(n)}>
      <span className="ndot" role="img" aria-label={n.read_at ? "Đã đọc" : "Chưa đọc"} />
      <button type="button" className="nmain nbtn" onClick={(e) => { e.stopPropagation(); onOpen(n); }}>
        <span className="ntitle">{n.title}</span>
        {n.body && <span className="nbody">{n.body}</span>}
        <span className="nmeta">{n.severity === "critical" && <b>Khẩn · </b>}{timeAgo(n.created_at)}</span>
      </button>
      <button className="btn ghost sm nx" aria-label="Ẩn thông báo" title="Ẩn" onClick={(e) => { e.stopPropagation(); dismiss(n); }}><Icon n="x" size={14} /></button>
    </div>
  );
}

function Settings() {
  const { desktop, toggleDesktop } = useNotifications();
  const { notify } = useApp();
  const [prefs, setPrefs] = useState(null);
  useEffect(() => { api("GET", "/notifications/preferences").then(setPrefs).catch(() => notify("Không tải được cài đặt", false)); }, [notify]);
  const set = async (cat, enabled) => {
    setPrefs((p) => p.map((x) => (x.category === cat ? { ...x, enabled } : x)));
    try { setPrefs(await api("PUT", "/notifications/preferences", { categories: { [cat]: enabled } })); }
    catch (e) { notify(e.message, false); setPrefs(await api("GET", "/notifications/preferences")); }
  };
  if (!prefs) return <div className="empty">Đang tải…</div>;
  return (
    <div className="nsettings">
      <p className="muted sm" style={{ margin: "0 0 10px" }}>Chọn loại thông báo bạn muốn nhận. Nhóm bắt buộc liên quan an toàn người bệnh/bảo mật không thể tắt.</p>
      {prefs.map((p) => (
        <label key={p.category} className="prefrow">
          <span><b>{p.label}</b>{p.mandatory && <span className="badge neutral" style={{ marginLeft: 6 }}>Bắt buộc</span>}<small>{p.description}</small></span>
          <input type="checkbox" role="switch" checked={p.enabled} disabled={p.mandatory} onChange={(e) => set(p.category, e.target.checked)} />
        </label>
      ))}
      <label className="prefrow">
        <span><b>Thông báo trên trình duyệt</b><small>Hiện khi bạn ở tab/cửa sổ khác. Không hiển thị tên người bệnh.</small></span>
        <input type="checkbox" role="switch" checked={desktop} onChange={toggleDesktop} />
      </label>
    </div>
  );
}

export function NotificationBell() {
  const n = useNotifications();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("all");
  const ref = useRef();
  useEffect(() => {
    if (!open) return;
    const down = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    const key = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", down); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);
  useEffect(() => { if (open && tab === "unread") n.loadUnread().catch(() => {}); /* eslint-disable-next-line */ }, [open, tab]);

  const go = (x) => {
    n.markRead(x);
    setOpen(false);
    location.hash = `#/${x.link_page || "dashboard"}${x.link_ref ? "/" + x.link_ref : ""}`;
  };
  const list = tab === "unread" ? n.items.filter((x) => !x.read_at) : n.items;
  const today = list.filter((x) => isToday(x.created_at)), earlier = list.filter((x) => !isToday(x.created_at));
  const { unread, critical } = n.counts;

  return (
    <div className="bellwrap" ref={ref}>
      <button className={`btn bell ${critical ? "crit" : ""}`} aria-label={`Thông báo${unread ? `, ${unread} chưa đọc` : ""}`} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}>
        <Icon n="bell" />{unread > 0 && <span className={`bellbadge ${critical ? "crit" : ""}`}>{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="np" role="dialog" aria-label="Trung tâm thông báo">
          <div className="nph">
            <b>Thông báo</b>
            <div className="row" style={{ marginLeft: "auto" }}>
              {tab !== "settings" && <button className="btn sm ghost" disabled={!unread} onClick={n.readAll}>Đọc tất cả</button>}
              <button className={`btn sm ghost ${tab === "settings" ? "on" : ""}`} aria-label="Cài đặt thông báo" onClick={() => setTab(tab === "settings" ? "all" : "settings")}>⚙</button>
            </div>
          </div>
          {tab !== "settings" && (
            <div className="npt">
              <button className={tab === "all" ? "on" : ""} onClick={() => setTab("all")}>Tất cả</button>
              <button className={tab === "unread" ? "on" : ""} onClick={() => setTab("unread")}>Chưa đọc{unread > 0 && <span className="n">{unread}</span>}</button>
            </div>
          )}
          <div className="npb">
            {tab === "settings" ? <Settings /> : n.loading ? <div className="empty">Đang tải…</div> : !list.length ? (
              <div className="empty"><b>{tab === "unread" ? "Bạn đã đọc hết thông báo" : "Chưa có thông báo"}</b>Các sự kiện cần bạn xử lý sẽ hiện ở đây.</div>
            ) : (
              <>
                {today.length > 0 && <div className="ngrp">Hôm nay</div>}{today.map((x) => <Item key={x.id} n={x} onOpen={go} />)}
                {earlier.length > 0 && <div className="ngrp">Trước đó</div>}{earlier.map((x) => <Item key={x.id} n={x} onOpen={go} />)}
                {n.more && tab === "all" && <button className="btn sm" style={{ margin: 10 }} onClick={n.loadMore}>Tải thêm</button>}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
