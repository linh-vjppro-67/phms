// E2E đầy đủ: Tài liệu y tế (M12) · Báo cáo (M10) · Quản trị hệ thống (M11).
import crypto from "node:crypto";
import fs from "node:fs";
import { api, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, ok, pickPatient, PDF, start, startEncounter, toast, uniq } from "./lib.mjs";

const T = await start("Tài liệu · Báo cáo · Quản trị (M10–M12)");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const tab = (page, label) => page.click(`.tabs button:has-text("${label}")`);
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const ask = async (page, value, title) => { await modalOpen(page, title); await page.fill('.modal [name="v"]', value); await dialogOk(page); };
const upload = async (page, { type = "Kết quả xét nghiệm", name, buffer, mime = "application/pdf" }) => {
  await page.click('button:has-text("+ Tải lên")'); await modalOpen(page, "Tải tài liệu y tế");
  await page.selectOption('.modal [name="doc_type"]', { label: type }); await page.fill('.modal [name="source"]', "Bệnh viện Đa khoa tỉnh");
  await page.setInputFiles('.modal input[type="file"]', { name, mimeType: mime, buffer });
  await modalSubmit(page, "Tải lên");
};
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");

const P = await managedPerson(nm("Tài Liệu Bệnh Nhân"));
const nur = await T.login("nurse1");
const doc = await T.login("doctor1");

