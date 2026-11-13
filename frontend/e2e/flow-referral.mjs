// E2E đầy đủ: Chuyển viện (M09, WF-06) – bác sĩ lập → người phê duyệt điều phối → điều dưỡng bàn giao → kết quả → hoàn thành.
import { api, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, ok, pickInModal, PDF, start, startEncounter, toast, uniq } from "./lib.mjs";

const T = await start("Chuyển viện (M09)");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const ask = async (page, value, title) => { await modalOpen(page, title); await page.fill('.modal [name="v"]', value); await dialogOk(page); };
const card = (page, name) => page.locator(`.kcard:has-text("${name}")`).first();
const openCard = async (page, name) => { await page.reload(); await page.waitForSelector(".side .nav"); await nav(page, "Chuyển viện"); await card(page, name).click(); await page.waitForSelector(".drawer"); };
const status = (page, text) => page.waitForSelector(`.drawer .card:has-text("Thông tin chuyển viện") .badge:has-text("${text}")`);
const closeDrawer = (page) => page.click('.drawer-bg header .btn:has-text("Quay lại")');

const P1 = await managedPerson(nm("Chuyển Viện Thường"));
const P2 = await managedPerson(nm("Chuyển Viện Cấp Cứu"));
const P3 = await managedPerson(nm("Chuyển Viện Kết Cục"));
const P4 = await managedPerson(nm("Chuyển Viện Hủy"));
const E1 = await startEncounter(P1.id), E2 = await startEncounter(P2.id), E3 = await startEncounter(P3.id), E4 = await startEncounter(P4.id);

const doc = await T.login("doctor1");
const app = await T.login("approver1");
const nur = await T.login("nurse1");

/** Lập đề nghị chuyển viện từ giao diện bác sĩ. */
const createReferral = async (person, { urgency, reason, dest }) => {
  await nav(doc, "Chuyển viện");
  await doc.click('button:has-text("+ Lập đề nghị chuyển viện")'); await modalOpen(doc, "chọn lượt khám");
  await pickInModal(doc, person.full_name);
  await doc.click('.modal-bg tr.click:has-text("Đang khám")');
  await modalOpen(doc, "Lập đề nghị chuyển viện");
  await doc.selectOption('.modal [name="urgency"]', urgency); await doc.fill('.modal [name="reason"]', reason); await doc.fill('.modal [name="destination"]', dest);
  await modalSubmit(doc, "Lưu dự thảo"); await toast(doc, "Đã lập đề nghị chuyển viện");
  await doc.waitForSelector(".drawer");
};

