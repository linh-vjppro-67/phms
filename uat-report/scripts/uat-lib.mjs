// Khung chạy UAT: đăng ký test case, thu bằng chứng (API log, screenshot, SQL), ghi results.json
import { chromium } from "/Users/linhpham/Documents/phms/frontend/node_modules/playwright/index.mjs";
import fs from "node:fs";
import { execFileSync } from "node:child_process";

export const BASE = "http://localhost:8765";           // STAGING – không phải cổng 8000 (server thật)
export const DB = "/private/tmp/claude-501/-Users-linhpham-Documents-phms/b31585b3-466f-4421-9023-356036bdd04e/scratchpad/uat/uat.db";
export const OUT = "/private/tmp/claude-501/-Users-linhpham-Documents-phms/b31585b3-466f-4421-9023-356036bdd04e/scratchpad/uat/evidence";
export const PASS = "Phms@2026dev";
fs.mkdirSync(OUT + "/shots", { recursive: true });
if (BASE.includes(":8000")) throw new Error("Từ chối chạy trên cổng 8000 (môi trường thật)");

export class Blocked extends Error {}
export const uniq = () => Date.now().toString(36).slice(-5) + Math.random().toString(36).slice(2, 4);
export const today = (d = 0) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
export const iso = (minAgo = 0) => new Date(Date.now() - minAgo * 60000).toISOString();

// ---------------------------------------------------------------- API
const tokens = {};
let curLog = null;
export async function login(user, password = PASS) {
  const r = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: user, password }) });
  const d = await r.json().catch(() => null);
  return { status: r.status, data: d };
}
export async function tok(user) {
  if (!tokens[user]) { const r = await login(user); if (r.status !== 200) throw new Error(`login ${user} -> ${r.status}`); tokens[user] = r.data.access_token; }
  return tokens[user];
}
export async function api(user, method, path, body, headers = {}) {
  const t = user ? await tok(user) : null;
  const r = await fetch(`${BASE}/api${path}`, { method, headers: { "content-type": "application/json", ...(t ? { authorization: `Bearer ${t}` } : {}), ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
  let data; const ct = r.headers.get("content-type") || "";
  try { data = ct.includes("json") ? await r.json() : await r.text(); } catch { data = null; }
  curLog?.push({ call: `${user || "anon"} ${method} /api${path}`, req: body, status: r.status, res: JSON.stringify(data)?.slice(0, 400) });
  return { status: r.status, data, headers: r.headers };
}
export async function ok(user, method, path, body, headers) {
  const r = await api(user, method, path, body, headers);
  if (r.status >= 300) throw new Error(`SETUP ${method} ${path} [${user}] -> ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`);
  return r.data;
}
export const code = (r) => r.data?.error?.code;
export function sql(q) {
  const out = execFileSync("sqlite3", ["-readonly", "-json", DB, q], { encoding: "utf8" }).trim();
  const rows = out ? JSON.parse(out) : [];
  curLog?.push({ call: "SQL", req: q, status: "-", res: JSON.stringify(rows).slice(0, 400) });
  return rows;
}
export const facilityId = async (c) => (await ok("admin", "GET", "/facilities")).find((f) => f.code === c).id;

// ---------------------------------------------------------------- dựng dữ liệu (dữ liệu giả lập, tên duy nhất)
export async function newPerson(name, { officer = "officer1", code = true, dob = "1988-04-04", stay = true } = {}) {
  const ext = code ? "UAT-" + uniq() : undefined;
  const p = await ok(officer, "POST", "/persons", { full_name: name, date_of_birth: dob, ...(code ? { source_system: "QLPN", external_id: ext } : {}) });
  p.code = ext;
  if (stay) p.stay = await ok(officer, "POST", `/persons/${p.id}/stays`, {});
  return p;
}
export async function startEnc(pid, { type = "ad_hoc", doctor = "doctor1", reason = "Khám theo yêu cầu", start = true } = {}) {
  const e = await ok(doctor, "POST", "/encounters", { person_id: pid, type, reason });
  if (start) await ok(doctor, "POST", `/encounters/${e.id}/transition`, { to: "in_progress" });
  return e;
}
export async function managedPerson(name, o = {}) {
  const p = await newPerson(name, o); const doctor = o.doctor || "doctor1";
  const e = await startEnc(p.id, { type: "initial", doctor, reason: "Khám sức khỏe ban đầu" });
  await ok(doctor, "POST", `/persons/${p.id}/allergy-status/none-confirmed`);
  await ok(doctor, "POST", `/encounters/${e.id}/transition`, { to: "completed" });
  return p;
}
export async function confirmedRx(encId, o = {}) {
  const body = { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1 viên", route: "uống", frequency: "2 lần/ngày", start_date: today(), duration_days: 15, quantity_prescribed: 30, ...o };
  const d = await ok("doctor1", "POST", `/encounters/${encId}/medication-orders`, body);
  return ok("doctor1", "POST", `/medication-orders/${d.id}/confirm`, d.warnings?.length ? { acknowledge_warnings: true, ack_note: "UAT dựng dữ liệu" } : {});
}
export const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n UAT document " + "x".repeat(200));
export async function upload(user, fields, buf = PDF, name = "uat.pdf", type = "application/pdf") {
  const t = await tok(user); const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  fd.append("file", new Blob([buf], { type }), name);
  const r = await fetch(`${BASE}/api/documents`, { method: "POST", headers: { authorization: `Bearer ${t}` }, body: fd });
  let data; try { data = await r.json(); } catch { data = null; }
  curLog?.push({ call: `${user} POST /api/documents (${name}, ${buf.length}B)`, status: r.status, res: JSON.stringify(data)?.slice(0, 300) });
  return { status: r.status, data };
}

// ---------------------------------------------------------------- trình duyệt (UI)
let browser;
const ctxs = {};
export async function ui(user, { w = 1440, h = 900 } = {}) {
  const key = `${user}-${w}`;
  if (ctxs[key]) return ctxs[key];
  browser ??= await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, bypassCSP: true });
  const page = await ctx.newPage(); page.setDefaultTimeout(12000);
  page.jsErrors = []; page.on("pageerror", (e) => page.jsErrors.push(e.message));
  await page.goto(BASE); await page.fill('input[name="u"]', user); await page.fill('input[name="p"]', PASS);
  await page.click("button.btn.primary"); await page.waitForSelector(".side .nav");
  ctxs[key] = page; return page;
}
export async function freshPage({ w = 1440, h = 900 } = {}) {
  browser ??= await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, bypassCSP: true });
  const page = await ctx.newPage(); page.setDefaultTimeout(12000); await page.goto(BASE); return page;
}
export const nav = async (page, label) => { await page.click(`.side .nav:has-text("${label}")`); await page.waitForTimeout(400); };
export const toast = (page, text, t = 9000) => page.waitForSelector(`.toast:has-text("${text}")`, { timeout: t });
export const navLabels = (page) => page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
export async function closeBrowser() { await browser?.close(); }

