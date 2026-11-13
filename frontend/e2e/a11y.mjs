// Kiểm thử accessibility (WCAG 2.1 A/AA) bằng axe-core trên màn hình đăng nhập, mọi tab của mọi vai trò, các hộp thoại/ngăn kéo,
// cộng kiểm tra thao tác bằng bàn phím (Tab, Esc, vòng focus trong hộp thoại, nhãn cho nút chỉ có biểu tượng).
// Chạy: BASE=http://localhost:8000 node e2e/a11y.mjs        (mặc định chỉ tính lỗi serious/critical là KHÔNG ĐẠT; A11Y_STRICT=1: tính cả moderate/minor)
import fs from "node:fs";
import { createRequire } from "node:module";
import { managedPerson, nav, start, startEncounter, uniq } from "./lib.mjs";

const require = createRequire(import.meta.url);
const AXE = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const STRICT = process.env.A11Y_STRICT === "1";
const T = await start("Accessibility (axe-core WCAG 2.1 A/AA) + bàn phím");
const U = uniq();
const P = await managedPerson(`Truy Cập ${U}`);
const E = await startEncounter(P.id);

const scan = async (page, where) => {
  await page.evaluate(AXE);
  const r = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } })).violations
    .map((v) => ({ id: v.id, impact: v.impact, help: v.help, n: v.nodes.length, ex: v.nodes.slice(0, 2).map((x) => x.target.join(" ").slice(0, 90)) })));
  const bad = r.filter((v) => (STRICT ? true : ["serious", "critical"].includes(v.impact)));
  if (bad.length) throw new Error(`${where}: ` + bad.map((v) => `${v.id}[${v.impact}]×${v.n} ${v.ex[0]}`).join(" ; "));
  const minor = r.filter((v) => !bad.includes(v));
  if (minor.length) console.log(`    · ${where}: ${minor.map((v) => `${v.id}(${v.impact})×${v.n}`).join(", ")}`);
};

await T.step("A0 màn hình đăng nhập", async () => { const p = await T.open("login"); await scan(p, "đăng nhập"); });

const ROLES = ["doctor1", "officer1", "nurse1", "pharm1", "approver1", "manager1", "admin"];
for (const role of ROLES) {
  await T.step(`A1 ${role}: mọi tab không có lỗi accessibility nghiêm trọng`, async () => {
    const page = await T.login(role);
    const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
    for (let i = 0; i < labels.length; i++) {
      await (await page.$$(".side .nav"))[i].click(); await page.waitForTimeout(600);
      await scan(page, `${role} › ${labels[i].replace(/M\d\d|WF-\d\d/g, "").trim()}`);
    }
    if (role === "doctor1") {
      await page.click(".btn.bell"); await page.waitForSelector(".np"); await scan(page, "trung tâm thông báo"); await page.click(".btn.bell");
      await page.click(".who"); await page.waitForSelector(".modal"); await scan(page, "hộp thoại tài khoản"); await page.keyboard.press("Escape");
    }
    await page.context().close();
  });
}

await T.step("A2 hộp thoại / ngăn kéo / bộ chọn người: không lỗi nghiêm trọng", async () => {
  const doc = await T.login("doctor1");
  await nav(doc, "Khám chữa bệnh");
  await doc.click(`tbody tr:has-text("${P.full_name}")`); await doc.waitForSelector(".drawer"); await scan(doc, "ngăn kéo lượt khám");
  for (const tab of ["Sinh hiệu", "Chẩn đoán", "Đơn thuốc"]) { await doc.click(`.drawer button[role="tab"]:has-text("${tab}")`); await doc.waitForTimeout(250); await scan(doc, `lượt khám › ${tab}`); }
  await doc.click('.drawer button:has-text("+ Kê đơn")'); await doc.waitForSelector(".modal"); await scan(doc, "hộp thoại kê đơn");
  await doc.keyboard.press("Escape"); await doc.keyboard.press("Escape");
  await doc.click('button:has-text("+ Lượt khám mới")'); await doc.waitForSelector(".modal"); await scan(doc, "hộp thoại lượt khám mới"); await doc.keyboard.press("Escape");
  await doc.click(".pctx button, button:has-text('Chọn người xử lý')"); await doc.waitForSelector(".modal"); await scan(doc, "bộ chọn người xử lý");
});

await T.step("A4 giao diện tối: tương phản đạt ở mọi tab của bác sĩ và quản lý", async () => {
  for (const role of ["doctor1", "manager1"]) {
    const page = await T.login(role);
    await page.evaluate(() => { document.documentElement.dataset.theme = "dark"; });
    const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
    for (let i = 0; i < labels.length; i++) { await (await page.$$(".side .nav"))[i].click(); await page.waitForTimeout(500); await scan(page, `tối · ${role} › ${labels[i].replace(/M\d\d|WF-\d\d/g, "").trim()}`); }
    await page.context().close();
  }
});

await T.step("A3 bàn phím: Tab đến được nút/liên kết; có viền focus thấy được; Esc đóng hộp thoại; focus quay về nút đã mở", async () => {
  const doc = await T.login("doctor1");
  await nav(doc, "Khám chữa bệnh");
  // 1) mọi nút chỉ có biểu tượng phải có tên truy cập
  const unnamed = await doc.$$eval("button, a[href]", (els) => els.filter((e) => !(e.innerText || "").trim() && !e.getAttribute("aria-label") && !e.getAttribute("title")).map((e) => e.outerHTML.slice(0, 80)));
  if (unnamed.length) throw new Error(`nút không có tên truy cập: ${unnamed[0]}`);
  // 2) focus thấy được
  await doc.focus('button:has-text("+ Lượt khám mới")');
  const ring = await doc.evaluate(() => { const s = getComputedStyle(document.activeElement); return { o: s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0, b: s.boxShadow !== "none" }; });
  if (!ring.o && !ring.b) throw new Error("nút đang focus không có viền/bóng focus nhìn thấy");
  // 3) mở hộp thoại bằng bàn phím, focus chuyển vào trong hộp thoại, Esc đóng, focus trả về nút
  await doc.keyboard.press("Enter"); await doc.waitForSelector(".modal");
  const inModal = await doc.evaluate(() => !!document.activeElement?.closest(".modal"));
  if (!inModal) throw new Error("mở hộp thoại xong focus phải nằm trong hộp thoại");
  for (let i = 0; i < 40; i++) { await doc.keyboard.press("Tab"); if (!(await doc.evaluate(() => !!document.activeElement?.closest(".modal")))) throw new Error(`Tab lần ${i + 1} làm focus thoát khỏi hộp thoại (không bị giữ trong hộp thoại)`); }
  await doc.keyboard.press("Escape"); await doc.waitForSelector(".modal", { state: "detached" });
  const back = await doc.evaluate(() => document.activeElement?.textContent?.trim());
  if (!/Lượt khám mới/.test(back || "")) throw new Error(`đóng hộp thoại xong focus phải quay về nút đã mở, hiện ở: "${(back || "body").slice(0, 30)}"`);
});

process.exit((await T.done()).length ? 1 : 0);
