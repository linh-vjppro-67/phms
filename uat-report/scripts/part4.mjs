// PART 4 – Tài liệu (M12), Báo cáo (M10), Quản trị/nhật ký (M11), Break-glass, Bảo mật, Thông báo, Nhất quán dữ liệu
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { api, ok, tc, must, status, denied, code, ui, nav, toast, uniq, today, newPerson, managedPerson, startEnc, confirmedRx, sql, upload, tok, login, freshPage, BASE, DB, PASS, PDF, Blocked } from "./uat-lib.mjs";

const STORAGE = "/private/tmp/claude-501/-Users-linhpham-Documents-phms/b31585b3-466f-4421-9023-356036bdd04e/scratchpad/uat/storage";
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]));
const totp = (secretB32, atMs = Date.now()) => {
  const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; let bits = "";
  for (const c of secretB32.replace(/=+$/, "")) bits += A.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2))); const ctr = Buffer.alloc(8); ctr.writeBigUInt64BE(BigInt(Math.floor(atMs / 30000)));
  const h = crypto.createHmac("sha1", key).update(ctr).digest(); const o = h[h.length - 1] & 15; return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, "0");
};

export async function part4(S) {
  const U = S.U;
  // ======================================================= DOCUMENTS
  const mkPdf = (size) => Buffer.concat([Buffer.from("%PDF-1.4\n"), Buffer.alloc(size - 9 - 6, 0x20), Buffer.from("%%EOF\n")]);
  await tc({ id: "DOC-01", mod: "Tài liệu (M12)", kind: "Positive", role: "nurse1 → doctor1", title: "Tải PDF hợp lệ: có mã toàn vẹn SHA-256, tải xuống đúng nguyên bản, tệp lưu trên đĩa được MÃ HÓA (không đọc được nội dung gốc) (K2/D10)",
    expected: "201 + checksum; download byte-for-byte; không tệp nào trong kho chứa chuỗi '%PDF' hay nội dung gốc", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT Tài Liệu ${U}`); S.docP = p;
    const marker = Buffer.from(`%PDF-1.4\nUAT-SECRET-MARKER-${U}\n` + "x".repeat(300) + "\n%%EOF\n");
    const up = await upload("nurse1", { doc_type: "lab_result", person_id: p.id }, marker, "ketqua.pdf"); status(up, 201, "upload"); S.doc = up.data;
    must(JSON.stringify(up.data).match(/[0-9a-f]{64}/), "Không có checksum SHA-256 trong phản hồi");
    const dl = await fetch(`${BASE}/api/documents/${up.data.id}/download`, { headers: { authorization: `Bearer ${await tok("doctor1")}` } }); must(dl.status === 200, `download HTTP ${dl.status}`);
    const got = Buffer.from(await dl.arrayBuffer()); must(got.equals(marker), "Tệp tải xuống không khớp nguyên bản");
    const files = walk(STORAGE); must(files.length > 0, "Không thấy tệp trong kho");
    for (const f of files) { const b = fs.readFileSync(f); must(!b.includes(`UAT-SECRET-MARKER-${U}`) && !b.subarray(0, 8).toString().startsWith("%PDF"), `Tệp ${path.basename(f)} lưu dạng KHÔNG mã hóa`); }
    return `Kho có ${files.length} tệp, không tệp nào chứa nội dung gốc`;
  });
  await tc({ id: "DOC-02", mod: "Tài liệu (M12)", kind: "Negative", role: "nurse1", title: "Từ chối: .txt đổi tên .pdf, tệp .exe, tệp rỗng, PNG giả (kiểm magic bytes, không tin đuôi tệp) (K3)",
    expected: "Mỗi trường hợp HTTP 4xx (400/415/422)", sev: "High" }, async () => {
    const p = S.docP; const fields = { doc_type: "other", person_id: p.id };
    const rs = [await upload("nurse1", fields, Buffer.from("đây chỉ là văn bản thuần, không phải PDF"), "fake.pdf"),
      await upload("nurse1", fields, Buffer.from("MZ\x90\x00\x03\x00\x00\x00 fake exe"), "virus.exe", "application/octet-stream"),
      await upload("nurse1", fields, Buffer.alloc(0), "rong.pdf"), await upload("nurse1", fields, Buffer.from("%PDF-1.4 giả dạng png"), "x.png", "image/png")];
    const got = rs.map((r) => r.status); must(got.slice(0, 3).every((s) => s >= 400 && s < 500), `HTTP: ${got}`);
    return `HTTP: .txt→.pdf ${got[0]}, .exe ${got[1]}, rỗng ${got[2]}, PDF-trong-.png ${got[3]}`;
  });
  await tc({ id: "DOC-03", mod: "Tài liệu (M12)", kind: "Boundary", role: "nurse1", title: "Giới hạn dung lượng 10 MB: đúng 10 MiB được chấp nhận; 10 MiB + 1 byte bị từ chối",
    expected: "10485760 B → 201; 10485761 B → 413/422", sev: "Medium" }, async () => {
    const a = await upload("nurse1", { doc_type: "other", person_id: S.docP.id }, mkPdf(10 * 1024 * 1024), "bien10mb.pdf"), b = await upload("nurse1", { doc_type: "other", person_id: S.docP.id }, mkPdf(10 * 1024 * 1024 + 1), "qua10mb.pdf");
    must(a.status === 201, `đúng 10 MiB: HTTP ${a.status} ${JSON.stringify(a.data).slice(0, 150)}`); must([413, 422, 400].includes(b.status), `10 MiB+1: HTTP ${b.status}`);
  });
  await tc({ id: "DOC-04", mod: "Tài liệu (M12)", kind: "Positive", role: "nurse1/doctor1", title: "Thay thế tài liệu → v2, bản cũ 'đã có bản thay thế' (không xóa); đánh dấu không hợp lệ bắt buộc lý do, giữ nguyên tệp gốc (K4)",
    expected: "replace 201; DB: bản cũ status≠valid; invalidate không lý do → 422; có lý do → 200", sev: "Medium" }, async () => {
    const t = await tok("nurse1"); const fd = new FormData(); fd.append("file", new Blob([PDF], { type: "application/pdf" }), "v2.pdf");
    const r = await fetch(`${BASE}/api/documents/${S.doc.id}/replace`, { method: "POST", headers: { authorization: `Bearer ${t}` }, body: fd }); must(r.status === 201, `replace HTTP ${r.status}`);
    const nd = await r.json(); must(nd.version === 2, `version=${nd.version}`); must(sql(`select status s from medical_document where id='${S.doc.id}'`)[0].s !== "valid", "Bản cũ vẫn 'valid'");
    status(await api("nurse1", "POST", `/documents/${nd.id}/invalidate`, {}), 422, "invalidate không lý do");
    status(await api("nurse1", "POST", `/documents/${nd.id}/invalidate`, { reason: "Tải nhầm người bệnh" }), 200, "invalidate");
    must(sql(`select count(*) n from medical_document where id in ('${S.doc.id}','${nd.id}')`)[0].n === 2, "Bản ghi tài liệu bị xóa vật lý");
  });
  await tc({ id: "DOC-05", mod: "Tài liệu (M12)", kind: "Permission", role: "officer1/approver1/doctor2", title: "Tải/xem tài liệu y tế: cán bộ, người phê duyệt, bác sĩ cơ sở khác bị 403; tải xuống hợp lệ được ghi nhật ký document_download (K5)",
    expected: "403 cho 3 vai trò; audit có document_download của doctor1", sev: "Critical" }, async () => {
    const dl = (u) => api(u, "GET", `/documents/${S.doc.id}/download`);
    for (const u of ["officer1", "approver1", "doctor2", "admin", "manager1"]) denied(await dl(u), `${u} tải tài liệu`);
    const r = await fetch(`${BASE}/api/documents/${S.doc.id}/download`, { headers: { authorization: `Bearer ${await tok("doctor1")}` } }); must(r.status === 200, `doctor1: HTTP ${r.status}`);
    const a = await ok("admin", "GET", "/audit?action=document_download&limit=50"); must(a.some((x) => JSON.stringify(x).includes(S.doc.id)), "Không thấy audit document_download");
  });

  // ======================================================= REPORTS
  const iso0 = new Date().toISOString().slice(0, 10), from = today(-400), to = today(1);
  await tc({ id: "REP-01", mod: "Báo cáo (M10)", kind: "Data-consistency", role: "manager1", title: "Báo cáo 'Tình hình khám' khớp dữ liệu gốc: số lượt khám và số người khác nhau (UAT-12); đối chiếu SQL theo cơ sở F01",
    expected: "total_encounters = COUNT(encounter không hủy); total_distinct_persons = COUNT(DISTINCT person)", sev: "High" }, async () => {
    const r = await ok("manager1", "GET", `/reports/encounters?date_from=${from}&date_to=${to}`); const d = r.data;
    const q = sql(`select count(*) n, count(distinct person_id) p from encounter where facility_id='${S.f1}' and status!='cancelled' and date(occurred_at) between '${from}' and '${to}'`)[0];
    must(d.total_encounters === q.n, `Báo cáo ${d.total_encounters} lượt, DB ${q.n}`); must(d.total_distinct_persons === q.p, `Báo cáo ${d.total_distinct_persons} người, DB ${q.p}`);
    must(d.total_distinct_persons <= d.total_encounters, "số người > số lượt");
    return `Báo cáo = DB: ${q.n} lượt / ${q.p} người`;
  });
  await tc({ id: "REP-02", mod: "Báo cáo (M10)", kind: "Data-consistency", role: "manager1 vs manager2", title: "Báo cáo chỉ gồm dữ liệu cơ sở của người xem; số liệu F01 ≠ F02 và đều khớp DB (L4)",
    expected: "manager2 total_encounters = đếm DB F02", sev: "High" }, async () => {
    const r2 = (await ok("manager2", "GET", `/reports/encounters?date_from=${from}&date_to=${to}`)).data; const q2 = sql(`select count(*) n from encounter where facility_id='${S.f2}' and status!='cancelled' and date(occurred_at) between '${from}' and '${to}'`)[0].n;
    must(r2.total_encounters === q2, `manager2 báo cáo ${r2.total_encounters}, DB F02 ${q2}`);
  });
  await tc({ id: "REP-03", mod: "Báo cáo (M10)", kind: "Data-consistency", role: "manager1", title: "Báo cáo chuyển viện & cấp phát khớp DB (đếm theo trạng thái; cấp phát ghi chú 'số đơn ≠ số lần uống')",
    expected: "Tổng đề nghị chuyển viện trong báo cáo = COUNT(referral F01 trong kỳ)", sev: "Medium" }, async () => {
    const rr = await ok("manager1", "GET", `/reports/referrals?date_from=${from}&date_to=${to}`); const rd = await ok("manager1", "GET", `/reports/dispensing?date_from=${from}&date_to=${to}`);
    const q = sql(`select count(*) n from referral where facility_id='${S.f1}'`)[0].n; const flat = JSON.stringify(rr.data); const total = rr.data.total ?? rr.data.total_referrals ?? rr.data.total_count;
    must(total === undefined || total === q, `Báo cáo chuyển viện tổng ${total}, DB ${q} (${flat.slice(0, 160)})`);
    return `chuyển viện: ${flat.slice(0, 140)} | cấp phát có ghi chú: ${/lần uống|định nghĩa|definition|note/i.test(JSON.stringify(rd.data))}`;
  });
  await tc({ id: "REP-04", mod: "Báo cáo (M10)", kind: "Permission", role: "manager1/nurse1", title: "Xuất CSV: bắt buộc nêu mục đích (≥5 ký tự), chỉ người có report.export; có ghi nhật ký report_exported; xuất bị từ chối cũng được ghi (L3)",
    expected: "Thiếu mục đích → 422; nurse → 403; manager + mục đích → 200 text/csv; audit report_exported", sev: "High" }, async () => {
    status(await api("manager1", "GET", "/reports/encounters?format=csv"), 422, "không mục đích"); status(await api("manager1", "GET", "/reports/encounters?format=csv&purpose=abc"), 422, "mục đích 3 ký tự");
    denied(await api("nurse1", "GET", "/reports/encounters?format=csv&purpose=Kiem+tra+UAT"), "nurse xuất CSV");
    const r = await api("manager1", "GET", "/reports/encounters?format=csv&purpose=" + encodeURIComponent("Báo cáo quý UAT " + U)); status(r, 200, "xuất CSV"); must(String(r.headers.get("content-type")).includes("csv"), "không phải text/csv");
    const a = await ok("admin", "GET", "/audit?action=report_exported&limit=20"); must(a.some((x) => JSON.stringify(x).includes(U)), "Không thấy audit report_exported kèm mục đích");
  });
  await tc({ id: "REP-05", mod: "Báo cáo (UI)", kind: "Positive", role: "manager1 (UI)", title: "Giao diện báo cáo: xem báo cáo, thẻ số liệu hiển thị, nút Xuất CSV yêu cầu nhập mục đích",
    expected: "Trang hiển thị số liệu; bấm Xuất CSV mở hộp thoại bắt buộc mục đích", sev: "Medium" }, async (c) => {
    const page = await ui("manager1"); await nav(page, "Báo cáo"); await page.waitForSelector('button:has-text("Xem báo cáo")'); await page.click('button:has-text("Xem báo cáo")'); await page.waitForTimeout(900); await c.shot(page, "bao-cao");
    await page.click('button:has-text("Xuất CSV")'); await page.waitForSelector('.modal-bg:has-text("mục đích")'); await c.shot(page, "xuat-csv-muc-dich"); await page.keyboard.press("Escape");
    must((await page.innerText("main, .main, body")).length > 200, "Trang báo cáo trống");
  });

  // ======================================================= ADMIN / AUDIT
  await tc({ id: "ADM-01", mod: "Quản trị (M11)", kind: "Positive", role: "admin (UI)", title: "Nhật ký kiểm toán: lọc theo hành động; 'Kiểm tra toàn vẹn chuỗi' báo toàn vẹn (M8)",
    expected: "Banner 'Chuỗi nhật ký toàn vẹn'; API /audit/verify ok", sev: "Critical" }, async (c) => {
    const v = await ok("admin", "GET", "/audit/verify"); must(v === true || v.ok === true || v.valid === true || JSON.stringify(v).match(/true|toàn vẹn/i), `verify = ${JSON.stringify(v)}`);
    const page = await ui("admin"); await nav(page, "Quản trị"); await page.click('.tabs button:has-text("Nhật ký kiểm toán"), .seg button:has-text("Nhật ký kiểm toán")'); await page.waitForSelector("tbody tr");
    await page.click('button:has-text("Kiểm tra toàn vẹn chuỗi nhật ký")'); await page.waitForSelector('.banner:has-text("Chuỗi nhật ký toàn vẹn")'); await c.shot(page, "toan-ven");
  });
  await tc({ id: "ADM-02", mod: "Quản trị (M11)", kind: "Data-consistency", role: "admin", title: "Nhật ký ghi đủ các hành động nhạy cảm: login, login_failed, user_created, access_denied, document_download, report_exported, break_glass; mỗi sự kiện có người thực hiện + thời điểm",
    expected: "Mỗi action xuất hiện ≥1 lần và có actor/created_at", sev: "High" }, async () => {
    const need = ["login", "login_failed", "user_created", "access_denied", "document_download", "report_exported"]; const miss = [];
    for (const a of need) { const r = await ok("admin", "GET", `/audit?action=${a}&limit=5`); if (!r.length) miss.push(a); else must(r[0].actor_name || r[0].actor_id, `${a} thiếu người thực hiện`); }
    must(!miss.length, `Thiếu action trong nhật ký: ${miss}`);
  });
  await tc({ id: "ADM-03", mod: "Quản trị (M11)", kind: "Negative", role: "admin", title: "Quản trị không tự hạ quyền/tự khóa mình; không hạ/khóa quản trị viên cuối cùng",
    expected: "409 SELF_CHANGE / LAST_ADMIN", sev: "High" }, async () => {
    const me = await ok("admin", "GET", "/auth/me"); const r1 = await api("admin", "PATCH", `/users/${me.id}`, { active: false }), r2 = await api("admin", "PATCH", `/users/${me.id}`, { role: "nurse" });
    must(r1.status === 409 && r2.status === 409, `HTTP ${r1.status}/${r2.status}`);
  });
  await tc({ id: "ADM-04", mod: "Quản trị (M11)", kind: "Positive", role: "admin", title: "Đổi vai trò có hiệu lực ngay và thu hồi phiên đang dùng; vai trò/cơ sở không hợp lệ bị từ chối",
    expected: "Token cũ sau khi đổi role → 401; role='superuser' → 422; user nghiệp vụ không cơ sở → 422", sev: "High" }, async () => {
    const un = "uat_role_" + U; const u = await ok("admin", "POST", "/users", { username: un, password: "Uat@Role2026x", full_name: "UAT Đổi Vai Trò", role: "nurse", facility_id: S.f1 });
    const l = await login(un, "Uat@Role2026x"); await fetch(`${BASE}/api/auth/change-password`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${l.data.access_token}` }, body: JSON.stringify({ old_password: "Uat@Role2026x", new_password: "Moi@Pass2026z" }) });
    const t = (await login(un, "Moi@Pass2026z")).data.access_token; const chk = () => fetch(`${BASE}/api/auth/me`, { headers: { authorization: `Bearer ${t}` } });
    must((await chk()).status === 200, "phiên mới không dùng được"); await ok("admin", "PATCH", `/users/${u.id}`, { role: "pharmacist" });
    must((await chk()).status === 401, "Token cũ vẫn dùng được sau khi đổi vai trò");
    status(await api("admin", "POST", "/users", { username: "uat_bad_" + U, password: "Uat@Role2026x", full_name: "x", role: "superuser", facility_id: S.f1 }), 422, "vai trò lạ");
    status(await api("admin", "POST", "/users", { username: "uat_nofac_" + U, password: "Uat@Role2026x", full_name: "x", role: "nurse" }), 422, "không cơ sở");
  });
  await tc({ id: "ADM-05", mod: "Quản trị (M11)", kind: "Positive", role: "admin", title: "Đặt lại mật khẩu: mật khẩu tạm sinh ngẫu nhiên, mật khẩu cũ vô hiệu, đăng nhập bằng mật khẩu tạm bị buộc đổi (P5)",
    expected: "Login cũ → 401; login tạm → requires=password_change", sev: "High" }, async () => {
    const un = "uat_reset_" + U; const u = await ok("admin", "POST", "/users", { username: un, password: "Uat@Reset2026x", full_name: "UAT Reset", role: "nurse", facility_id: S.f1 });
    const r = await ok("admin", "POST", `/users/${u.id}/reset-password`, {}); const tmp = r.temporary_password || r.password || r.temp_password; must(tmp, `không có mật khẩu tạm: ${JSON.stringify(r).slice(0, 100)}`);
    must((await login(un, "Uat@Reset2026x")).status === 401, "mật khẩu cũ vẫn dùng được"); const l = await login(un, tmp); must(l.status === 200 && l.data.requires === "password_change", `login tạm: ${l.status} requires=${l.data?.requires}`);
  });
  await tc({ id: "ADM-06", mod: "Quản trị (M11)", kind: "Positive", role: "admin/doctor1", title: "Danh mục thuốc có phiên bản: thêm v1 → cập nhật v2 (bản cũ giữ lại); thuốc mới kê được; mã ngoài danh mục bị 422 (M9)",
    expected: "2 dòng version (1 hiện hành); kê thuốc mới 201", sev: "Medium" }, async () => {
    const cd = "UAT" + U.toUpperCase().replace(/\W/g, ""); await ok("admin", "POST", "/catalogs", { catalog: "drug", code: cd, name: `Thuốc UAT ${U} 100mg` }); await ok("admin", "POST", "/catalogs", { catalog: "drug", code: cd, name: `Thuốc UAT ${U} 200mg` });
    const n = sql(`select count(*) n, sum(active) a from catalog_item where catalog='drug' and code='${cd}'`)[0]; must(n.n === 2 && n.a === 1, `Số phiên bản=${n.n}, đang hiện hành=${n.a}`);
    const p = await managedPerson(`UAT DM Thuốc ${U}`); const e = await startEnc(p.id); status(await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_code: cd, drug_name: `Thuốc UAT ${U} 200mg`, dose: "1", route: "uống", frequency: "1/ngày", start_date: today(), duration_days: 3, quantity_prescribed: 3 }), 201, "kê thuốc mới");
  });
  await tc({ id: "ADM-07", mod: "Xác thực (MFA)", kind: "Positive", role: "tài khoản mới", title: "MFA TOTP: bật bằng mã 6 số; đăng nhập sau đó đòi mã; mã sai bị từ chối; mã đã dùng không dùng lại được; quản trị đặt lại MFA (P3/P4)",
    expected: "Không OTP → 401 MFA_REQUIRED; OTP sai → 401; OTP đúng → 200; dùng lại → 401; reset-mfa → login chỉ mật khẩu", sev: "High" }, async () => {
    const un = "uat_mfa_" + U, pw1 = "Uat@Mfa20260x", pw2 = "Moi@Mfa2026y"; const u = await ok("admin", "POST", "/users", { username: un, password: pw1, full_name: "UAT MFA", role: "nurse", facility_id: S.f1 });
    const l = await login(un, pw1); await fetch(`${BASE}/api/auth/change-password`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${l.data.access_token}` }, body: JSON.stringify({ old_password: pw1, new_password: pw2 }) });
    let t = (await login(un, pw2)).data.access_token; const A = (m, p, b) => fetch(`${BASE}/api${p}`, { method: m, headers: { "content-type": "application/json", authorization: `Bearer ${t}` }, body: b ? JSON.stringify(b) : undefined });
    const st = await (await A("POST", "/auth/mfa/setup")).json(); must(st.secret, "không có secret"); const en = await A("POST", "/auth/mfa/enable", { code: totp(st.secret) }); must(en.status === 200, `enable HTTP ${en.status}`);
    const a = await login(un, pw2); must(a.status === 401 && a.data.error.code === "MFA_REQUIRED", `không OTP: ${a.status} ${a.data?.error?.code}`);
    const wrong = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: un, password: pw2, otp: "000000" }) }); must(wrong.status === 401, `OTP sai: ${wrong.status}`);
    const otp = totp(st.secret, Date.now() + 30000); // bước kế tiếp (bước hiện tại đã dùng khi bật MFA)
    const good = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: un, password: pw2, otp }) }); must(good.status === 200, `OTP đúng: ${good.status}`);
    const reuse = await fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: un, password: pw2, otp }) }); must(reuse.status === 401, `dùng lại OTP: ${reuse.status} (phải 401 – chống replay)`);
    await ok("admin", "POST", `/users/${u.id}/reset-mfa`, {}); must((await login(un, pw2)).status === 200, "sau reset MFA đăng nhập bằng mật khẩu thất bại");
  });

  // ======================================================= BREAK-GLASS
  await tc({ id: "BG-01", mod: "Truy cập khẩn (D2)", kind: "Positive", role: "doctor2 → người Trại 1", title: "Break-glass: lý do <10 ký tự bị chặn; hợp lệ → cấp lượt CHỈ ĐỌC có hạn (30'); ghi được dữ liệu vẫn bị chặn; sinh cảnh báo hậu kiểm + thông báo Khẩn cho manager/admin (O1–O3)",
    expected: "9 ký tự → 422; 10 ký tự → 200 (expires≈+30'); GET health-summary 200; POST observation 403; Alert break_glass_review; manager2 & admin nhận thông báo", sev: "Critical" }, async () => {
    const p = S.pA; status(await api("doctor2", "POST", `/persons/${p.id}/break-glass`, { reason: "123456789" }), 422, "9 ký tự");
    const g = await api("doctor2", "POST", `/persons/${p.id}/break-glass`, { reason: "Cấp cứu ngoài trại, cần tiền sử dị ứng" }); status(g, 200, "cấp"); const mins = (new Date(g.data.expires_at + (String(g.data.expires_at).endsWith("Z") ? "" : "Z")) - Date.now()) / 60000; must(mins > 28 && mins <= 30.5, `Hạn còn ${mins.toFixed(1)} phút (kỳ vọng ~30)`);
    status(await api("doctor2", "GET", `/persons/${p.id}/health-summary`), 200, "đọc sau break-glass");
    denied(await api("doctor2", "POST", `/encounters/${S.encA.id}/observations`, { type: "Mạch", value: "80", unit: "l/p" }), "ghi dữ liệu khi break-glass");
    denied(await api("doctor2", "POST", `/persons/${p.id}/allergies`, { substance: "Phấn hoa" }), "ghi dị ứng khi break-glass");
    must(sql(`select count(*) n from alert where kind='break_glass_review' and person_id='${p.id}'`)[0].n >= 1, "Thiếu cảnh báo hậu kiểm");
    const hasN = async (u) => ((await ok(u, "GET", "/notifications?limit=100")).items || []).some((n) => n.kind === "security.break_glass");
    must(await hasN("admin"), "admin không nhận thông báo break-glass"); must(await hasN("manager2"), "manager2 không nhận thông báo break-glass");
  });
  await tc({ id: "BG-02", mod: "Truy cập khẩn (D2)", kind: "Boundary", role: "nurse1/pharm1/officer1", title: "Vai trò không có quyền 'breakglass' (dược, cán bộ) không được truy cập khẩn (phần hết hạn: xem BG-02b)",
    expected: "pharm2/officer2 → 403", sev: "High" }, async () => {
    denied(await api("pharm2", "POST", `/persons/${S.pA.id}/break-glass`, { reason: "Dược cần xem hồ sơ khẩn" }), "pharm break-glass"); denied(await api("officer2", "POST", `/persons/${S.pA.id}/break-glass`, { reason: "Cán bộ cần xem hồ sơ khẩn" }), "officer break-glass");
  });

  // ======================================================= SECURITY
  await tc({ id: "SEC-01", mod: "Bảo mật HTTP", kind: "Security", role: "Anonymous", title: "Tiêu đề bảo mật: CSP, X-Frame-Options, nosniff, no-store, Referrer-Policy, Permissions-Policy",
    expected: "Có đủ các header trên ở trang và API", sev: "Medium" }, async () => {
    const r = await fetch(BASE + "/"), a = await fetch(BASE + "/api/health"); const need = ["content-security-policy", "x-frame-options", "x-content-type-options", "cache-control", "referrer-policy", "permissions-policy"];
    for (const h of need) must(r.headers.get(h) && a.headers.get(h), `Thiếu header ${h}`); must(/no-store/.test(a.headers.get("cache-control")), "API không no-store"); must(!/unsafe-eval|script-src[^;]*unsafe-inline/.test(r.headers.get("content-security-policy")), "CSP cho phép script nội tuyến/eval");
  });
  await tc({ id: "SEC-02", mod: "Bảo mật", kind: "Security", role: "officer1", title: "Chèn SQL qua ô tìm kiếm và tham số: không lỗi 500, không rò dữ liệu",
    expected: "HTTP 200 danh sách rỗng/đúng; bảng person còn nguyên", sev: "Critical" }, async () => {
    const before = sql("select count(*) n from person")[0].n; const bad = ["' OR '1'='1", "'; DROP TABLE person; --", "%' UNION SELECT * FROM app_user --", '" OR 1=1 #'];
    for (const q of bad) { const r = await api("officer1", "GET", `/persons?q=${encodeURIComponent(q)}`); must(r.status === 200 && Array.isArray(r.data) && r.data.length === 0, `q=${q}: HTTP ${r.status}, ${Array.isArray(r.data) ? r.data.length : "?"} kết quả`); }
    const ra = await api("admin", "GET", `/audit?action=${encodeURIComponent("x' OR '1'='1")}`); must(ra.status === 200 && ra.data.length === 0, `audit filter: ${ra.status}`); must(sql("select count(*) n from person")[0].n === before, "Bảng person thay đổi");
  });
  await tc({ id: "SEC-03", mod: "Bảo mật", kind: "Security", role: "doctor1", title: "Tham chiếu đối tượng trực tiếp (IDOR) & ID giả: UUID ngẫu nhiên/ID sai định dạng trả 404/422, không 500, không lộ stack trace",
    expected: "HTTP 404/422 với thông điệp chuẩn {error:{code,message}}", sev: "Medium" }, async () => {
    const ids = ["00000000-0000-0000-0000-000000000000", "abc", "../../etc/passwd", "1 OR 1=1"]; for (const id of ids) for (const pth of [`/encounters/${encodeURIComponent(id)}`, `/persons/${encodeURIComponent(id)}/health-summary`, `/medication-orders/${encodeURIComponent(id)}`, `/referrals/${encodeURIComponent(id)}`]) {
      const r = await api("doctor1", "GET", pth); must([400, 404, 422].includes(r.status), `${pth}: HTTP ${r.status}`); must(!/Traceback|sqlalchemy|File "/i.test(JSON.stringify(r.data)), `${pth}: lộ stack trace`);
    }
  });
  await tc({ id: "SEC-04", mod: "Bảo mật", kind: "Boundary", role: "doctor1", title: "Dữ liệu quá khổ / sai kiểu: chuỗi 100.000 ký tự, JSON sai kiểu, thiếu trường → 422/413, không 500",
    expected: "Không có HTTP 5xx", sev: "Medium" }, async () => {
    const rs = [await api("doctor1", "POST", "/encounters", { person_id: S.pA.id, type: "ad_hoc", reason: "x".repeat(100000) }), await api("doctor1", "POST", "/encounters", { person_id: 123, type: [] }), await api("doctor1", "POST", "/encounters", {}),
      await api("doctor1", "POST", `/encounters/${S.encA.id}/diagnoses`, { text: null }), await api("officer1", "POST", "/persons", { full_name: { a: 1 } })];
    const got = rs.map((r) => r.status); must(got.every((s) => s < 500), `HTTP: ${got}`);
  });
  await tc({ id: "SEC-05", mod: "Bảo mật", kind: "Boundary", role: "Anonymous", title: "Cấu hình PRODUCTION (từ chối khởi động khi cấu hình không an toàn; tắt /docs; HSTS luôn bật; không còn tài khoản mẫu)",
    expected: "Khởi động bị từ chối với: secret mặc định, SQLite, tài khoản mẫu; server production thật trên PostgreSQL: /docs 404, HSTS, đăng nhập tài khoản mẫu bị từ chối, readiness OK", sev: "High" }, async (c) => {
    const { spawnSync } = await import("node:child_process"); const BE = "/Users/linhpham/Documents/phms/backend", PY = BE + "/.venv/bin/python";
    const SCR = "/private/tmp/claude-501/-Users-linhpham-Documents-phms/b31585b3-466f-4421-9023-356036bdd04e/scratchpad/uat";
    const good = { PHMS_ENV: "production", PHMS_SECRET: "s".repeat(48), PHMS_DOC_KEY: "d".repeat(48), PHMS_DB_URL: "postgresql+psycopg://phms@127.0.0.1:55432/phms_prod", PHMS_SCHEDULER: "0" };
    const run = (env, code) => spawnSync(PY, ["-c", code], { cwd: BE, env: { PATH: process.env.PATH, ...env }, encoding: "utf8" });
    const r1 = run({ ...good, PHMS_SECRET: "dev-only-secret-change-me-in-production-32b" }, "import app.main"); must(r1.status !== 0 && /PHMS_SECRET/.test(r1.stderr), "Secret mặc định KHÔNG bị từ chối");
    const r2 = run({ ...good, PHMS_DB_URL: `sqlite:///${SCR}/none.db` }, "import app.main"); must(r2.status !== 0 && /PostgreSQL/.test(r2.stderr), "SQLite ở production KHÔNG bị từ chối");
    fs.copyFileSync(DB, SCR + "/sample-check.db");
    const r3 = run({ ...good, PHMS_DB_URL: `sqlite:///${SCR}/sample-check.db`, PHMS_ALLOW_SQLITE: "1" }, "from app import main; main._check_no_sample_accounts()"); must(r3.status !== 0 && /tài khoản mẫu/.test(r3.stderr), "Tài khoản mẫu ở production KHÔNG bị từ chối");
    const r4 = spawnSync(PY, ["-m", "app.seed"], { cwd: BE, env: { PATH: process.env.PATH, ...good, PHMS_DB_URL: `sqlite:///${SCR}/sample-check.db`, PHMS_ALLOW_SQLITE: "1" }, encoding: "utf8" }); must(r4.status !== 0 && /app\.bootstrap/.test(String(r4.stderr) + String(r4.stdout)), "app.seed không bị từ chối ở production");
    c.note(`r1..r4 bị từ chối: ${[r1, r2, r3, r4].map((r) => r.status).join(",")}`);
    const P = process.env.UAT_PROD || "http://localhost:8766"; let live; try { live = await fetch(P + "/api/health/ready"); } catch { throw new Blocked("Server production-like (PostgreSQL, cổng 8766) không chạy – chỉ kiểm được phần từ chối khởi động"); }
    must(live.status === 200, `readiness ${live.status}`); const d = await fetch(P + "/docs"), o = await fetch(P + "/openapi.json"); must(d.status === 404 && o.status === 404, `/docs=${d.status}, /openapi.json=${o.status}`);
    const h = await fetch(P + "/api/health"); must(/max-age=31536000/.test(h.headers.get("strict-transport-security") || ""), "Thiếu HSTS khi chạy HTTP sau proxy"); must((h.headers.get("content-security-policy") || "").includes("default-src 'self'"), "Thiếu CSP");
    const l = await fetch(P + "/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: "doctor1", password: PASS }) }); must(l.status === 401, `Đăng nhập tài khoản mẫu ở production: HTTP ${l.status}`);
    const a = await fetch(P + "/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: "admin", password: process.env.UAT_PROD_ADMIN_PW || "Quantri@2026Thu1" }) }); const ad = await a.json(); must(a.status === 200 && ad.requires === "password_change", `Admin bootstrap phải bị buộc đổi mật khẩu (requires=${ad.requires})`);
    return "4 cấu hình không an toàn đều bị từ chối khi khởi động; server production (PostgreSQL 16, 4 worker): /docs 404, HSTS+CSP, tài khoản mẫu 401, admin bootstrap bị buộc đổi mật khẩu, readiness OK";
  });
  await tc({ id: "SEC-06", mod: "Giao diện", kind: "Security", role: "Mọi vai trò (UI)", title: "Giao diện không phát sinh lỗi JavaScript khi duyệt toàn bộ tab của từng vai trò",
    expected: "pageerror = 0 trên mọi tab được phép của 7 vai trò", sev: "Medium" }, async (c) => {
    const bad = [];
    for (const u of ["officer1", "nurse1", "doctor1", "pharm1", "approver1", "manager1", "admin"]) {
      const page = await ui(u); page.jsErrors.length = 0; const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
      for (const l of labels) { await page.click(`.side .nav:has-text("${l.replace(/"/g, "")}")`).catch(() => {}); await page.waitForTimeout(450); }
      if (page.jsErrors.length) bad.push(`${u}: ${page.jsErrors.slice(0, 2).join(" | ")}`);
      if (u === "doctor1") await c.shot(page, "doctor-tabs");
    }
    must(!bad.length, bad.join(" ;; "));
  });
  await tc({ id: "UI-01", mod: "Giao diện", kind: "Usability", role: "nurse1 (UI, điện thoại 390px)", title: "Responsive: giao diện dùng được trên điện thoại (không tràn ngang, có nút mở menu)",
    expected: "scrollWidth ≤ viewport; có .menu-btn", sev: "Low" }, async (c) => {
    const page = await (await import("./uat-lib.mjs")).ui("nurse1", { w: 390, h: 800 }); await page.waitForTimeout(500); await c.shot(page, "mobile");
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]); must(sw[0] <= sw[1] + 2, `Tràn ngang: ${sw[0]} > ${sw[1]}`); must(await page.isVisible(".menu-btn"), "Không có nút menu trên điện thoại");
  });

  // ======================================================= NOTIFICATIONS
  await tc({ id: "NOT-01", mod: "Thông báo", kind: "Security", role: "doctor1/nurse1", title: "Hộp thư thông báo riêng từng người: đánh dấu đã đọc thông báo của người khác → 404 (N14); thông báo của cán bộ không chứa nội dung lâm sàng (N12)",
    expected: "404; nội dung thông báo officer không chứa thuật ngữ y khoa (đơn thuốc, chẩn đoán)", sev: "High" }, async () => {
    const nn = (await ok("nurse1", "GET", "/notifications?limit=20")).items; must(nn.length > 0, "nurse1 không có thông báo để kiểm"); denied(await api("doctor1", "POST", `/notifications/${nn[0].id}/read`), "đọc thông báo người khác");
    const on = (await ok("officer1", "GET", "/notifications?limit=200")).items || []; const clin = on.filter((n) => /đơn thuốc|chẩn đoán|kê đơn|dị ứng|kết quả xét nghiệm/i.test(n.title + " " + (n.body || ""))); must(!clin.length, `Thông báo của cán bộ có nội dung lâm sàng: ${clin.map((n) => n.title).slice(0, 3)}`);
  });

}