// =============================================================== M12 tài liệu
await T.step("K1 tải PDF lên: lưu kèm checksum SHA-256, loại, nguồn; hiện trong danh sách", async () => {
  await pickPatient(nur, P.full_name); await nav(nur, "Tài liệu y tế");
  await upload(nur, { name: `ketqua_${U}.pdf`, buffer: PDF }); await toast(nur, "Đã tải lên và lưu mã hóa");
  await nur.waitForSelector(`tbody tr:has-text("ketqua_${U}.pdf")`);
  await mustContain(nur, `tbody tr:has-text("ketqua_${U}.pdf")`, "Kết quả xét nghiệm", "Hợp lệ", "Bệnh viện Đa khoa tỉnh", "v1");
  const shown = await nur.$eval(`tbody tr:has-text("ketqua_${U}.pdf") code`, (e) => e.textContent.replace("…", ""));
  if (!sha(PDF).startsWith(shown)) throw new Error(`checksum hiển thị ${shown} không khớp SHA-256 thật ${sha(PDF).slice(0, 10)}`);
});
await T.step("K2 tải xuống: nhận ĐÚNG nội dung tệp đã lưu (đã mã hóa khi lưu, giải mã khi tải)", async () => {
  const [dl] = await Promise.all([nur.waitForEvent("download"), nur.click(`tbody tr:has-text("ketqua_${U}.pdf") button:has-text("Tải xuống")`)]);
  const got = fs.readFileSync(await dl.path());
  if (!got.equals(PDF)) throw new Error("nội dung tải xuống khác tệp gốc");
  if (dl.suggestedFilename() !== `ketqua_${U}.pdf`) throw new Error("tên tệp tải xuống sai");
});
await T.step("K3 chặn tệp không hợp lệ: sai định dạng thật, mã độc (EICAR), quá 10 MB", async () => {
  await upload(nur, { name: `gia_pdf_${U}.pdf`, buffer: Buffer.from("MZ đây là tệp thực thi đổi đuôi .pdf") }); await toast(nur, "Chỉ chấp nhận PDF/PNG/JPEG");
  await nur.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(nur);
  await upload(nur, { name: `eicar_${U}.pdf`, buffer: Buffer.concat([PDF, Buffer.from("EICAR-STANDARD-ANTIVIRUS-TEST-FILE")]) }); await toast(nur, "chống mã độc");
  await nur.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(nur);
  await upload(nur, { name: `lon_${U}.pdf`, buffer: Buffer.concat([PDF, Buffer.alloc(10 * 1024 * 1024 + 10, 48)]) }); await toast(nur, "vượt 10MB");
  await nur.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(nur);
  await mustNotContain(nur, "tbody", `gia_pdf_${U}`, `eicar_${U}`, `lon_${U}`);
});
await T.step("K4 thay thế → bản v2 hợp lệ, bản v1 'đã có bản thay thế'; đánh dấu 'không hợp lệ' kèm lý do (không xóa tệp gốc)", async () => {
  const v2 = Buffer.concat([PDF, Buffer.from(" bản thay thế")]);
  await nur.click(`tbody tr:has-text("ketqua_${U}.pdf") button:has-text("Thay thế")`); await modalOpen(nur, "Thay thế tài liệu");
  await nur.setInputFiles('.modal input[type="file"]', { name: `ketqua_${U}_v2.pdf`, mimeType: "application/pdf", buffer: v2 }); await modalSubmit(nur, "Tải lên"); await toast(nur, "Đã tải lên");
  await nur.waitForSelector(`tbody tr:has-text("ketqua_${U}_v2.pdf") .badge:has-text("Hợp lệ")`); await mustContain(nur, `tbody tr:has-text("ketqua_${U}_v2.pdf")`, "v2");
  await nur.waitForSelector(`tbody tr:has-text("ketqua_${U}.pdf"):not(:has-text("v2")) .badge:has-text("Đã có bản thay thế")`);
  await nur.click(`tbody tr:has-text("ketqua_${U}_v2.pdf") button:has-text("Không hợp lệ")`); await ask(nur, "Nhầm người bệnh", "Đánh dấu tài liệu không hợp lệ");
  await toast(nur, "Đã đánh dấu không hợp lệ"); await nur.waitForSelector(`tbody tr:has-text("ketqua_${U}_v2.pdf") .badge:has-text("Không hợp lệ")`);
  const docs = await ok("doctor1", "GET", `/documents?person_id=${P.id}`); if (docs.length !== 2) throw new Error("tệp gốc không được xóa");
  const [dl] = await Promise.all([nur.waitForEvent("download"), nur.click(`tbody tr:has-text("ketqua_${U}.pdf"):not(:has-text("v2")) button:has-text("Tải xuống")`)]);
  if (!fs.readFileSync(await dl.path()).equals(PDF)) throw new Error("bản cũ phải còn nguyên để truy vết");
});
await T.step("K5 phân quyền tài liệu: cán bộ tiếp nhận không có tab; bác sĩ Trại 2 bị chặn (403); mọi lần xem/tải có nhật ký", async () => {
  const off = await T.login("officer1");
  if ((await off.$$eval(".side .nav", (e) => e.map((x) => x.textContent))).some((x) => x.includes("Tài liệu"))) throw new Error("cán bộ tiếp nhận không được thấy tab Tài liệu");
  if ((await api("officer1", "GET", `/documents?person_id=${P.id}`)).status !== 403) throw new Error("API tài liệu phải trả 403 cho cán bộ tiếp nhận");
  const id = (await ok("doctor1", "GET", `/documents?person_id=${P.id}`))[0].id;
  if ((await api("doctor2", "GET", `/documents/${id}/download`)).status !== 403) throw new Error("bác sĩ cơ sở khác phải bị 403");
  const a = (await ok("admin", "GET", `/audit?person_id=${P.id}&limit=500`)).map((x) => x.action);
  for (const need of ["document_uploaded", "document_download", "document_invalidated", "access_denied"]) if (!a.includes(need)) throw new Error(`thiếu nhật ký ${need}`);
});

