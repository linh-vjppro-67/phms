// Smoke test giao diện: đăng nhập từng vai trò, mở mọi tab, bắt lỗi console/JS/toast đỏ.
// Chạy: BASE=http://localhost:8000 SHOTS=./shots node e2e/smoke.mjs   (cần backend đã seed + demo)
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE || "http://localhost:8000";
const SHOTS = process.env.SHOTS;
const PASS = "Phms@2026dev";
const ROLES = (process.env.ROLES || "officer1,nurse1,doctor1,pharm1,approver1,manager1,admin").split(",");
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch();
let failures = 0;
for (const user of ROLES) {
  const ctx = await browser.newContext({ bypassCSP: true, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
  page.on("console", (m) => m.type() === "error" && errs.push("console: " + m.text()));
  await page.goto(BASE);
  await page.fill('input[name="u"]', user);
  await page.fill('input[name="p"]', PASS);
  await page.click("button.btn.primary");
  await page.waitForSelector(".side .nav");
  const labels = await page.$$eval(".side .nav", (els) => els.map((e) => e.textContent.trim()));
  const visited = [];
  for (let i = 0; i < labels.length; i++) {
    const nav = (await page.$$(".side .nav"))[i];
    await nav.click();
    await page.waitForTimeout(700);
    const toast = await page.$(".toast");
    if (toast) {
      const bg = await toast.evaluate((e) => e.style.background);
      if (bg.includes("185, 28, 28") || bg.includes("#b91c1c")) errs.push(`[${labels[i]}] toast lỗi: ${await toast.textContent()}`);
    }
    const blank = await page.$eval(".content", (e) => e.innerText.trim().length < 5);
    if (blank) errs.push(`[${labels[i]}] màn hình trống`);
    visited.push(labels[i]);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/${user}-${i}.png` });
  }
  console.log(`${errs.length ? "✗" : "✓"} ${user}: ${visited.length} tab -> ${visited.join(" | ")}`);
  errs.forEach((e) => console.log("    ", e));
  failures += errs.length;
  await ctx.close();
}
await browser.close();
process.exit(failures ? 1 : 0);