await T.step("H1 bác sĩ lập đề nghị chuyển viện (dự thảo) từ lượt khám", async () => {
  await createReferral(P1, { urgency: "routine", reason: "Nghi viêm ruột thừa, cần siêu âm và phẫu thuật", dest: "Bệnh viện Đa khoa tỉnh" });
  await status(doc, "Dự thảo"); await mustContain(doc, ".drawer", P1.full_name, "Nghi viêm ruột thừa");
  if (await doc.$('.drawer button:has-text("Phê duyệt")')) throw new Error("bác sĩ không được thấy nút Phê duyệt");
});
await T.step("H2 bác sĩ gửi duyệt → 'Chờ xử lý'", async () => {
  await doc.click('.drawer button:has-text("Gửi duyệt/điều phối")'); await modalOpen(doc, "Gửi duyệt");
  await doc.click('.modal-bg footer button:has-text("Gửi")'); await toast(doc, "Đã gửi duyệt"); await status(doc, "Chờ xử lý"); await closeDrawer(doc);
});
await T.step("H3 người phê duyệt: KHÔNG thấy lý do chuyên môn, không thấy tài liệu; phê duyệt & điều phối", async () => {
  await openCard(app, P1.full_name);
  await mustContain(app, ".drawer", "Ẩn theo phân quyền");
  await mustNotContain(app, ".drawer", "Nghi viêm ruột thừa", "Tài liệu chuyển viện");
  if (await app.$('.drawer button:has-text("Gửi duyệt")')) throw new Error("người phê duyệt không được gửi duyệt hộ bác sĩ");
  await app.click('.drawer button:has-text("Phê duyệt & điều phối")'); await modalOpen(app, "Phê duyệt & điều phối");
  const dest = await app.$eval('.modal [name="destination"]', (e) => e.value); if (dest !== "Bệnh viện Đa khoa tỉnh") throw new Error("nơi tiếp nhận phải được điền sẵn");
  await modalSubmit(app, "Lưu"); await toast(app, "Đã điều phối"); await status(app, "Đã điều phối"); await closeDrawer(app);
});
await T.step("H4 bệnh viện không tiếp nhận: trả về 'Chờ xử lý' bắt buộc lý do + ghi lịch sử; duyệt lại; điều dưỡng xác nhận rời trại", async () => {
  await openCard(nur, P1.full_name);
  if (await nur.$('.drawer button:has-text("Phê duyệt")')) throw new Error("điều dưỡng không được phê duyệt");
  await nur.click('.drawer button:has-text("BV đổi / không tiếp nhận")'); await modalOpen(nur, "Bệnh viện đổi / không tiếp nhận");
  await modalSubmit(nur, "Lưu"); await nur.waitForTimeout(300);
  if (!(await nur.$('.modal-bg:has-text("Bệnh viện đổi")'))) throw new Error("trả về khi chưa nêu lý do");
  await nur.fill('.modal [name="note"]', "BV tỉnh hết giường"); await nur.fill('.modal [name="destination"]', "Bệnh viện Đa khoa khu vực");
  await modalSubmit(nur, "Lưu"); await toast(nur, "Đã cập nhật điều phối"); await status(nur, "Chờ xử lý"); await mustContain(nur, ".drawer .tl", "BV tỉnh hết giường");
  await closeDrawer(nur);
  await openCard(app, P1.full_name);
  await app.click('.drawer button:has-text("Phê duyệt & điều phối")'); await modalSubmit(app, "Lưu"); await toast(app, "Đã điều phối"); await closeDrawer(app);
  await openCard(nur, P1.full_name);
  await nur.click('.drawer button:has-text("Xác nhận đã rời trại")'); await modalOpen(nur, "Xác nhận rời trại");
  const left = await nur.$eval('.modal [name="left_at"]', (e) => e.value); if (!left) throw new Error("thời điểm rời trại phải điền sẵn");
  await modalSubmit(nur, "Lưu"); await toast(nur, "Đã ghi nhận rời trại"); await status(nur, "Đang điều trị ngoài trại");
});
await T.step("H5 điều dưỡng tải giấy chuyển viện (PDF) gắn đúng hồ sơ chuyển viện", async () => {
  await nur.click('.drawer button:has-text("+ Tải lên")'); await modalOpen(nur, "Tải tài liệu y tế");
  await nur.setInputFiles('.modal input[type="file"]', { name: "giay_chuyen_vien.pdf", mimeType: "application/pdf", buffer: PDF });
  await modalSubmit(nur, "Tải lên"); await toast(nur, "Đã tải lên và lưu mã hóa");
  await nur.waitForSelector('.drawer td:has-text("giay_chuyen_vien.pdf")');
});
await T.step("H6 ghi nhận kết quả: bỏ trống bị chặn; có kết quả → 'Đã có kết quả'", async () => {
  await nur.click('.drawer button:has-text("Ghi nhận kết quả điều trị")'); await modalOpen(nur, "Kết quả điều trị ngoài trại");
  await modalSubmit(nur, "Lưu"); await nur.waitForTimeout(300);
  if (!(await nur.$('.modal-bg:has-text("Kết quả điều trị ngoài trại")'))) throw new Error("ghi nhận được khi chưa có kết quả");
  await nur.fill('.modal [name="result_note"]', "Đã phẫu thuật cắt ruột thừa, hậu phẫu ổn định");
  await modalSubmit(nur, "Lưu"); await toast(nur, "Đã ghi nhận kết quả"); await status(nur, "Đã có kết quả"); await closeDrawer(nur);
});
await T.step("H7 bác sĩ hoàn thành (kế hoạch sau chuyển viện + kết cục) → 'Hoàn tất'; chuyển viện KHÔNG đổi đợt tiếp nhận (BR-05)", async () => {
  await openCard(doc, P1.full_name);
  await doc.click('.drawer button:has-text("Hoàn thành chuyển viện")'); await modalOpen(doc, "Hoàn thành chuyển viện");
  await modalSubmit(doc, "Lưu"); await doc.waitForTimeout(300);
  if (!(await doc.$('.modal-bg:has-text("Hoàn thành chuyển viện")'))) throw new Error("hoàn thành được khi thiếu kế hoạch sau chuyển viện");
  await doc.selectOption('.modal [name="outcome"]', "returned"); await doc.fill('.modal [name="plan"]', "Cắt chỉ sau 7 ngày, tái khám, kháng sinh theo đơn bệnh viện");
  await modalSubmit(doc, "Lưu"); await toast(doc, "Đã hoàn thành chuyển viện"); await status(doc, "Hoàn tất");
  await mustContain(doc, ".drawer", "Đã trở lại trại", "Cắt chỉ sau 7 ngày");
  const nEvents = await doc.$$eval(".drawer .tl li", (l) => l.length); if (nEvents < 7) throw new Error(`lịch sử điều phối phải đủ các mốc (có ${nEvents})`);
  const stays = (await ok("officer1", "GET", `/persons/${P1.id}/stays`)); if (!["received", "managed"].includes(stays.at(-1).status)) throw new Error("chuyển viện không được kết thúc đợt tiếp nhận");
  await closeDrawer(doc);
  await seg(doc, "Đã đóng"); await doc.waitForSelector(`tbody tr:has-text("${P1.full_name}")`);
});
await T.step("H8 chuyển viện CẤP CỨU đi tắt: không cần duyệt, gắn 'cần hậu kiểm'; người phê duyệt hậu kiểm → đóng cờ", async () => {
  await createReferral(P2, { urgency: "emergency", reason: "Đau thắt ngực cấp, nghi nhồi máu cơ tim", dest: "Bệnh viện Tim mạch" });
  await doc.click('.drawer button:has-text("Chuyển viện khẩn (đi tắt)")'); await modalOpen(doc, "Chuyển viện khẩn");
  await modalSubmit(doc, "Xác nhận chuyển"); await toast(doc, "Đã chuyển khẩn – chờ hậu kiểm");
  await status(doc, "Đang điều trị ngoài trại"); await mustContain(doc, ".drawer", "cần hậu kiểm");
  await closeDrawer(doc);
  await openCard(app, P2.full_name);
  await mustContain(app, ".drawer", "đường tắt");
  await app.click('.drawer button:has-text("Hậu kiểm")'); await ask(app, "Hợp lệ: tình trạng khẩn cấp, đã bàn giao đủ hồ sơ", "Hậu kiểm chuyển viện cấp cứu");
  await toast(app, "Đã hậu kiểm"); await app.waitForFunction(() => !document.querySelector(".drawer")?.innerText.includes("cần hậu kiểm"));
  const notes = await ok("approver1", "GET", "/notifications?limit=100");
  if (!notes.items.some((n) => n.kind === "referral.shortcut" && n.link_ref)) throw new Error("người phê duyệt phải nhận thông báo Khẩn khi có chuyển viện đi tắt");
});
await T.step("H9 kết cục 'Tử vong' → bắt buộc hậu kiểm theo quy trình, không đóng im lặng", async () => {
  const r = await ok("doctor1", "POST", `/encounters/${E3.id}/referrals`, { urgency: "urgent", reason: "Suy hô hấp cấp", destination: "BV Phổi" });
  await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" }); await ok("approver1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated" });
  await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" }); await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "result_received", result_note: "Đã cấp cứu, tiên lượng nặng" });
  await openCard(doc, P3.full_name);
  await doc.click('.drawer button:has-text("Hoàn thành chuyển viện")'); await modalOpen(doc, "Hoàn thành chuyển viện");
  await doc.selectOption('.modal [name="outcome"]', "deceased"); await doc.fill('.modal [name="plan"]', "Báo cáo theo quy trình, thông báo cấp có thẩm quyền");
  await modalSubmit(doc, "Lưu"); await toast(doc, "Đã hoàn thành chuyển viện");
  await mustContain(doc, ".drawer", "Kết thúc với kết cục", "Tử vong", "xác nhận theo quy trình");
  await closeDrawer(doc);
  app.use(); await app.reload(); await app.waitForSelector(".side .nav"); await nav(app, "Chuyển viện"); await seg(app, "Đã đóng");
  await app.click(`tbody tr:has-text("${P3.full_name}")`); await app.waitForSelector(".drawer");
  await app.click('.drawer button:has-text("Hậu kiểm")'); await ask(app, "Đã báo cáo theo quy trình được duyệt", "Hậu kiểm chuyển viện cấp cứu"); await toast(app, "Đã hậu kiểm");
});
await T.step("H10 hủy đề nghị còn nháp (bắt buộc lý do) → vào mục 'Đã đóng'", async () => {
  const r = await ok("doctor1", "POST", `/encounters/${E4.id}/referrals`, { urgency: "routine", reason: "Chụp CT ngoài", destination: "BV A" });
  await openCard(doc, P4.full_name);
  await doc.click('.drawer button:has-text("Hủy")'); await modalOpen(doc, "Hủy đề nghị chuyển viện");
  await doc.fill('.modal [name="note"]', "Bệnh nhân ổn định, không còn chỉ định"); await modalSubmit(doc, "Lưu"); await toast(doc, "Đã hủy");
  await status(doc, "Đã hủy"); await closeDrawer(doc);
  await seg(doc, "Đã đóng"); await doc.waitForSelector(`tbody tr:has-text("${P4.full_name}")`);
});
await T.step("H11 quyền: điều dưỡng không gửi duyệt/hoàn thành; người phê duyệt không lập đề nghị", async () => {
  if (await app.$('button:has-text("+ Lập đề nghị chuyển viện")')) throw new Error("người phê duyệt không được lập đề nghị");
  if (await nur.$('button:has-text("+ Lập đề nghị chuyển viện")')) throw new Error("điều dưỡng không được lập đề nghị");
  const r = await api("nurse1", "PATCH", `/referrals/${(await ok("doctor1", "POST", `/encounters/${E4.id}/referrals`, { urgency: "routine", reason: "Kiểm thử quyền", destination: "BV A" })).id}/status`, { to: "pending" });
  if (r.status !== 403) throw new Error(`điều dưỡng gửi duyệt phải bị 403, nhận ${r.status}`);
});

process.exit((await T.done()).length ? 1 : 0);
