// E2E thông báo: không còn số trên thanh bên; chuông + số chưa đọc; thông báo trực tiếp (poll); liên kết sâu;
// đọc/đọc tất cả; cài đặt nhóm; riêng tư giữa các tài khoản. Cần backend đã seed + demo.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS;
const PASS = "Phms@2026dev";
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

const apiToken = async (u) => (await (await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: u, password: PASS }) })).json()).access_token;
const browser = await chromium.launch();
const errs = [];
let current;
const step = async (name, fn) => { try { await fn(); console.log("✓", name); } catch (e) { errs.push(`${name}: ${e.message.split("\n")[0]}`); console.log("✗", name, "-", e.message.split("\n")[0]); if (SHOTS && current) await current.screenshot({ path: `${SHOTS}/notify-FAIL.png` }); throw e; } };

async function login(user) {
  const ctx = await browser.newContext({ bypassCSP: true, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errs.push(`${user} pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && errs.push(`${user} console: ${m.text()}`));
  await page.goto(BASE);
  await page.fill('input[name="u"]', user); await page.fill('input[name="p"]', PASS);
  await page.click("button.btn.primary"); await page.waitForSelector(".side .nav");
  return page;
}
const badge = async (page) => { const el = await page.$(".bellbadge"); return el ? parseInt((await el.textContent()).replace(/\D/g, "") || "0", 10) : 0; };

// Điều kiện đầu vào tự tạo: một người mới tiếp nhận -> nhân viên y tế có thông báo chưa đọc (chạy lặp được)
async function seedUnread() {
  const t = await apiToken("officer1"), h = { "content-type": "application/json", authorization: `Bearer ${t}` };
  const p = await (await fetch(`${BASE}/api/persons`, { method: "POST", headers: h, body: JSON.stringify({ full_name: "Người Thử Thông Báo", source_system: "QLPN", external_id: "E2E-" + Date.now() }) })).json();
  const r = await fetch(`${BASE}/api/persons/${p.id}/stays`, { method: "POST", headers: h, body: JSON.stringify({}) });
  if (r.status !== 201) throw new Error("không tạo được dữ liệu đầu vào: " + r.status);
}

try {
  await seedUnread();
  const page = await login("nurse1");
  current = page;
  await step("thanh bên không còn số đếm; chuông có số chưa đọc", async () => {
    if ((await page.$$(".side .nav .cnt")).length) throw new Error("vẫn còn số trên thanh bên");
    await page.waitForSelector(".bellbadge");
    if ((await badge(page)) < 1) throw new Error("chuông không có số chưa đọc");
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/notify-1-bell.png` });
  });

  let first;
  await step("mở trung tâm thông báo, lọc chưa đọc, mở một thông báo", async () => {
    await page.click(".btn.bell"); await page.waitForSelector(".np .nitem");
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/notify-2-panel.png` });
    await page.click('.npt button:has-text("Chưa đọc")');
    first = await badge(page);
    await page.click(".np .nitem.unread");
    await page.waitForFunction(() => !document.querySelector(".np"));
    await page.waitForTimeout(500);
    if ((await badge(page)) !== first - 1) throw new Error(`mong đợi ${first - 1}, thực tế ${await badge(page)}`);
  });

  await step("sự kiện mới đến trực tiếp: toast + chuông đỏ + tiêu đề tab", async () => {
    const t = await apiToken("doctor1");
    const before = await badge(page);
    const r = await fetch(`${BASE}/api/emergency-events`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${t}` }, body: JSON.stringify({ temp_identity: "Nam ~35 tuổi, khu C", location: "Khu C", description: "Ngã cầu thang, đau đầu" }) });
    if (r.status !== 201) throw new Error("không tạo được sự kiện cấp cứu: " + r.status);
    globalThis.emergencyId = (await r.json()).id;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));   // mô phỏng quay lại tab -> poll ngay
    await page.waitForSelector('.toast:has-text("CẤP CỨU")');
    await page.waitForSelector(".btn.bell.crit");
    if ((await badge(page)) !== before + 1) throw new Error("số chưa đọc không tăng");
    if (!(await page.title()).startsWith("(")) throw new Error("tiêu đề tab không hiện số chưa đọc: " + (await page.title()));
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/notify-3-live.png` });
  });

  await step("bấm thông báo cấp cứu -> đi tới tab Cấp cứu", async () => {
    await page.click(".btn.bell"); await page.waitForSelector(".np");
    await page.locator('.np .nitem.bad.unread:has-text("CẤP CỨU")').first().click();
    await page.waitForFunction((id) => location.hash === `#/emergency/${id}`, globalThis.emergencyId);
    await page.waitForSelector('.side .nav.on:has-text("Cấp cứu")');
  });

  await step("Đọc tất cả -> hết số, tiêu đề tab trở lại bình thường", async () => {
    await page.click(".btn.bell");
    const off = await page.$eval('.nph button:has-text("Đọc tất cả")', (e) => e.disabled);   // vô hiệu khi không còn thông báo chưa đọc
    if (!off) await page.click('.nph button:has-text("Đọc tất cả")');
    await page.waitForFunction(() => !document.querySelector(".bellbadge"));
    if ((await page.title()).startsWith("(")) throw new Error("tiêu đề vẫn còn số");
  });

  await step("cài đặt: tắt nhóm tùy chọn, nhóm bắt buộc bị khóa, lưu bền sau khi tải lại", async () => {
    await page.click('.nph button[aria-label="Cài đặt thông báo"]');
    await page.waitForSelector(".prefrow");
    const lock = await page.$eval('.prefrow:has-text("Cấp cứu") input', (e) => e.disabled);
    if (!lock) throw new Error("nhóm Cấp cứu phải bị khóa");
    await page.click('.prefrow:has-text("Thuốc & xét nghiệm") input');
    await page.waitForTimeout(500);
    await page.reload(); await page.waitForSelector(".side .nav");
    await page.click(".btn.bell"); await page.click('.nph button[aria-label="Cài đặt thông báo"]');
    await page.waitForSelector(".prefrow");
    if (await page.$eval('.prefrow:has-text("Thuốc & xét nghiệm") input', (e) => e.checked)) throw new Error("tùy chọn không được lưu");
    await page.click('.prefrow:has-text("Thuốc & xét nghiệm") input');   // bật lại
    await page.waitForTimeout(400);
  });

  await step("liên kết sâu: approver mở thông báo chuyển viện -> mở đúng hồ sơ", async () => {
    const ap = await login("approver1");
    await ap.click(".btn.bell"); await ap.waitForSelector(".np .nitem");
    await ap.click('.np .nitem:has-text("chờ phê duyệt")');
    await ap.waitForSelector('.drawer header h2:has-text("Chuyển viện")');
    if (SHOTS) await ap.screenshot({ path: `${SHOTS}/notify-4-deeplink.png` });
  });

  await step("riêng tư: cán bộ tiếp nhận không thấy nội dung lâm sàng trong thông báo", async () => {
    const of = await login("officer1");
    await of.click(".btn.bell"); await of.waitForSelector(".np");
    const text = await of.$eval(".np", (e) => e.innerText);
    for (const bad of ["Ngã cầu thang", "đau đầu", "Co giật", "Amlodipine", "Amoxicillin"]) if (text.includes(bad)) throw new Error(`lộ nội dung lâm sàng: ${bad}`);
  });
} catch { /* đã in lỗi ở step */ }
await browser.close();
console.log(errs.length ? `\n${errs.length} lỗi:\n- ${errs.join("\n- ")}` : "\nTất cả bước đạt, không có lỗi console.");
process.exit(errs.length ? 1 : 0);
