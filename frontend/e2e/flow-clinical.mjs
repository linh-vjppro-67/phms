// E2E đầy đủ: Khám chữa bệnh (M04) + Chỉ định & Kê đơn (M05) + Cấp phát thuốc (M06).
import { api, confirmedRx, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, ok, pickInModal, rowOf, start, startEncounter, toast, uniq } from "./lib.mjs";

const T = await start("Khám chữa bệnh · Kê đơn · Cấp phát (M04–M06)");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const tab = (page, label) => page.click(`.drawer button[role="tab"]:has-text("${label}")`);
const closeDrawer = (page) => page.click('.drawer-bg header .btn:has-text("Quay lại")');
const openEncounter = async (page, personName, { view = "Tất cả" } = {}) => {
  await nav(page, "Khám chữa bệnh"); await seg(page, view);
  await page.click(`tbody tr.click:has-text("${personName}")`); await page.waitForSelector(".drawer");
};
const ask = async (page, value, title) => { await modalOpen(page, title); await page.fill('.modal [name="v"]', value); await dialogOk(page); };

// ---------------- dữ liệu dựng sẵn
const p2 = await managedPerson(nm("Bệnh Nhân Khám"));
const pAllergy = await managedPerson(nm("Bệnh Nhân Dị Ứng"));
await ok("nurse1", "POST", `/persons/${pAllergy.id}/allergies`, { substance: "Amoxicillin", reaction: "Phát ban", confirmed: true });
const pRx = await managedPerson(nm("Bệnh Nhân Thuốc"));
const pCancel = await managedPerson(nm("Bệnh Nhân Hủy Khám"));
const pPharm = await managedPerson(nm("Bệnh Nhân Cấp Phát"));
const pLab = await managedPerson(nm("Bệnh Nhân Chờ Xét Nghiệm"));
const pConc = await managedPerson(nm("Bệnh Nhân Xung Đột"));
const encAllergy = await startEncounter(pAllergy.id);
const encRx = await startEncounter(pRx.id);
const encPharm = await startEncounter(pPharm.id);
const omep = await confirmedRx(encPharm.id, { drug_name: "Omeprazole 20mg", drug_code: "OMEP20", quantity_prescribed: 14, duration_days: 14 });
const unused = await confirmedRx(encPharm.id, { drug_name: "Cetirizine 10mg", drug_code: "CETI10", quantity_prescribed: 10, duration_days: 10 });   // chưa cấp lần nào
const encDraft = await startEncounter(pRx.id);
await ok("doctor1", "POST", `/encounters/${encDraft.id}/medication-orders`, { drug_name: "Ibuprofen 400mg", drug_code: "IBU400", dose: "1 viên", route: "uống", frequency: "2 lần/ngày", start_date: new Date().toISOString().slice(0, 10), duration_days: 5, quantity_prescribed: 10 });
const encLab = await startEncounter(pLab.id);
await ok("doctor1", "POST", `/encounters/${encLab.id}/orders`, { kind: "lab", description: "Công thức máu" });
await ok("doctor1", "POST", `/encounters/${encLab.id}/transition`, { to: "awaiting_results" });
const encConc = await startEncounter(pConc.id);
const encCancel = await startEncounter(pCancel.id);

const doc = await T.login("doctor1");

