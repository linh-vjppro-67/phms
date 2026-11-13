// E2E: tái khám theo kế hoạch theo dõi (lịch quá hạn) -> Khám -> hoàn tất -> lịch được đóng và sinh lịch kỳ kế tiếp.
import { chromium } from "playwright";

const BASE = process.env.BASE || "http://localhost:8000";
const browser = await chromium.launch();
const page = await (await browser.newContext({ bypassCSP: true, viewport: { width: 1440, height: 1000 } })).newPage();
const errs = [];
page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
page.on("console", (m) => m.type() === "error" && errs.push("console: " + m.text()));
const run = async (name, fn) => { try { await fn(); console.log("✓", name); } catch (e) { errs.push(`${name}: ${e.message.split("\n")[0]}`); console.log("✗", name, "-", e.message.split("\n")[0]); throw e; } };

try {
  await run("đăng nhập bác sĩ, mở Bệnh lý & Cảnh báo", async () => {
    await page.goto(BASE);
    await page.fill('input[name="u"]', "doctor1"); await page.fill('input[name="p"]', "Phms@2026dev");
    await page.click("button.btn.primary"); await page.waitForSelector(".side .nav");
    await page.click('.side .nav:has-text("Bệnh lý & Cảnh báo")');
    await page.click('button[role="tab"]:has-text("Lịch tái khám")');
    await page.waitForSelector('.badge:has-text("Trễ")');
  });
  let before = 0, name = "";
  await run("đếm lịch quá hạn và bấm Khám", async () => {
    before = await page.$$eval("tbody tr", (r) => r.length);
    name = await page.$eval("tbody tr td b", (e) => e.textContent);
    await page.click('tbody tr button:has-text("Khám")');
    await page.waitForSelector('.drawer .step.cur:has-text("Đang khám")');
  });
  await run("ghi sinh hiệu rồi hoàn tất khám", async () => {
    await page.click('.drawer button[role="tab"]:has-text("Sinh hiệu")');
    await page.fill('.drawer input[name="sys"]', "132"); await page.fill('.drawer input[name="dia"]', "84");
    await page.click('.drawer button:has-text("Ghi nhận sinh hiệu")');
    await page.waitForSelector('.drawer td:has-text("132 mmHg")');
    await page.click('.drawer button:has-text("Hoàn tất khám")');
    await page.click('.modal-bg footer button:has-text("Đồng ý")');
    await page.waitForSelector('.drawer .badge:has-text("Hoàn tất")');
  });
  await run("lịch cũ biến mất khỏi danh sách quá hạn", async () => {
    await page.click('.drawer-bg header .btn:has-text("Quay lại")');
    await page.waitForTimeout(800);
    const after = await page.$$eval("tbody tr", (r) => r.length);
    if (after !== before - 1) throw new Error(`mong đợi ${before - 1} dòng, thực tế ${after}`);
    console.log(`   (${name}: quá hạn ${before} → ${after})`);
  });
  await run("lịch kỳ kế tiếp được sinh ra ở 'Tất cả lịch đang mở'", async () => {
    await page.click('.seg button:has-text("Tất cả lịch đang mở")');
    await page.waitForSelector(`tbody tr:has-text("${name}")`);
  });
} catch { /* đã in lỗi */ }
await browser.close();
console.log(errs.length ? `\n${errs.length} lỗi:\n- ${errs.join("\n- ")}` : "\nĐạt, không có lỗi console.");
process.exit(errs.length ? 1 : 0);