// =============================================================== M10 báo cáo
const mgr = await T.login("manager1");
const mgr2 = await T.login("manager2");
const tile = async (page, label) => Number(await page.$eval(`.kpi:has-text("${label}") b`, (e) => e.textContent.replace(/\D/g, "")));
await T.step("L1 báo cáo lượt khám: đếm LƯỢT khác đếm NGƯỜI; chỉ tính cơ sở của mình (UAT-12)", async () => {
  await nav(mgr, "Báo cáo & Thống kê"); await mgr.click('.kcard:has-text("Tình hình khám chữa bệnh")'); await mgr.waitForSelector('.kpi:has-text("Tổng số lượt khám")');
  await nav(mgr2, "Báo cáo & Thống kê"); await mgr2.click('.kcard:has-text("Tình hình khám chữa bệnh")'); await mgr2.waitForSelector('.kpi:has-text("Tổng số lượt khám")');
  const [e0, p0, f0] = [await tile(mgr, "Tổng số lượt khám"), await tile(mgr, "Số người đã khám"), await tile(mgr2, "Tổng số lượt khám")];
  const px = await managedPerson(nm("Báo Cáo Người Mới"));            // 1 người mới (đã có 1 lượt khám ban đầu) …
  await startEncounter(px.id); await startEncounter(px.id);           // … + 2 lượt phát sinh => +3 lượt, +1 người
  await mgr.click('button:has-text("Xem báo cáo")'); await mgr.waitForTimeout(800);
  const [e1, p1] = [await tile(mgr, "Tổng số lượt khám"), await tile(mgr, "Số người đã khám")];
  if (e1 - e0 !== 3 || p1 - p0 !== 1) throw new Error(`mong đợi +3 lượt/+1 người, thực tế +${e1 - e0} lượt/+${p1 - p0} người`);
  await mgr2.click('button:has-text("Xem báo cáo")'); await mgr2.waitForTimeout(800);
  if ((await tile(mgr2, "Tổng số lượt khám")) !== f0) throw new Error("báo cáo Trại 2 không được tính lượt khám của Trại 1");
});
await T.step("L2 mọi báo cáo còn lại hiển thị được (không lỗi) và lọc theo khoảng ngày hoạt động", async () => {
  for (const r of ["Khám sức khỏe định kỳ", "Quản lý bệnh lý", "Cấp phát thuốc", "Chuyển viện", "Theo dõi & cảnh báo"]) {
    await mgr.click(`.kcard:has-text("${r}")`); await mgr.waitForTimeout(700);
    if (await mgr.$('.toast[style*="185, 28, 28"], .toast[style*="#b91c1c"]')) throw new Error(`báo cáo “${r}” báo lỗi`);
    if ((await mgr.$$(".split .kpi, .split table.tbl, .split .empty")).length === 0) throw new Error(`báo cáo “${r}” không có số liệu hiển thị`);
  }
  await mgr.click('.kcard:has-text("Tình hình khám chữa bệnh")');
  console.log("    [dbg] date inputs:", await mgr.$$eval('input[type="date"]', (e) => e.map((x) => `${x.value}|${x.disabled}|${x.readOnly}`)), "url:", mgr.url());
  await mgr.fill('input[type="date"] >> nth=0', "2001-01-01"); await mgr.fill('input[type="date"] >> nth=1', "2001-01-31"); await mgr.click('button:has-text("Xem báo cáo")');
  await mgr.waitForFunction(() => document.querySelector('.kpi b')?.textContent.trim() === "0");
});
await T.step("L3 xuất CSV: bắt buộc nêu mục đích; tệp đúng định dạng; có nhật ký 'report_exported'", async () => {
  await mgr.click('.kcard:has-text("Tình hình khám chữa bệnh")'); await mgr.fill('input[type="date"] >> nth=0', ""); await mgr.fill('input[type="date"] >> nth=1', ""); await mgr.click('button:has-text("Xem báo cáo")');
  await mgr.click('button:has-text("Xuất CSV")'); await modalOpen(mgr, "Xuất dữ liệu");
  await dialogOk(mgr); await mgr.waitForTimeout(300);
  if (!(await mgr.$('.modal-bg:has-text("Xuất dữ liệu")'))) throw new Error("xuất được khi chưa nêu mục đích");
  await mgr.fill('.modal [name="v"]', "Báo cáo tháng gửi cấp trên");
  const [dl] = await Promise.all([mgr.waitForEvent("download"), dialogOk(mgr)]);
  const csv = fs.readFileSync(await dl.path(), "utf8"); if (!csv.startsWith("metric,value") || !csv.includes("total_encounters")) throw new Error("CSV sai định dạng");
  if (!(await ok("admin", "GET", "/audit?action=report_exported")).some((a) => a.reason === "Báo cáo tháng gửi cấp trên")) throw new Error("thiếu nhật ký xuất dữ liệu kèm mục đích");
});
await T.step("L4 điều dưỡng không có tab Báo cáo; API báo cáo trả 403", async () => {
  if ((await nur.$$eval(".side .nav", (e) => e.map((x) => x.textContent))).some((x) => x.includes("Báo cáo"))) throw new Error("điều dưỡng không được thấy tab Báo cáo");
  if ((await api("nurse1", "GET", "/reports/encounters")).status !== 403) throw new Error("API báo cáo phải trả 403");
});

