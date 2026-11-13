// E2E đầy đủ: Khám định kỳ (M07, WF-04) + Bệnh lý & Cảnh báo (M08, WF-05) – nhiều vai trò trên giao diện.
import { api, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, newPerson, ok, pickPatient, start, toast, today, uniq } from "./lib.mjs";

const T = await start("Khám định kỳ · Bệnh lý & Cảnh báo (M07–M08)");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const tab = (page, label) => page.click(`button[role="tab"]:has-text("${label}")`);
const ask = async (page, value, title) => { await modalOpen(page, title); await page.fill('.modal [name="v"]', value); await dialogOk(page); };

const A = await managedPerson(nm("Định Kỳ Đã Khám"));
const B = await managedPerson(nm("Định Kỳ Hoãn"));
const C = await managedPerson(nm("Định Kỳ Từ Chối"));
const N = await newPerson(nm("Định Kỳ Mới Tiếp Nhận"));            // chưa khám ban đầu -> bị loại trừ
const roundName = nm("Khám định kỳ E2E");

const mgr = await T.login("manager1");
const nurse = await T.login("nurse1");
const doc = await T.login("doctor1");

// ============================================================== M07
await T.step("F1 quản lý tạo đợt khám: hệ thống sinh nhiệm vụ cho người ĐANG QUẢN LÝ và báo số loại trừ", async () => {
  await nav(mgr, "Khám định kỳ");
  await mgr.click('button:has-text("+ Tạo đợt khám")'); await modalOpen(mgr, "Tạo đợt khám định kỳ");
  await mgr.fill('.modal [name="name"]', roundName); await mgr.fill('.modal [name="due_date"]', today(10));
  await modalSubmit(mgr, "Tạo đợt & sinh danh sách"); await toast(mgr, "nhiệm vụ khám");
  await mgr.waitForSelector(`.kcard:has-text("${roundName}")`);
  await mustContain(mgr, ".split", "Tổng nhiệm vụ", "Loại trừ khỏi đợt");
});
await T.step("F2 điều dưỡng thấy đúng nhiệm vụ; người chưa khám ban đầu nằm ở 'Loại trừ' kèm lý do", async () => {
  await nav(nurse, "Khám định kỳ");
  await nurse.click(`.kcard:has-text("${roundName}")`);
  for (const p of [A, B, C]) await nurse.waitForSelector(`tbody tr:has-text("${p.full_name}")`);
  if (await nurse.$(`tbody tr:has-text("${N.full_name}")`)) throw new Error("người chưa khám ban đầu không được có nhiệm vụ trong đợt");
  await tab(nurse, "Loại trừ");
  await nurse.waitForSelector(`tbody tr:has-text("${N.full_name}")`); await mustContain(nurse, `tbody tr:has-text("${N.full_name}")`, "Chưa hoàn tất khám ban đầu");
  await tab(nurse, "Danh sách khám");
});
await T.step("F3 bác sĩ khám một nhiệm vụ → hoàn tất → nhiệm vụ 'Hoàn tất', tiến độ tăng", async () => {
  await nav(doc, "Khám định kỳ"); await doc.click(`.kcard:has-text("${roundName}")`);
  await doc.click(`tbody tr:has-text("${A.full_name}") button:has-text("Khám")`);
  await doc.waitForSelector('.drawer .badge:has-text("Đang khám")'); await mustContain(doc, ".drawer", A.full_name);
  await doc.click('.drawer button[role="tab"]:has-text("Sinh hiệu")');
  await doc.fill('.drawer [name="sys"]', "125"); await doc.fill('.drawer [name="dia"]', "80"); await doc.click('.drawer button:has-text("Ghi nhận sinh hiệu")');
  await doc.waitForSelector('.drawer td:has-text("125 mmHg")');
  await doc.click('.drawer-bg button:has-text("Hoàn tất khám")'); await dialogOk(doc); await toast(doc, "Đã hoàn tất lượt khám");
  await doc.click('.drawer-bg header .btn:has-text("Quay lại")');
  await doc.waitForSelector(`tbody tr:has-text("${A.full_name}"):has-text("Hoàn tất")`);
  const done = await doc.$eval(".split .kpis", (e) => e.innerText);
  if (!/Đã hoàn thành/i.test(done)) throw new Error("không thấy chỉ số 'Đã hoàn thành'");
  if (await doc.$(`tbody tr:has-text("${A.full_name}") button:has-text("Khám")`)) throw new Error("nhiệm vụ đã hoàn tất không được khám lại");
});
await T.step("F4 hoãn (lý do + ngày hẹn mới → sinh lịch mới) và 'không thực hiện' (bắt buộc lý do)", async () => {
  await nurse.reload(); await nurse.waitForSelector(".side .nav"); await nav(nurse, "Khám định kỳ"); await nurse.click(`.kcard:has-text("${roundName}")`);
  await nurse.click(`tbody tr:has-text("${B.full_name}") button:has-text("Hoãn")`); await modalOpen(nurse, "Hoãn khám");
  await modalSubmit(nurse, "Lưu"); await nurse.waitForTimeout(300);
  if (!(await nurse.$('.modal-bg:has-text("Hoãn khám")'))) throw new Error("hoãn được khi chưa nhập lý do");
  await nurse.fill('.modal [name="reason"]', "Đang lao động ngoài trại"); await nurse.fill('.modal [name="new_due_date"]', today(5));
  await modalSubmit(nurse, "Lưu"); await toast(nurse, "Đã cập nhật");
  await nurse.waitForSelector(`tbody tr:has-text("${B.full_name}") .badge:has-text("Hoãn")`); await mustContain(nurse, "tbody", "Đang lao động ngoài trại");
  if ((await nurse.$$(`tbody tr:has-text("${B.full_name}")`)).length < 2) throw new Error("hoãn kèm ngày mới phải sinh thêm một lịch mới");
  await nurse.click(`tbody tr:has-text("${C.full_name}") button:has-text("Không thực hiện")`); await modalOpen(nurse, "Ghi nhận không thực hiện");
  await nurse.fill('.modal [name="reason"]', "Người bệnh từ chối khám, đã lập biên bản"); await modalSubmit(nurse, "Lưu"); await toast(nurse, "Đã cập nhật");
  await nurse.waitForSelector(`tbody tr:has-text("${C.full_name}") .badge:has-text("Không thực hiện")`);
});
await T.step("F5 tránh trùng lịch: đợt thứ hai loại người đã có lịch định kỳ đang mở", async () => {
  const r2 = await ok("manager1", "POST", "/checkup-rounds", { name: nm("Đợt trùng lịch"), due_date: today(12) });
  if (!r2.excluded.some((x) => x.reason.startsWith("Đã có lịch khám định kỳ khác"))) throw new Error("không loại trừ người đã có lịch định kỳ đang mở");
  if (r2.excluded.some((x) => x.person_id === A.id)) throw new Error("người đã khám xong không có lịch mở nên không được loại");
  await ok("manager1", "POST", `/checkup-rounds/${r2.id}/lock`);
});
await T.step("F6 quản lý khóa đợt: người chưa khám ghi 'không thực hiện' (không bỏ sót), không thao tác thêm được", async () => {
  await mgr.reload(); await mgr.waitForSelector(".side .nav"); await nav(mgr, "Khám định kỳ"); await mgr.click(`.kcard:has-text("${roundName}")`);
  await mgr.waitForSelector(`tbody tr`);
  if (await mgr.$('tbody button:has-text("Khám")')) throw new Error("quản lý không được thấy nút Khám");
  await mustNotContain(mgr, "tbody", A.full_name);                             // quản lý không thấy tên người bệnh
  await mgr.click('button:has-text("Khóa đợt & chốt kết quả")'); await modalOpen(mgr, "Khóa đợt khám");
  await mgr.click('.modal-bg footer button:has-text("Khóa đợt")'); await toast(mgr, "Đã khóa đợt khám");
  await mgr.waitForSelector('.card .badge:has-text("Đã khóa")');
  const stats = await mgr.$eval(".split .kpis", (e) => e.innerText.replace(/\s+/g, " "));
  if (!/0 Chưa khám/.test(stats)) throw new Error("sau khi khóa không còn nhiệm vụ 'chưa khám': " + stats);
  if (await mgr.$('button:has-text("Khóa đợt & chốt kết quả")')) throw new Error("đợt đã khóa vẫn còn nút khóa");
  await nurse.reload(); await nurse.waitForSelector(".side .nav"); await nav(nurse, "Khám định kỳ"); await nurse.click(`.kcard:has-text("${roundName}")`);
  await nurse.waitForSelector("tbody tr");
  if (await nurse.$('tbody button:has-text("Hoãn")')) throw new Error("đợt đã khóa không được hoãn/khám thêm");
});

