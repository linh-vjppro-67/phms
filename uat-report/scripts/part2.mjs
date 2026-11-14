// PART 2 – Tiếp nhận (WF-01/M01), Khám (M03/M04), Thuốc (M05/M06)
import { api, ok, tc, must, status, denied, code, ui, nav, toast, uniq, today, iso, newPerson, managedPerson, startEnc, confirmedRx, sql, Blocked, freshPage, BASE } from "./uat-lib.mjs";

export async function part2(S) {
  const U = S.U;
  // ======================================================= INTAKE
  await tc({ id: "INT-01", mod: "Tiếp nhận (M01)", kind: "Positive", role: "officer1 (UI)", title: "Tiếp nhận mới trọn 3 bước trên giao diện: kiểm tra trùng → tạo hồ sơ → xác nhận đợt tiếp nhận",
    expected: "Hồ sơ 'Đã xác minh', đợt tiếp nhận 'Mới tiếp nhận', khám ban đầu 'Chưa hoàn tất' (A1)", sev: "Critical" }, async (c) => {
    const page = await ui("officer1"); await nav(page, "Tiếp nhận & Hồ sơ");
    const name = `UAT Nguyễn Văn Mới ${U}`; S.intakeName = name;
    const field = (l) => page.locator(`.modal-bg label:has-text("${l}") input, .modal-bg label:has-text("${l}") select`).first();
    await page.click('button:has-text("+ Tiếp nhận mới")'); await page.waitForSelector('.modal-bg:has-text("Tiếp nhận mới")');
    await field("Họ và tên").fill(name); await field("Ngày sinh").fill("1991-01-01"); await field("Hệ thống nguồn").fill("QLPN"); await field("Mã phạm nhân").fill("UAT-" + U + "-A1");
    await c.shot(page, "b1-nhap"); await page.click('.modal-bg footer button:has-text("Kiểm tra & tiếp tục")');
    await page.waitForSelector('.modal-bg:has-text("Không tìm thấy hồ sơ trùng")'); await c.shot(page, "b2-kiem-tra-trung");
    await page.click('.modal-bg footer button:has-text("Tạo hồ sơ mới")'); await toast(page, "Đã tạo hồ sơ");
    await page.waitForSelector('.modal-bg:has-text("Đợt tiếp nhận")'); await page.click('.modal-bg footer button:has-text("Xác nhận tiếp nhận")'); await toast(page, "Đã xác nhận tiếp nhận mới");
    await page.click('.modal-bg footer button:has-text("Đóng")'); await page.waitForSelector(".modal-bg", { state: "detached" });
    const row = page.locator(`tbody tr:has-text("${name}")`).first(); await row.waitFor(); const txt = await row.innerText(); await c.shot(page, "danh-sach");
    must(/Mới tiếp nhận/.test(txt) && /Chưa hoàn tất/.test(txt), `Dòng hồ sơ: ${txt.replace(/\s+/g, " ")}`);
    const p = (await ok("officer1", "GET", `/persons?q=${encodeURIComponent(name)}`))[0]; must(p.status === "verified", `trạng thái hồ sơ = ${p.status}`);
  });
  await tc({ id: "INT-02", mod: "Tiếp nhận (M01)", kind: "Negative", role: "officer1", title: "Trùng mã nguồn (source_system + external_id) → không tạo hồ sơ mới (BR-01)",
    expected: "HTTP 409/422, không có bản ghi mới; DB có đúng 1 person với mã đó", sev: "Critical" }, async () => {
    const r = await api("officer1", "POST", "/persons", { full_name: "UAT Tên Khác Hoàn Toàn " + U, source_system: "QLPN", external_id: S.pA.code, confirm_distinct: true });
    must([409, 422].includes(r.status), `HTTP ${r.status}`);
    must(sql(`select count(*) n from person where external_id='${S.pA.code}'`)[0].n === 1, "Có nhiều hơn 1 hồ sơ cùng mã nguồn");
  });
  await tc({ id: "INT-03", mod: "Tiếp nhận (M01)", kind: "Negative", role: "officer1", title: "Trùng họ tên + ngày sinh: API báo nghi trùng, KHÔNG tự gộp; chỉ tạo khi xác nhận 'người khác' → hồ sơ chờ đối soát",
    expected: "Lần 1: 409 DUPLICATE_SUSPECTED + ứng viên; lần 2 (confirm_distinct): 201, status pending_verification, duplicate_candidates", sev: "High" }, async () => {
    const nm = `UAT Trùng Tên ${U}`; const a = await ok("officer1", "POST", "/persons", { full_name: nm, date_of_birth: "1990-02-02", source_system: "QLPN", external_id: "UAT-D1-" + U });
    const r1 = await api("officer1", "POST", "/persons", { full_name: nm, date_of_birth: "1990-02-02", source_system: "QLPN", external_id: "UAT-D2-" + U });
    status(r1, 409, "Tạo trùng tên+ngày sinh"); must(code(r1) === "DUPLICATE_SUSPECTED", `code=${code(r1)}`);
    const r2 = await api("officer1", "POST", "/persons", { full_name: nm, date_of_birth: "1990-02-02", confirm_distinct: true });
    status(r2, 201, "Xác nhận người khác"); must(r2.data.status === "pending_verification", `status=${r2.data.status}`);
    S.dupPending = r2.data; S.dupOriginal = a;
  });
  await tc({ id: "INT-04", mod: "Tiếp nhận (M01)", kind: "Negative", role: "officer1", title: "Mã nguồn và hệ thống nguồn phải đi cùng nhau",
    expected: "HTTP 422 IDENTITY_INCOMPLETE khi chỉ có một trong hai", sev: "Medium" }, async () => {
    const a = await api("officer1", "POST", "/persons", { full_name: "UAT Thiếu Nguồn " + U, external_id: "UAT-X-" + U });
    const b = await api("officer1", "POST", "/persons", { full_name: "UAT Thiếu Mã " + U, source_system: "QLPN" });
    must(a.status === 422 && b.status === 422, `HTTP ${a.status}/${b.status}`);
  });
  await tc({ id: "INT-05", mod: "Tiếp nhận (M01)", kind: "Boundary", role: "officer1", title: "Biên độ dài họ tên: 1 ký tự và 201 ký tự bị từ chối; 2 và 200 ký tự được chấp nhận",
    expected: "1→422, 2→201, 200→201, 201→422 (không lỗi 500)", sev: "Medium" }, async () => {
    const mk = (n) => api("officer1", "POST", "/persons", { full_name: n, confirm_distinct: true });
    const rs = [await mk("A"), await mk("Ab"), await mk("N".repeat(200)), await mk("N".repeat(201))];
    const got = rs.map((r) => r.status); must(JSON.stringify(got) === JSON.stringify([422, 201, 201, 422]), `HTTP thực tế ${got}`);
  });
  await tc({ id: "INT-06", mod: "Tiếp nhận (M01)", kind: "Boundary", role: "officer1", title: "Ngày sinh: tương lai bị từ chối; hôm nay/ngày hợp lệ xét theo quy tắc BR-03 (không cho thời gian tương lai)",
    expected: "Ngày sinh ngày mai → 422; ngày sinh 1990-01-01 → 201", sev: "Medium" }, async () => {
    const f = await api("officer1", "POST", "/persons", { full_name: "UAT Sinh Tương Lai " + U, date_of_birth: today(1), confirm_distinct: true });
    const g = await api("officer1", "POST", "/persons", { full_name: "UAT Sinh Hợp Lệ " + U, date_of_birth: "1990-01-01", confirm_distinct: true });
    must(f.status === 422, `Ngày sinh tương lai trả HTTP ${f.status}`); must(g.status === 201, `Ngày sinh hợp lệ trả HTTP ${g.status}`);
  });
  await tc({ id: "INT-07", mod: "Tiếp nhận (M01)", kind: "Negative", role: "officer1/officer2", title: "Người đang trong đợt tiếp nhận ở cơ sở này/cơ sở khác không thể tiếp nhận thêm kỳ mới",
    expected: "officer1 tạo kỳ thứ 2 cho người đang hoạt động → 409; officer2 tạo kỳ cho người của F01 → 409/403", sev: "High" }, async () => {
    const r1 = await api("officer1", "POST", `/persons/${S.pA.id}/stays`, {}); must(r1.status === 409, `kỳ trùng cùng cơ sở: HTTP ${r1.status}`);
    const r2 = await api("officer2", "POST", `/persons/${S.pA.id}/stays`, {}); must([403, 404, 409].includes(r2.status), `kỳ ở cơ sở khác: HTTP ${r2.status}`);
    must(sql(`select count(*) n from custody_stay where person_id='${S.pA.id}' and status in ('received','managed')`)[0].n === 1, "Người có >1 đợt tiếp nhận hoạt động cùng lúc");
  });
  await tc({ id: "INT-08", mod: "Tiếp nhận (M01)", kind: "Positive", role: "officer1", title: "Đối soát danh tính: mã đã thuộc hồ sơ khác bị chặn (cần quy trình gộp); mã hợp lệ → 'Đã xác minh'",
    expected: "Mã trùng → 409/422; mã mới → 200 verified", sev: "High" }, async () => {
    const p = await newPerson(`UAT Chờ Đối Soát ${U}`, { code: false });
    must(p.status === "pending_verification", `hồ sơ không mã phải 'chờ đối soát', thực tế ${p.status}`);
    const bad = await api("officer1", "POST", `/persons/${p.id}/verify`, { source_system: "QLPN", external_id: S.pA.code, note: "Thử mã đã tồn tại" });
    must([409, 422].includes(bad.status), `Mã trùng: HTTP ${bad.status}`);
    const good = await api("officer1", "POST", `/persons/${p.id}/verify`, { source_system: "QLPN", external_id: "UAT-V-" + U, note: "Đối chiếu hồ sơ giấy" });
    status(good, 200, "Đối soát hợp lệ"); must(good.data.status === "verified", `status=${good.data.status}`);
  });
  await tc({ id: "INT-09", mod: "Tiếp nhận (M01)", kind: "Cross-dept", role: "officer1 → approver1", title: "Gộp hồ sơ trùng: bốn mắt – người đề nghị không tự duyệt; người phê duyệt duyệt → dữ liệu chuyển sang hồ sơ giữ lại, hồ sơ nguồn 'merged'",
    expected: "officer duyệt → 403; approver duyệt → 200; source.status=merged; lượt khám chuyển sang target", sev: "High" }, async () => {
    const keep = await managedPerson(`UAT Gộp Giữ ${U}`, { dob: "1985-05-05" });
    const dup = await ok("officer1", "POST", "/persons", { full_name: `UAT Gộp Giữ ${U}`, date_of_birth: "1985-05-05", confirm_distinct: true });
    const m = await ok("officer1", "POST", "/person-merges", { source_id: dup.id, target_id: keep.id, reason: "Cùng họ tên, ngày sinh; đối chiếu hồ sơ giấy xác nhận một người" });
    denied(await api("officer1", "POST", `/person-merges/${m.id}/decision`, { approve: true }), "officer tự duyệt");
    status(await api("approver1", "POST", `/person-merges/${m.id}/decision`, { approve: true }), 200, "approver duyệt");
    must(sql(`select status s from person where id='${dup.id}'`)[0].s === "merged", "hồ sơ nguồn không chuyển 'merged'");
    must(sql(`select count(*) n from health_record where person_id='${keep.id}'`)[0].n === 1, "Hồ sơ giữ lại phải có đúng 1 hồ sơ sức khỏe");
  });
  await tc({ id: "INT-10", mod: "Tiếp nhận (UI)", kind: "Security", role: "officer1 (UI)", title: "Họ tên chứa mã HTML/script được hiển thị dạng văn bản (không chạy mã – XSS)",
    expected: "Không có hộp thoại alert, không có phần tử <script>/<img> được chèn; chuỗi hiển thị nguyên văn", sev: "Critical" }, async (c) => {
    const evil = `<img src=x onerror=alert(1)>UAT-XSS-${U}`;
    await ok("officer1", "POST", "/persons", { full_name: evil, confirm_distinct: true });
    const page = await ui("officer1"); let dialog = false; page.once("dialog", (d) => { dialog = true; d.dismiss(); });
    await nav(page, "Tiếp nhận & Hồ sơ"); await page.click('.seg button:has-text("Tra cứu hồ sơ")'); await page.fill("input.search", "UAT-XSS-" + U); await page.waitForTimeout(1200);
    const injected = await page.$("tbody img[src='x']"); await c.shot(page, "xss");
    must(!dialog && !injected, "Mã script/HTML được thực thi/chèn vào DOM");
    must((await page.innerText("tbody")).includes("onerror=alert(1)"), "Chuỗi không được hiển thị nguyên văn");
  });

  // ======================================================= ENCOUNTERS (khám)
  await tc({ id: "ENC-01", mod: "Khám (M03)", kind: "Positive", role: "doctor1", title: "Khám ban đầu hoàn tất → đợt tiếp nhận chuyển 'Đang quản lý'; lượt khám ban đầu thứ 2 cho cùng đợt bị chặn (B1/B5)",
    expected: "stay.status=managed; POST encounters type=initial lần 2 → 409", sev: "High" }, async () => {
    const p = await newPerson(`UAT Khám Ban Đầu ${U}`);
    const e = await startEnc(p.id, { type: "initial" });
    await ok("doctor1", "POST", `/encounters/${e.id}/observations`, { type: "Mạch", value: "78", unit: "lần/phút" });
    await ok("doctor1", "POST", `/persons/${p.id}/allergy-status/none-confirmed`);
    await ok("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" });
    must(sql(`select status s from custody_stay where id='${p.stay.id}'`)[0].s === "managed", "Đợt tiếp nhận không chuyển 'managed'");
    status(await api("doctor1", "POST", "/encounters", { person_id: p.id, type: "initial", reason: "Lần 2" }), 409, "Khám ban đầu lần 2");
  });
  await tc({ id: "ENC-02", mod: "Khám (M04)", kind: "Negative", role: "doctor1", title: "Không hoàn tất khám khi còn chỉ định xét nghiệm chưa có kết quả (UAT-04); có kết quả thì hoàn tất được",
    expected: "Trước KQ → 4xx (mã nêu rõ chỉ định chưa có kết quả); sau KQ → 200 completed", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Chờ XN ${U}`); const e = await startEnc(p.id);
    const o = await ok("doctor1", "POST", `/encounters/${e.id}/orders`, { kind: "lab", description: "Công thức máu" });
    const r = await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" }); must(r.status >= 400 && r.status < 500, `Hoàn tất khi còn chỉ định chờ KQ: HTTP ${r.status}`);
    await ok("nurse1", "POST", `/orders/${o.id}/result`, { result_text: "WBC 7.2" });
    const r2 = await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" }); status(r2, 200, "hoàn tất sau KQ");
  });
  await tc({ id: "ENC-03", mod: "Khám (M04/M05)", kind: "Negative", role: "doctor1", title: "Không hoàn tất khám khi còn đơn thuốc nháp (tránh đơn mồ côi)",
    expected: "HTTP 4xx; sau khi xác nhận/hủy đơn nháp thì hoàn tất được", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Đơn Nháp ${U}`); const e = await startEnc(p.id);
    const d = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1", route: "uống", frequency: "2/ngày", start_date: today(), duration_days: 5, quantity_prescribed: 10 });
    const r = await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" }); must(r.status >= 400 && r.status < 500, `HTTP ${r.status} – hoàn tất được khi còn đơn nháp`);
    await ok("doctor1", "POST", `/medication-orders/${d.id}/stop`, { outcome: "cancelled" });
    status(await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" }), 200, "hoàn tất sau khi hủy đơn nháp");
  });
  await tc({ id: "ENC-04", mod: "Khám (M04)", kind: "Negative", role: "doctor1", title: "Lượt khám đã hoàn tất không sửa trực tiếp; chỉ bổ sung bằng addendum có lý do (BR-02, UAT-10)",
    expected: "PATCH/observation vào lượt đã khóa → 409; addendum thiếu lý do → 422; addendum đủ → 201 và hiện trong lượt khám", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT Khóa Khám ${U}`); const e = await startEnc(p.id); await ok("doctor1", "POST", `/encounters/${e.id}/observations`, { type: "Nhiệt độ", value: "37", unit: "°C" });
    await ok("doctor1", "PATCH", `/encounters/${e.id}`, { summary: "Tóm tắt ban đầu" }); await ok("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" });
    const r1 = await api("doctor1", "PATCH", `/encounters/${e.id}`, { summary: "Sửa lén sau khi khóa" });
    const r2 = await api("doctor1", "POST", `/encounters/${e.id}/observations`, { type: "Mạch", value: "80", unit: "l/p" });
    must(r1.status === 409 && r2.status === 409, `PATCH/observation sau khóa: HTTP ${r1.status}/${r2.status}`);
    must((await ok("doctor1", "GET", `/encounters/${e.id}`)).summary === "Tóm tắt ban đầu", "Nội dung gốc bị ghi đè");
    status(await api("doctor1", "POST", `/encounters/${e.id}/addenda`, { text: "Bổ sung kết quả" }), 422, "addendum thiếu lý do");
    status(await api("doctor1", "POST", `/encounters/${e.id}/addenda`, { text: "Bổ sung: tái khám sau 1 tuần", reason: "Quên ghi lúc khám" }), 201, "addendum hợp lệ");
  });
  await tc({ id: "ENC-05", mod: "Khám (M04)", kind: "Negative", role: "doctor1", title: "Hủy lượt khám bắt buộc có lý do; sau khi hủy không đổi trạng thái được nữa",
    expected: "Hủy không lý do → 4xx; có lý do → cancelled; chuyển tiếp từ cancelled → 409", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Hủy Khám ${U}`); const e = await startEnc(p.id);
    const r1 = await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "cancelled" }); must(r1.status >= 400 && r1.status < 500, `Hủy không lý do: HTTP ${r1.status}`);
    status(await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "cancelled", reason: "Nhập nhầm người" }), 200, "hủy có lý do");
    const r3 = await api("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "in_progress" }); must(r3.status === 409, `Mở lại lượt đã hủy: HTTP ${r3.status}`);
  });
  await tc({ id: "ENC-06", mod: "Khám (M04)", kind: "Concurrency", role: "doctor1/nurse1", title: "Hai người sửa cùng lượt khám: người lưu sau nhận xung đột phiên bản, không ghi đè âm thầm (BR-06, C5)",
    expected: "PATCH với expected_version cũ → 409", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Xung Đột ${U}`); const e = await startEnc(p.id); const v0 = (await ok("doctor1", "GET", `/encounters/${e.id}`)).version;
    status(await api("doctor1", "PATCH", `/encounters/${e.id}`, { summary: "Kết luận A", expected_version: v0 }), 200, "lưu lần 1");
    const r = await api("nurse1", "PATCH", `/encounters/${e.id}`, { nursing_assessment: "Đánh giá B", expected_version: v0 });
    status(r, 409, "lưu với phiên bản cũ");
  });
  await tc({ id: "ENC-07", mod: "Khám (M04)", kind: "Boundary", role: "nurse1", title: "BR-03: thời điểm đo không được ở tương lai (dung sai 5 phút) – ghi nhận +4 phút được, +6 phút bị từ chối",
    expected: "+4' → 201; +6' → 422 FUTURE_TIME", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Thời Gian ${U}`); const e = await startEnc(p.id);
    const at = (m) => new Date(Date.now() + m * 60000).toISOString();
    const a = await api("nurse1", "POST", `/encounters/${e.id}/observations`, { type: "Mạch", value: "70", unit: "l/p", occurred_at: at(4) });
    const b = await api("nurse1", "POST", `/encounters/${e.id}/observations`, { type: "Mạch", value: "71", unit: "l/p", occurred_at: at(6) });
    must(a.status === 201 && b.status === 422, `+4'→${a.status}, +6'→${b.status}`);
    const row = (await ok("doctor1", "GET", `/encounters/${e.id}`)); must(JSON.stringify(row).includes("recorded_at"), "Thiếu mốc 'ghi vào hệ thống' (recorded_at) bên cạnh occurred_at");
  });
  await tc({ id: "ENC-08", mod: "Khám (M04)", kind: "Positive", role: "doctor1", title: "Ưu tiên khám (WF-02): ca khẩn cấp xếp đầu danh sách lượt khám",
    expected: "Lượt priority=emergent đứng trước các lượt routine được tạo trước đó", sev: "Low" }, async () => {
    const pr = await managedPerson(`UAT Thường ${U}`), pu = await managedPerson(`UAT Khẩn ${U}`);
    await ok("doctor1", "POST", "/encounters", { person_id: pr.id, type: "ad_hoc", reason: "Thường" });
    await ok("doctor1", "POST", "/encounters", { person_id: pu.id, type: "ad_hoc", reason: "Khẩn", priority: "emergent" });
    const list = await ok("doctor1", "GET", "/encounters?status=draft&limit=500"); const arr = Array.isArray(list) ? list : list.items;
    const idxU = arr.findIndex((x) => x.person_id === pu.id), idxR = arr.findIndex((x) => x.person_id === pr.id);
    must(idxU >= 0 && idxR >= 0, "Không thấy lượt khám trong danh sách"); must(idxU < idxR, `Ca khẩn ở vị trí ${idxU}, ca thường ở ${idxR}`);
  });
  await tc({ id: "ENC-09", mod: "Hồ sơ SK (M02)", kind: "Positive", role: "doctor1", title: "BR-07: 'chưa ghi nhận dị ứng' ≠ 'đã xác nhận không dị ứng'; hồ sơ trống không suy ra 'không có'",
    expected: "allergy_status: unknown (có notice) → none_confirmed sau xác nhận", sev: "High" }, async () => {
    const p = await newPerson(`UAT Dị Ứng Trạng Thái ${U}`);
    const s1 = await ok("doctor1", "GET", `/persons/${p.id}/health-summary`);
    must(s1.clinical.allergy_status === "unknown", `allergy_status ban đầu = ${s1.clinical.allergy_status}`); must(JSON.stringify(s1).toLowerCase().includes("chưa"), "Thiếu thông báo 'chưa ghi nhận' (notice)");
    await ok("doctor1", "POST", `/persons/${p.id}/allergy-status/none-confirmed`);
    const s2 = await ok("doctor1", "GET", `/persons/${p.id}/health-summary`); must(s2.clinical.allergy_status === "none_confirmed", `sau xác nhận = ${s2.clinical.allergy_status}`);
  });
  await tc({ id: "ENC-10", mod: "Hồ sơ SK (M02)", kind: "Negative", role: "nurse1", title: "Điều dưỡng ghi dị ứng khai báo (chưa xác nhận); không gỡ được dị ứng đã xác nhận bởi bác sĩ",
    expected: "nurse tạo dị ứng confirmed=false OK; nurse retract dị ứng confirmed → 403", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Dị Ứng Gỡ ${U}`);
    const a = await ok("doctor1", "POST", `/persons/${p.id}/allergies`, { substance: "Penicillin", confirmed: true });
    await ok("nurse1", "POST", `/persons/${p.id}/allergies`, { substance: "Phấn hoa", confirmed: false });
    denied(await api("nurse1", "POST", `/allergies/${a.id}/retract`, { reason: "Thử gỡ dị ứng đã xác nhận" }), "nurse gỡ dị ứng xác nhận");
  });

  // ======================================================= MEDICATION
  const rxBody = (o = {}) => ({ drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1 viên", route: "uống", frequency: "2 lần/ngày", start_date: today(), duration_days: 15, quantity_prescribed: 30, ...o });
  await tc({ id: "MED-01", mod: "Kê đơn (M05)", kind: "Positive", role: "doctor1", title: "Cảnh báo dị ứng khi kê Amoxicillin cho người dị ứng Amoxicillin; xác nhận bắt buộc ghi nhận đã đọc + ghi chú xử lý (UAT-02)",
    expected: "Đơn nháp có warnings; confirm không ack → 4xx; ack + ghi chú → 200; audit có medication_warning_acknowledged", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT Dị Ứng Amox ${U}`); await ok("doctor1", "POST", `/persons/${p.id}/allergies`, { substance: "Amoxicillin", reaction: "Phát ban", confirmed: true });
    const e = await startEnc(p.id);
    const d = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ drug_name: "Amoxicillin 500mg", drug_code: "AMOX500" }));
    must(d.warnings?.length > 0, "Không có cảnh báo dị ứng trên đơn nháp");
    const r1 = await api("doctor1", "POST", `/medication-orders/${d.id}/confirm`, {}); must(r1.status >= 400 && r1.status < 500, `Xác nhận không ack: HTTP ${r1.status}`);
    const r2 = await api("doctor1", "POST", `/medication-orders/${d.id}/confirm`, { acknowledge_warnings: true }); must(r2.status >= 400 && r2.status < 500, `Ack nhưng không ghi chú: HTTP ${r2.status} (phải bắt buộc ghi chú xử lý)`);
    status(await api("doctor1", "POST", `/medication-orders/${d.id}/confirm`, { acknowledge_warnings: true, ack_note: "Đã cân nhắc, dùng thay thế dưới theo dõi sát" }), 200, "xác nhận có ack");
    const a = await ok("admin", "GET", `/audit?action=medication_warning_acknowledged&limit=20`); must(a.some((x) => x.object_id === d.id || x.entity_id === d.id || JSON.stringify(x).includes(d.id)), "Không thấy audit medication_warning_acknowledged cho đơn này");
  });
  await tc({ id: "MED-02", mod: "Kê đơn (M05)", kind: "Positive", role: "doctor1", title: "Dị ứng chéo cùng nhóm: dị ứng Penicillin → cảnh báo khi kê Amoxicillin; trùng thuốc đang hiệu lực → cảnh báo",
    expected: "Có cảnh báo 'cùng nhóm' và 'trùng đơn đang hiệu lực'", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Nhóm Thuốc ${U}`); await ok("doctor1", "POST", `/persons/${p.id}/allergies`, { substance: "Penicillin", confirmed: true });
    const e = await startEnc(p.id);
    const d = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ drug_name: "Amoxicillin 500mg", drug_code: "AMOX500" })); must(d.warnings?.length > 0, "Dị ứng Penicillin không cảnh báo khi kê Amoxicillin");
    await ok("doctor1", "POST", `/medication-orders/${d.id}/stop`, { outcome: "cancelled" });
    const p2 = await managedPerson(`UAT Trùng Thuốc ${U}`); const e2 = await startEnc(p2.id); await confirmedRx(e2.id);
    const e3 = await startEnc(p2.id); const d2 = await ok("doctor1", "POST", `/encounters/${e3.id}/medication-orders`, rxBody());
    must(d2.warnings?.length > 0, "Kê trùng thuốc đang hiệu lực không có cảnh báo");
  });
  await tc({ id: "MED-03", mod: "Kê đơn (M05)", kind: "Positive", role: "doctor1", title: "Điều chỉnh đơn đã xác nhận = phiên bản mới (v2), bản cũ 'đã thay thế'; không sửa trực tiếp đơn đã xác nhận (BR-02)",
    expected: "PATCH đơn confirmed → 409; revise → 201 version=2; đơn cũ status=superseded", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Điều Chỉnh ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    must((await api("doctor1", "PATCH", `/medication-orders/${o.id}`, { dose: "3 viên" })).status === 409, "Sửa trực tiếp đơn đã xác nhận không bị chặn");
    const r = await api("doctor1", "POST", `/medication-orders/${o.id}/revise`, { dose: "2 viên", reason: "Tăng liều theo đáp ứng" }); status(r, 201, "revise"); must(r.data.version === 2, `version=${r.data.version}`);
    must(sql(`select status s from medication_order where id='${o.id}'`)[0].s === "active", "Bản cũ phải còn hiệu lực cho đến khi bản mới được xác nhận");
    status(await api("doctor1", "POST", `/medication-orders/${r.data.id}/confirm`, {}), 200, "xác nhận bản v2");
    must(sql(`select status s from medication_order where id='${o.id}'`)[0].s === "superseded", "Sau khi xác nhận v2, bản cũ không chuyển 'superseded'");
  });
  await tc({ id: "MED-04", mod: "Cấp phát (M06)", kind: "Boundary", role: "pharm1", title: "Không cấp quá số kê (BR-04): cấp 10/30 → còn 20; cấp 21 bị chặn OVER_DISPENSE; cấp đúng 20 được → 'đã cấp đủ'",
    expected: "21 → 409 OVER_DISPENSE; 20 → 200; tổng cấp ròng = 30", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT Cấp Phát ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    must((await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 10 })).status < 300, "cấp 10");
    const r = await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 21 }); must(r.status === 409 && code(r) === "OVER_DISPENSE", `cấp 21: HTTP ${r.status} ${code(r)}`);
    must((await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 20 })).status < 300, "cấp đúng phần còn lại");
    must(sql(`select sum(case kind when 'dispense' then quantity else -quantity end) t from dispense_event where order_id='${o.id}'`)[0].t === 30, "Tổng cấp ròng khác số kê");
    S.rxDone = o;
  });
  await tc({ id: "MED-05", mod: "Cấp phát (M06)", kind: "Negative", role: "pharm1", title: "Hoàn trả vượt số đã cấp bị chặn; hoàn trả hợp lệ là sự kiện riêng tham chiếu lần cấp (BR-04)",
    expected: "Hoàn trả > đã cấp → 409; hoàn trả hợp lệ → 200 và ghi thành dòng riêng kind=return", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Hoàn Trả ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    const d1 = await ok("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 10 });
    const evId = sql(`select id from dispense_event where order_id='${o.id}' and kind='dispense'`)[0].id;
    const bad = await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { kind: "return", quantity: 11, ref_dispense_id: evId, note: "Hoàn trả thử vượt số" }); must(bad.status === 409, `hoàn trả 11/10: HTTP ${bad.status} ${JSON.stringify(bad.data).slice(0, 160)}`);
    must((await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { kind: "return", quantity: 4, ref_dispense_id: evId, note: "Người bệnh không dùng" })).status < 300, "hoàn trả 4");
    must(sql(`select count(*) n from dispense_event where order_id='${o.id}'`)[0].n === 2, "Hoàn trả phải là bản ghi riêng (tổng 2 bản ghi)");
  });
  await tc({ id: "MED-06", mod: "Cấp phát (M06)", kind: "Negative", role: "pharm1", title: "Không cấp theo đơn nháp, đơn đã hết liệu trình, đơn chưa tới ngày bắt đầu",
    expected: "Cả ba trường hợp → 409; đơn nháp không nằm trong hàng đợi cấp phát", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Hiệu Lực Đơn ${U}`); const e = await startEnc(p.id);
    const draft = await ok("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ frequency: "1 lần/ngày" }));
    const expired = await confirmedRx(e.id, { drug_name: "Ibuprofen 400mg", drug_code: "IBU400", start_date: today(-30), duration_days: 5, quantity_prescribed: 10 });
    const future = await confirmedRx(e.id, { drug_name: "Cetirizine 10mg", drug_code: "CETI10", start_date: today(10), duration_days: 5, quantity_prescribed: 5 });
    const rs = [draft, expired, future].map(async (o) => api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 1 }));
    const got = (await Promise.all(rs)).map((r) => r.status); must(got.every((s) => s === 409), `HTTP (nháp/hết hạn/chưa tới): ${got}`);
    const q = await ok("pharm1", "GET", "/dispense-queue"); must(!q.some((x) => [draft.id, expired.id, future.id].includes(x.id)), "Đơn không hợp lệ vẫn xuất hiện trong hàng đợi cấp phát");
  });
  await tc({ id: "MED-07", mod: "Cấp phát (M06)", kind: "Boundary", role: "pharm1/doctor1", title: "Biên số lượng: 0, âm, NaN, > 1.000.000 bị từ chối (cả kê đơn và cấp phát)",
    expected: "Tất cả HTTP 422, không lỗi 500", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Biên Số Lượng ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    const rs = [];
    for (const q of [0, -5, 1_000_001]) { rs.push(await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: q })); rs.push(await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ quantity_prescribed: q }))); }
    rs.push(await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ duration_days: 0 }))); rs.push(await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ duration_days: 3651 })));
    const got = rs.map((r) => r.status); must(got.every((s) => s === 422), `HTTP: ${got}`);
  });
  await tc({ id: "MED-08", mod: "Kê đơn (M05)", kind: "Negative", role: "doctor1", title: "Mã thuốc không có trong danh mục bị từ chối",
    expected: "422", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Mã Thuốc ${U}`); const e = await startEnc(p.id);
    status(await api("doctor1", "POST", `/encounters/${e.id}/medication-orders`, rxBody({ drug_code: "KHONGTONTAI999" })), 422, "mã thuốc lạ");
  });
  await tc({ id: "MED-09", mod: "Điều trị (M06)", kind: "Negative", role: "nurse1", title: "Ghi nhận sử dụng thuốc: chưa cấp phát → chặn; 'không dùng' phải có lý do",
    expected: "Chưa cấp → 4xx; đã cấp + không dùng không lý do → 4xx; có lý do → 201", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Sử Dụng Thuốc ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    const r0 = await api("nurse1", "POST", `/medication-orders/${o.id}/administrations`, { administered: true }); must(r0.status >= 400 && r0.status < 500, `ghi nhận khi chưa cấp: HTTP ${r0.status}`);
    await ok("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 10 });
    const r1 = await api("nurse1", "POST", `/medication-orders/${o.id}/administrations`, { administered: false }); must(r1.status >= 400 && r1.status < 500, `không dùng, thiếu lý do: HTTP ${r1.status}`);
    status(await api("nurse1", "POST", `/medication-orders/${o.id}/administrations`, { administered: false, reason: "Người bệnh từ chối uống" }), 201, "không dùng có lý do");
    status(await api("nurse1", "POST", `/medication-orders/${o.id}/administrations`, { administered: true }), 201, "ghi nhận đã dùng");
  });
  await tc({ id: "MED-10", mod: "Kê đơn (M05)", kind: "Negative", role: "doctor1", title: "Dừng đơn: bắt buộc lý do; đơn đã cấp phát không được 'hủy' (chỉ 'ngừng')",
    expected: "Dừng không lý do → 422; cancelled sau cấp → 409 ALREADY_DISPENSED; stopped → 200", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Dừng Đơn ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id); await ok("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 5 });
    status(await api("doctor1", "POST", `/medication-orders/${o.id}/stop`, { outcome: "stopped" }), 422, "dừng không lý do");
    const r = await api("doctor1", "POST", `/medication-orders/${o.id}/stop`, { outcome: "cancelled", reason: "Hủy đơn đã cấp" }); must(r.status === 409, `hủy đơn đã cấp: HTTP ${r.status}`);
    status(await api("doctor1", "POST", `/medication-orders/${o.id}/stop`, { outcome: "stopped", reason: "Dị ứng, ngừng thuốc" }), 200, "ngừng đơn");
  });
  await tc({ id: "MED-11", mod: "Cấp phát (M06)", kind: "Concurrency", role: "pharm1", title: "5 yêu cầu cấp phát đồng thời (mỗi 10 đơn vị) trên đơn 30: tổng cấp không vượt số kê (BR-04/BR-06)",
    expected: "Đúng 3 yêu cầu thành công, 2 bị 409; tổng cấp = 30", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT Đồng Thời ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id);
    const rs = await Promise.all([1, 2, 3, 4, 5].map(() => api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 10 })));
    const got = rs.map((r) => r.status).sort(); const tot = sql(`select coalesce(sum(quantity),0) t from dispense_event where order_id='${o.id}' and kind='dispense'`)[0].t;
    must(tot <= 30, `Tổng cấp ${tot} vượt số kê 30 (HTTP ${got})`); must(tot === 30, `Tổng cấp ${tot} (kỳ vọng 30), HTTP ${got}`);
  });
  await tc({ id: "MED-12", mod: "Cấp phát (M06)", kind: "Idempotency", role: "pharm1", title: "BR-06: gửi lặp cùng Idempotency-Key (mất mạng, thử lại) chỉ tạo MỘT lần cấp phát",
    expected: "Hai request cùng key → cùng kết quả; DB có đúng 1 bản ghi cấp phát", sev: "High" }, async () => {
    const p = await managedPerson(`UAT Idempotency ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id); const key = "uat-idem-" + U;
    const a = await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 7 }, { "Idempotency-Key": key });
    const b = await api("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 7 }, { "Idempotency-Key": key });
    must(a.status < 300 && b.status < 300, `HTTP ${a.status}/${b.status}`); must(a.data.id === b.data.id, "Lần gửi lặp không trả về cùng bản ghi"); const n = sql(`select count(*) n from dispense_event where order_id='${o.id}'`)[0].n; must(n === 1, `Có ${n} bản ghi cấp phát (mong đợi 1)`);
  });
  await tc({ id: "MED-13", mod: "Cấp phát (UI)", kind: "Positive", role: "pharm1 (UI)", title: "Dược sĩ cấp một phần trên giao diện: thông báo 'cấp một phần – còn thiếu', trạng thái 'Cấp một phần' (E1)",
    expected: "Toast 'Cấp một phần'; đơn còn trong hàng đợi", sev: "High" }, async (c) => {
    const p = await managedPerson(`UAT Cấp Một Phần UI ${U}`); const e = await startEnc(p.id); const o = await confirmedRx(e.id, { quantity_prescribed: 14, duration_days: 14 });
    const page = await ui("pharm1"); await nav(page, "Cấp phát thuốc"); await page.reload(); await page.waitForSelector(".side .nav"); await nav(page, "Cấp phát thuốc");
    await page.fill('input[aria-label="Tìm đơn thuốc"]', p.full_name); await page.waitForSelector(`button.ohead:has-text("${p.full_name}")`); await c.shot(page, "hang-doi");
    await page.click(`.ogroup:has-text("${p.full_name}") button:has-text("Mở")`); await page.waitForSelector(".drawer"); await c.shot(page, "chi-tiet-don");
    await page.click('.drawer button:has-text("Cấp thuốc")'); await page.waitForSelector(".modal-bg"); await page.fill('.modal input[type="number"], .modal input[name="quantity"]', "10"); await c.shot(page, "hop-thoai");
    await page.click('.modal-bg footer button:has-text("Ghi nhận cấp phát")'); await toast(page, "Cấp một phần – còn thiếu 4"); await c.shot(page, "ket-qua");
    must(sql(`select coalesce(sum(quantity),0) t from dispense_event where order_id='${o.id}'`)[0].t === 10, "DB không ghi đúng 10");
  });
}
