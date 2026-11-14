// M11 – Người dùng, phân quyền, danh mục, nhật ký kiểm toán, tác vụ nền.
import { useState } from "react";
import { api, qs } from "../api";
import { PERM_LABEL, ROLE_LABEL } from "../labels";
import { Badge, Banner, Card, DataTable, Empty, Field, Form, FormModal, Modal, PageHeader, Seg, Status, Tabs, fmtDT, useApp, useAct, useAuth, useLoad } from "../ui.jsx";

function ResetPassword({ u, onClose }) {
  const act = useAct();
  const [res, setRes] = useState(null);
  const run = async (d) => { const r = await act(() => api("POST", `/users/${u.id}/reset-password`, d.new_password ? { new_password: d.new_password } : {})); if (r?.temporary_password) setRes(r); return false; };
  if (res) {
    return (
      <Modal title={`Mật khẩu tạm – ${u.username}`} onClose={onClose} footer={<button className="btn primary" onClick={onClose}>Đã ghi lại, đóng</button>}>
        <Banner tone="warn">Mật khẩu này <b>chỉ hiện một lần</b>. Chuyển cho người dùng qua kênh an toàn. Họ bị buộc đổi ngay ở lần đăng nhập đầu; mọi phiên cũ đã bị thu hồi.</Banner>
        <p><code className="secret" style={{ fontSize: 18 }}>{res.temporary_password}</code></p>
        <button className="btn sm" onClick={() => navigator.clipboard?.writeText(res.temporary_password)}>Sao chép</button>
      </Modal>
    );
  }
  return (
    <FormModal title={`Đặt lại mật khẩu – ${u.username}`} onClose={onClose} submit="Đặt lại" onSubmit={run}>
      <p style={{ marginTop: 0 }}>Người dùng sẽ bị thu hồi mọi phiên và <b>phải đổi mật khẩu</b> khi đăng nhập lại.</p>
      <Field label="Mật khẩu tạm" hint="Bỏ trống để hệ thống sinh ngẫu nhiên (khuyến nghị)"><input name="new_password" type="text" autoComplete="off" /></Field>
    </FormModal>
  );
}

function Users() {
  const act = useAct();
  const { confirm } = useApp();
  const { data, reload } = useLoad(() => api("GET", "/users"), []);
  const { data: facs } = useLoad(() => api("GET", "/facilities"), []);
  const [m, setM] = useState(null);
  const code = (id) => facs?.find((f) => f.id === id)?.code || "—";
  return (
    <Card title="Tài khoản" actions={<button className="btn primary sm" onClick={() => setM({ t: "new" })}>+ Tạo người dùng</button>} flat>
      <DataTable rows={data} columns={[{ h: "Tài khoản", c: (u) => <b>{u.username}</b> }, { h: "Họ tên", c: (u) => u.full_name }, { h: "Vai trò", c: (u) => ROLE_LABEL[u.role] || u.role }, { h: "Cơ sở", c: (u) => code(u.facility_id) },
        { h: "Trạng thái", c: (u) => <>{u.active ? <Badge tone="ok">Hoạt động</Badge> : <Badge tone="bad">Đã khóa</Badge>}{u.must_change_password && <Badge tone="warn">Chờ đổi mật khẩu</Badge>}</> },
        { h: "MFA", c: (u) => (u.mfa_enabled ? <Badge tone="ok">Bật</Badge> : u.mfa_required ? <Badge tone="warn">Bắt buộc – chưa bật</Badge> : <span className="muted">—</span>) },
        { h: "", c: (u) => <div className="row"><button className="btn sm" onClick={() => setM({ t: "role", u })}>Đổi vai trò</button>
          <button className="btn sm" onClick={() => setM({ t: "reset", u })}>Đặt lại mật khẩu</button>
          {u.mfa_enabled && <button className="btn sm" onClick={async () => { if (await confirm({ title: "Đặt lại MFA", message: `Xóa xác thực 2 lớp của ${u.username}? Người dùng sẽ phải đăng ký lại thiết bị${u.mfa_required ? " ở lần đăng nhập kế tiếp" : ""}. Mọi phiên đang đăng nhập bị thu hồi. Chỉ làm khi đã xác minh đúng người yêu cầu.` }) && await act(() => api("POST", `/users/${u.id}/reset-mfa`), "Đã đặt lại MFA")) reload(); }}>Đặt lại MFA</button>}
          <button className="btn sm" onClick={async () => { if (await confirm({ message: `${u.active ? "Khóa" : "Mở khóa"} tài khoản ${u.username}? Phiên đăng nhập hiện tại sẽ bị thu hồi.` }) && await act(() => api("PATCH", `/users/${u.id}`, { active: !u.active }), "Đã cập nhật")) reload(); }}>{u.active ? "Khóa" : "Mở khóa"}</button></div> }]} />
      {m?.t === "new" && (
        <FormModal title="Tạo người dùng" onClose={() => setM(null)} onSubmit={async (d) => { const r = await act(() => api("POST", "/users", d), "Đã tạo tài khoản"); if (r) reload(); return !!r; }}>
          <div className="grid2"><Field label="Tên đăng nhập" required><input name="username" required minLength={3} /></Field><Field label="Họ tên" required><input name="full_name" required /></Field>
            <Field label="Vai trò" required><select name="role" required>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Cơ sở" hint="Bắt buộc với vai trò nghiệp vụ"><select name="facility_id" defaultValue=""><option value="">—</option>{(facs || []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field></div>
          <Field label="Mật khẩu ban đầu" required hint="Tối thiểu 10 ký tự, có chữ hoa, chữ thường và số"><input type="password" name="password" required autoComplete="new-password" /></Field>
        </FormModal>
      )}
      {m?.t === "reset" && <ResetPassword u={m.u} onClose={() => { setM(null); reload(); }} />}
      {m?.t === "role" && (
        <FormModal title={`Đổi vai trò – ${m.u.username}`} onClose={() => setM(null)} onSubmit={async (d) => { const r = await act(() => api("PATCH", `/users/${m.u.id}`, d), "Đã cập nhật"); if (r) reload(); return !!r; }}>
          <Field label="Vai trò" required><select name="role" defaultValue={m.u.role}>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Cơ sở"><select name="facility_id" defaultValue={m.u.facility_id || ""}><option value="">—</option>{(facs || []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select></Field>
        </FormModal>
      )}
    </Card>
  );
}