// ============================================================== M08
const G1 = await managedPerson(nm("Mạn Tính Quá Hạn"));
const G2 = await managedPerson(nm("Mạn Tính Lập Kế Hoạch"));
{
  const prob = await ok("doctor1", "POST", `/persons/${G1.id}/problems`, { name: "Tăng huyết áp vô căn", code: "I10" });
  await ok("doctor1", "POST", `/persons/${G1.id}/care-plans`, { problem_id: prob.id, goals: "Huyết áp < 140/90", review_interval_days: 14, start_date: today(-40), measures: [{ name: "Huyết áp tâm thu", unit: "mmHg" }] });
  await ok("admin", "POST", "/scheduler/run");
}
await T.step("G1 cảnh báo lịch quá hạn: Tiếp nhận (người chịu trách nhiệm) → Xử lý xong (nhập kết quả); không tiếp nhận 2 lần", async () => {
  await nav(nurse, "Bệnh lý & Cảnh báo");
  await nurse.waitForSelector('tbody tr:has-text("quá hạn")');
  await nurse.click('tbody tr:has-text("quá hạn") button:has-text("Tiếp nhận")'); await toast(nurse, "bạn là người chịu trách nhiệm");
  await seg(nurse, "Đã tiếp nhận"); await nurse.waitForSelector('tbody tr:has-text("quá hạn")');
  await nurse.click('tbody tr:has-text("quá hạn") button:has-text("Xử lý xong")'); await ask(nurse, "Đã sắp xếp khám trong tuần, cập nhật lịch", "Xử lý cảnh báo");
  await toast(nurse, "Đã xử lý");
  await seg(nurse, "Đã xử lý"); await nurse.waitForSelector('tbody tr:has-text("Đã sắp xếp khám trong tuần")');
});
await T.step("G2 'Lịch tái khám & quá hạn': hoãn kèm lý do + ngày mới → hết quá hạn", async () => {
  await tab(nurse, "Lịch tái khám & quá hạn");
  await nurse.waitForSelector(`tbody tr:has-text("${G1.full_name}")`); await mustContain(nurse, `tbody tr:has-text("${G1.full_name}")`, "Trễ");
  await nurse.click(`tbody tr:has-text("${G1.full_name}") button:has-text("Hoãn")`); await modalOpen(nurse, "Hoãn lịch");
  await nurse.fill('.modal [name="reason"]', "Đang điều trị ngoại viện"); await nurse.fill('.modal [name="new_due_date"]', today(3));
  await modalSubmit(nurse, "Lưu"); await toast(nurse, "Đã cập nhật");
  await nurse.waitForFunction((n) => ![...document.querySelectorAll("tbody tr")].some((r) => r.innerText.includes(n) && r.innerText.includes("Trễ")), G1.full_name);
  await seg(nurse, "Tất cả lịch đang mở"); await nurse.waitForSelector(`tbody tr:has-text("${G1.full_name}")`);
});
await T.step("G3 'Kế hoạch theo dõi': liệt kê kế hoạch; kết thúc kế hoạch kèm lý do → lịch mở bị đóng", async () => {
  await tab(nurse, "Kế hoạch theo dõi");
  await nurse.waitForSelector(`tbody tr:has-text("${G1.full_name}")`); await mustContain(nurse, `tbody tr:has-text("${G1.full_name}")`, "Tăng huyết áp vô căn", "14 ngày");
  if (await nurse.$(`tbody tr:has-text("${G1.full_name}") button:has-text("Kết thúc")`)) throw new Error("điều dưỡng không có quyền kết thúc kế hoạch (chỉ bác sĩ)");
  await nav(doc, "Bệnh lý & Cảnh báo"); await tab(doc, "Kế hoạch theo dõi");
  await doc.click(`tbody tr:has-text("${G1.full_name}") button:has-text("Kết thúc")`); await ask(doc, "Ổn định, kết thúc theo dõi", "Kết thúc kế hoạch");
  await toast(doc, "Đã kết thúc");
  await doc.waitForFunction((n) => !document.body.innerText.includes(n), G1.full_name);
});
await T.step("G4 bác sĩ lập vấn đề sức khỏe → kế hoạch theo dõi → hẹn tái khám cho người đang chọn", async () => {
  await nav(doc, "Bệnh lý & Cảnh báo"); await tab(doc, "Theo dõi người đang chọn");
  await pickPatient(doc, G2.full_name);
  await doc.waitForSelector('text=Vấn đề sức khỏe / bệnh mạn tính');
  await doc.fill('.card:has-text("Vấn đề sức khỏe / bệnh mạn tính") [name="name"]', "Đái tháo đường típ 2");
  await doc.click('.card:has-text("Vấn đề sức khỏe / bệnh mạn tính") button:has-text("Thêm")'); await toast(doc, "Đã ghi nhận vấn đề sức khỏe");
  await doc.waitForSelector('td:has-text("Đái tháo đường típ 2")');
  await doc.click('button:has-text("+ Lập kế hoạch")'); await modalOpen(doc, "Lập kế hoạch theo dõi");
  await doc.fill('.modal [name="goals"]', "HbA1c < 7%"); await doc.fill('.modal [name="measures"]', "Đường huyết | mmol/L");
  await doc.fill('.modal [name="review_interval_days"]', "30"); await modalSubmit(doc, "Lưu"); await toast(doc, "Đã lập kế hoạch");
  await doc.waitForSelector('td:has-text("HbA1c < 7%")');
  await doc.click('button:has-text("+ Hẹn tái khám")'); await modalOpen(doc, "Hẹn tái khám");
  await doc.fill('.modal [name="due_date"]', today(20)); await doc.fill('.modal [name="note"]', "Đánh giá đáp ứng điều trị"); await modalSubmit(doc, "Lưu");
  await toast(doc, "Đã tạo lịch hẹn");
  const s = await ok("doctor1", "GET", `/persons/${G2.id}/health-summary`);
  if (s.clinical.upcoming_appointments.length < 2) throw new Error("phải có lịch theo kế hoạch + lịch hẹn tay");
});
await T.step("G5 điều dưỡng KHÔNG có quyền ghi vấn đề sức khỏe / lập kế hoạch (chỉ bác sĩ)", async () => {
  await nav(nurse, "Hồ sơ sức khỏe"); await pickPatient(nurse, G2.full_name);
  await nurse.click('.tabs button:has-text("Dị ứng & vấn đề sức khỏe")');
  await nurse.waitForSelector('text=Vấn đề sức khỏe / bệnh mạn tính');
  if (await nurse.$('.card:has-text("Vấn đề sức khỏe / bệnh mạn tính") [name="name"]')) throw new Error("điều dưỡng không được thêm vấn đề sức khỏe");
  await nurse.click('.tabs button:has-text("Kế hoạch theo dõi")');
  if (await nurse.$('button:has-text("+ Lập kế hoạch")')) throw new Error("điều dưỡng không được lập kế hoạch");
});
await T.step("G6 tác vụ nền: chạy lại KHÔNG sinh cảnh báo trùng", async () => {
  const adm = await T.login("admin");
  await nav(adm, "Quản trị hệ thống"); await adm.click('.tabs button:has-text("Tác vụ nền")');
  await adm.click('button:has-text("Chạy ngay")'); await toast(adm, "Đã chạy");
  await adm.waitForSelector(".kpis .kpi");
  const t = await adm.$eval(".kpis", (e) => e.innerText.replace(/\s+/g, " "));
  if (!/0 Cảnh báo quá hạn mới/.test(t)) throw new Error("lần chạy lại không được sinh cảnh báo quá hạn mới: " + t);
});

process.exit((await T.done()).length ? 1 : 0);
