// Kiểm thử chạy dài (soak): tải ổn định trong nhiều phút/giờ, đo theo từng cửa sổ thời gian để phát hiện
// suy giảm hiệu năng, tăng lỗi, rò rỉ bộ nhớ máy chủ; cuối cùng kiểm tra chuỗi nhật ký và đối chiếu số bản ghi.
// Chạy: BASE=http://localhost:8000 USERS=20 MINUTES=60 WINDOW=60 node e2e/soak.mjs     (dùng CSDL THỬ, không dùng dữ liệu thật)
// Bộ nhớ máy chủ: tự tìm PID theo cổng của BASE (lsof) hoặc đặt SERVER_PID.
import { execSync } from "node:child_process";

const BASE = process.env.BASE || "http://localhost:8000";
const USERS = +(process.env.USERS || 20), MINUTES = +(process.env.MINUTES || 10), WINDOW = +(process.env.WINDOW || 60) * 1000;
const PASS = "Phms@2026dev";
const uniq = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
const pct = (a, p) => (a.length ? a.slice().sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(a.length * p))] : 0);

const login = async (u) => (await (await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: u, password: PASS }) })).json()).access_token;
const names = ["officer1", "nurse1", "doctor1", "pharm1", "manager1", "approver1", "admin"];
let tok = Object.fromEntries(await Promise.all(names.map(async (u) => [u, await login(u)])));

