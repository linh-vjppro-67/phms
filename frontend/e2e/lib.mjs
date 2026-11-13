// Thư viện dùng chung cho các bài E2E luồng nghiệp vụ.
// Mỗi bài TỰ TẠO dữ liệu cần thiết qua API (tên duy nhất mỗi lần chạy) rồi thao tác GIAO DIỆN thật nhiều vai trò,
// nên chạy được trên CSDL chỉ có dữ liệu seed (python -m app.seed) – không phụ thuộc dữ liệu demo.
import { chromium, firefox, webkit } from "playwright";
const ENGINE = { chromium, firefox, webkit }[process.env.BROWSER || "chromium"];
import fs from "node:fs";

export const BASE = process.env.BASE || "http://localhost:8000";
export const PASS = "Phms@2026dev";
export const SHOTS = process.env.SHOTS;
export const uniq = () => Date.now().toString(36).slice(-5) + Math.random().toString(36).slice(2, 4);
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

// ------------------------------------------------------------------ API (dựng dữ liệu & kiểm tra phía máy chủ)
const tokens = {};
export async function api(user, method, path, body, headers = {}) {
  if (!tokens[user]) {
    const r = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: user, password: PASS }) });
    if (!r.ok) throw new Error(`đăng nhập ${user} thất bại (${r.status})`);
    tokens[user] = (await r.json()).access_token;
  }
  const r = await fetch(`${BASE}/api${path}`, { method, headers: { "content-type": "application/json", authorization: `Bearer ${tokens[user]}`, ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
  let data; const ct = r.headers.get("content-type") || "";
  try { data = ct.includes("json") ? await r.json() : await r.text(); } catch { data = null; }
  return { status: r.status, data };
}
export async function ok(user, method, path, body, headers) {
  const r = await api(user, method, path, body, headers);
  if (r.status >= 300) throw new Error(`${method} ${path} [${user}] -> ${r.status} ${JSON.stringify(r.data).slice(0, 220)}`);
  return r.data;
}

export async function facilityId(code) { return (await ok("admin", "GET", "/facilities")).find((f) => f.code === code).id; }

/** Người + đợt tiếp nhận ở cơ sở của cán bộ. */
export async function newPerson(name, { officer = "officer1", code = true, dob = "1988-04-04", stay = true } = {}) {
  const ext = code ? "E2E-" + uniq() : undefined;
  const p = await ok(officer, "POST", "/persons", { full_name: name, date_of_birth: dob, ...(code ? { source_system: "QLPN", external_id: ext } : {}) });
  p.code = ext;
  if (stay) p.stay = await ok(officer, "POST", `/persons/${p.id}/stays`, {});
  return p;
}
export async function startEncounter(pid, { type = "ad_hoc", doctor = "doctor1", reason = "Khám theo yêu cầu", start = true } = {}) {
  const e = await ok(doctor, "POST", "/encounters", { person_id: pid, type, reason });
  if (start) await ok(doctor, "POST", `/encounters/${e.id}/transition`, { to: "in_progress" });
  return e;
}
/** Người đã khám ban đầu xong -> đợt tiếp nhận "Đang quản lý". */
export async function managedPerson(name, o = {}) {
  const p = await newPerson(name, o);
  const doctor = o.doctor || "doctor1";
  const e = await startEncounter(p.id, { type: "initial", doctor, reason: "Khám sức khỏe ban đầu" });
  await ok(doctor, "POST", `/persons/${p.id}/allergy-status/none-confirmed`);
  await ok(doctor, "POST", `/encounters/${e.id}/transition`, { to: "completed" });
  return p;
}
export const today = (d = 0) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
export async function confirmedRx(encId, o = {}) {
  const body = { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1 viên", route: "uống", frequency: "2 lần/ngày", start_date: today(), duration_days: 15, quantity_prescribed: 30, ...o };
  const d = await ok("doctor1", "POST", `/encounters/${encId}/medication-orders`, body);
  return ok("doctor1", "POST", `/medication-orders/${d.id}/confirm`, d.warnings?.length ? { acknowledge_warnings: true, ack_note: "E2E dựng dữ liệu" } : {});
}
export const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n E2E test document " + "x".repeat(200));

// ------------------------------------------------------------------ bộ chạy
export async function start(title) {
  const browser = await ENGINE.launch();
  const errs = [];
  let cur = null;
  const pages = [];
  console.log(`\n== ${title}`);
  const step = async (name, fn) => {
    try { await fn(); console.log("  ✓", name); }
    catch (e) {
      const where = (e.stack || "").split("\n").find((l) => /e2e\/(?!lib)/.test(l))?.match(/([\w-]+\.mjs:\d+)/)?.[1];
      const m = e.message.split("\n")[0] + (where ? `  [${where}]` : "");
      errs.push(`${name}: ${m}`); console.log("  ✗", name, "-", m);
      if (SHOTS && cur) await cur.screenshot({ path: `${SHOTS}/FAIL-${title.replace(/\W+/g, "_")}-${name.replace(/\W+/g, "_").slice(0, 40)}.png` }).catch(() => {});
      for (let i = 0; i < 3 && cur; i++) await cur.keyboard.press("Escape").catch(() => {});   // đóng hộp thoại/ngăn kéo còn mở để không lây sang bước sau
    }
  };
  // bypassCSP: Playwright cần eval để chạy waitForFunction. Việc "ứng dụng không vi phạm CSP" được kiểm riêng ở e2e/security.mjs (CSP bật nguyên).
  /** Mở trang mới (chưa đăng nhập). */
  const open = async (label, viewport = { width: 1440, height: 950 }, opts = {}) => {
    const ctx = await browser.newContext({ viewport, acceptDownloads: true, bypassCSP: !opts.enforceCsp });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errs.push(`${label} pageerror: ${e.message}`));
    page.on("console", (m) => m.type() === "error" && !/status of 4\d\d/.test(m.text()) && errs.push(`${label} console: ${m.text()}`));
    page.setDefaultTimeout(12000);
    await page.goto(BASE);
    cur = page; pages.push(page);
    page.use = () => { cur = page; return page; };
    return page;
  };
  const login = async (user, viewport, opts, password = PASS) => {
    const page = await open(user, viewport, opts);
    await page.fill('input[name="u"]', user); await page.fill('input[name="p"]', password);
    await page.click("button.btn.primary"); await page.waitForSelector(".side .nav");
    return page;
  };
  const done = async () => {
    await browser.close();
    console.log(errs.length ? `  → ${errs.length} LỖI` : "  → tất cả bước đạt");
    errs.filter((e) => /pageerror|console:/.test(e)).forEach((e) => console.log("     ·", e.slice(0, 300)));
    return errs;
  };
  return { step, login, open, done, errs, setCur: (p) => (cur = p) };
}

// ------------------------------------------------------------------ thao tác giao diện thường dùng
export const nav = async (page, label) => {
  page.use?.();
  if (await page.isVisible(".menu-btn") && !(await page.$(".side.open"))) { await page.click(".menu-btn"); await page.waitForSelector(".side.open"); }   // màn hình nhỏ: mở menu trước
  await page.click(`.side .nav:has-text("${label}")`); await page.waitForTimeout(350);
};
export const toast = (page, text, t = 9000) => page.waitForSelector(`.toast:has-text("${text}")`, { timeout: t });
export const dialogOk = (page) => page.click('.modal-bg footer button:has-text("Đồng ý")');
export const modalSubmit = (page, label) => page.click(`.modal-bg footer button:has-text("${label}")`);
export const modalOpen = (page, title) => page.waitForSelector(`.modal-bg:has-text("${title}")`);
export const modalGone = (page) => page.waitForSelector(".modal-bg", { state: "detached" });
/** Chọn người xử lý ở thanh trên (thẻ người đang chọn hoặc nút chọn). */
export async function pickPatient(page, name) {
  if (await page.$(".pctx")) await page.click('.pctx button:has-text("Đổi")'); else await page.click('button:has-text("Chọn người xử lý")');
  await page.fill(".modal input.search", name);
  await page.click(`.modal tr.click:has-text("${name}")`);
  await page.waitForSelector(`.pctx:has-text("${name}")`);
}
export async function pickInModal(page, name) {   // bộ chọn người lồng trong modal khác (modal trên cùng = modal cuối)
  const top = page.locator(".modal-bg").last();
  await top.locator("input.search").fill(name);
  await top.locator(`tr.click:has-text("${name}")`).click();
}
export const rowOf = (page, text) => page.locator(`tbody tr:has-text("${text}")`).first();
export async function expect(cond, msg) { if (!(await cond)) throw new Error(msg); }
export const bodyText = (page, sel = "body") => page.$eval(sel, (e) => e.innerText);
export async function mustContain(page, sel, ...texts) {
  const t = (await bodyText(page, sel)).toLowerCase();   // innerText phản ánh text-transform của CSS (tiêu đề cột in hoa)
  for (const x of texts) if (!t.includes(x.toLowerCase())) throw new Error(`không thấy “${x}” trong ${sel}`);
}
export async function mustNotContain(page, sel, ...texts) {
  const t = await bodyText(page, sel);
  for (const x of texts) if (t.includes(x)) throw new Error(`không được hiện “${x}” trong ${sel}`);
}

/** TOTP (RFC 6238) cho test MFA – cùng thuật toán với ứng dụng xác thực. */
import crypto from "node:crypto";
export function totp(secretB32, atMs = Date.now()) {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; let bits = "";
  for (const c of secretB32.replace(/=+$/, "")) bits += A.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const ctr = Buffer.alloc(8); ctr.writeBigUInt64BE(BigInt(Math.floor(atMs / 30000)));
  const h = crypto.createHmac("sha1", key).update(ctr).digest(); const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, "0");
}
/** Tải tài liệu lên qua API (multipart). */
export async function uploadDoc(user, personId, name = "ketqua.pdf", docType = "lab_result") {
  await api(user, "GET", "/auth/me");   // bảo đảm đã có token trong bộ nhớ đệm
  const r = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: user, password: PASS }) });
  const tok = (await r.json()).access_token;
  const fd = new FormData(); fd.append("doc_type", docType); fd.append("person_id", personId); fd.append("file", new Blob([PDF], { type: "application/pdf" }), name);
  const u = await fetch(`${BASE}/api/documents`, { method: "POST", headers: { authorization: `Bearer ${tok}` }, body: fd });
  if (!u.ok) throw new Error(`upload ${name} -> ${u.status} ${await u.text()}`);
  return u.json();
}
