// Tranh chấp trên cấu hình production-like: PostgreSQL + 4 worker. Chỉ dùng API.
import { api, ok, newPerson, startEnc, confirmedRx } from "./uat-lib.mjs";
const par = (n, f) => Promise.all(Array.from({ length: n }, (_, i) => f(i)));
const U = Date.now().toString(36).slice(-5); const out = [];
// DEF-02: 5 lần x 8 yêu cầu đồng thời tạo khám ban đầu
for (let t = 0; t < 5; t++) { const p = await newPerson(`PG Race Initial ${t} ${U}`); const r = await par(8, () => api("doctor1", "POST", "/encounters", { person_id: p.id, type: "initial", reason: "khám" }));
  const n = (await ok("doctor1", "GET", `/persons/${p.id}/encounters`)).filter((e) => e.type === "initial" && e.status !== "cancelled").length; out.push(`DEF-02 lần ${t + 1}: ${r.filter((x) => x.status === 201).length}×201, ${r.filter((x) => x.status === 409).length}×409 → ${n} khám ban đầu`); if (n !== 1) out.push("  ✗ SAI"); }
// DEF-03: confirm / revise / approve / ack
const p = await newPerson(`PG Race Rx ${U}`); const e = await startEnc(p.id);
const o = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1 viên", route: "uống", frequency: "2 lần/ngày", start_date: new Date().toISOString().slice(0, 10), duration_days: 15, quantity_prescribed: 30 });
let r = await par(6, () => api("doctor1", "POST", `/medication-orders/${o.id}/confirm`, {})); out.push(`confirm ×6: ${r.map((x) => x.status).join(",")}`);
const ev1 = (await ok("admin", "GET", `/audit?action=medication_order_confirmed&person_id=${p.id}`)).length; out.push(`  audit confirmed = ${ev1} ${ev1 === 1 ? "" : "✗ SAI"}`);
r = await par(6, () => api("doctor1", "POST", `/medication-orders/${o.id}/revise`, { reason: "Đổi liều", dose: "2 viên" })); out.push(`revise ×6: ${r.map((x) => x.status).join(",")}`);
const ref = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { reason: "Cần chụp CT ngoài", destination: "BV A" }); await ok("doctor1", "PATCH", `/referrals/${ref.id}/status`, { to: "pending" });
r = await par(6, () => api("approver1", "PATCH", `/referrals/${ref.id}/status`, { to: "coordinated", destination: "BV A" })); out.push(`approve ×6: ${r.map((x) => x.status).join(",")}`);
const rr = await ok("approver1", "GET", `/referrals/${ref.id}`); const nc = rr.events.filter((x) => x.to_status === "coordinated").length; out.push(`  sự kiện coordinated = ${nc} ${nc === 1 ? "" : "✗ SAI"}`);
const al = await ok("nurse1", "GET", "/alerts"); const a = al.find((x) => x.status === "new");
if (a) { r = await par(6, () => api("nurse1", "POST", `/alerts/${a.id}/acknowledge`)); out.push(`ack ×6: ${r.map((x) => x.status).join(",")}`); } else out.push("ack: (không có cảnh báo mới để thử)");
console.log(out.join("\n"));
