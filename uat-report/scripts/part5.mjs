// PART 5 – UAT đầu-cuối trên giao diện (bác sĩ/bàn giao/cấp cứu) + kiểm thử khám phá (đồng thời, ngoại lệ, cách ly, toàn vẹn)
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { api, ok, tc, must, status, denied, code, ui, nav, toast, uniq, today, iso, newPerson, managedPerson, startEnc, confirmedRx, sql, upload, tok, login, freshPage, BASE, DB, OUT, Blocked, PDF } from "./uat-lib.mjs";

const dialogOk = (p) => p.click('.modal-bg footer button:has-text("Đồng ý")');
const modalOpen = (p, t) => p.waitForSelector(`.modal-bg:has-text("${t}")`);
const modalSubmit = (p, l) => p.click(`.modal-bg footer button:has-text("${l}")`);

export async function part5(S) {
  const U = S.U;
  // ===================================================== UI đầu-cuối
  await tc({ id: "UI-02", mod: "Khám ban đầu (UI)", kind: "Positive", role: "doctor1 (UI)", title: "Bác sĩ thực hiện khám ban đầu 6 bước trên giao diện: dị ứng → sinh hiệu → chẩn đoán → kê đơn → hẹn tái khám → hoàn tất (B1, WF-01)",
    expected: "Banner 'Khám ban đầu đã hoàn tất'; đợt tiếp nhận 'Đang quản lý'; đơn thuốc 'Đang hiệu lực'; có lịch tái khám", sev: "Critical" }, async (c) => {
    const p = await newPerson(`UAT Khám UI ${U}`); const page = await ui("doctor1"); await page.reload(); await page.waitForSelector(".side .nav"); await nav(page, "Khám ban đầu");
    await page.waitForSelector('button:has-text("Bắt đầu khám")'); await page.click(`tr:has-text("${p.full_name}") button:has-text("Bắt đầu khám")`); await page.waitForSelector('.step.cur:has-text("Tiền sử & dị ứng")'); await c.shot(page, "b0-bat-dau");
    await page.click('button:has-text("Xác nhận không có dị ứng")'); await dialogOk(page); await page.waitForSelector('.badge:has-text("Đã xác nhận không dị ứng")'); await c.shot(page, "b1-di-ung"); await page.click('button:has-text("Tiếp tục →")');
    await page.fill('input[name="pulse"]', "80"); await page.fill('input[name="sys"]', "150"); await page.fill('input[name="dia"]', "95"); await page.click('button:has-text("Ghi nhận sinh hiệu")'); await page.waitForSelector('td:has-text("150 mmHg")'); await c.shot(page, "b2-sinh-hieu"); await page.click('button:has-text("Tiếp tục →")');
    await page.fill('textarea[name="summary"]', "Tăng huyết áp, cần theo dõi."); await page.click('button:has-text("Lưu")'); await page.fill('input[name="text"]', "Tăng huyết áp vô căn"); await page.selectOption('select[name="kind"]', "final"); await page.click('button:has-text("Thêm chẩn đoán")'); await page.waitForSelector('td:has-text("Tăng huyết áp vô căn")'); await c.shot(page, "b3-chan-doan"); await page.click('button:has-text("Tiếp tục →")');
    await page.click('button:has-text("+ Kê đơn")'); await page.fill('.modal input[name="drug_name"]', "Amlodipine 5mg"); await page.click('.modal footer button:has-text("Tạo đơn nháp")'); await page.waitForSelector('td:has-text("Chờ xác nhận")'); await page.click('table button:has-text("Xác nhận")'); await page.waitForSelector('td .badge:has-text("Đang hiệu lực")'); await c.shot(page, "b4-ke-don"); await page.click('button:has-text("Tiếp tục →")');
    await page.click('button:has-text("+ Hẹn tái khám")'); await page.fill('.modal input[name="due_date"]', today(14)); await page.click('.modal footer button:has-text("Lưu")'); await page.waitForSelector('.badge:has-text("tái khám")'); await c.shot(page, "b5-hen"); await page.click('button:has-text("Tiếp tục →")');
    await c.shot(page, "b6-checklist"); await page.click('button:has-text("Hoàn tất khám ban đầu")'); await dialogOk(page); await page.waitForSelector('.banner:has-text("Khám ban đầu đã hoàn tất")'); await c.shot(page, "b7-hoan-tat");
    must(sql(`select status s from custody_stay where id='${p.stay.id}'`)[0].s === "managed", "Đợt tiếp nhận không chuyển 'managed'");
    must(sql(`select count(*) n from appointment where person_id='${p.id}' and status in ('scheduled','due')`)[0].n >= 1, "Không có lịch tái khám");
  });
  await tc({ id: "UI-03", mod: "Chuyển trại (UI)", kind: "Cross-dept", role: "officer1 → nurse1 → officer1 (UI)", title: "Chuyển trại trên giao diện: cán bộ khởi tạo → điều dưỡng soạn tóm tắt → cán bộ xác nhận (không thấy nội dung y tế) (J1–J4)",
    expected: "Phiếu 4 bước; nút Xác nhận chặn khi thiếu tóm tắt; cán bộ không thấy nội dung tóm tắt; xác nhận xong stay 'transferred'", sev: "High" }, async (c) => {
    const p = await managedPerson(`UAT Bàn Giao UI ${U}`); const off = await ui("officer1"), nur = await ui("nurse1");
    await off.reload(); await off.waitForSelector(".side .nav"); await nav(off, "Chuyển trại & Bàn giao"); await off.click('button:has-text("+ Khởi tạo bàn giao")'); await modalOpen(off, "Khởi tạo bàn giao");
    await off.selectOption('.modal [name="stay_id"]', { label: `${p.full_name} (${p.code})` }); await off.selectOption('.modal [name="to_facility_id"]', { label: "Trại giam số 2" }); await off.fill('.modal [name="reason"]', "Quyết định điều chuyển UAT"); await c.shot(off, "j1-khoi-tao");
    await modalSubmit(off, "Khởi tạo"); await toast(off, "Đã khởi tạo phiếu bàn giao"); await off.waitForSelector(`.card:has-text("${p.full_name}")`);
    await off.click(`.card:has-text("${p.full_name}") button:has-text("Xác nhận bàn giao")`); await modalOpen(off, "Xác nhận bàn giao"); await modalSubmit(off, "Xác nhận đã bàn giao"); await toast(off, "Chưa có bản tóm tắt y tế"); await c.shot(off, "j2-chan-thieu-tom-tat");
    await off.click('.modal-bg footer button:has-text("Hủy")');
    await nur.reload(); await nur.waitForSelector(".side .nav"); await nav(nur, "Chuyển trại & Bàn giao"); await nur.click(`.card:has-text("${p.full_name}") button:has-text("Soạn tóm tắt y tế")`); await modalOpen(nur, "Tóm tắt y tế bàn giao");
    await nur.fill('.modal [name="summary"]', "Huyết áp ổn định, không dị ứng, không đang điều trị. BÍ-MẬT-" + U); await modalSubmit(nur, "Lưu"); await toast(nur, "Đã lưu tóm tắt bàn giao"); await c.shot(nur, "j3-tom-tat");
    await off.reload(); await off.waitForSelector(".side .nav"); await nav(off, "Chuyển trại & Bàn giao"); await off.waitForSelector(`.card:has-text("${p.full_name}")`);
    must(!(await off.innerText(`.card:has-text("${p.full_name}")`)).includes("BÍ-MẬT-" + U), "Cán bộ tiếp nhận ĐỌC ĐƯỢC nội dung tóm tắt y tế trên giao diện"); await c.shot(off, "j3-can-bo-khong-doc-duoc");
    await off.click(`.card:has-text("${p.full_name}") button:has-text("Xác nhận bàn giao")`); await modalOpen(off, "Xác nhận bàn giao"); await off.fill('.modal [name="receiver_name"]', "Cán bộ Trại 2"); await modalSubmit(off, "Xác nhận đã bàn giao"); await toast(off, "Đã xác nhận bàn giao"); await c.shot(off, "j4-xac-nhan");
    must(sql(`select status s from custody_stay where id='${p.stay.id}'`)[0].s === "transferred", "stay không 'transferred'");
  });
  await tc({ id: "UI-04", mod: "Cấp cứu (UI)", kind: "Positive", role: "nurse1 → doctor1 (UI)", title: "Cấp cứu trên giao diện: điều dưỡng ghi nhận tối thiểu (chưa rõ danh tính) → hồ sơ tạm; bác sĩ đóng sớm bị chặn kèm lý do cụ thể (I1/I4)",
    expected: "Thẻ sự kiện 'Danh tính tạm – cần đối soát'; đóng sớm → thông báo 'chưa hoàn tất hồ sơ… chưa được đối soát'", sev: "Critical" }, async (c) => {
    const TEMP = `Nam khoảng 35 tuổi, buồng ${U}`; const nur = await ui("nurse1"), doc = await ui("doctor1"); await nur.reload(); await nur.waitForSelector(".side .nav"); await nav(nur, "Cấp cứu");
    await nur.click('button:has-text("+ Ghi nhận cấp cứu")'); await modalOpen(nur, "Ghi nhận cấp cứu"); await nur.fill('.modal [name="temp_identity"]', TEMP); await nur.fill('.modal [name="location"]', "Buồng 9, khu C"); await c.shot(nur, "i1-ghi-nhan");
    await modalSubmit(nur, "Ghi nhận & mở hồ sơ"); await toast(nur, "Đã ghi nhận sự kiện cấp cứu"); await nur.waitForSelector('.drawer .badge:has-text("Đang khám")'); await c.shot(nur, "i1-ho-so-tam"); await nur.click('.drawer-bg header .btn:has-text("Quay lại")');
    await nur.waitForSelector(`.card:has-text("${TEMP}")`); must(/Danh tính tạm/.test(await nur.innerText(`.card:has-text("${TEMP}")`)), "Thiếu nhãn 'Danh tính tạm'");
    await doc.reload(); await doc.waitForSelector(".side .nav"); await nav(doc, "Cấp cứu"); await doc.waitForSelector(`.card:has-text("${TEMP}")`); await doc.click(`.card:has-text("${TEMP}") button:has-text("Đóng sự kiện")`); await modalOpen(doc, "Đóng sự kiện cấp cứu");
    await doc.fill('.modal [name="note"]', "Thử đóng sớm"); await modalSubmit(doc, "Đóng sự kiện"); await toast(doc, "Chưa đủ điều kiện đóng sự kiện cấp cứu"); await c.shot(doc, "i4-chan-dong-som"); await doc.click('.modal-bg footer button:has-text("Hủy")');
  });

  // ===================================================== KHÁM PHÁ: đồng thời
  const par = (n, f) => Promise.all(Array.from({ length: n }, (_, i) => f(i)));
  await tc({ id: "EXP-01", mod: "Đồng thời", kind: "Concurrency", role: "doctor1/officer1", title: "6 yêu cầu ĐỒNG THỜI tạo khám ban đầu cho cùng một đợt tiếp nhận: chỉ 1 thành công (không nhân đôi lượt khám ban đầu)",
    expected: "Đúng 1 HTTP 201; DB có 1 encounter initial không hủy", sev: "High" }, async () => {
    const p = await newPerson(`UAT Đồng Thời Khám ${U}`); const rs = await par(6, () => api("doctor1", "POST", "/encounters", { person_id: p.id, type: "initial", reason: "Khám ban đầu song song" }));
    const n = sql(`select count(*) n from encounter where person_id='${p.id}' and type='initial' and status!='cancelled'`)[0].n; must(n === 1, `Có ${n} lượt khám ban đầu (HTTP ${rs.map((r) => r.status)})`);
    must(rs.every((r) => r.status < 500), `Có lỗi 5xx: ${rs.map((r) => r.status)}`);
  });
  await tc({ id: "EXP-02", mod: "Đồng thời", kind: "Concurrency", role: "officer1", title: "5 yêu cầu đồng thời tạo đợt tiếp nhận cho cùng người: chỉ 1 đợt hoạt động",
    expected: "Đúng 1 stay received/managed", sev: "High" }, async () => {
    const p = await newPerson(`UAT Đồng Thời Kỳ ${U}`, { stay: false }); const rs = await par(5, () => api("officer1", "POST", `/persons/${p.id}/stays`, {}));
    const n = sql(`select count(*) n from custody_stay where person_id='${p.id}' and status in ('received','managed')`)[0].n; must(n === 1, `${n} đợt hoạt động (HTTP ${rs.map((r) => r.status)})`); must(rs.every((r) => r.status < 500), `5xx: ${rs.map((r) => r.status)}`);
  });
  await tc({ id: "EXP-03", mod: "Đồng thời", kind: "Concurrency", role: "officer1", title: "5 yêu cầu đồng thời tạo hồ sơ với CÙNG mã nguồn: chỉ 1 hồ sơ (BR-01)",
    expected: "DB có đúng 1 person với mã đó; không lỗi 5xx", sev: "Critical" }, async () => {
    const ext = "UAT-RACE-" + U; const rs = await par(5, (i) => api("officer1", "POST", "/persons", { full_name: `UAT Race Tên ${i} ${U}`, source_system: "QLPN", external_id: ext, confirm_distinct: true }));
    const n = sql(`select count(*) n from person where external_id='${ext}'`)[0].n; must(n === 1, `${n} hồ sơ cùng mã (HTTP ${rs.map((r) => r.status)})`); must(rs.every((r) => r.status < 500), `5xx: ${rs.map((r) => r.status)}`);
  });
  await tc({ id: "EXP-04", mod: "Đồng thời", kind: "Concurrency", role: "officer1", title: "3 yêu cầu đồng thời tạo phiếu bàn giao cho cùng người: chỉ 1 phiếu 'chờ'",
    expected: "Đúng 1 handover pending", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Đồng Thời Bàn Giao ${U}`); const rs = await par(3, () => api("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind: "transfer", to_facility_id: S.f2, reason: "Song song" }));
    const n = sql(`select count(*) n from handover where stay_id='${p.stay.id}' and status='pending'`)[0].n; must(n === 1, `${n} phiếu chờ (HTTP ${rs.map((r) => r.status)})`);
  });
  await tc({ id: "EXP-05", mod: "Idempotency", kind: "Negative", role: "pharm1", title: "Dùng lại Idempotency-Key với NỘI DUNG KHÁC bị từ chối (không âm thầm trả kết quả cũ)",
    expected: "HTTP 422 IDEMPOTENCY_MISMATCH", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Idem Khác ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id); const k = "uat-mismatch-" + U;
    must((await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 5 }, { "Idempotency-Key": k })).status < 300, "lần 1"); const r = await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 9 }, { "Idempotency-Key": k });
    must(r.status === 422, `HTTP ${r.status} ${code(r)}`);
  });

  // ===================================================== KHÁM PHÁ: người đã rời cơ sở
  await tc({ id: "EXP-06", mod: "Chuyển trại (WF-07)", kind: "Negative", role: "doctor1/pharm1 (cơ sở cũ)", title: "Sau khi người đã chuyển sang Trại 2: cơ sở cũ không tạo lượt khám mới / không cấp phát đơn cũ cho người đó",
    expected: "Tạo lượt khám & cấp phát cho người đã chuyển trại bị chặn (người không còn trong quản lý của cơ sở)", sev: "High", unconfirmed: true }, async () => {
    const p = await managedPerson(`UAT Sau Chuyển Trại ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    const h = await ok("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind: "transfer", to_facility_id: S.f2, reason: "Điều chuyển" }); await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Đang dùng Paracetamol 15 ngày" });
    await ok("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true });
    const enc = await api("doctor1", "POST", "/encounters", { person_id: p.id, type: "ad_hoc", reason: "Khám sau khi đã chuyển trại" }); const dis = await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 5 });
    const inQ = (await ok("pharm1", "GET", "/dispense-queue")).some((x) => x.id === o.id);
    const bad = []; if (enc.status < 300) bad.push(`bác sĩ Trại 1 vẫn TẠO ĐƯỢC lượt khám mới (HTTP ${enc.status})`); if (dis.status < 300) bad.push(`dược sĩ Trại 1 vẫn CẤP PHÁT được (HTTP ${dis.status})`); if (inQ) bad.push("đơn vẫn nằm trong hàng đợi cấp phát của Trại 1");
    must(!bad.length, bad.join("; "));
  });
  await tc({ id: "EXP-07", mod: "Chuyển trại (WF-07)", kind: "Negative", role: "doctor1", title: "Người đã kết thúc quản lý (mãn hạn/ended): không tạo lượt khám mới khi chưa tái tiếp nhận",
    expected: "POST /encounters bị chặn (409/403/422) cho người không có đợt tiếp nhận hoạt động", sev: "Medium", unconfirmed: true }, async () => {
    const p = await managedPerson(`UAT Đã Ra Trại ${U}`); const h = await ok("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind: "release", reason: "Mãn hạn" }); await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Sức khỏe bình thường khi ra trại" }); await ok("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true });
    const r = await api("doctor1", "POST", "/encounters", { person_id: p.id, type: "ad_hoc", reason: "Khám người đã ra trại" }); must(r.status >= 400 && r.status < 500, `Tạo được lượt khám cho người đã ra trại: HTTP ${r.status}`);
  });
  await tc({ id: "EXP-08", mod: "Chuyển trại (WF-07)", kind: "Negative", role: "officer1", title: "Bàn giao: chuyển sang CHÍNH cơ sở hiện tại, thiếu cơ sở đích, hoặc cơ sở không tồn tại đều bị từ chối",
    expected: "HTTP 4xx cho cả 3 trường hợp", sev: "Medium" }, async () => {
    const mk = async (tag, body) => { const p = await managedPerson(`UAT BG Biên ${tag} ${U}`); return api("officer1", "POST", `/stays/${p.stay.id}/handover`, { reason: "Kiểm tra biên", ...body }); };
    const a = await mk("a", { kind: "transfer", to_facility_id: S.f1 }), b = await mk("b", { kind: "transfer" }), d = await mk("c", { kind: "transfer", to_facility_id: "00000000-0000-0000-0000-000000000000" });
    const got = [a, b, d].map((r) => r.status); must(got.every((s) => s >= 400 && s < 500), `HTTP (cùng cơ sở/thiếu đích/không tồn tại): ${got}`);
  });

  // ===================================================== KHÁM PHÁ: cách ly & rò rỉ
  await tc({ id: "EXP-09", mod: "Phân quyền (cơ sở)", kind: "Permission", role: "Người dùng Trại 2", title: "Mọi danh sách (alerts, lịch hẹn, hàng đợi cấp phát, chuyển viện, bàn giao, cấp cứu, lượt khám, đơn thuốc, kế hoạch, thông báo, báo cáo) của người Trại 2 KHÔNG chứa người bệnh của Trại 1",
    expected: "Không có id/họ tên người Trại 1 trong bất kỳ phản hồi nào", sev: "Critical" }, async () => {
    const marker = await managedPerson(`UAT Cách Ly Danh Sách ${U}`); const e = await startEnc(marker.id); await confirmedRx(e.id); await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "emergency", reason: "Cách ly thử", destination: "BV A" });
    await ok("nurse1", "POST", "/appointments", { person_id: marker.id, due_date: today(5), note: "x" }); await ok("nurse1", "POST", "/emergency-events", { person_id: marker.id, description: "cách ly" }).catch(() => {});
    const leaks = []; const paths = ["/alerts", "/appointments", "/dispense-queue", "/referrals", "/handovers", "/emergency-events", "/encounters", "/medication-orders", "/care-plans", "/stays", "/notifications?limit=300", "/checkup-rounds", "/dashboard"];
    for (const u of ["doctor2", "nurse2", "pharm2", "approver2", "manager2", "officer2"]) for (const pth of paths) {
      const r = await api(u, "GET", pth); if (r.status !== 200) continue; const s = JSON.stringify(r.data); if (s.includes(marker.id) || s.includes(marker.full_name)) leaks.push(`${u} ${pth}`);
    }
    must(!leaks.length, `Rò rỉ người bệnh Trại 1 sang Trại 2 qua: ${leaks.join(", ")}`);
  });
  await tc({ id: "EXP-10", mod: "Phân quyền (cơ sở)", kind: "Permission", role: "pharm2/approver2/manager2/doctor2", title: "Tra cứu danh tính liên cơ sở: chỉ vai trò cần đối soát trùng (cán bộ tiếp nhận) mới tìm được người của cơ sở khác; dược sĩ/phê duyệt/bác sĩ không nên liệt kê được danh tính toàn hệ thống",
    expected: "pharm2/approver2/doctor2 tìm tên người Trại 1 (chưa từng có quan hệ) → không thấy", sev: "Medium", unconfirmed: true }, async () => {
    const fresh = await managedPerson(`UAT Tra Cứu Riêng ${U}`);       // người CHƯA TỪNG có quan hệ/break-glass với Trại 2 (S.pA đã bị cấp break-glass ở ABAC nên không dùng được)
    const who = fresh.full_name; const res = {}; for (const u of ["officer2", "pharm2", "approver2", "doctor2", "nurse2"]) { const r = await api(u, "GET", `/persons?q=${encodeURIComponent(who)}`); res[u] = r.status === 200 ? r.data.length : r.status; }
    const bad = ["pharm2", "approver2", "doctor2", "nurse2"].filter((u) => res[u] > 0); must(!bad.length, `Người dùng Trại 2 tra cứu được danh tính người Trại 1: ${bad.map((u) => u + "=" + res[u]).join(", ")} (officer2=${res.officer2}, được phép theo BR-01 để đối soát trùng)`);
  });
  await tc({ id: "EXP-10b", mod: "Phân quyền (cơ sở)", kind: "Permission", role: "doctor2/pharm2/officer1", title: "Tình huống khẩn cấp: người có quyền break-glass tìm được người NGOÀI cơ sở chỉ bằng ĐÚNG mã nguồn, thông tin tối thiểu, có nhật ký; mở hồ sơ vẫn cần break-glass",
    expected: "doctor2: tên → 0; mã một phần → 0; mã đầy đủ → 1 bản ghi không có ngày sinh; pharm2 (không có quyền break-glass) → 0; GET /persons/{id} → 403; có audit person_lookup_out_of_scope", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Khẩn Cấp Mã ${U}`); const ext = p.external_id; must(ext, "người thử không có mã nguồn");
    const byName = await ok("doctor2", "GET", `/persons?q=${encodeURIComponent(p.full_name)}`); must(byName.length === 0, `Tìm theo tên thấy ${byName.length}`);
    const part = await ok("doctor2", "GET", `/persons?q=${encodeURIComponent(ext.slice(0, ext.length - 2))}`); must(!part.some((x) => x.id === p.id), "Mã một phần vẫn thấy");
    const full = await ok("doctor2", "GET", `/persons?q=${encodeURIComponent(ext)}`); must(full.length === 1 && full[0].id === p.id && full[0].out_of_scope === true, `Mã đầy đủ: ${full.length} kết quả`);
    must(full[0].date_of_birth === null, "Lộ ngày sinh trong tra cứu khẩn cấp");
    const ph = await ok("pharm2", "GET", `/persons?q=${encodeURIComponent(ext)}`); must(ph.length === 0, "Dược (không có quyền break-glass) thấy người ngoài cơ sở");
    denied(await api("doctor2", "GET", `/persons/${p.id}`), "mở danh tính khi chưa break-glass");
    const ev = sql(`select count(*) n from audit_event where action='person_lookup_out_of_scope' and person_id='${p.id}'`)[0].n; must(ev >= 1, "Không có nhật ký tra cứu khẩn cấp");
  });
  await tc({ id: "EXP-11", mod: "Bảo mật", kind: "Security", role: "officer1", title: "Gán hàng loạt (mass-assignment): gửi kèm status/id/created_by khi tạo hồ sơ không được ghi đè trạng thái xác minh",
    expected: "Hồ sơ không mã nguồn luôn 'pending_verification'; id do máy chủ cấp", sev: "High" }, async () => {
    const r = await api("officer1", "POST", "/persons", { full_name: `UAT Mass Assign ${U}`, status: "verified", id: "11111111-1111-1111-1111-111111111111", is_temporary: false, created_by: "x", merged_into_id: S.pA.id });
    if (r.status === 201) { must(r.data.status === "pending_verification", `status=${r.data.status}`); must(r.data.id !== "11111111-1111-1111-1111-111111111111", "client chọn được id"); }
    else must(r.status === 422 || r.status === 409, `HTTP ${r.status}`);
    const u = await api("admin", "POST", "/users", { username: "uat_ma_" + U, password: "Uat@Mass2026x", full_name: "x", role: "nurse", facility_id: S.f1, must_change_password: false, active: true, permissions: ["user.manage"], mfa_enabled: false });
    if (u.status === 201) { const l = await login("uat_ma_" + U, "Uat@Mass2026x"); must(l.data.requires === "password_change", "Mass-assignment tắt được bắt buộc đổi mật khẩu"); const me = await ok("admin", "GET", "/users"); must(!me.find((x) => x.username === "uat_ma_" + U).permissions.includes("user.manage"), "Gán được quyền user.manage"); }
  });
  await tc({ id: "EXP-12", mod: "Nguyên tắc BR-02", kind: "Security", role: "admin/doctor1", title: "Không có API xóa (DELETE) cho hồ sơ, lượt khám, đơn thuốc, tài liệu, chuyển viện, nhật ký (BR-02, NFR-07)",
    expected: "DELETE → 405/404 trên mọi tài nguyên", sev: "High" }, async () => {
    const ids = { persons: S.pA.id, encounters: S.encA.id, documents: S.doc.id, referrals: S.refDone.id, "medication-orders": S.rxDone.id, audit: "x", allergies: "x", handovers: "x", "emergency-events": "x" }; const bad = [];
    for (const [k, id] of Object.entries(ids)) for (const u of ["admin", "doctor1"]) { const r = await api(u, "DELETE", `/${k}/${id}`); if (![404, 405].includes(r.status)) bad.push(`${u} DELETE /${k}/{id} → ${r.status}`); }
    must(!bad.length, bad.join("; ")); must(sql("select count(*) n from person")[0].n > 0, "dữ liệu mất");
  });
  await tc({ id: "EXP-13", mod: "Nhật ký kiểm toán", kind: "Security", role: "DB (bản sao)", title: "Phát hiện can thiệp nhật ký: sửa 1 bản ghi audit trong BẢN SAO CSDL → verify_chain báo đứt chuỗi tại đúng vị trí",
    expected: "verify_chain = {ok:false, broken_at_seq: seq đã sửa}", sev: "Critical" }, async () => {
    const copy = OUT + "/audit-tamper-copy.db"; fs.copyFileSync(DB, copy); const seq = sql("select seq from audit_event order by seq limit 1 offset 50")[0].seq;
    execFileSync("sqlite3", [copy, `update audit_event set reason='bị sửa bởi UAT' where seq=${seq};`]);
    const py = `import sys; sys.path.insert(0,'/Users/linhpham/Documents/phms/backend')\nfrom app.db import SessionLocal\nfrom app.audit import verify_chain\nwith SessionLocal() as s: print(verify_chain(s))`;
    const out = execFileSync("/Users/linhpham/Documents/phms/backend/.venv/bin/python", ["-c", py], { cwd: OUT, env: { ...process.env, PHMS_DB_URL: "sqlite:///" + copy, PHMS_SCHEDULER: "0" }, encoding: "utf8" }).trim();
    fs.unlinkSync(copy); must(/'ok': False/.test(out) && out.includes(`'broken_at_seq': ${seq}`), `verify_chain trả: ${out} (seq đã sửa = ${seq})`); return `Bản sao bị sửa seq ${seq} → ${out}`;
  });
  await tc({ id: "EXP-14", mod: "Cấp cứu (WF-08)", kind: "Negative", role: "nurse1/nurse2", title: "Cấp cứu cho người đang ở cơ sở khác bị chặn (dùng break-glass); can thiệp vào sự kiện đã đóng bị chặn",
    expected: "ACTIVE_STAY_ELSEWHERE 409; thêm can thiệp vào sự kiện đã đóng → 409", sev: "Medium" }, async () => {
    status(await api("nurse2", "POST", "/emergency-events", { person_id: S.pA.id, description: "Cấp cứu người Trại 1 từ Trại 2" }), 409, "cấp cứu người cơ sở khác");
    const ev = await ok("nurse1", "POST", "/emergency-events", { person_id: (await managedPerson(`UAT Cấp Cứu Đóng ${U}`)).id, description: "Ngất" }); await ok("doctor1", "POST", `/encounters/${ev.encounter_id}/transition`, { to: "completed" });
    await ok("doctor1", "POST", `/emergency-events/${ev.id}/close`, { note: "Ổn định, đóng" }); const r = await api("nurse1", "POST", `/emergency-events/${ev.id}/interventions`, { action: "Can thiệp sau khi đóng" }); must(r.status === 409, `can thiệp sau đóng: HTTP ${r.status}`);
  });
  await tc({ id: "EXP-15", mod: "Chuyển viện (M09)", kind: "Negative", role: "doctor1/approver1", title: "Quy tắc chuyển viện: 'đi tắt' chỉ cho mức Cấp cứu; điều phối bắt buộc có cơ sở tiếp nhận",
    expected: "routine draft→in_external_treatment 409; coordinated không destination 422", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT CV Quy Tắc ${U}`); const e = await startEnc(p.id); const r1 = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "routine", reason: "Không có nơi tiếp nhận" });
    status(await api("doctor1", "PATCH", `/referrals/${r1.id}/status`, { to: "in_external_treatment" }), 409, "đi tắt cho mức routine"); await ok("doctor1", "PATCH", `/referrals/${r1.id}/status`, { to: "pending" });
    status(await api("approver1", "PATCH", `/referrals/${r1.id}/status`, { to: "coordinated" }), 422, "điều phối thiếu nơi tiếp nhận");
  });
  await tc({ id: "EXP-23", mod: "Khám (M04)", kind: "Negative", role: "doctor1", title: "Không ghi thêm chẩn đoán / chỉ định / đơn thuốc / đề nghị chuyển viện vào lượt khám đã HỦY (BR-02: hủy = đóng, không phát sinh dữ liệu mới)",
    expected: "Mọi thao tác ghi vào lượt đã hủy bị 409 ENCOUNTER_LOCKED (không để lại chuyển viện/đơn mồ côi)", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Ghi Vào Lượt Đã Hủy ${U}`); const e = await startEnc(p.id); await ok("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "cancelled", reason: "Nhập nhầm người bệnh" });
    const res = { "chẩn đoán": await api("doctor1", "POST", `/encounters/${e.id}/diagnoses`, { text: "Viêm họng cấp", kind: "final" }), "chỉ định XN": await api("doctor1", "POST", `/encounters/${e.id}/orders`, { kind: "lab", description: "Công thức máu" }),
      "đơn thuốc": await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1", route: "uống", frequency: "2/ngày", start_date: today(), duration_days: 5, quantity_prescribed: 10 }),
      "đề nghị chuyển viện": await api("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "routine", reason: "Lập trên lượt đã hủy", destination: "BV A" }) };
    const open = Object.entries(res).filter(([, r]) => r.status < 400).map(([k, r]) => `${k} (HTTP ${r.status})`); must(!open.length, `Vẫn ghi được vào lượt khám ĐÃ HỦY: ${open.join(", ")}`);
  });
  await tc({ id: "BG-03", mod: "Truy cập khẩn (D2)", kind: "Security", role: "doctor2 (break-glass) → tài liệu Trại 1", title: "Break-glass là CHỈ ĐỌC (mục 10.1/D2): người ngoài cơ sở đang có lượt break-glass không được tải lên / thay thế / vô hiệu hóa tài liệu y tế của người bệnh",
    expected: "Upload, replace, invalidate bởi người break-glass → 403 BREAKGLASS_READ_ONLY; tài liệu gốc vẫn 'valid'", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT BG Tài Liệu ${U}`); const d = await upload("nurse1", { doc_type: "lab_result", person_id: p.id }); status(d, 201, "tài liệu gốc");
    status(await api("doctor2", "POST", `/persons/${p.id}/break-glass`, { reason: "Cấp cứu ngoài trại cần xem hồ sơ" }), 200, "break-glass");
    const up = await upload("doctor2", { doc_type: "other", person_id: p.id }); const t = await tok("doctor2"); const fd = new FormData(); fd.append("file", new Blob([PDF], { type: "application/pdf" }), "bg-replace.pdf");
    const rp = await fetch(`${BASE}/api/documents/${d.data.id}/replace`, { method: "POST", headers: { authorization: `Bearer ${t}` }, body: fd }); const iv = await api("doctor2", "POST", `/documents/${d.data.id}/invalidate`, { reason: "vô hiệu bởi người break-glass" });
    const st = sql(`select group_concat(status) s from medical_document where person_id='${p.id}'`)[0].s; const bad = []; if (up.status < 300) bad.push("UPLOAD"); if (rp.status < 300) bad.push("REPLACE"); if (iv.status < 300) bad.push("INVALIDATE");
    must(!bad.length, `Break-glass 'chỉ đọc' nhưng vẫn ${bad.join(" + ")} được trên hồ sơ cơ sở khác (HTTP upload ${up.status}, replace ${rp.status}, invalidate ${iv.status}); trạng thái tài liệu trong DB: ${st}`);
  });
  await tc({ id: "EXP-24", mod: "Đồng thời", kind: "Concurrency", role: "doctor1", title: "3 yêu cầu đồng thời XÁC NHẬN cùng một đơn thuốc nháp: chỉ 1 thành công, không nhân đôi nhật ký/thông báo cấp phát (BR-06)",
    expected: "Đúng 1 HTTP 2xx (2 còn lại 409 NOT_DRAFT); đúng 1 audit medication_order_confirmed", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Đồng Thời Xác Nhận ${U}`); const e = await startEnc(p.id); const d = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1", route: "uống", frequency: "2/ngày", start_date: today(), duration_days: 5, quantity_prescribed: 10 });
    const c1 = await par(3, () => api("doctor1", "POST", `/medication-orders/${d.id}/confirm`, {})); const okc = c1.filter((r) => r.status < 300).length; const au = sql(`select count(*) n from audit_event where object_id='${d.id}' and action='medication_order_confirmed'`)[0].n;
    must(okc === 1 && au === 1, `${okc}/3 xác nhận thành công (HTTP ${c1.map((r) => r.status)}); ${au} bản ghi nhật ký 'confirmed' cho cùng một đơn`);
  });
  await tc({ id: "EXP-24b", mod: "Đồng thời", kind: "Concurrency", role: "doctor1", title: "3 yêu cầu đồng thời ĐIỀU CHỈNH cùng một đơn đã xác nhận: chỉ 1 phiên bản mới (không sinh nhiều bản nháp v2 song song)",
    expected: "Đúng 1 bản con (version 2) trong DB", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Đồng Thời Điều Chỉnh ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    const r1 = await par(3, () => api("doctor1", "POST", `/medication-orders/${o.id}/revise`, { dose: "2 viên", reason: "Điều chỉnh song song" })); const kids = sql(`select count(*) n from medication_order where parent_order_id='${o.id}'`)[0].n;
    must(kids === 1, `${kids} bản điều chỉnh v2 song song trong DB (HTTP ${r1.map((r) => r.status)})`);
  });
  await tc({ id: "EXP-25", mod: "Đồng thời", kind: "Concurrency", role: "approver1", title: "3 người cùng duyệt MỘT đề nghị chuyển viện: chỉ 1 thao tác thành công, lịch sử điều phối không ghi trùng bước",
    expected: "Đúng 1 HTTP 2xx; đúng 1 sự kiện pending→coordinated", sev: "Low" }, async () => {
    const p = await managedPerson(`UAT Đồng Thời CV ${U}`); const e = await startEnc(p.id); const r = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "routine", reason: "Song song", destination: "BV A" }); await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" });
    const a = await par(3, () => api("approver1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated", destination: "BV A" })); const ev = sql(`select count(*) n from referral_event where referral_id='${r.id}' and to_status='coordinated'`)[0].n;
    must(a.filter((x) => x.status < 300).length === 1 && ev === 1, `HTTP ${a.map((x) => x.status)}; ${ev} sự kiện 'coordinated' trong lịch sử`);
  });
  await tc({ id: "EXP-25b", mod: "Đồng thời", kind: "Concurrency", role: "officer1", title: "3 người cùng xác nhận MỘT phiếu bàn giao: chỉ 1 thành công, đợt tiếp nhận chuyển 'transferred' đúng một lần",
    expected: "Đúng 1 HTTP 2xx; 1 audit handover_confirmed", sev: "Medium" }, async () => {
    const p2 = await managedPerson(`UAT Đồng Thời BG ${U}`); const h = await ok("officer1", "POST", `/stays/${p2.stay.id}/handover`, { kind: "transfer", to_facility_id: S.f2, reason: "Song song" }); await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Tóm tắt y tế song song đủ dài" });
    const b = await par(3, () => api("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true })); const au = sql(`select count(*) n from audit_event where object_id='${h.id}' and action='handover_confirmed'`)[0].n;
    must(b.filter((x) => x.status < 300).length === 1 && au === 1, `HTTP ${b.map((x) => x.status)}; ${au} audit handover_confirmed`);
  });
  await tc({ id: "EXP-25c", mod: "Đồng thời", kind: "Concurrency", role: "manager1", title: "3 người cùng tiếp nhận MỘT cảnh báo: chỉ 1 người trở thành người chịu trách nhiệm (không 2 người cùng 'nhận')",
    expected: "Đúng 1 HTTP 2xx", sev: "Low" }, async () => {
    const m = await managedPerson(`UAT Đồng Thời Cảnh Báo ${U}`); const e = await startEnc(m.id); const r = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "emergency", reason: "Tạo cảnh báo", destination: "BV A" }); await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" });
    const al = sql(`select id from alert where dedupe_key='ref-review:${r.id}'`)[0].id; const c = await par(3, () => api("manager1", "POST", `/alerts/${al}/acknowledge`)); must(c.filter((x) => x.status < 300).length === 1, `HTTP ${c.map((x) => x.status)}`);
  });
  await tc({ id: "EXP-16", mod: "Bệnh lý (M08)", kind: "Boundary", role: "doctor1", title: "Kế hoạch theo dõi: chu kỳ 0, âm, rất lớn bị từ chối (không sinh lịch vô hạn / chia 0)",
    expected: "review_interval_days = 0, -1, 4000 → 422", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Chu Kỳ ${U}`); const pr = await ok("doctor1", "POST", `/persons/${p.id}/problems`, { name: "Tăng huyết áp vô căn", code: "I10" }); const got = [];
    for (const d of [0, -1, 4000]) got.push((await api("doctor1", "POST", `/persons/${p.id}/care-plans`, { problem_id: pr.id, goals: "HA<140/90", review_interval_days: d, measures: [{ name: "HA", unit: "mmHg" }] })).status);
    must(got.every((s) => s >= 400 && s < 500), `HTTP cho chu kỳ 0/-1/4000: ${got}`);
  });
  await tc({ id: "EXP-17", mod: "Kê đơn (M05)", kind: "Positive", role: "doctor1/nurse1", title: "Cảnh báo dị ứng: không phân biệt hoa/thường; dị ứng đã gỡ (retract) thì hết cảnh báo; 'đã gỡ' vẫn lưu vết, không xóa (BR-02)",
    expected: "AMOXICILLIN (hoa) vẫn cảnh báo; sau retract → không cảnh báo; bản ghi còn trong allergies_retracted", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Dị Ứng Hoa Thường ${U}`); const a = await ok("doctor1", "POST", `/persons/${p.id}/allergies`, { substance: "AMOXICILLIN", confirmed: true }); const e = await startEnc(p.id);
    const rx = { drug_name: "Amoxicillin 500mg", drug_code: "AMOX500", dose: "1", route: "uống", frequency: "2/ngày", start_date: today(), duration_days: 5, quantity_prescribed: 10 };
    const d1 = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rx); must(d1.warnings?.length > 0, "Dị ứng ghi HOA không cảnh báo khi kê tên thường"); await ok("doctor1", "POST", `/medication-orders/${d1.id}/stop`, { outcome: "cancelled" });
    await ok("doctor1", "POST", `/allergies/${a.id}/retract`, { reason: "Ghi nhầm người bệnh" }); const d2 = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rx); must(!d2.warnings?.length, "Đã gỡ dị ứng nhưng vẫn cảnh báo");
    const hs = await ok("doctor1", "GET", `/persons/${p.id}/health-summary`); must((hs.clinical.allergies_retracted || []).length === 1, "Không giữ vết dị ứng đã gỡ");
  });
  await tc({ id: "EXP-18", mod: "Tiếp nhận (M01)", kind: "Negative", role: "officer1/approver1", title: "Gộp hồ sơ: không tự gộp chính mình; chặn khi cả hai hồ sơ cùng có đợt tiếp nhận đang hiệu lực (D6)",
    expected: "source=target → 4xx; cả hai đang hoạt động → duyệt bị 409", sev: "High" }, async () => {
    const a = await managedPerson(`UAT Gộp Hai Kỳ ${U}`, { dob: "1979-09-09" }), b = await ok("officer1", "POST", "/persons", { full_name: `UAT Gộp Hai Kỳ ${U}`, date_of_birth: "1979-09-09", confirm_distinct: true }); await ok("officer1", "POST", `/persons/${b.id}/stays`, {});
    const self = await api("officer1", "POST", "/person-merges", { source_id: a.id, target_id: a.id, reason: "Tự gộp chính mình thử nghiệm" }); must(self.status >= 400 && self.status < 500, `tự gộp: HTTP ${self.status}`);
    const m = await api("officer1", "POST", "/person-merges", { source_id: b.id, target_id: a.id, reason: "Cùng họ tên ngày sinh, đối chiếu giấy tờ" }); if (m.status === 201) { const d = await api("approver1", "POST", `/person-merges/${m.data.id}/decision`, { approve: true }); must(d.status === 409, `duyệt gộp khi cả hai có kỳ hoạt động: HTTP ${d.status}`); } else must(m.status >= 400 && m.status < 500, `HTTP ${m.status}`);
    must(sql(`select status s from person where id='${b.id}'`)[0].s !== "merged", "Hồ sơ có đợt tiếp nhận hoạt động đã bị gộp");
  });
  await tc({ id: "EXP-19", mod: "Tài liệu (M12)", kind: "Permission", role: "doctor2/nurse1", title: "Tải tài liệu cho người bệnh Trại khác bị chặn; tài liệu gắn lượt khám của NGƯỜI KHÁC (lệch person_id/encounter_id) bị từ chối",
    expected: "doctor2 upload cho người Trại 1 → 403; upload person A + encounter của B → 4xx", sev: "High" }, async () => {
    const fx = await managedPerson(`UAT Tài Liệu Chéo Cơ Sở ${U}`);   // người Trại 1 CHƯA có lượt break-glass nào
    denied(await upload("doctor2", { doc_type: "other", person_id: fx.id }), "doctor2 upload cho người Trại 1");
    const b = await managedPerson(`UAT Tài Liệu Lệch ${U}`); const eb = await startEnc(b.id); const r = await upload("nurse1", { doc_type: "other", person_id: fx.id, encounter_id: eb.id }); must(r.status >= 400 && r.status < 500, `Upload lệch người/lượt khám: HTTP ${r.status} (dữ liệu y tế gắn sai người)`);
  });
  await tc({ id: "EXP-20", mod: "Xác thực", kind: "Negative", role: "tài khoản mới", title: "Đổi mật khẩu: sai mật khẩu cũ không bị đăng xuất; đặt lại đúng mật khẩu cũ bị chặn; mật khẩu yếu bị chặn; phiên cũ bị thu hồi sau khi đổi (P2)",
    expected: "Sai cũ → 401/422 và token còn dùng được; trùng cũ → 4xx; yếu → 422; sau đổi token cũ → 401", sev: "High" }, async () => {
    const un = "uat_pwd_" + U, p1 = "Uat@Pwd20260x", p2 = "Moi@Pwd2026y"; await ok("admin", "POST", "/users", { username: un, password: p1, full_name: "UAT Đổi MK", role: "nurse", facility_id: S.f1 });
    const l = await login(un, p1); const t0 = l.data.access_token; const ch = (t, o, n) => fetch(`${BASE}/api/auth/change-password`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${t}` }, body: JSON.stringify({ old_password: o, new_password: n }) });
    must((await ch(t0, p1, p2)).status === 200, "đổi lần đầu"); const t1 = (await login(un, p2)).data.access_token; const me = (t) => fetch(`${BASE}/api/auth/me`, { headers: { authorization: `Bearer ${t}` } });
    must((await ch(t1, "SaiMatKhauCu!1", "Khac@Pwd2026z")).status >= 400, "sai mật khẩu cũ phải bị từ chối"); must((await me(t1)).status === 200, "sai mật khẩu cũ làm mất phiên");
    must((await ch(t1, p2, p2)).status >= 400, "đặt lại đúng mật khẩu cũ phải bị chặn"); must((await ch(t1, p2, "yeu123")).status === 422, "mật khẩu yếu phải 422");
    must((await ch(t1, p2, "Khac@Pwd2026z")).status === 200, "đổi hợp lệ"); must((await me(t1)).status === 401, "phiên cũ chưa bị thu hồi sau khi đổi mật khẩu");
  });
  await tc({ id: "EXP-21", mod: "Độ bền API", kind: "Boundary", role: "officer1/admin", title: "Tham số phân trang bất thường (limit âm, chữ, rất lớn) không gây lỗi 500 và được giới hạn trần",
    expected: "Không HTTP 5xx; limit lớn bị cắt trần (≤ 500)", sev: "Low" }, async () => {
    const got = []; for (const l of ["-1", "abc", "0", "1000000", "1e9"]) { const r = await api("officer1", "GET", `/persons?limit=${l}`); got.push(r.status); if (r.status === 200) must(r.data.length <= 500, `limit=${l} trả ${r.data.length} dòng`); const a = await api("admin", "GET", `/audit?limit=${l}`); got.push(a.status); if (a.status === 200) must(a.data.length <= 500, `audit limit=${l} trả ${a.data.length}`); }
    must(got.every((s) => s < 500), `HTTP: ${got}`);
  });
  await tc({ id: "EXP-22", mod: "Dữ liệu sinh hiệu", kind: "Boundary", role: "nurse1", title: "Sinh hiệu: giá trị phi lý (nhiệt độ 370 °C, mạch -5, giá trị chữ) có bị kiểm soát miền giá trị không",
    expected: "YÊU CẦU CHƯA CÓ trong tài liệu (không nêu miền giá trị hợp lệ) – ghi nhận hiện trạng để BA quyết định", sev: "Low", unconfirmed: true }, async () => {
    const p = await managedPerson(`UAT Sinh Hiệu Phi Lý ${U}`); const e = await startEnc(p.id); const got = [];
    for (const [t, v, u] of [["Nhiệt độ", "370", "°C"], ["Mạch", "-5", "lần/phút"], ["Huyết áp tâm thu", "abc", "mmHg"]]) got.push((await api("nurse1", "POST", `/encounters/${e.id}/observations`, { type: t, value: v, unit: u })).status);
    must(got.every((s) => s === 422), `Hệ thống CHẤP NHẬN sinh hiệu phi lý (HTTP nhiệt độ 370/mạch -5/chữ = ${got}); không có kiểm soát miền giá trị`);
  });
}
