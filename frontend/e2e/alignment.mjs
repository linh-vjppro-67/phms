// E2E các điểm đã rà soát cho khớp luồng: break-glass có hạn, thông tin lâm sàng cần thiết, biên nhận bàn giao.
// Cần CSDL demo MỚI (python -m app.demo --reset).
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS;
const PASS = "Phms@2026dev";
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch();
const errs = [];
let cur;
const step = async (name, fn) => { try { await fn(); console.log("✓", name); } catch (e) { errs.push(`${name}: ${e.message.split("\n")[0]}`); console.log("✗", name, "-", e.message.split("\n")[0]); if (SHOTS && cur) await cur.screenshot({ path: `${SHOTS}/align-FAIL.png` }); throw e; } };
const token = async (u) => (await (await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: u, password: PASS }) })).json()).access_token;

async function login(user) {
  const page = await (await browser.newContext({ bypassCSP: true, viewport: { width: 1440, height: 900 } })).newPage();
  page.on("pageerror", (e) => errs.push(`${user} pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && !/403|409/.test(m.text()) && errs.push(`${user} console: ${m.text()}`));
  await page.goto(BASE);
  await page.fill('input[name="u"]', user); await page.fill('input[name="p"]', PASS);
  await page.click("button.btn.primary"); await page.waitForSelector(".side .nav");
  cur = page;
  return page;
}

try {
  const d2 = await login("doctor2");
  await step("bác sĩ Trại 2 chọn người của Trại 1 -> hộp thoại truy cập khẩn cấp", async () => {
    await d2.click('button:has-text("Chọn người xử lý")');
    await d2.fill('.modal input.search', "Bùi Hữu Lộc");
    await d2.click('.modal tr.click:has-text("Bùi Hữu Lộc")');
    await d2.waitForSelector('.modal-bg:has-text("Truy cập khẩn cấp (break-glass)")');
    if (SHOTS) await d2.screenshot({ path: `${SHOTS}/align-1-breakglass.png` });
  });
  await step("lý do quá ngắn bị từ chối; lý do hợp lệ -> chỉ đọc, có hạn", async () => {
    await d2.fill('.modal textarea[name="reason"]', "gấp");
    await d2.click('.modal footer button:has-text("Xác nhận truy cập khẩn cấp")');
    await d2.waitForTimeout(400);
    if (!(await d2.$('.modal-bg:has-text("Truy cập khẩn cấp (break-glass)")'))) throw new Error("lý do quá ngắn vẫn được chấp nhận");
    await d2.fill('.modal textarea[name="reason"]', "Nghi ngộ độc thuốc, cần tiền sử dị ứng gấp để xử trí");
    await d2.click('.modal footer button:has-text("Xác nhận truy cập khẩn cấp")');
    await d2.waitForSelector('.pctx .badge:has-text("Truy cập khẩn cấp (chỉ đọc) đến")');
    if (SHOTS) await d2.screenshot({ path: `${SHOTS}/align-2-granted.png` });
  });
  await step("xem được hồ sơ sức khỏe (giao diện) nhưng máy chủ từ chối mọi thao tác GHI ở cơ sở khác", async () => {
    await d2.click('.side .nav:has-text("Hồ sơ sức khỏe")');
    await d2.waitForSelector('.tabs button:has-text("Lịch sử khám")');
    await d2.click('.tabs button:has-text("Lịch sử khám")');
    await d2.waitForSelector("tbody tr.click");
    const t = await token("doctor2"), h = { "content-type": "application/json", authorization: `Bearer ${t}` };
    const p = (await (await fetch(`${BASE}/api/persons?q=${encodeURIComponent("Bùi Hữu Lộc")}`, { headers: h })).json())[0];
    const g = await (await fetch(`${BASE}/api/persons/${p.id}/break-glass`, { headers: h })).json();
    if (!g.active) throw new Error("quyền khẩn cấp không còn hiệu lực");
    const encs = await (await fetch(`${BASE}/api/persons/${p.id}/encounters`, { headers: h })).json();
    const w = await fetch(`${BASE}/api/encounters/${encs[0].id}/observations`, { method: "POST", headers: h, body: JSON.stringify({ type: "Mạch", value: "80", unit: "lần/phút" }) });
    if (w.status !== 403) throw new Error(`ghi dữ liệu phải bị từ chối (403) nhưng nhận ${w.status}`);
  });
  await d2.context().close();

  const doc = await login("doctor1");
  await step("bàn làm việc hiện 'Thông tin lâm sàng cần thiết' (dị ứng, thuốc đang dùng, vấn đề mở)", async () => {
    await doc.click('.side .nav:has-text("Khám chữa bệnh")');
    await doc.click('tbody tr.click:has-text("Bùi Ngọc Hùng")').catch(async () => { await doc.click('.seg button:has-text("Tất cả")'); await doc.click('tbody tr.click:has-text("Bùi Ngọc Hùng")'); });
    await doc.waitForSelector('.drawer .card:has-text("Thông tin lâm sàng cần thiết")');
    const txt = await doc.$eval('.drawer .card:has-text("Thông tin lâm sàng cần thiết")', (e) => e.innerText);
    for (const need of ["Aspirin", "Amlodipine", "Tăng huyết áp"]) if (!txt.includes(need)) throw new Error(`thiếu "${need}" trong bảng thông tin lâm sàng`);
    if (SHOTS) await doc.screenshot({ path: `${SHOTS}/align-3-context.png` });
  });
  await doc.context().close();

  const of1 = await login("officer1");
  await step("bàn giao: xác nhận -> 'Chờ cơ sở nhận tiếp nhận' (biên nhận)", async () => {
    await of1.click('.side .nav:has-text("Chuyển trại")');
    await of1.waitForSelector('.card:has-text("Dương Ngọc Nghĩa")');
    await of1.click('.card:has-text("Dương Ngọc Nghĩa") button:has-text("Xác nhận bàn giao")');
    await of1.check('.modal input[name="ack"]');
    await of1.click('.modal footer button:has-text("Xác nhận đã bàn giao")');
    await of1.waitForTimeout(600);
    await of1.click('.seg button:has-text("Chờ cơ sở nhận tiếp nhận")');
    await of1.waitForSelector('.card:has-text("Dương Ngọc Nghĩa"):has-text("Cơ sở nhận tiếp nhận")');
    if (SHOTS) await of1.screenshot({ path: `${SHOTS}/align-4-receipt-wait.png` });
  });
  await step("cơ sở nhận tạo kỳ mới -> phiếu có biên nhận", async () => {
    const t = await token("officer2"), h = { "content-type": "application/json", authorization: `Bearer ${t}` };
    const ps = await (await fetch(`${BASE}/api/persons?q=${encodeURIComponent("Dương Ngọc Nghĩa")}`, { headers: h })).json();
    const r = await fetch(`${BASE}/api/persons/${ps[0].id}/stays`, { method: "POST", headers: h, body: "{}" });
    if (r.status !== 201) throw new Error("không tạo được đợt tiếp nhận ở cơ sở nhận: " + r.status);
    await of1.reload(); await of1.waitForSelector(".side .nav");
    await of1.click('.side .nav:has-text("Chuyển trại")');
    await of1.click('.seg button:has-text("Đã bàn giao")');
    await of1.waitForSelector('.card:has-text("Dương Ngọc Nghĩa"):has-text("biên nhận hoàn tất")');
    if (SHOTS) await of1.screenshot({ path: `${SHOTS}/align-5-receipt-done.png` });
  });
} catch { /* đã in lỗi ở step */ }
await browser.close();
console.log(errs.length ? `\n${errs.length} lỗi:\n- ${errs.join("\n- ")}` : "\nTất cả bước đạt, không có lỗi console.");
process.exit(errs.length ? 1 : 0);