// =============================================================== M04 khám chữa bệnh
await T.step("C1 tạo lượt khám mới từ giao diện → bàn làm việc ở trạng thái Đang khám", async () => {
  await nav(doc, "Khám chữa bệnh");
  await doc.click('button:has-text("+ Lượt khám mới")'); await modalOpen(doc, "Lượt khám mới");
  await doc.click('.modal button:has-text("Chọn người…")');
  await pickInModal(doc, p2.full_name);
  await doc.fill('.modal [name="reason"]', "Đau đầu, chóng mặt 2 ngày");
  await modalSubmit(doc, "Tạo & bắt đầu khám");
  await doc.waitForSelector('.drawer .badge:has-text("Đang khám")');
  await mustContain(doc, ".drawer", p2.full_name);
});
await T.step("C2 sinh hiệu: để trống bị chặn; nhập hợp lệ hiện ở bảng với 2 mốc thời gian", async () => {
  await tab(doc, "Sinh hiệu");
  await doc.click('.drawer button:has-text("Ghi nhận sinh hiệu")'); await toast(doc, "Nhập ít nhất một chỉ số");
  await doc.fill('.drawer [name="pulse"]', "78"); await doc.fill('.drawer [name="sys"]', "150"); await doc.fill('.drawer [name="dia"]', "95");
  await doc.click('.drawer button:has-text("Ghi nhận sinh hiệu")');
  await doc.waitForSelector('.drawer td:has-text("150 mmHg")');
  await mustContain(doc, ".drawer", "Thời điểm đo", "Ghi vào hệ thống");
});
await T.step("C3 chẩn đoán chính thức", async () => {
  await tab(doc, "Chẩn đoán");
  await doc.fill('.drawer [name="text"]', "Tăng huyết áp vô căn"); await doc.selectOption('.drawer [name="kind"]', "final");
  await doc.click('.drawer button:has-text("Thêm chẩn đoán")');
  await doc.waitForSelector('.drawer td:has-text("Tăng huyết áp vô căn")'); await mustContain(doc, ".drawer", "Chính thức");
});
await T.step("C4 còn chỉ định chờ kết quả → KHÔNG hoàn tất được; có kết quả → hoàn tất (UAT-04)", async () => {
  await tab(doc, "Chỉ định XN");
  await doc.fill('.drawer [name="description"]', "Công thức máu"); await doc.click('.drawer form button:has-text("Chỉ định")');
  await doc.waitForSelector('.drawer td:has-text("Chờ kết quả")');
  await doc.click('.drawer-bg button:has-text("Hoàn tất khám")'); await dialogOk(doc);
  await toast(doc, "Còn chỉ định chưa có kết quả");
  await doc.click('.drawer button:has-text("Nhập kết quả")'); await ask(doc, "Bạch cầu bình thường", "Kết quả");
  await toast(doc, "Đã ghi kết quả");
  await doc.click('.drawer-bg button:has-text("Hoàn tất khám")'); await dialogOk(doc);
  await toast(doc, "Đã hoàn tất lượt khám");
  await doc.waitForSelector('.drawer .badge:has-text("Hoàn tất")');
});
await T.step("C5 lượt khám đã hoàn tất bị KHÓA: không sửa/ghi thêm; chỉ bổ sung bằng addendum có lý do (UAT-10)", async () => {
  await tab(doc, "Tổng quan");
  if (await doc.$('.drawer textarea[name="summary"]')) throw new Error("lượt khám đã hoàn tất vẫn cho sửa trực tiếp");
  await tab(doc, "Sinh hiệu");
  if (await doc.$('.drawer button:has-text("Ghi nhận sinh hiệu")')) throw new Error("lượt khám đã hoàn tất vẫn cho ghi sinh hiệu");
  await tab(doc, "Tổng quan");
  await doc.click('.drawer button:has-text("+ Thêm addendum")');
  await ask(doc, "Bổ sung kết quả huyết áp đo lại: 140/90", "Bổ sung hồ sơ khám");
  await ask(doc, "Sót thông tin khi ghi", "Lý do bổ sung");
  await toast(doc, "Đã thêm addendum");
  await doc.waitForSelector('.drawer .tl li:has-text("140/90")'); await mustContain(doc, ".drawer .tl", "Sót thông tin khi ghi");
  await closeDrawer(doc);
});
await T.step("C6 hủy lượt khám bắt buộc lý do; sau hủy không thao tác thêm được", async () => {
  await openEncounter(doc, pCancel.full_name, { view: "Đang thực hiện" });
  await doc.click('.drawer-bg button:has-text("Hủy lượt khám")'); await ask(doc, "Nhập nhầm người bệnh", "Hủy lượt khám");
  await toast(doc, "Đã cập nhật trạng thái"); await doc.waitForSelector('.drawer .badge:has-text("Đã hủy")');
  if (await doc.$('.drawer-bg button:has-text("Hoàn tất khám")')) throw new Error("lượt khám đã hủy vẫn còn nút thao tác");
  await closeDrawer(doc);
});
await T.step("C7 hai người cùng sửa một lượt khám: người lưu sau nhận cảnh báo xung đột phiên bản (BR-06)", async () => {
  const nurse = await T.login("nurse1");
  await openEncounter(nurse, pConc.full_name, { view: "Đang thực hiện" });
  await openEncounter(doc.use(), pConc.full_name, { view: "Đang thực hiện" });
  await doc.fill('.drawer textarea[name="summary"]', "Bác sĩ ghi trước"); await doc.click('.drawer button:has-text("Lưu")'); await toast(doc, "Đã lưu");
  await nurse.use().fill('.drawer textarea[name="summary"]', "Điều dưỡng ghi sau"); await nurse.click('.drawer button:has-text("Lưu")');
  await toast(nurse, "Dữ liệu đã được người khác thay đổi");
  doc.use(); await closeDrawer(doc);
});