// ---------------------------------------------------------------- bộ đăng ký test case
export const results = [];
let seq = 0;
export async function tc(meta, fn) {
  const r = { ...meta, status: "PASS", actual: "", evidence: [], screenshots: [] };
  const log = []; curLog = log;
  const t0 = Date.now();
  const ctx = {
    shot: async (page, name) => { const f = `shots/${meta.id}-${name}.png`; await page.screenshot({ path: `${OUT}/${f}` }); r.screenshots.push(f); },
    note: (s) => log.push({ call: "NOTE", res: s }),
  };
  try { r.actual = (await fn(ctx)) || "Đúng như mong đợi"; }
  catch (e) {
    if (e instanceof Blocked) { r.status = "BLOCKED"; r.actual = e.message; }
    else { r.status = "FAIL"; r.actual = (e.message || String(e)).split("\n")[0].slice(0, 500); }
  }
  r.evidence = log; r.ms = Date.now() - t0; curLog = null;
  results.push(r);
  const icon = { PASS: "✓", FAIL: "✗", BLOCKED: "⊘" }[r.status];
  console.log(`${icon} ${meta.id.padEnd(11)} ${meta.title.slice(0, 70)}${r.status !== "PASS" ? "\n     → " + r.actual : ""}`);
  fs.writeFileSync(`${OUT}/results.json`, JSON.stringify(results, null, 1));
}
export function must(cond, msg) { if (!cond) throw new Error(msg); }
export function status(r, want, what = "") { if (r.status !== want) throw new Error(`${what} mong đợi HTTP ${want}, thực tế ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`); }
export function denied(r, what = "") { if (![401, 403, 404].includes(r.status)) throw new Error(`${what} phải bị từ chối (403), thực tế HTTP ${r.status}`); }
