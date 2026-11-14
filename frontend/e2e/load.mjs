// Kiểm thử tải: N người dùng ảo (nhiều vai trò) thao tác nghiệp vụ thật đồng thời trong DURATION giây.
// Đo p50/p95/p99 theo loại yêu cầu, tỷ lệ lỗi, và kiểm tra: không mất/trùng dữ liệu, chuỗi nhật ký toàn vẹn.
// Chạy: BASE=http://localhost:8000 USERS=30 DURATION=40 node e2e/load.mjs   (nên dùng CSDL thử, KHÔNG dùng dữ liệu thật)
const BASE = process.env.BASE || "http://localhost:8000";
const USERS = +(process.env.USERS || 30), DURATION = +(process.env.DURATION || 40) * 1000;
const PASS = "Phms@2026dev";
const uniq = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 5);

const lat = {}; const errs = {}; let total = 0;
async function call(tok, name, method, path, body) {
  const t0 = performance.now();
  let status = 0;
  try {
    const r = await fetch(`${BASE}/api${path}`, { method, headers: { "content-type": "application/json", authorization: `Bearer ${tok}` }, body: body ? JSON.stringify(body) : undefined });
    status = r.status; const data = await r.json().catch(() => null);
    (lat[name] ||= []).push(performance.now() - t0); total++;
    if (status >= 400) (errs[`${name} -> ${status}`] ||= 0), errs[`${name} -> ${status}`]++;
    return { status, data };
  } catch (e) { (errs[`${name} -> ${e.cause?.code || e.message}`] ||= 0), errs[`${name} -> ${e.cause?.code || e.message}`]++; (lat[name] ||= []).push(performance.now() - t0); total++; return { status: 0 }; }
}
const login = async (u) => (await (await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: u, password: PASS }) })).json()).access_token;
const tok = Object.fromEntries(await Promise.all(["officer1", "nurse1", "doctor1", "pharm1", "manager1", "approver1", "admin"].map(async (u) => [u, await login(u)])));
const pct = (a, p) => a.slice().sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(a.length * p))];

const created = { persons: 0, encounters: 0, obs: 0, referrals: 0 };
const persons = [];
async function officer(id) {                       // tiếp nhận người mới liên tục
  const end = Date.now() + DURATION;
  while (Date.now() < end) {
    const p = await call(tok.officer1, "POST /persons", "POST", "/persons", { full_name: `Tải ${id} ${uniq()}`, date_of_birth: "1990-01-01", source_system: "QLPN", external_id: `LOAD-${id}-${uniq()}` });
    if (p.status === 201) { created.persons++; const s = await call(tok.officer1, "POST /persons/{id}/stays", "POST", `/persons/${p.data.id}/stays`, {}); if (s.status === 201) persons.push(p.data.id); }
    await call(tok.officer1, "GET /persons?q", "GET", `/persons?q=${encodeURIComponent("Tải")}`);
  }
}
async function doctor(id) {                        // khám: tạo lượt khám, sinh hiệu, chẩn đoán, hoàn tất
  const end = Date.now() + DURATION;
  while (Date.now() < end) {
    const pid = persons[Math.floor(Math.random() * persons.length)];
    if (!pid) { await new Promise((r) => setTimeout(r, 200)); continue; }
    const e = await call(tok.doctor1, "POST /encounters", "POST", "/encounters", { person_id: pid, type: "ad_hoc", reason: "Tải" });
    if (e.status !== 200 && e.status !== 201) continue;
    created.encounters++;
    await call(tok.doctor1, "POST /encounters/{id}/transition", "POST", `/encounters/${e.data.id}/transition`, { to: "in_progress" });
    for (const [t, v, u] of [["Mạch", "78", "lần/phút"], ["Huyết áp tâm thu", "125", "mmHg"]]) { const o = await call(tok.nurse1, "POST /observations", "POST", `/encounters/${e.data.id}/observations`, { type: t, value: v, unit: u }); if (o.status === 201) created.obs++; }
    await call(tok.doctor1, "POST /diagnoses", "POST", `/encounters/${e.data.id}/diagnoses`, { text: "Khám tải", kind: "final" });
    await call(tok.doctor1, "GET /encounters/{id}", "GET", `/encounters/${e.data.id}`);
    await call(tok.doctor1, "POST transition completed", "POST", `/encounters/${e.data.id}/transition`, { to: "completed" });
  }
}
async function viewer(name, user, paths) {          // người xem: bảng điều khiển, danh sách, thông báo, báo cáo
  const end = Date.now() + DURATION; let i = 0;
  while (Date.now() < end) { const p = paths[i++ % paths.length]; await call(tok[user], `GET ${p.split("?")[0]}`, "GET", p); await new Promise((r) => setTimeout(r, 50)); }
}
const jobs = [];
const n = (k) => Math.max(1, Math.round(USERS * k));
for (let i = 0; i < n(0.2); i++) jobs.push(officer(i));
for (let i = 0; i < n(0.3); i++) jobs.push(doctor(i));
for (let i = 0; i < n(0.1); i++) jobs.push(viewer("dash", "doctor1", ["/dashboard", "/encounters?open_only=true&limit=100", "/medication-orders?status=active&limit=100"]));
for (let i = 0; i < n(0.1); i++) jobs.push(viewer("nurse", "nurse1", ["/notifications/poll?after_seq=0", "/appointments?limit=100", "/alerts"]));
for (let i = 0; i < n(0.1); i++) jobs.push(viewer("mgr", "manager1", ["/reports/encounters", "/reports/checkups", "/dashboard", "/notifications"]));
for (let i = 0; i < n(0.1); i++) jobs.push(viewer("pharm", "pharm1", ["/dispense-queue", "/dashboard"]));
for (let i = 0; i < n(0.1); i++) jobs.push(viewer("admin", "admin", ["/audit?limit=50", "/users", "/dashboard"]));
const t0 = Date.now();
await Promise.all(jobs);
const secs = (Date.now() - t0) / 1000;