// =============================================================== M05 kê đơn
await T.step("D1 kê thuốc người dị ứng: đơn nháp có cảnh báo; xác nhận BẮT BUỘC ghi nhận xử lý (UAT-02)", async () => {
  await openEncounter(doc.use(), pAllergy.full_name, { view: "Đang thực hiện" });
  await tab(doc, "Đơn thuốc");
  await doc.click('.drawer button:has-text("+ Kê đơn")'); await modalOpen(doc, "Kê đơn thuốc");
  await doc.fill('.modal [name="drug_name"]', "Amoxicillin 500mg"); await modalSubmit(doc, "Tạo đơn nháp");
  await toast(doc, "Đã tạo đơn nháp");
  await doc.waitForSelector('.drawer td:has-text("Dị ứng đã ghi nhận")');
  await doc.click('.drawer tbody button:has-text("Xác nhận")'); await modalOpen(doc, "Cảnh báo an toàn khi kê đơn");
  await modalSubmit(doc, "Vẫn xác nhận đơn");                                  // chưa ghi chú -> trình duyệt chặn (required)
  await doc.waitForTimeout(300);
  if (!(await doc.$('.modal-bg:has-text("Cảnh báo an toàn khi kê đơn")'))) throw new Error("xác nhận được khi chưa ghi nhận xử lý cảnh báo");
  await doc.fill('.modal [name="note"]', "Cân nhắc lợi ích/nguy cơ, theo dõi sát 24h đầu"); await modalSubmit(doc, "Vẫn xác nhận đơn");
  await toast(doc, "Đã xác nhận đơn thuốc"); await doc.waitForSelector('.drawer td .badge:has-text("Đang hiệu lực")');
  const audit = await ok("admin", "GET", "/audit?action=medication_warning_acknowledged");
  if (!audit.length) throw new Error("không có nhật ký xử lý cảnh báo");
});
await T.step("D2 kê trùng thuốc đang hiệu lực → cảnh báo trùng; lượt khám còn đơn NHÁP không hoàn tất được", async () => {
  await doc.click('.drawer button:has-text("+ Kê đơn")'); await modalOpen(doc, "Kê đơn thuốc");
  await doc.fill('.modal [name="drug_name"]', "Amoxicillin 500mg"); await modalSubmit(doc, "Tạo đơn nháp"); await toast(doc, "Đã tạo đơn nháp");
  await doc.waitForSelector('.drawer td:has-text("Đã có đơn đang hiệu lực cùng thuốc")');
  await doc.click('.drawer-bg button:has-text("Hoàn tất khám")'); await dialogOk(doc);
  await toast(doc, "Còn đơn thuốc nháp chưa xác nhận");
  await closeDrawer(doc);
});
await T.step("D3 điều dưỡng chỉ XEM đơn: không có nút kê/xác nhận/điều chỉnh/dừng", async () => {
  const nurse = await T.login("nurse1");
  await nav(nurse, "Chỉ định & Kê đơn");
  await nurse.waitForSelector("tbody tr");
  for (const b of ["Xác nhận", "Điều chỉnh", "Dừng"]) if (await nurse.$(`tbody button:has-text("${b}")`)) throw new Error(`điều dưỡng không được thấy nút “${b}”`);
  if (await nurse.$('button:has-text("+ Kê đơn mới")')) throw new Error("điều dưỡng không được thấy nút kê đơn mới");
});
await T.step("D4 bác sĩ xác nhận đơn nháp ở tab Kê đơn (Ibuprofen); dừng đơn nháp có cảnh báo (hủy)", async () => {
  await nav(doc.use(), "Chỉ định & Kê đơn");
  await doc.waitForSelector('tbody tr:has-text("Ibuprofen")');
  await doc.click('tbody tr:has-text("Ibuprofen") button:has-text("Xác nhận")'); await toast(doc, "Đã xác nhận đơn thuốc");
  await seg(doc, "Chờ xác nhận");
  await doc.click('tbody tr:has-text("Amoxicillin") button:has-text("Dừng")'); await modalOpen(doc, "Dừng/kết thúc đơn");
  await doc.selectOption('.modal [name="outcome"]', "cancelled"); await doc.fill('.modal [name="reason"]', "Nhập trùng đơn, hủy bản nháp");
  await modalSubmit(doc, "Xác nhận"); await toast(doc, "Đã cập nhật đơn");
});
await T.step("D5 đơn đã xác nhận KHÔNG sửa trực tiếp: Điều chỉnh → bản v2 nháp → xác nhận → bản cũ 'đã thay thế' (UAT-10)", async () => {
  await seg(doc, "Đang hiệu lực");
  await doc.click('tbody tr:has-text("Ibuprofen") button:has-text("Điều chỉnh")'); await modalOpen(doc, "Điều chỉnh đơn");
  await doc.fill('.modal [name="dose"]', "2 viên"); await doc.fill('.modal [name="reason"]', "Đau tăng, tăng liều");
  await modalSubmit(doc, "Tạo phiên bản mới"); await toast(doc, "Đã tạo bản điều chỉnh");
  await seg(doc, "Chờ xác nhận");
  await doc.waitForSelector('tbody tr:has-text("Ibuprofen"):has-text("v2")');
  await doc.click('tbody tr:has-text("Ibuprofen") button:has-text("Xác nhận")'); await toast(doc, "Đã xác nhận đơn thuốc");
  await seg(doc, "Đã kết thúc"); await doc.waitForSelector('tbody tr:has-text("Ibuprofen"):has-text("Đã thay bằng bản mới")');
});
await T.step("D6 dừng/hoàn thành đơn đang hiệu lực kèm lý do", async () => {
  await seg(doc, "Đang hiệu lực");
  await doc.click('tbody tr:has-text("Ibuprofen"):has-text("v2") button:has-text("Dừng")'); await modalOpen(doc, "Dừng/kết thúc đơn");
  await doc.selectOption('.modal [name="outcome"]', "completed"); await doc.fill('.modal [name="reason"]', "Hết đau, hoàn thành liệu trình");
  await modalSubmit(doc, "Xác nhận"); await toast(doc, "Đã cập nhật đơn");
  await seg(doc, "Đã kết thúc"); await doc.waitForSelector('tbody tr:has-text("Ibuprofen"):has-text("Hoàn tất")');
});
await T.step("D7 tab 'Chờ kết quả XN/thủ thuật' → mở lượt khám → nhập kết quả", async () => {
  await seg(doc, "Chờ kết quả XN");
  await doc.click(`tbody tr:has-text("${pLab.full_name}")`); await doc.waitForSelector(".drawer");
  await tab(doc, "Chỉ định XN"); await doc.click('.drawer button:has-text("Nhập kết quả")'); await ask(doc, "Hồng cầu, bạch cầu bình thường", "Kết quả");
  await toast(doc, "Đã ghi kết quả"); await closeDrawer(doc);
});
await T.step("D8 hủy lượt khám kéo theo hủy đơn/chỉ định; đơn ĐÃ cấp phát thì bị chặn", async () => {
  const e1 = await startEncounter(pCancel.id);
  await ok("doctor1", "POST", `/encounters/${e1.id}/orders`, { kind: "lab", description: "X-quang" });
  await ok("doctor1", "POST", `/encounters/${e1.id}/medication-orders`, { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1", route: "uống", frequency: "2/ngày", start_date: new Date().toISOString().slice(0, 10), duration_days: 5, quantity_prescribed: 10 });
  await openEncounter(doc.use(), pCancel.full_name, { view: "Đang thực hiện" });
  await doc.click('.drawer-bg button:has-text("Hủy lượt khám")'); await ask(doc, "Nhầm lượt khám", "Hủy lượt khám"); await toast(doc, "Đã cập nhật trạng thái");
  const d = await ok("doctor1", "GET", `/encounters/${e1.id}`);
  if (d.medication_orders[0].status !== "cancelled" || d.orders[0].status !== "cancelled") throw new Error("đơn/chỉ định không bị hủy theo lượt khám");
  await closeDrawer(doc);
  const e2 = await startEncounter(pCancel.id);
  const o = await confirmedRx(e2.id); await ok("pharm1", "POST", `/medication-orders/${o.id}/dispenses`, { quantity: 3 });
  await doc.reload(); await doc.waitForSelector(".side .nav");   // danh sách không tự cập nhật khi tạo bằng API
  await openEncounter(doc, pCancel.full_name, { view: "Đang thực hiện" });
  await doc.click('.drawer-bg button:has-text("Hủy lượt khám")'); await ask(doc, "Nhầm lượt khám lần 2", "Hủy lượt khám");
  await toast(doc, "đã được cấp phát"); await closeDrawer(doc);
});

// =============================================================== M06 cấp phát
const pharm = await T.login("pharm1");
const openOrder = async (page, personName, drug, view) => {
  await nav(page, "Cấp phát thuốc"); if (view) await seg(page, view);
  await page.click(`tbody tr:has-text("${personName}"):has-text("${drug}")`); await page.waitForSelector(".drawer");
};
await T.step("E1 hàng đợi: cấp 10/14 → 'một phần'; KHÔNG tự thành 'đã dùng'; cấp nốt 4 → 'đủ' và rời hàng đợi (UAT-03)", async () => {
  await nav(pharm, "Cấp phát thuốc");
  await pharm.waitForSelector(`tbody tr:has-text("${pPharm.full_name}"):has-text("Omeprazole")`);
  if (await pharm.$(`tbody tr:has-text("Ibuprofen")`)) throw new Error("đơn nháp/đã kết thúc không được vào hàng đợi");
  await openOrder(pharm, pPharm.full_name, "Omeprazole");
  await pharm.click('.drawer button:has-text("Cấp thuốc")'); await modalOpen(pharm, "Cấp thuốc");
  const max = await pharm.$eval('.modal [name="quantity"]', (e) => e.max); if (max !== "14") throw new Error(`ô số lượng phải giới hạn tối đa 14, thực tế ${max}`);
  await pharm.fill('.modal [name="quantity"]', "10"); await modalSubmit(pharm, "Ghi nhận cấp phát");
  await toast(pharm, "Cấp một phần – còn thiếu 4");
  await pharm.waitForSelector('.drawer .badge:has-text("Cấp một phần")');
  await mustContain(pharm, ".drawer", "Chưa có ghi nhận sử dụng");
  if (await pharm.$('.drawer button:has-text("Ghi nhận sử dụng thuốc")')) throw new Error("nhân viên dược không được ghi nhận sử dụng");
  await pharm.click('.drawer button:has-text("Cấp thuốc")'); await pharm.fill('.modal [name="quantity"]', "4"); await modalSubmit(pharm, "Ghi nhận cấp phát");
  await toast(pharm, "Đã cấp đủ theo đơn"); await pharm.click('.drawer-bg header .btn:has-text("Quay lại")'); await pharm.waitForTimeout(600);
  if (await pharm.$(`tbody tr:has-text("${pPharm.full_name}"):has-text("Omeprazole")`)) throw new Error("đơn đã cấp đủ vẫn còn trong hàng đợi");
});
await T.step("E2 máy chủ từ chối cấp vượt số kê (409) và hoàn trả vượt số đã cấp", async () => {
  const r = await api("pharm1", "POST", `/medication-orders/${unused.id}/dispenses`, { quantity: 99 });
  if (r.status !== 409 || r.data.error.code !== "OVER_DISPENSE") throw new Error(`mong đợi 409 OVER_DISPENSE, nhận ${r.status}`);
});
await T.step("E3 hoàn trả có lý do ghi thành sự kiện riêng; dòng lịch sử 'Hoàn trả'", async () => {
  await openOrder(pharm.use(), pPharm.full_name, "Omeprazole", "Tất cả đơn");
  await pharm.click('.drawer button:has-text("Hoàn trả / hủy cấp phát")'); await modalOpen(pharm, "Hoàn trả / hủy cấp phát");
  await pharm.fill('.modal [name="quantity"]', "3"); await pharm.fill('.modal [name="note"]', "Người nhận trả lại do hết triệu chứng");
  await modalSubmit(pharm, "Ghi nhận"); await toast(pharm, "Đã ghi nhận");
  await pharm.waitForSelector('.drawer td .badge:has-text("Hoàn trả")'); await mustContain(pharm, ".drawer", "Người nhận trả lại");
  await pharm.click('.drawer button:has-text("Hoàn trả / hủy cấp phát")'); await pharm.fill('.modal [name="quantity"]', "50"); await pharm.fill('.modal [name="note"]', "quá số");
  await modalSubmit(pharm, "Ghi nhận"); await toast(pharm, "vượt số đã cấp");
  await pharm.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(pharm);
});
const nurse2 = await T.login("nurse1");
await T.step("E4 điều dưỡng ghi nhận SỬ DỤNG: đơn chưa cấp bị chặn; 'không dùng' bắt buộc lý do (UAT-03)", async () => {
  await openOrder(nurse2, pPharm.full_name, "Cetirizine", "Tất cả đơn");
  await nurse2.click('.drawer button:has-text("Ghi nhận sử dụng thuốc")'); await modalOpen(nurse2, "Ghi nhận sử dụng thuốc");
  await modalSubmit(nurse2, "Lưu"); await toast(nurse2, "Chưa có cấp phát");
  await nurse2.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(nurse2);
  await ok("pharm1", "POST", `/medication-orders/${unused.id}/dispenses`, { quantity: 5 });
  await nurse2.reload(); await nurse2.waitForSelector(".side .nav");
  await openOrder(nurse2, pPharm.full_name, "Cetirizine", "Tất cả đơn");
  await nurse2.click('.drawer button:has-text("Ghi nhận sử dụng thuốc")'); await modalOpen(nurse2, "Ghi nhận sử dụng thuốc");
  await nurse2.selectOption('.modal [name="administered"]', "no"); await modalSubmit(nurse2, "Lưu"); await toast(nurse2, "ghi lý do");
  await nurse2.fill('.modal [name="reason"]', "Người bệnh từ chối uống, đã giáo dục"); await modalSubmit(nurse2, "Lưu"); await toast(nurse2, "Đã ghi nhận");
  await nurse2.waitForSelector('.drawer td .badge:has-text("Không dùng")'); await mustContain(nurse2, ".drawer", "Người bệnh từ chối uống");
  await nurse2.click('.drawer button:has-text("Ghi nhận sử dụng thuốc")'); await nurse2.selectOption('.modal [name="administered"]', "yes");
  await modalSubmit(nurse2, "Lưu"); await toast(nurse2, "Đã ghi nhận"); await nurse2.waitForSelector('.drawer td .badge:has-text("Đã dùng")');
});

process.exit((await T.done()).length ? 1 : 0);
