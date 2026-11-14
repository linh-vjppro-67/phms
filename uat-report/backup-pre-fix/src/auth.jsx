// Đăng nhập, bắt buộc đổi mật khẩu / đăng ký MFA, và hộp thoại tài khoản (đổi mật khẩu, xác thực 2 lớp).
import qrcode from "qrcode-generator";
import { useEffect, useState } from "react";
import { ApiError, api, setToken } from "./api";
import { Badge, Banner, Field, Icon, Modal, Tabs, useAct, useApp } from "./ui.jsx";

const SSO_ERR = {
  idp_error: "Nhà cung cấp đăng nhập từ chối yêu cầu.", state_expired: "Phiên đăng nhập SSO đã hết hạn, hãy thử lại.",
  bad_state: "Yêu cầu SSO không hợp lệ (state không khớp).", idp_verify: "Không xác minh được phản hồi từ nhà cung cấp đăng nhập.",
  no_account: "Tài khoản SSO của bạn chưa được cấp quyền trong PHMS. Liên hệ quản trị viên.",
};
const POLICY = "Tối thiểu 10 ký tự, có chữ hoa, chữ thường và chữ số.";

/** Dạng chuẩn hóa để App dùng: phiên đầy đủ hoặc cần thao tác bắt buộc. */
const finish = (r, onLogin) => { setToken(r.access_token); onLogin(r.user, r.requires || null); };

export function Login({ onLogin }) {
  const { notify } = useApp();
  const [busy, setBusy] = useState(false);
  const [cred, setCred] = useState(null);          // {u,p} khi đang chờ mã OTP
  const [sso, setSso] = useState({ enabled: false, password_login_disabled: false });
  const [showPwd, setShowPwd] = useState(false);
  const ssoErr = new URLSearchParams(location.hash.split("?")[1] || "").get("sso_error");
  useEffect(() => { api("GET", "/auth/sso/config").then(setSso).catch(() => {}); }, []);

  const submit = async (u, p, otp) => {
    setBusy(true);
    try { finish(await api("POST", "/auth/login", { username: u, password: p, ...(otp && { otp }) }), onLogin); }
    catch (e) {
      if (e instanceof ApiError && e.data.code === "MFA_REQUIRED") setCred({ u, p });
      else notify(e instanceof ApiError ? e.message : "Không kết nối được máy chủ", false);
    } finally { setBusy(false); }
  };
  const go = (e) => {
    e.preventDefault();
    const f = e.currentTarget.elements;
    if (cred) return submit(cred.u, cred.p, f.otp.value.replace(/\s/g, ""));
    submit(f.u.value.trim(), f.p.value);
  };
  const form = !sso.password_login_disabled || showPwd;
  return (
    <main className="login">
      <form className="card" onSubmit={go}><div className="cb">
        <div className="logo"><Icon n="cross" size={26} /></div><h1>PHMS</h1><p className="muted" style={{ marginTop: 0, marginBottom: 22 }}>Hệ thống quản lý sức khỏe phạm nhân</p>
        {ssoErr && <Banner tone="bad">{SSO_ERR[ssoErr] || "Đăng nhập SSO thất bại."}</Banner>}
        {sso.enabled && !cred && <a className="btn primary" style={{ width: "100%", justifyContent: "center", marginBottom: 12 }} href="/api/auth/sso/login">Đăng nhập bằng SSO</a>}
        {form && (cred ? (
          <>
            <Banner tone="info">Tài khoản <b>{cred.u}</b> bật xác thực 2 lớp. Nhập mã 6 số trong ứng dụng xác thực.</Banner>
            <Field label="Mã xác thực (6 số)"><input name="otp" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} autoFocus required /></Field>
            <button type="button" className="btn ghost sm" onClick={() => setCred(null)} style={{ marginBottom: 10 }}>← Dùng tài khoản khác</button>
          </>
        ) : (
          <>
            <Field label="Tên đăng nhập"><input name="u" autoComplete="username" autoFocus required /></Field>
            <Field label="Mật khẩu"><input name="p" type="password" autoComplete="current-password" required /></Field>
          </>
        ))}
        {form && <button className="btn primary" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>{busy ? "Đang đăng nhập…" : cred ? "Xác nhận" : "Đăng nhập"}</button>}
        {sso.password_login_disabled && !showPwd && <button type="button" className="btn ghost sm" style={{ marginTop: 10 }} onClick={() => setShowPwd(true)}>Đăng nhập quản trị bằng mật khẩu</button>}
      </div></form>
    </main>
  );
}

// ---------------------------------------------------------------- đổi mật khẩu
export function PasswordForm({ onDone, forced }) {
  const act = useAct();
  const [err, setErr] = useState(null);
  const go = async (e) => {
    e.preventDefault();
    const f = e.currentTarget.elements;
    if (f.n.value !== f.n2.value) return setErr("Mật khẩu nhập lại không khớp");
    setErr(null);
    const r = await act(() => api("POST", "/auth/change-password", { old_password: f.o.value, new_password: f.n.value }), "Đã đổi mật khẩu");
    if (r?.access_token) { setToken(r.access_token); onDone(r); }
  };
  return (
    <form onSubmit={go} id="pwdform">
      {forced && <Banner tone="warn">Bạn cần đặt mật khẩu mới trước khi sử dụng hệ thống.</Banner>}
      {err && <Banner tone="bad">{err}</Banner>}
      <Field label={forced ? "Mật khẩu hiện tại (do quản trị cấp)" : "Mật khẩu hiện tại"} required><input name="o" type="password" autoComplete="current-password" required autoFocus /></Field>
      <Field label="Mật khẩu mới" required hint={POLICY}><input name="n" type="password" autoComplete="new-password" required minLength={10} /></Field>
      <Field label="Nhập lại mật khẩu mới" required><input name="n2" type="password" autoComplete="new-password" required minLength={10} /></Field>
      <button className="btn primary" style={{ marginTop: 4 }}>Đổi mật khẩu</button>
    </form>
  );
}