function Matrix() {
  const { data } = useLoad(() => api("GET", "/roles"), []);
  if (!data) return null;
  const roles = Object.keys(data);
  const perms = [...new Set(Object.values(data).flat())].sort();
  return (
    <>
      <Banner tone="info"><span className="sm">Phân quyền kết hợp vai trò (RBAC) và phạm vi cơ sở/quan hệ điều trị (ABAC). <b>Quản trị hệ thống không có quyền đọc dữ liệu lâm sàng.</b> Quyết định chuyên môn (bác sĩ) tách khỏi duyệt hành chính (người phê duyệt).</span></Banner>
      <Card flat><div className="tblwrap"><table className="tbl matrix"><thead><tr><th>Quyền</th>{roles.map((r) => <th key={r}>{ROLE_LABEL[r]}</th>)}</tr></thead>
        <tbody>{perms.map((p) => <tr key={p}><td>{PERM_LABEL[p] || p}<div className="muted sm">{p}</div></td>{roles.map((r) => <td key={r}>{data[r].includes(p) ? <Badge tone="ok">✓</Badge> : <span className="muted">·</span>}</td>)}</tr>)}</tbody></table></div></Card>
    </>
  );
}

function Catalog() {
  const act = useAct();
  const [cat, setCat] = useState("drug");
  const [m, setM] = useState(null);
  const { data, reload } = useLoad(() => api("GET", `/catalogs/${cat}`), [cat]);
  return (
    <>
      <div className="row" style={{ marginBottom: 14 }}><Seg value={cat} onChange={setCat} items={[{ id: "drug", label: "Thuốc" }, { id: "icd", label: "Chẩn đoán (ICD)" }, { id: "unit", label: "Đơn vị đo" }]} />
        <button className="btn primary right" onClick={() => setM({})}>+ Thêm / cập nhật</button></div>
      <Card flat><DataTable rows={data} empty={<Empty title="Danh mục trống" />} columns={[{ h: "Mã", c: (i) => <code>{i.code}</code> }, { h: "Tên", c: (i) => i.name }, { h: "Phiên bản", c: (i) => <Badge>v{i.version}</Badge> }, { h: "", c: (i) => <button className="btn sm" onClick={() => setM(i)}>Cập nhật</button> }]} /></Card>
      <p className="muted sm">Danh mục có phiên bản: cập nhật tạo phiên bản mới, bản cũ được giữ để truy vết.</p>
      {m && <FormModal title={m.code ? `Cập nhật ${m.code}` : "Thêm mục danh mục"} onClose={() => setM(null)} onSubmit={async (d) => { const r = await act(() => api("POST", "/catalogs", { catalog: cat, ...d }), "Đã lưu (phiên bản mới)"); if (r) reload(); return !!r; }}>
        <Field label="Mã" required><input name="code" defaultValue={m.code} readOnly={!!m.code} required /></Field><Field label="Tên" required><input name="name" defaultValue={m.name} required /></Field></FormModal>}
    </>
  );
}

