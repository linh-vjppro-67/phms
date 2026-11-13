// E2E đầy đủ: Cấp cứu (WF-08) – ghi nhận tối thiểu → can thiệp → bổ sung hồ sơ → đối soát danh tính → đóng sự kiện.
import { api, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, newPerson, ok, pickInModal, start, toast, today, uniq } from "./lib.mjs";

const T = await start("Cấp cứu (WF-08)");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const card = (page, text) => page.locator(`.card:has-text("${text}")`).filter({ has: page.locator('button:has-text("Mở hồ sơ khám cấp cứu"), button:has-text("Đang mở"), .badge') }).first();
const closeDrawer = (page) => page.click('.drawer-bg header .btn:has-text("Quay lại")');
const localDT = (daysAgo) => { const d = new Date(Date.now() - daysAgo * 864e5); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const TEMP = `Nam khoảng 40 tuổi, buồng ${U}`;

const known = await managedPerson(nm("Cấp Cứu Đã Biết"));
const noStay = await newPerson(nm("Cấp Cứu Chưa Có Kỳ"), { stay: false });

const nur = await T.login("nurse1");
const doc = await T.login("doctor1");
const off = await T.login("officer1");

await T.step("I1 ghi nhận cấp cứu CHƯA RÕ DANH TÍNH chỉ với thông tin tối thiểu → tạo hồ sơ tạm + lượt khám cấp cứu", async () => {
  await nav(nur, "Cấp cứu");
  await nur.click('button:has-text("+ Ghi nhận cấp cứu")'); await modalOpen(nur, "Ghi nhận cấp cứu");
  await nur.fill('.modal [name="temp_identity"]', TEMP); await nur.fill('.modal [name="location"]', "Buồng 5, khu B");
  await modalSubmit(nur, "Ghi nhận & mở hồ sơ"); await toast(nur, "Đã ghi nhận sự kiện cấp cứu");
  await nur.waitForSelector('.drawer .badge:has-text("Đang khám")'); await mustContain(nur, ".drawer", "Cấp cứu", "[TẠM]");
  await closeDrawer(nur);
  await nur.waitForSelector(`.card:has-text("${TEMP}")`); await mustContain(nur, `.card:has-text("${TEMP}")`, "Danh tính tạm – cần đối soát", "Buồng 5, khu B");
});
await T.step("I2 thông báo: bác sĩ nhận 'CẤP CỨU' (Khẩn), cán bộ tiếp nhận nhận 'cần đối soát', người ghi KHÔNG tự nhận", async () => {
  const d = (await ok("doctor1", "GET", "/notifications?limit=100")).items;
  if (!d.some((n) => n.kind === "emergency.created" && n.severity === "critical")) throw new Error("bác sĩ phải nhận thông báo Khẩn");
  const o = (await ok("officer1", "GET", "/notifications?limit=100")).items;
  const idn = o.find((n) => n.kind === "emergency.identity"); if (!idn) throw new Error("cán bộ tiếp nhận phải nhận thông báo đối soát");
  if (JSON.stringify(idn).includes("buồng")) throw new Error("thông báo cho cán bộ không được lộ nội dung lâm sàng");
  const n = (await ok("nurse1", "GET", "/notifications?limit=100")).items;
  if (n.some((x) => x.kind === "emergency.created" && x.body?.includes(TEMP))) throw new Error("người ghi nhận không được tự nhận thông báo");
});
await T.step("I3 ghi nhận can thiệp: dòng thời gian có người thực hiện + giờ nhập", async () => {
  const c = `.card:has-text("${TEMP}")`;
  await nur.fill(`${c} [name="action"]`, "Đặt tư thế an toàn, bảo vệ đường thở"); await nur.fill(`${c} [name="performer"]`, "Điều dưỡng Lan");
  await nur.click(`${c} button:has-text("Ghi nhận")`); await toast(nur, "Đã ghi nhận");
  await nur.waitForSelector(`${c} .tl li:has-text("Đặt tư thế an toàn")`); await mustContain(nur, `${c} .tl`, "Điều dưỡng Lan", "nhập");
});
await T.step("I4 đóng sự kiện khi CHƯA hoàn thiện: bị chặn, liệt kê đủ điều kiện còn thiếu; bác sĩ không đối soát danh tính", async () => {
  await nav(doc, "Cấp cứu"); await doc.waitForSelector(`.card:has-text("${TEMP}")`);
  if (await doc.$(`.card:has-text("${TEMP}") button:has-text("Đối soát danh tính")`)) throw new Error("bác sĩ không được đối soát danh tính (việc của cán bộ tiếp nhận)");
  await doc.click(`.card:has-text("${TEMP}") button:has-text("Đóng sự kiện")`); await modalOpen(doc, "Đóng sự kiện cấp cứu");
  await doc.fill('.modal [name="note"]', "Thử đóng sớm"); await modalSubmit(doc, "Đóng sự kiện");
  await toast(doc, "Chưa đủ điều kiện đóng sự kiện cấp cứu"); await mustContain(doc, ".toast", "chưa hoàn tất hồ sơ", "chưa được đối soát");
  await doc.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(doc);
});
await T.step("I5 bổ sung hồ sơ sau cấp cứu: bác sĩ thêm chẩn đoán và hoàn tất lượt khám", async () => {
  await doc.click(`.card:has-text("${TEMP}") button:has-text("Mở hồ sơ khám cấp cứu")`); await doc.waitForSelector(".drawer");
  await doc.click('.drawer button[role="tab"]:has-text("Chẩn đoán")');
  await doc.fill('.drawer [name="text"]', "Cơn động kinh toàn thể"); await doc.selectOption('.drawer [name="kind"]', "final"); await doc.click('.drawer form button:has-text("Thêm chẩn đoán")');
  await doc.waitForSelector('.drawer td:has-text("Cơn động kinh toàn thể")');
  await doc.click('.drawer-bg button:has-text("Hoàn tất khám")'); await dialogOk(doc); await toast(doc, "Đã hoàn tất lượt khám"); await closeDrawer(doc);
});
await T.step("I6 cán bộ tiếp nhận đối soát hồ sơ TẠM (danh tính thật + căn cứ) → 'Đã xác minh'", async () => {
  await nav(off, "Tiếp nhận & Hồ sơ"); await off.click('.seg button:has-text("Chờ đối soát danh tính")');
  await off.click(`tbody tr:has-text("${TEMP}")`); await off.waitForSelector(".drawer"); await mustContain(off, ".drawer", "hồ sơ tạm");
  await off.click('.drawer button:has-text("Đối soát")'); await modalOpen(off, "Đối soát danh tính");
  await off.fill('.modal [name="full_name"]', nm("Trần Văn Đã Rõ")); await off.fill('.modal [name="date_of_birth"]', "1984-08-19");
  await off.fill('.modal [name="external_id"]', "E2E-EMG-" + U); await off.fill('.modal [name="note"]', "Đối chiếu ảnh và hồ sơ giấy với quản giáo buồng");
  await modalSubmit(off, "Xác minh"); await toast(off, "Đã xác minh danh tính"); await off.waitForSelector('.drawer .badge:has-text("Đã xác minh")');
});
await T.step("I7 đã đủ điều kiện: bác sĩ đóng sự kiện + hẹn theo dõi → sự kiện sang 'Đã đóng', sinh lịch theo dõi", async () => {
  await doc.reload(); await doc.waitForSelector(".side .nav"); await nav(doc, "Cấp cứu");
  await doc.waitForSelector(`.card:has-text("${nm("Trần Văn Đã Rõ")}")`);
  if (await doc.$(`.card:has-text("${nm("Trần Văn Đã Rõ")}") .badge:has-text("Danh tính tạm")`)) throw new Error("đã đối soát nhưng vẫn hiện nhãn danh tính tạm");
  await doc.click(`.card:has-text("${nm("Trần Văn Đã Rõ")}") button:has-text("Đóng sự kiện")`); await modalOpen(doc, "Đóng sự kiện cấp cứu");
  await doc.fill('.modal [name="note"]', "Đã ổn định, đã hoàn thiện hồ sơ"); await doc.fill('.modal [name="follow_up_date"]', today(3));
  await modalSubmit(doc, "Đóng sự kiện"); await toast(doc, "Đã đóng sự kiện");
  await seg(doc, "Đã đóng"); await doc.waitForSelector(`.card:has-text("${nm("Trần Văn Đã Rõ")}")`);
  const ap = await ok("doctor1", "GET", "/appointments?kind=follow_up&limit=500");
  if (!ap.some((a) => a.person_name === nm("Trần Văn Đã Rõ"))) throw new Error("không sinh lịch theo dõi sau cấp cứu");
});
await T.step("I8 ghi nhận muộn: khi thời điểm xảy ra cách >15 phút phải nêu lý do; lưu cả 2 mốc thời gian (BR-03)", async () => {
  await nav(nur, "Cấp cứu"); await nur.click('button:has-text("+ Ghi nhận cấp cứu")'); await modalOpen(nur, "Ghi nhận cấp cứu");
  await nur.click('.modal button:has-text("Đã biết danh tính")'); await nur.click('.modal button:has-text("Chọn…")'); await pickInModal(nur, known.full_name);
  await nur.fill('.modal input[type="datetime-local"]', localDT(1));
  await nur.waitForSelector('.modal [name="late_entry_reason"]');
  await modalSubmit(nur, "Ghi nhận & mở hồ sơ"); await nur.waitForTimeout(300);
  if (!(await nur.$('.modal-bg:has-text("Ghi nhận cấp cứu")'))) throw new Error("ghi muộn được khi chưa nêu lý do");
  await nur.fill('.modal [name="late_entry_reason"]', "Mất điện khu B, ghi bổ sung sau khi có điện");
  await modalSubmit(nur, "Ghi nhận & mở hồ sơ"); await toast(nur, "Đã ghi nhận sự kiện cấp cứu"); await closeDrawer(nur);
  await nur.waitForSelector(`.card:has-text("${known.full_name}")`); await mustContain(nur, `.card:has-text("${known.full_name}")`, "Lý do ghi muộn", "Mất điện khu B", "Xảy ra lúc", "Ghi vào hệ thống");
  if (await nur.$(`.card:has-text("${known.full_name}") .badge:has-text("Danh tính tạm")`)) throw new Error("người đã biết danh tính không được gắn nhãn tạm");
});
await T.step("I9 KHÔNG chặn cấp cứu: người chưa có đợt tiếp nhận ở cơ sở vẫn ghi nhận được (kỳ tạm cần đối soát)", async () => {
  await nur.click('button:has-text("+ Ghi nhận cấp cứu")'); await modalOpen(nur, "Ghi nhận cấp cứu");
  await nur.click('.modal button:has-text("Đã biết danh tính")'); await nur.click('.modal button:has-text("Chọn…")'); await pickInModal(nur, noStay.full_name);
  await modalSubmit(nur, "Ghi nhận & mở hồ sơ"); await toast(nur, "Đã ghi nhận sự kiện cấp cứu"); await closeDrawer(nur);
  const stays = await ok("officer1", "GET", `/persons/${noStay.id}/stays`);
  if (!stays.length || !stays.at(-1).provisional) throw new Error("phải tạo đợt tiếp nhận tạm (provisional) khi cấp cứu");
});

process.exit((await T.done()).length ? 1 : 0);