// =============================================================== M11 quản trị
const adm = await T.login("admin");
const NEWUSER = `e2e_${U}`;
await T.step("M1 tạo người dùng: mật khẩu yếu bị từ chối; hợp lệ → đăng nhập được; khóa → không đăng nhập; mở khóa → đăng nhập lại", async () => {
  await nav(adm, "Quản trị hệ thống");
  await adm.click('button:has-text("+ Tạo người dùng")'); await modalOpen(adm, "Tạo người dùng");
  await adm.fill('.modal [name="username"]', NEWUSER); await adm.fill('.modal [name="full_name"]', "Điều dưỡng E2E");
  await adm.selectOption('.modal [name="role"]', { label: "Điều dưỡng" }); await adm.selectOption('.modal [name="facility_id"]', { label: "Trại giam số 1" });
  await adm.fill('.modal [name="password"]', "ngan"); await modalSubmit(adm, "Lưu"); await toast(adm, "Mật khẩu tối thiểu 10 ký tự");
  await adm.fill('.modal [name="password"]', "Abcdefghij1"); await modalSubmit(adm, "Lưu"); await toast(adm, "Đã tạo tài khoản");
  await adm.waitForSelector(`tbody tr:has-text("${NEWUSER}")`); await mustContain(adm, `tbody tr:has-text("${NEWUSER}")`, "Điều dưỡng", "Hoạt động");
  const login = (pw) => fetch(`${process.env.BASE || "http://localhost:8000"}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: NEWUSER, password: pw }) });
  if ((await login("Abcdefghij1")).status !== 200) throw new Error("tài khoản mới phải đăng nhập được");
  await adm.click(`tbody tr:has-text("${NEWUSER}") button:has-text("Khóa")`); await dialogOk(adm); await toast(adm, "Đã cập nhật");
  await adm.waitForSelector(`tbody tr:has-text("${NEWUSER}") .badge:has-text("Đã khóa")`);
  if ((await login("Abcdefghij1")).status !== 401) throw new Error("tài khoản bị khóa không được đăng nhập");
  await adm.click(`tbody tr:has-text("${NEWUSER}") button:has-text("Mở khóa")`); await dialogOk(adm);
  await adm.waitForSelector(`tbody tr:has-text("${NEWUSER}") .badge:has-text("Hoạt động")`);      // chờ trạng thái thật (toast cũ có thể còn hiện)
  if ((await login("Abcdefghij1")).status !== 200) throw new Error("mở khóa xong phải đăng nhập lại được");
});
await T.step("M2 đổi vai trò có hiệu lực ngay (phiên cũ bị thu hồi)", async () => {
  const tok = (await (await fetch(`${process.env.BASE || "http://localhost:8000"}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: NEWUSER, password: "Abcdefghij1" }) })).json()).access_token;
  await adm.click(`tbody tr:has-text("${NEWUSER}") button:has-text("Đổi vai trò")`); await modalOpen(adm, "Đổi vai trò");
  await adm.selectOption('.modal [name="role"]', { label: "Quản lý y tế" }); await modalSubmit(adm, "Lưu"); await toast(adm, "Đã cập nhật");
  await adm.waitForSelector(`tbody tr:has-text("${NEWUSER}"):has-text("Quản lý y tế")`);
  const me = await fetch(`${process.env.BASE || "http://localhost:8000"}/api/auth/me`, { headers: { authorization: `Bearer ${tok}` } });
  if (me.status !== 401) throw new Error("token cũ phải bị thu hồi sau khi đổi vai trò");
});
await T.step("M3 ma trận phân quyền: quản trị hệ thống KHÔNG có 'Xem dữ liệu lâm sàng'; bác sĩ có", async () => {
  await tab(adm, "Ma trận phân quyền"); await adm.waitForSelector("table.matrix");
  const m = await adm.$eval("table.matrix", (t) => {
    const heads = [...t.querySelectorAll("thead th")].map((h) => h.innerText.trim());
    const row = [...t.querySelectorAll("tbody tr")].find((r) => r.cells[0].innerText.startsWith("Xem dữ liệu lâm sàng"));
    return Object.fromEntries(heads.slice(1).map((h, i) => [h.toLowerCase(), row.cells[i + 1].innerText.includes("✓")]));   // CSS in hoa tiêu đề cột
  });
  if (m["quản trị hệ thống"] !== false) throw new Error("quản trị hệ thống không được đọc dữ liệu lâm sàng");
  if (m["bác sĩ"] !== true || m["cán bộ tiếp nhận"] !== false) throw new Error("ma trận quyền lâm sàng sai: " + JSON.stringify(m));
});
await T.step("M4 danh mục có phiên bản: thêm v1 → cập nhật v2 (một dòng hiện hành); thuốc mới dùng được khi kê đơn", async () => {
  const code = `E2E${U.toUpperCase()}`;
  await tab(adm, "Danh mục"); await seg(adm, "Thuốc");
  await adm.click('button:has-text("+ Thêm / cập nhật")'); await modalOpen(adm, "Thêm mục danh mục");
  await adm.fill('.modal [name="code"]', code); await adm.fill('.modal [name="name"]', `Thuốc thử ${U} 100mg`); await modalSubmit(adm, "Lưu"); await toast(adm, "Đã lưu");
  await adm.waitForSelector(`tbody tr:has-text("${code}"):has-text("v1")`);
  const e = await startEncounter(P.id);
  const r = await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_code: code, drug_name: `Thuốc thử ${U} 100mg`, dose: "1", route: "uống", frequency: "1/ngày", start_date: new Date().toISOString().slice(0, 10), duration_days: 3, quantity_prescribed: 3 });
  if (r.status !== 201) throw new Error("thuốc vừa thêm phải kê được: " + JSON.stringify(r.data));
  await adm.click(`tbody tr:has-text("${code}") button:has-text("Cập nhật")`); await modalOpen(adm, `Cập nhật ${code}`);
  await adm.fill('.modal [name="name"]', `Thuốc thử ${U} 200mg`); await modalSubmit(adm, "Lưu"); await toast(adm, "Đã lưu");
  await adm.waitForSelector(`tbody tr:has-text("${code}"):has-text("v2")`);
  if ((await adm.$$(`tbody tr:has-text("${code}")`)).length !== 1) throw new Error("chỉ được hiện phiên bản hiện hành");
  const bad = await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_code: "KHONG_CO_" + U, drug_name: "Thuốc lạ", dose: "1", route: "uống", frequency: "1/ngày", start_date: new Date().toISOString().slice(0, 10), duration_days: 3, quantity_prescribed: 3 });
  if (bad.status !== 422) throw new Error("mã thuốc không có trong danh mục phải bị từ chối (422)");
});
await T.step("M5 nhật ký kiểm toán: lọc theo hành động/người; kiểm tra toàn vẹn chuỗi hash", async () => {
  await tab(adm, "Nhật ký kiểm toán");
  await adm.fill('[name="action"]', "user_created"); await adm.click('button:has-text("Lọc")'); await adm.waitForSelector(`tbody tr:has-text("user_created")`);
  await mustContain(adm, "tbody", NEWUSER.slice(0, 4)); await mustNotContain(adm, "tbody", "login_failed");
  await adm.fill('[name="action"]', ""); await adm.fill('[name="actor"]', "admin"); await adm.click('button:has-text("Lọc")'); await adm.waitForSelector("tbody tr");
  await adm.click('button:has-text("Kiểm tra toàn vẹn chuỗi nhật ký")'); await adm.waitForSelector('.banner:has-text("Chuỗi nhật ký toàn vẹn")');
});
await T.step("M6 khóa tài khoản sau 5 lần sai mật khẩu → quản trị nhận thông báo bảo mật", async () => {
  for (let i = 0; i < 5; i++) await fetch(`${process.env.BASE || "http://localhost:8000"}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: NEWUSER, password: "sai-mat-khau" }) });
  const r = await fetch(`${process.env.BASE || "http://localhost:8000"}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: NEWUSER, password: "Abcdefghij1" }) });
  if (r.status !== 423) throw new Error(`mong đợi 423 (khóa tạm), nhận ${r.status}`);
  const n = (await ok("admin", "GET", "/notifications?limit=100")).items; if (!n.some((x) => x.kind === "security.lockout" && x.body.includes(NEWUSER))) throw new Error("quản trị phải nhận thông báo khóa tài khoản");
});
await T.step("M7 vai trò khác không vào được Quản trị (tab ẩn; API 403); quản trị không đọc được bệnh án", async () => {
  if ((await nur.$$eval(".side .nav", (e) => e.map((x) => x.textContent))).some((x) => x.includes("Quản trị"))) throw new Error("điều dưỡng không được thấy tab Quản trị");
  if ((await api("nurse1", "GET", "/users")).status !== 403) throw new Error("API người dùng phải trả 403");
  if ((await api("admin", "GET", `/persons/${P.id}/health-summary`)).status !== 403) throw new Error("quản trị không được đọc hồ sơ sức khỏe");
});

process.exit((await T.done()).length ? 1 : 0);