console.log(`\n== Kiểm thử tải: ${jobs.length} người dùng ảo · ${secs.toFixed(0)}s · ${total} yêu cầu · ${(total / secs).toFixed(0)} req/s`);
console.log("   loại yêu cầu".padEnd(44), "SL".padStart(6), "p50".padStart(7), "p95".padStart(7), "p99".padStart(7), "max".padStart(7));
for (const [k, a] of Object.entries(lat).sort((x, y) => y[1].length - x[1].length))
  console.log("  ", k.padEnd(42), String(a.length).padStart(6), pct(a, 0.5).toFixed(0).padStart(6) + "ms", pct(a, 0.95).toFixed(0).padStart(6) + "ms", pct(a, 0.99).toFixed(0).padStart(6) + "ms", Math.max(...a).toFixed(0).padStart(6) + "ms");
const all = Object.values(lat).flat();
console.log(`   TỔNG: p50 ${pct(all, 0.5).toFixed(0)}ms · p95 ${pct(all, 0.95).toFixed(0)}ms · p99 ${pct(all, 0.99).toFixed(0)}ms`);
console.log("   Lỗi:", Object.keys(errs).length ? errs : "không có");

// ---- đối chiếu dữ liệu & chuỗi nhật ký
const verify = await (await fetch(`${BASE}/api/audit/verify`, { headers: { authorization: `Bearer ${tok.admin}` } })).json();
const encs = await (await fetch(`${BASE}/api/encounters?limit=500&status=completed`, { headers: { authorization: `Bearer ${tok.doctor1}` } })).json();
console.log(`   Đã tạo: ${created.persons} hồ sơ, ${created.encounters} lượt khám, ${created.obs} sinh hiệu`);
console.log(`   Chuỗi nhật ký: ${JSON.stringify(verify)}`);
let bad = 0;
const hard = Object.entries(errs).filter(([k]) => !/-> (409|422)$/.test(k) && !/->\s*4\d\d$/.test(k));   // 4xx nghiệp vụ không tính là lỗi hệ thống
if (hard.length) { console.log("   ✗ có lỗi hệ thống/kết nối:", hard); bad++; }
if (!verify.ok) { console.log("   ✗ chuỗi nhật ký bị đứt dưới tải"); bad++; }
if (pct(all, 0.95) > 3000) { console.log("   ✗ p95 vượt 3s (NFR-01)"); bad++; }
console.log(bad ? "  → KHÔNG ĐẠT" : "  → ĐẠT (không lỗi hệ thống, p95 ≤ 3s, chuỗi nhật ký toàn vẹn)");
process.exit(bad ? 1 : 0);
