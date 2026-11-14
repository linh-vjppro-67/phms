// BG-02b: hết hạn truy cập khẩn cấp THẬT – server staging thứ hai (cổng 8767) chạy PHMS_BREAK_GLASS_MINUTES=1, chờ quá hạn rồi kiểm tra.
import { api, ok, tc, must, denied, newPerson, results, closeBrowser } from "./uat-lib.mjs";
const U = Date.now().toString(36).slice(-5);
await tc({ id: "BG-02b", mod: "Truy cập khẩn (D2)", kind: "Boundary", role: "doctor2", title: "Quyền truy cập khẩn cấp TỰ HẾT HẠN: sau khi quá hạn, hồ sơ ngoài cơ sở bị đóng lại (cấu hình 1 phút để kiểm thật)",
  expected: "Trước hạn: đọc được, GET break-glass active=true; sau hạn: 403 FACILITY_SCOPE, active=false", sev: "High" }, async (c) => {
  const p = await newPerson(`UAT Hết Hạn ${U}`);
  denied(await api("doctor2", "GET", `/persons/${p.id}/health-summary`), "trước khi cấp quyền");     // health-summary: danh tính + clinical ẩn nếu ngoài phạm vi?
  const g = await ok("doctor2", "POST", `/persons/${p.id}/break-glass`, { reason: "Nghi ngộ độc thuốc, cần tiền sử dị ứng gấp" });
  const exp = new Date(g.expires_at + (g.expires_at.endsWith("Z") ? "" : "Z")).getTime(); const mins = (exp - Date.now()) / 60000; must(mins <= 1.1 && mins > 0.5, `Hạn cấp = ${mins.toFixed(2)} phút (kỳ vọng ~1)`);
  const before = await api("doctor2", "GET", `/persons/${p.id}/encounters`); must(before.status === 200, `Trước hạn: HTTP ${before.status}`);
  must((await ok("doctor2", "GET", `/persons/${p.id}/break-glass`)).active === true, "active != true trước hạn");
  c.note(`chờ ${Math.ceil((exp - Date.now()) / 1000) + 3}s cho quyền hết hạn`); await new Promise((r) => setTimeout(r, exp - Date.now() + 3000));
  const after = await api("doctor2", "GET", `/persons/${p.id}/encounters`); must(after.status === 403 && after.data?.error?.code === "FACILITY_SCOPE", `Sau hạn: HTTP ${after.status} ${after.data?.error?.code}`);
  must((await ok("doctor2", "GET", `/persons/${p.id}/break-glass`)).active === false, "active != false sau hạn");
  return `Cấp ${mins.toFixed(1)} phút; trước hạn đọc 200; sau hạn 403 FACILITY_SCOPE, active=false`;
});
await closeBrowser(); console.log(results.map((r) => `${r.status} ${r.id} ${r.actual}`).join("\n"));
