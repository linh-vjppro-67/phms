// E2E đầy đủ: Tiếp nhận & Hồ sơ (M01, WF-01 bước 1–3) – cán bộ tiếp nhận thao tác trên giao diện.
import { pickPatient, api, dialogOk, facilityId, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, nav, newPerson, ok, rowOf, start, startEncounter, toast, uniq } from "./lib.mjs";

const T = await start("Tiếp nhận & Hồ sơ (M01)");
const U = uniq();
const name = (s) => `${s} ${U}`;
const field = (page, label) => page.locator(`.modal-bg label:has-text("${label}") input, .modal-bg label:has-text("${label}") select`).first();
const wizard = async (page, { full_name, dob, code, source = "QLPN" }) => {
  await page.click('button:has-text("+ Tiếp nhận mới")'); await modalOpen(page, "Tiếp nhận mới");
  await field(page, "Họ và tên").fill(full_name);
  if (dob) await field(page, "Ngày sinh").fill(dob);
  await field(page, "Hệ thống nguồn").fill(source);
  await field(page, "Mã phạm nhân").fill(code || "");
  await page.click('.modal-bg footer button:has-text("Kiểm tra & tiếp tục")');
};
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);

// ---- dữ liệu dựng sẵn
const existing = await managedPerson(name("Người Có Sẵn"), { dob: "1990-02-02" });                 // trùng mã / trùng tên+ngày sinh
const elsewhere = await newPerson(name("Người Ở Trại Hai"), { officer: "officer2" });             // đang ở cơ sở khác
const nocode = await newPerson(name("Người Thiếu Mã"), { code: false });                          // chờ đối soát
const ended = await managedPerson(name("Người Mãn Hạn"));                                         // đã kết thúc kỳ -> tái tiếp nhận
{
  const h = await ok("officer1", "POST", `/stays/${ended.stay.id}/handover`, { kind: "release", reason: "Mãn hạn tù (E2E)" });
  await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Sức khỏe bình thường, đã khám ban đầu (E2E)" });
  await ok("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true });
}
const withClinical = await newPerson(name("Người Có Dữ Liệu Lâm Sàng"));                          // kỳ 'received' đã có lượt khám
await startEncounter(withClinical.id, { type: "initial", start: false });
const nostay = await newPerson(name("Người Chưa Có Kỳ"), { stay: false });

const page = await T.login("officer1");
await nav(page, "Tiếp nhận & Hồ sơ");

let created;
await T.step("A1 tiếp nhận mới trọn 3 bước (kiểm tra trùng → hồ sơ → đợt tiếp nhận)", async () => {
  created = name("Nguyễn Văn Mới");
  await wizard(page, { full_name: created, dob: "1991-01-01", code: "E2E-" + U + "-A1" });
  await page.waitForSelector('.modal-bg:has-text("Không tìm thấy hồ sơ trùng")');
  await page.click('.modal-bg footer button:has-text("Tạo hồ sơ mới")'); await toast(page, "Đã tạo hồ sơ");
  await page.waitForSelector('.modal-bg:has-text("Đợt tiếp nhận")');
  await page.click('.modal-bg footer button:has-text("Xác nhận tiếp nhận")'); await toast(page, "Đã xác nhận tiếp nhận mới");
  await page.waitForSelector('.modal-bg:has-text("Đã tiếp nhận")');
  await page.click('.modal-bg footer button:has-text("Đóng")'); await modalGone(page);
  await page.waitForSelector(`tbody tr:has-text("${created}")`);
  await mustContain(page, `tbody tr:has-text("${created}")`, "Mới tiếp nhận", "Chưa hoàn tất");
});

await T.step("A2 trùng mã nguồn: hiện hồ sơ trùng, tạo mới bị máy chủ từ chối", async () => {
  await wizard(page, { full_name: name("Tên Khác Hẳn"), code: existing.code });
  await page.waitForSelector('.modal-bg:has-text("không tự gộp")');
  await mustContain(page, ".modal-bg", existing.full_name);
  await page.click('.modal-bg footer button:has-text("Đây là người khác")');
  await toast(page, "Đã tồn tại hồ sơ cùng mã nguồn");
  await page.click('.modal-bg header .btn'); await modalGone(page);
});

await T.step("A3 trùng tên + ngày sinh: tạo hồ sơ mới ở trạng thái CHỜ ĐỐI SOÁT (không tự gộp)", async () => {
  await wizard(page, { full_name: existing.full_name, dob: "1990-02-02", code: "E2E-" + U + "-A3" });
  await page.waitForSelector('.modal-bg:has-text("không tự gộp")');
  await page.click('.modal-bg footer button:has-text("Đây là người khác")'); await toast(page, "Đã tạo hồ sơ");
  await page.click('.modal-bg footer button:has-text("Để sau")'); await modalGone(page);
  await seg(page, "Chờ đối soát danh tính");
  await page.waitForSelector(`tbody tr:has-text("${existing.full_name}")`);
  await mustContain(page, `tbody tr:has-text("${existing.full_name}")`, "Nghi trùng");
});

await T.step("A4 có mã thì phải có hệ thống nguồn; chưa có mã thì bỏ qua hệ thống nguồn mặc định (QLPN) và vẫn tiếp tục", async () => {
  await page.click('button:has-text("+ Tiếp nhận mới")'); await modalOpen(page, "Tiếp nhận mới");
  await field(page, "Họ và tên").fill(name("Có Mã Thiếu Nguồn")); await field(page, "Hệ thống nguồn").fill(""); await field(page, "Mã phạm nhân").fill("PN-THIEU-NGUON");
  await page.click('.modal-bg footer button:has-text("Kiểm tra & tiếp tục")');
  await page.waitForSelector('.modal-bg:has-text("phải đi cùng nhau")');                       // có mã mà thiếu nguồn -> chặn
  await field(page, "Hệ thống nguồn").fill("QLPN"); await field(page, "Mã phạm nhân").fill("");   // chưa có mã, nguồn mặc định -> tự bỏ qua
  await page.click('.modal-bg footer button:has-text("Kiểm tra & tiếp tục")');
  await page.waitForSelector('.modal-bg:has-text("Kiểm tra trùng hồ sơ")');
  await page.click('.modal-bg header .btn'); await modalGone(page);
});

await T.step("A5 đối soát: mã đã thuộc hồ sơ khác bị chặn, mã hợp lệ → đã xác minh", async () => {
  await seg(page, "Chờ đối soát danh tính");
  await page.click(`tbody tr:has-text("${nocode.full_name}")`);
  await page.waitForSelector(".drawer");
  await mustContain(page, ".drawer", "chưa được đối soát");
  await page.click('.drawer button:has-text("Đối soát")'); await modalOpen(page, "Đối soát danh tính");
  await page.fill('.modal [name="external_id"]', existing.code); await page.fill('.modal [name="note"]', "Thử mã trùng");
  await modalSubmit(page, "Xác minh"); await toast(page, "cần quy trình gộp");
  await page.fill('.modal [name="external_id"]', "E2E-" + U + "-OK"); await page.fill('.modal [name="note"]', "Đối chiếu hồ sơ giấy số 12");
  await modalSubmit(page, "Xác minh"); await toast(page, "Đã xác minh danh tính");
  await page.waitForSelector('.drawer .badge:has-text("Đã xác minh")');
  await page.click('.drawer header .btn:has-text("Quay lại")');
});

await T.step("A6 người đang ở cơ sở khác: không thể tiếp nhận kỳ mới", async () => {
  await wizard(page, { full_name: elsewhere.full_name, dob: "1988-04-04", code: "", source: "" });
  await page.waitForSelector(`.modal-bg tr:has-text("${elsewhere.full_name}")`);
  await mustContain(page, ".modal-bg", "Cơ sở khác");
  await page.click(`.modal-bg tr:has-text("${elsewhere.full_name}") button:has-text("Dùng hồ sơ này")`);
  await page.waitForSelector('.modal-bg:has-text("đang trong đợt tiếp nhận ở cơ sở khác")');
  await page.click('.modal-bg footer button:has-text("Xác nhận tiếp nhận")');
  await toast(page, "đang trong một đợt tiếp nhận");
  await page.click('.modal-bg header .btn'); await modalGone(page);
});

await T.step("A7 tái tiếp nhận người đã mãn hạn: 2 kỳ, KHÔNG tạo hồ sơ sức khỏe mới, lịch sử còn nguyên", async () => {
  await seg(page, "Tra cứu hồ sơ");
  await page.fill("input.search", ended.full_name);
  await page.click(`tbody tr:has-text("${ended.full_name}")`); await page.waitForSelector(".drawer");
  await mustContain(page, ".drawer", "Đã kết thúc");
  await page.click('.drawer button:has-text("+ Tiếp nhận kỳ mới")'); await modalOpen(page, "Xác nhận tiếp nhận mới");
  await modalSubmit(page, "Lưu"); await toast(page, "Đã tiếp nhận");
  await page.waitForFunction(() => document.querySelectorAll(".drawer table.tbl tbody tr").length === 2);
  const before = await ok("doctor1", "GET", `/persons/${ended.id}/health-summary`);
  if (before.stays.length !== 2) throw new Error("phải có đúng 2 đợt tiếp nhận");
  if (await page.$('.drawer header button:has-text("Mở hồ sơ sức khỏe")')) throw new Error("cán bộ tiếp nhận không được thấy nút Mở hồ sơ sức khỏe");
  await page.click('.drawer header .btn:has-text("Quay lại")');
  // bác sĩ kiểm tra hồ sơ sức khỏe: 2 đợt tiếp nhận, lịch sử khám cũ còn, vẫn MỘT hồ sơ sức khỏe
  const doc = await T.login("doctor1");
  await pickPatient(doc, ended.full_name); await nav(doc, "Hồ sơ sức khỏe");
  await doc.click('.tabs button:has-text("Đợt tiếp nhận")');
  await doc.waitForFunction(() => document.querySelectorAll("tbody tr").length === 2);
  await doc.click('.tabs button:has-text("Lịch sử khám")');
  await doc.waitForSelector("tbody tr"); await mustContain(doc, "tbody", "Khám ban đầu");
  const after = await ok("doctor1", "GET", `/persons/${ended.id}/health-summary`);
  if (after.clinical.health_record_id !== before.clinical.health_record_id) throw new Error("tạo trùng hồ sơ sức khỏe");
  page.use();
});

await nav(page, "Tiếp nhận & Hồ sơ");
await T.step("A8a hủy liên kết nhầm người (chưa có dữ liệu lâm sàng) → thành công, có lý do", async () => {
  await seg(page, "Đang quản lý tại cơ sở");
  await page.click(`tbody tr:has-text("${created}")`); await page.waitForSelector(".drawer");
  await page.click('.drawer button:has-text("Hủy liên kết")'); await modalOpen(page, "Hủy liên kết đợt tiếp nhận");
  await page.fill('.modal input[name="v"]', "Nhập nhầm người, đã báo cán bộ quản lý"); await dialogOk(page);
  await toast(page, "Đã hủy liên kết"); await page.waitForSelector('.drawer .badge:has-text("Đã hủy liên kết")');
  await page.click('.drawer header .btn:has-text("Quay lại")');
});

await T.step("A8b hủy liên kết khi ĐÃ có dữ liệu lâm sàng → bị chặn", async () => {
  await page.click(`tbody tr:has-text("${withClinical.full_name}")`); await page.waitForSelector(".drawer");
  await page.click('.drawer button:has-text("Hủy liên kết")'); await modalOpen(page, "Hủy liên kết đợt tiếp nhận");
  await page.fill('.modal input[name="v"]', "Thử hủy khi đã có lượt khám"); await dialogOk(page);
  await toast(page, "dữ liệu lâm sàng");
  await page.click('.drawer header .btn:has-text("Quay lại")');
});

await T.step("A9 người chưa có đợt tiếp nhận: tìm thấy nhưng không có trạng thái kỳ; tra cứu theo tên hoạt động", async () => {
  await seg(page, "Tra cứu hồ sơ");
  await page.fill("input.search", nostay.full_name);
  await page.waitForSelector(`tbody tr:has-text("${nostay.full_name}")`);
  const cell = await page.$eval(`tbody tr:has-text("${nostay.full_name}")`, (r) => r.cells[r.cells.length - 1].innerText.trim());
  if (cell !== "—") throw new Error(`cột "Tại cơ sở này" phải là "—", thực tế "${cell}"`);
  await page.fill("input.search", "không-tồn-tại-" + U);
  await page.waitForSelector('.empty:has-text("Không tìm thấy hồ sơ")');
});

await T.step("A10 cán bộ tiếp nhận KHÔNG thấy tab/dữ liệu lâm sàng (UAT-09 trên giao diện)", async () => {
  const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent));
  for (const bad of ["Khám ban đầu", "Khám chữa bệnh", "Cấp phát", "Hồ sơ sức khỏe", "Tài liệu", "Báo cáo", "Quản trị"])
    if (labels.some((l) => l.includes(bad))) throw new Error(`cán bộ tiếp nhận không được thấy tab “${bad}”`);
  await page.goto(page.url().split("#")[0] + "#/exam"); await page.waitForTimeout(500);
  await page.waitForSelector('.side .nav.on:has-text("Bảng điều khiển")');   // gõ thẳng URL tab bị cấm -> về trang được phép
});

process.exit((await T.done()).length ? 1 : 0);
