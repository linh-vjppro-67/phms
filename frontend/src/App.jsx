import { useCallback, useEffect, useMemo, useState } from "react";
import { api, getToken, setToken } from "./api";
import { ROLE_LABEL } from "./labels";
import { AuthCtx, Badge, Field, Icon, ThemeToggle, useApp, useAct } from "./ui.jsx";
import { AccountDialog, Login, SecurityGate } from "./auth.jsx";
import { PatientPicker, PatientProvider, usePatient } from "./patient.jsx";
import { NotificationBell, NotifyProvider } from "./notifications.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Intake from "./pages/Intake.jsx";
import Handover from "./pages/Handover.jsx";
import InitialExam from "./pages/InitialExam.jsx";
import Encounters from "./pages/Encounters.jsx";
import Emergency from "./pages/Emergency.jsx";
import Prescribing from "./pages/Prescribing.jsx";
import Pharmacy from "./pages/Pharmacy.jsx";
import Periodic from "./pages/Periodic.jsx";
import Chronic from "./pages/Chronic.jsx";
import Referrals from "./pages/Referrals.jsx";
import Record from "./pages/Record.jsx";
import Documents from "./pages/Documents.jsx";
import Reports from "./pages/Reports.jsx";
import Admin from "./pages/Admin.jsx";

// Mỗi tab = một phân hệ (M..) hoặc luồng nghiệp vụ (WF-..) trong tài liệu thiết kế.
const NAV = [
  { group: "Tổng quan", items: [{ id: "dashboard", label: "Bảng điều khiển", icon: "home", C: Dashboard }] },
  { group: "Tiếp nhận & quản lý", items: [
    { id: "intake", label: "Tiếp nhận & Hồ sơ", code: "M01", icon: "users", any: ["person.read"], C: Intake, stat: "pending_verification" },
    { id: "handover", label: "Chuyển trại & Bàn giao", code: "WF-07", icon: "swap", any: ["handover.initiate", "handover.confirm", "handover.summary"], C: Handover, stat: "pending_handovers" },
  ] },
  { group: "Khám chữa bệnh", items: [
    { id: "initial", label: "Khám ban đầu", code: "M03", icon: "clip", any: ["encounter.write"], C: InitialExam, stat: "awaiting_initial_exam" },
    { id: "exam", label: "Khám chữa bệnh", code: "M04", icon: "activity", any: ["clinical.read"], C: Encounters, stat: "open_encounters", plain: true },
    { id: "emergency", label: "Cấp cứu", code: "WF-08", icon: "alert", any: ["emergency.write"], C: Emergency, stat: "open_emergencies" },
  ] },
  { group: "Thuốc", items: [
    { id: "rx", label: "Chỉ định & Kê đơn", code: "M05", icon: "file", any: ["clinical.read"], C: Prescribing, stat: "orders_draft" },
    { id: "pharmacy", label: "Cấp phát thuốc", code: "M06", icon: "pill", any: ["dispense.write", "admin.write"], C: Pharmacy, stat: "dispense_queue" },
  ] },
  { group: "Theo dõi", items: [
    { id: "periodic", label: "Khám định kỳ", code: "M07", icon: "calendar", any: ["schedule.read"], C: Periodic },
    { id: "chronic", label: "Bệnh lý & Cảnh báo", code: "M08", icon: "bell", any: ["schedule.read"], C: Chronic, stat: "new_alerts" },
    { id: "referral", label: "Chuyển viện", code: "M09", icon: "truck", any: ["referral.read"], C: Referrals, stat: "open_referrals", plain: true },
  ] },
  { group: "Hồ sơ", items: [
    { id: "record", label: "Hồ sơ sức khỏe", code: "M02", icon: "heart", any: ["clinical.read"], C: Record },
    { id: "docs", label: "Tài liệu y tế", code: "M12", icon: "file", any: ["document.read"], C: Documents },
  ] },
  { group: "Quản lý", items: [
    { id: "reports", label: "Báo cáo & Thống kê", code: "M10", icon: "chart", any: ["report.read"], C: Reports },
    { id: "admin", label: "Quản trị hệ thống", code: "M11", icon: "shield", any: ["user.manage", "audit.read"], C: Admin },
  ] },
];
const FLAT = NAV.flatMap((g) => g.items);

