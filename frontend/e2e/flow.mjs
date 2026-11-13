// E2E luồng chính trên trình duyệt thật: khám ban đầu (wizard) từ đầu đến cuối bằng bác sĩ.
// Cần CSDL demo MỚI (python -m app.demo --reset): người được chọn phải đang chờ khám ban đầu.
// Chạy: BASE=http://localhost:8000 SHOTS=./shots node e2e/flow.mjs   (cần backend đã seed + demo)
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS;
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
const browser = await chromium.launch();
const page = await (await browser.newContext({ bypassCSP: true, viewport: { width: 1440, height: 1000 } })).newPage();
const errs = [];
page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
page.on("console", (m) => m.type() === "error" && errs.push("console: " + m.text()));
const shot = (n) => SHOTS && page.screenshot({ path: `${SHOTS}/flow-${n}.png` });
const step = async (name, fn) => { try { await fn(); console.log("✓", name); } catch (e) { errs.push(`${name}: ${e.message.split("\n")[0]}`); console.log("✗", name, "-", e.message.split("\n")[0]); await shot("fail-" + name.replace(/\W+/g, "_")); throw e; } };
const WHO = process.env.FLOW_PERSON || "Phan Ngọc Dũng";   // người chờ khám ban đầu trong dữ liệu demo
const dialogOk = () => page.click('.modal-bg footer button:has-text("Đồng ý")');

try {
  await step("đăng nhập bác sĩ", async () => {
    await page.goto(BASE);
    await page.fill('input[name="u"]', "doctor1"); await page.fill('input[name="p"]', "Phms@2026dev");
    await page.click("button.btn.primary"); await page.waitForSelector(".side .nav");
  });
  await step("mở tab Khám ban đầu, bắt đầu khám một người chờ khám", async () => {
    await page.click('.side .nav:has-text("Khám ban đầu")');
    await page.waitForSelector('button:has-text("Bắt đầu khám")');
    await shot("1-worklist");
    await page.click(`tr:has-text("${WHO}") button:has-text("Bắt đầu khám")`);
    await page.waitForSelector('.step.cur:has-text("Tiền sử & dị ứng")');
    await shot("2-wizard-step0");
  });
  await step("bước 1: xác nhận không dị ứng", async () => {
    await page.click('button:has-text("Xác nhận không có dị ứng")'); await dialogOk();
    await page.waitForSelector('.badge:has-text("Đã xác nhận không dị ứng")');
    await page.click('button:has-text("Tiếp tục →")');
  });
  await step("bước 2: ghi sinh hiệu", async () => {
    await page.fill('input[name="pulse"]', "80"); await page.fill('input[name="sys"]', "150"); await page.fill('input[name="dia"]', "95");
    await page.click('button:has-text("Ghi nhận sinh hiệu")');
    await page.waitForSelector('td:has-text("150 mmHg")');
    await shot("3-vitals");
    await page.click('button:has-text("Tiếp tục →")');
  });
  await step("bước 3: lưu tóm tắt + chẩn đoán", async () => {
    await page.fill('textarea[name="summary"]', "Tăng huyết áp, cần theo dõi."); await page.click('button:has-text("Lưu")');
    await page.fill('input[name="text"]', "Tăng huyết áp vô căn"); await page.selectOption('select[name="kind"]', "final");
    await page.click('button:has-text("Thêm chẩn đoán")');
    await page.waitForSelector('td:has-text("Tăng huyết áp vô căn")');
    await page.click('button:has-text("Tiếp tục →")');
  });
  await step("bước 4: kê đơn nháp và xác nhận", async () => {
    await page.click('button:has-text("+ Kê đơn")');
    await page.fill('.modal input[name="drug_name"]', "Amlodipine 5mg");
    await shot("4-rx-modal");
    await page.click('.modal footer button:has-text("Tạo đơn nháp")');
    await page.waitForSelector('td:has-text("Chờ xác nhận")');
    await page.click('table button:has-text("Xác nhận")');
    await page.waitForSelector('td .badge:has-text("Đang hiệu lực")');
    await shot("5-rx-confirmed");
    await page.click('button:has-text("Tiếp tục →")');
  });
  await step("bước 5: lập kế hoạch theo dõi", async () => {
    await page.click('button:has-text("+ Hẹn tái khám")');
    const d = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
    await page.fill('.modal input[name="due_date"]', d);
    await page.click('.modal footer button:has-text("Lưu")');
    await page.waitForSelector('.badge:has-text("tái khám")');
    await page.click('button:has-text("Tiếp tục →")');
  });
  await step("bước 6: hoàn tất khám ban đầu", async () => {
    await shot("6-checklist");
    await page.click('button:has-text("Hoàn tất khám ban đầu")'); await dialogOk();
    await page.waitForSelector('.banner:has-text("Khám ban đầu đã hoàn tất")');
    await shot("7-done");
  });
  await step("đợt tiếp nhận chuyển sang Đang quản lý", async () => {
    await page.click('.side .nav:has-text("Tiếp nhận & Hồ sơ")');
    await page.waitForSelector('.badge:has-text("Đang quản lý")');
  });
} catch { /* đã in lỗi ở step */ }
await browser.close();
console.log(errs.length ? `\n${errs.length} lỗi:\n- ${errs.join("\n- ")}` : "\nTất cả bước đạt, không có lỗi console.");
process.exit(errs.length ? 1 : 0);