// ---------------------------------------------------------------- MFA
function Qr({ text }) {
  const q = qrcode(0, "M"); q.addData(text); q.make();
  return <div className="qr" role="img" aria-label="Mã QR đăng ký ứng dụng xác thực" dangerouslySetInnerHTML={{ __html: q.createSvgTag({ cellSize: 4, margin: 2, scalable: true }) }} />;
}

export function MfaEnroll({ onDone }) {
  const act = useAct();
  const [s, setS] = useState(null);
  useEffect(() => { act(() => api("POST", "/auth/mfa/setup")).then((r) => r && setS(r)); }, [act]);
  const go = async (e) => {
    e.preventDefault();
    const r = await act(() => api("POST", "/auth/mfa/enable", { code: e.currentTarget.elements.c.value.replace(/\s/g, "") }), "Đã bật xác thực 2 lớp");
    if (r?.access_token) { setToken(r.access_token); onDone(r); }
  };
  if (!s) return <p className="muted">Đang tạo khóa…</p>;
  return (
    <form onSubmit={go}>
      <ol className="steps">
        <li>Cài ứng dụng xác thực (Google Authenticator, Microsoft Authenticator, Authy…).</li>
        <li>Quét mã QR bên dưới, hoặc nhập khóa thủ công: <code className="secret">{s.secret}</code></li>
        <li>Nhập mã 6 số hiện trên ứng dụng để xác nhận.</li>
      </ol>
      <Qr text={s.otpauth_uri} />
      <Field label="Mã xác thực (6 số)" required><input name="c" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} required autoFocus /></Field>
      <button className="btn primary">Bật xác thực 2 lớp</button>
    </form>
  );
}

function MfaPanel({ user, onChanged }) {
  const act = useAct();
  const [enrolling, setEnrolling] = useState(false);
  if (user.mfa_enabled) {
    const off = async (e) => {
      e.preventDefault();
      const f = e.currentTarget.elements;
      const r = await act(() => api("POST", "/auth/mfa/disable", { password: f.p.value, code: f.c.value.replace(/\s/g, "") }), "Đã tắt xác thực 2 lớp");
      if (r?.access_token) { setToken(r.access_token); onChanged(r.user); }
    };
    return (
      <>
        <Banner tone="ok">Xác thực 2 lớp <b>đang bật</b> cho tài khoản của bạn.</Banner>
        {user.mfa_required ? <p className="muted sm">Vai trò của bạn bắt buộc dùng xác thực 2 lớp nên không thể tắt. Mất thiết bị? Liên hệ quản trị viên để đặt lại.</p> : (
          <form onSubmit={off}>
            <p className="muted sm">Để tắt, nhập mật khẩu và một mã xác thực hiện tại.</p>
            <div className="grid2"><Field label="Mật khẩu" required><input name="p" type="password" autoComplete="current-password" required /></Field>
              <Field label="Mã xác thực" required><input name="c" inputMode="numeric" maxLength={7} required /></Field></div>
            <button className="btn danger">Tắt xác thực 2 lớp</button>
          </form>
        )}
      </>
    );
  }
  return enrolling ? <MfaEnroll onDone={(r) => onChanged(r.user)} /> : (
    <>
      <Banner tone={user.mfa_required ? "warn" : "info"}>Xác thực 2 lớp {user.mfa_required ? "là bắt buộc với vai trò của bạn" : "chưa bật"}. Bật để bảo vệ tài khoản khi mật khẩu bị lộ.</Banner>
      <button className="btn primary" onClick={() => setEnrolling(true)}>Bật xác thực 2 lớp</button>
    </>
  );
}

/** Hộp thoại tài khoản tự phục vụ. */
export function AccountDialog({ user, onClose, onUserChange }) {
  const [tab, setTab] = useState("pwd");
  return (
    <Modal title="Tài khoản của tôi" onClose={onClose}>
      <p style={{ marginTop: 0 }}><b>{user.full_name}</b> · {user.username} {user.mfa_enabled && <Badge tone="ok">MFA bật</Badge>}</p>
      <Tabs value={tab} onChange={setTab} items={[{ id: "pwd", label: "Đổi mật khẩu" }, { id: "mfa", label: "Xác thực 2 lớp" }]} />
      <div style={{ marginTop: 14 }}>
        {tab === "pwd" ? <PasswordForm onDone={onClose} /> : <MfaPanel user={user} onChanged={(u) => onUserChange(u)} />}
      </div>
    </Modal>
  );
}

/** Màn hình chặn: bắt buộc đổi mật khẩu / đăng ký MFA trước khi vào hệ thống. */
export function SecurityGate({ requires, user, onProgress, onLogout }) {
  return (
    <main className="login">
      <div className="card" style={{ maxWidth: 460 }}><div className="cb">
        <div className="logo"><Icon n="shield" size={26} /></div>
        <h1 style={{ fontSize: 20 }}>{requires === "password_change" ? "Đổi mật khẩu lần đầu" : "Bật xác thực 2 lớp"}</h1>
        <p className="muted" style={{ marginTop: 0 }}>{user.full_name} · {user.username}</p>
        {requires === "password_change" ? <PasswordForm forced onDone={(r) => onProgress(r.user, r.requires)} /> : <MfaEnroll onDone={(r) => onProgress(r.user, r.requires)} />}
        <button className="btn ghost sm" style={{ marginTop: 14 }} onClick={onLogout}>Đăng xuất</button>
      </div></div>
    </main>
  );
}