let win = { lat: [], err: {}, n: 0 };
const created = { persons: 0, encounters: 0, obs: 0 };
async function call(user, method, path, body) {
  const t0 = performance.now();
  try {
    const r = await fetch(`${BASE}/api${path}`, { method, headers: { "content-type": "application/json", authorization: `Bearer ${tok[user]}` }, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => null);
    win.lat.push(performance.now() - t0); win.n++;
    if (r.status >= 500 || (r.status >= 400 && ![404, 409, 422].includes(r.status))) win.err[`${method} ${path.split("?")[0].replace(/[0-9a-f-]{36}/g, ":id")} -> ${r.status}`] = (win.err[`${method} ${path.split("?")[0].replace(/[0-9a-f-]{36}/g, ":id")} -> ${r.status}`] || 0) + 1;
    return { status: r.status, data };
  } catch (e) { win.n++; win.lat.push(performance.now() - t0); const k = `network ${e.cause?.code || e.message}`; win.err[k] = (win.err[k] || 0) + 1; return { status: 0 }; }
}
const pids = () => { try { return process.env.SERVER_PID ? [process.env.SERVER_PID] : execSync(`lsof -ti tcp:${new URL(BASE).port || 80} -sTCP:LISTEN`).toString().trim().split("\n"); } catch { return []; } };
const rssMB = () => { try { return pids().reduce((s, p) => s + +execSync(`ps -o rss= -p ${p}`).toString().trim() / 1024, 0); } catch { return NaN; } };

const persons = [];
const end = Date.now() + MINUTES * 60000;
async function officer(id) {
  while (Date.now() < end) {
    const p = await call("officer1", "POST", "/persons", { full_name: `Soak ${id} ${uniq()}`, date_of_birth: "1990-01-01", source_system: "QLPN", external_id: `SOAK-${id}-${uniq()}` });
    if (p.status === 201) { created.persons++; const s = await call("officer1", "POST", `/persons/${p.data.id}/stays`, {}); if (s.status === 201) persons.push(p.data.id); }
    await call("officer1", "GET", `/persons?q=${encodeURIComponent("Soak")}&limit=20`);
    await new Promise((r) => setTimeout(r, 150));
  }
}
async function doctor() {
  while (Date.now() < end) {
    const pid = persons[Math.floor(Math.random() * persons.length)];
    if (!pid) { await new Promise((r) => setTimeout(r, 300)); continue; }
    const e = await call("doctor1", "POST", "/encounters", { person_id: pid, type: "ad_hoc", reason: "Soak" });
    if (e.status !== 201) continue;
    created.encounters++;
    await call("doctor1", "POST", `/encounters/${e.data.id}/transition`, { to: "in_progress" });
    const o = await call("nurse1", "POST", `/encounters/${e.data.id}/observations`, { type: "Mạch", value: String(60 + Math.floor(Math.random() * 40)), unit: "lần/phút" });
    if (o.status === 201) created.obs++;
    await call("doctor1", "POST", `/encounters/${e.data.id}/diagnoses`, { text: "Soak", kind: "final" });
    await call("doctor1", "POST", `/encounters/${e.data.id}/transition`, { to: "completed" });
    await new Promise((r) => setTimeout(r, 200));
  }
}
async function viewer(user, paths) {
  let i = 0;
  while (Date.now() < end) { await call(user, "GET", paths[i++ % paths.length]); await new Promise((r) => setTimeout(r, 120)); }
}
// token sống 30 phút mặc định: làm mới định kỳ (nền, không chặn kết thúc) để chạy được hàng giờ
const refresh = setInterval(async () => { try { tok = Object.fromEntries(await Promise.all(names.map(async (u) => [u, await login(u)]))); } catch { /* thử lại ở vòng sau */ } }, 15 * 60000);

const k = (f) => Math.max(1, Math.round(USERS * f));
const jobs = [];
for (let i = 0; i < k(0.15); i++) jobs.push(officer(i));
for (let i = 0; i < k(0.3); i++) jobs.push(doctor());
for (let i = 0; i < k(0.15); i++) jobs.push(viewer("doctor1", ["/dashboard", "/encounters?open_only=true&limit=100", "/medication-orders?status=active&limit=100"]));
for (let i = 0; i < k(0.15); i++) jobs.push(viewer("nurse1", ["/notifications/poll?after_seq=0", "/appointments?limit=100", "/alerts"]));
for (let i = 0; i < k(0.1); i++) jobs.push(viewer("manager1", ["/reports/encounters", "/reports/checkups", "/dashboard"]));
for (let i = 0; i < k(0.1); i++) jobs.push(viewer("admin", ["/audit?limit=50", "/users"]));

console.log(`\n== Soak: ${jobs.length} người dùng ảo · ${MINUTES} phút · cửa sổ ${WINDOW / 1000}s · máy chủ PID ${pids().join(",") || "?"}`);
console.log("  phút   yêu cầu  req/s    p50    p95    p99    lỗi   RSS máy chủ");
const rows = [];
const t0 = Date.now();
const tick = setInterval(() => {
  const w = win; win = { lat: [], err: {}, n: 0 };
  const row = { min: (Date.now() - t0) / 60000, n: w.n, rps: w.n / (WINDOW / 1000), p50: pct(w.lat, 0.5), p95: pct(w.lat, 0.95), p99: pct(w.lat, 0.99), errs: Object.values(w.err).reduce((a, b) => a + b, 0), errMap: w.err, rss: rssMB() };
  rows.push(row);
  console.log(`  ${row.min.toFixed(1).padStart(5)} ${String(row.n).padStart(8)} ${row.rps.toFixed(0).padStart(6)} ${row.p50.toFixed(0).padStart(5)}ms ${row.p95.toFixed(0).padStart(5)}ms ${row.p99.toFixed(0).padStart(5)}ms ${String(row.errs).padStart(6)} ${Number.isNaN(row.rss) ? "   ?" : row.rss.toFixed(0).padStart(6) + " MB"}`);
}, WINDOW);
await Promise.all(jobs);
clearInterval(tick); clearInterval(refresh);

// ---- đánh giá
const verify = await (await fetch(`${BASE}/api/audit/verify`, { headers: { authorization: `Bearer ${tok.admin}` } })).json();
console.log(`\n  Đã tạo: ${created.persons} hồ sơ, ${created.encounters} lượt khám, ${created.obs} sinh hiệu · chuỗi nhật ký: ${JSON.stringify(verify)}`);
let bad = 0;
const body = rows.slice(1, -1).length >= 2 ? rows.slice(1, -1) : rows;            // bỏ cửa sổ đầu (khởi động) và cuối (rút tải)
const first = body.slice(0, Math.max(1, Math.floor(body.length / 3))), last = body.slice(-Math.max(1, Math.floor(body.length / 3)));
const avg = (a, f) => a.reduce((s, x) => s + x[f], 0) / a.length;
const totalErr = rows.reduce((s, r) => s + r.errs, 0);
console.log(`  p95 đầu → cuối: ${avg(first, "p95").toFixed(0)}ms → ${avg(last, "p95").toFixed(0)}ms · req/s đầu → cuối: ${avg(first, "rps").toFixed(0)} → ${avg(last, "rps").toFixed(0)} · RSS đầu → cuối: ${avg(first, "rss").toFixed(0)} → ${avg(last, "rss").toFixed(0)} MB`);
if (totalErr) { console.log("  ✗ có lỗi hệ thống:", rows.flatMap((r) => Object.entries(r.errMap)).slice(0, 6)); bad++; }
if (!verify.ok) { console.log("  ✗ chuỗi nhật ký đứt"); bad++; }
if (body.length >= 4) {
  if (avg(last, "p95") > Math.max(avg(first, "p95") * 2, 300)) { console.log("  ✗ p95 suy giảm > 2× theo thời gian"); bad++; }
  if (avg(last, "rps") < avg(first, "rps") * 0.6) { console.log("  ✗ thông lượng giảm > 40%"); bad++; }
  if (!Number.isNaN(avg(first, "rss")) && avg(last, "rss") > avg(first, "rss") * 1.5 + 100) { console.log("  ✗ bộ nhớ máy chủ tăng bất thường (nghi rò rỉ)"); bad++; }
}
if (Math.max(...rows.map((r) => r.p95)) > 3000) { console.log("  ✗ có cửa sổ p95 > 3s (NFR-01)"); bad++; }
console.log(bad ? "  → KHÔNG ĐẠT" : "  → ĐẠT (không lỗi, không suy giảm, bộ nhớ ổn định, chuỗi nhật ký toàn vẹn)");
process.exit(bad ? 1 : 0);