// Đăng nhập SSO thành công: máy chủ chuyển về #/sso?token=… -> nhận phiên rồi xóa token khỏi thanh địa chỉ
{
  const m = location.hash.match(/^#\/sso\?token=([\w.-]+)$/);
  if (m) { setToken(m[1]); history.replaceState(null, "", location.pathname + "#/dashboard"); }
}
const needGate = (u) => (u.must_change_password ? "password_change" : u.mfa_required && !u.mfa_enabled ? "mfa_enroll" : null);

const route = () => { const [page, param] = location.hash.replace(/^#\/?/, "").split("/"); return { page: page || "dashboard", param: param || null }; };

/** Đồng hồ thanh trên: giờ:phút:giây + thứ, ngày theo múi giờ của máy đang dùng. */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  const time = now.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const date = now.toLocaleDateString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
  return (
    <time className="clock" dateTime={now.toISOString()} title={`${date} ${time}`}>
      <b aria-hidden="true">{time}</b><small aria-hidden="true">{date}</small>
    </time>
  );
}

function PatientChip() {
  const { patient, summary, activeStay, bgUntil, select, clear } = usePatient();
  const [open, setOpen] = useState(false);
  return (
    <>
      {patient ? (
        <div className="pctx" title="Người đang xử lý – dùng chung cho các tab">
          <Icon n="user" size={16} /><b>{patient.name}</b>
          {activeStay ? <Badge tone="ok">Đang trong đợt tiếp nhận</Badge>
            : bgUntil ? <Badge tone="bad" >Truy cập khẩn cấp (chỉ đọc) đến {new Date(/[zZ]|[+-]\d\d:\d\d$/.test(bgUntil) ? bgUntil : bgUntil + "Z").toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}</Badge>
            : summary && <Badge tone="warn">Không có kỳ hiệu lực</Badge>}
          {summary?.clinical?.allergy_status === "recorded" && <Badge tone="bad">Dị ứng</Badge>}
          <button className="btn sm ghost" onClick={() => setOpen(true)}>Đổi</button>
          <button className="btn sm ghost" onClick={clear} aria-label="Bỏ chọn"><Icon n="x" size={14} /></button>
        </div>
      ) : <button className="btn" onClick={() => setOpen(true)}><Icon n="search" size={15} /> Chọn người xử lý</button>}
      {open && <PatientPicker onPick={select} onClose={() => setOpen(false)} />}
    </>
  );
}

export default function App() {
  const { notify } = useApp();
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(!getToken());
  const [loc, setLoc] = useState(route());
  const [stats, setStats] = useState({});
  const [menu, setMenu] = useState(false);
  const [gate, setGate] = useState(null);          // phiên hạn chế: password_change | mfa_enroll
  const [acct, setAcct] = useState(false);
  useEffect(() => { const k = (e) => e.key === "Escape" && setMenu(false); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, []);

  const logout = useCallback(() => { setToken(null); setUser(null); setGate(null); setStats({}); }, []);
  const refreshStats = useCallback(() => api("GET", "/dashboard").then(setStats).catch(() => {}), []);

  useEffect(() => {
    if (getToken()) api("GET", "/auth/me").then((u) => { setUser(u); setGate(needGate(u)); }).catch(() => setToken(null)).finally(() => setReady(true));
    const h = () => { setToken(null); setUser(null); notify("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại", false); };
    const r = () => { setLoc(route()); setMenu(false); };
    window.addEventListener("phms-unauthorized", h);
    window.addEventListener("hashchange", r);
    return () => { window.removeEventListener("phms-unauthorized", h); window.removeEventListener("hashchange", r); };
  }, [notify]);

  useEffect(() => {
    if (!user) return;
    refreshStats();
    const t = setInterval(refreshStats, 60000);
    return () => clearInterval(t);
  }, [user, refreshStats]);

  const has = useCallback((p) => !!user?.permissions.includes(p), [user]);
  const allowed = useCallback((it) => !it.any || it.any.some(has), [has]);
  const groups = useMemo(() => NAV.map((g) => ({ ...g, items: g.items.filter(allowed) })).filter((g) => g.items.length), [allowed]);

  if (!ready) return null;
  if (!user) return <Login onLogin={(u, req) => { setUser(u); setGate(req); if (!req) location.hash = "#/dashboard"; }} />;
  if (gate) return <SecurityGate requires={gate} user={user} onLogout={logout} onProgress={(u, req) => { setUser(u); setGate(req); if (!req) location.hash = "#/dashboard"; }} />;

  const cur = FLAT.find((i) => i.id === loc.page && allowed(i)) || FLAT[0];
  const Page = cur.C;
  const go = (id, param) => { location.hash = `#/${id}${param ? "/" + param : ""}`; setMenu(false); };   // đóng menu kể cả khi bấm đúng tab đang mở
  return (
    <AuthCtx.Provider value={{ user, has, stats, refreshStats, go }}>
      <NotifyProvider>
      <PatientProvider>
        <div className="app">
          <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Bỏ qua điều hướng, tới nội dung chính</a>
          <div className={`side-bg ${menu ? "open" : ""}`} onClick={() => setMenu(false)} aria-hidden="true" />
          <nav className={`side ${menu ? "open" : ""}`} aria-label="Điều hướng">
            <div className="brand"><span className="logo"><Icon n="cross" size={20} /></span><div>PHMS<small>Quản lý sức khỏe phạm nhân</small></div></div>
            {groups.map((g) => (
              <div key={g.group}>
                <div className="grp">{g.group}</div>
                {g.items.map((i) => (
                  <button key={i.id} className={`nav ${cur.id === i.id ? "on" : ""}`} onClick={() => go(i.id)}>
                    <Icon n={i.icon} size={17} />{i.label}
                    {i.code && <span className="code">{i.code}</span>}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="main">
            <header className="top">
              <button className="btn menu-btn" onClick={() => setMenu(!menu)} aria-label="Menu"><Icon n="menu" /></button>
              {(has("person.read") || has("clinical.read")) && <PatientChip />}
              <div className="grow" />
              <Clock />
              <ThemeToggle />
              <NotificationBell />
              <button className="who" onClick={() => setAcct(true)} aria-label={`Tài khoản: ${user.full_name}`} title="Tài khoản của tôi – đổi mật khẩu, xác thực 2 lớp"><b>{user.full_name}</b><small>{ROLE_LABEL[user.role] || user.role}</small></button>
              <button className="btn" onClick={logout} aria-label="Đăng xuất"><Icon n="logout" size={15} /><span className="lbl"> Đăng xuất</span></button>
            </header>
            <main className="content" id="main" tabIndex={-1}><Page key={cur.id + (loc.param || "")} focus={loc.param} /></main>
            {acct && <AccountDialog user={user} onClose={() => setAcct(false)} onUserChange={(u) => setUser(u)} />}
          </div>
        </div>
      </PatientProvider>
      </NotifyProvider>
    </AuthCtx.Provider>
  );
}