function AuditLog() {
  const act = useAct();
  const [f, setF] = useState({});
  const [applied, setApplied] = useState({});
  const { data, loading } = useLoad(() => api("GET", "/audit" + qs({ ...applied, limit: 300 })), [applied]);
  const [v, setV] = useState(null);
  return (
    <>
      <Card><div className="row" style={{ alignItems: "end" }}>
        <Form className="row" keep onSubmit={(d) => { setApplied(d); return true; }}>
          <Field label="Người thực hiện"><input name="actor" placeholder="tên đăng nhập" /></Field><Field label="Hành động"><input name="action" placeholder="vd: break_glass" /></Field><Field label="Mã hồ sơ (person_id)"><input name="person_id" /></Field>
          <div style={{ marginBottom: 12 }}><button className="btn primary">Lọc</button></div>
        </Form>
        <div className="right" style={{ marginBottom: 12 }}><button className="btn" onClick={async () => { const r = await act(() => api("GET", "/audit/verify")); if (r && r !== true) setV(r); }}>Kiểm tra toàn vẹn chuỗi nhật ký</button></div>
      </div>
        {v && (v.ok ? <Banner tone="ok">Chuỗi nhật ký toàn vẹn ({v.checked} bản ghi).</Banner> : <Banner tone="bad">PHÁT HIỆN SỬA ĐỔI tại bản ghi #{v.broken_at_seq}.</Banner>)}</Card>
      <Card flat><DataTable rows={data} loading={loading} empty={<Empty title="Không có bản ghi" />}
        columns={[{ h: "Thời gian", c: (a) => fmtDT(a.at) }, { h: "Người", c: (a) => a.actor_name || "—" }, { h: "Hành động", c: (a) => <code>{a.action}</code> }, { h: "Đối tượng", c: (a) => a.object_type || "—" }, { h: "Kết quả", c: (a) => <Status d="result" v={a.result} /> }, { h: "Lý do / chi tiết", c: (a) => <span className="sm">{a.reason || ""}</span> }, { h: "IP", c: (a) => <span className="muted sm">{a.source_ip}</span> }]} /></Card>
    </>
  );
}

function Jobs() {
  const act = useAct();
  const [out, setOut] = useState(null);
  return (
    <Card title="Tác vụ nền (scheduler)">
      <p style={{ marginTop: 0 }}>Hệ thống tự chạy định kỳ: chuyển lịch “đến hạn”, sinh cảnh báo lịch quá hạn (không trùng), sinh lịch cho kế hoạch theo dõi, nâng mức cảnh báo chưa xử lý.</p>
      <button className="btn primary" onClick={async () => { const r = await act(() => api("POST", "/scheduler/run"), "Đã chạy"); if (r && r !== true) setOut(r); }}>Chạy ngay</button>
      {out && <div className="kpis mt">{Object.entries({ marked_due: "Lịch chuyển đến hạn", overdue_alerts: "Cảnh báo quá hạn mới", care_plan_tasks: "Lịch kế hoạch mới", escalated: "Cảnh báo được nâng mức", postponed_out_of_scope: "Lịch hoãn (người đã chuyển)" }).map(([k, l]) => <div key={k} className="kpi" style={{ cursor: "default" }}><b>{out[k]}</b><span>{l}</span></div>)}</div>}
    </Card>
  );
}

export default function Admin() {
  const { has } = useAuth();
  const [tab, setTab] = useState(has("user.manage") ? "users" : "audit");
  return (
    <>
      <PageHeader title="Quản trị hệ thống" sub="M11 · Người dùng, phân quyền, danh mục và nhật ký kiểm toán. Không có quyền xem nội dung bệnh án." />
      <Tabs value={tab} onChange={setTab} items={[has("user.manage") && { id: "users", label: "Người dùng" }, has("user.manage") && { id: "roles", label: "Ma trận phân quyền" }, has("catalog.write") && { id: "catalog", label: "Danh mục" },
        has("audit.read") && { id: "audit", label: "Nhật ký kiểm toán" }, has("scheduler.run") && { id: "jobs", label: "Tác vụ nền" }]} />
      {tab === "users" && <Users />}{tab === "roles" && <Matrix />}{tab === "catalog" && <Catalog />}{tab === "audit" && <AuditLog />}{tab === "jobs" && <Jobs />}
    </>
  );
}
