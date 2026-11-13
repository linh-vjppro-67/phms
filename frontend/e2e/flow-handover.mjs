// E2E đầy đủ: Chuyển trại & Bàn giao (WF-07) – hai cơ sở: khởi tạo → tóm tắt y tế → xác nhận → cơ sở nhận tiếp nhận (biên nhận).
import { api, confirmedRx, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, ok, pickPatient, start, startEncounter, toast, today, uniq } from "./lib.mjs";

const T = await start("Chuyển trại & Bàn giao (WF-07)");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const card = (page, name) => page.locator(`.card:has-text("${name}")`).first();

const PT = await managedPerson(nm("Chuyển Trại Còn Điều Trị"));   // sẽ có đơn thuốc đang hiệu lực + lịch hẹn mở
const PR = await managedPerson(nm("Kết Thúc Quản Lý"));
{
  const e = await startEncounter(PT.id);
  await confirmedRx(e.id);
  await ok("nurse1", "POST", "/appointments", { person_id: PT.id, due_date: today(7), note: "Tái khám tuần sau" });
  await ok("doctor1", "POST", `/encounters/${e.id}/transition`, { to: "completed" });
}
const SUMMARY = "Đang dùng Paracetamol 500mg x2/ngày. Cần theo dõi huyết áp hằng tuần. Dị ứng: không. Tái khám sau 7 ngày.";

const off1 = await T.login("officer1");
const nur = await T.login("nurse1");
const off2 = await T.login("officer2");
const doc2 = await T.login("doctor2");

await T.step("J1 cán bộ khởi tạo phiếu chuyển trại sang Trại 2 → thanh tiến độ ở bước 'Tóm tắt y tế'", async () => {
  await nav(off1, "Chuyển trại & Bàn giao");
  await off1.click('button:has-text("+ Khởi tạo bàn giao")'); await modalOpen(off1, "Khởi tạo bàn giao");
  await off1.selectOption('.modal [name="stay_id"]', { label: `${PT.full_name} (${PT.code})` });
  await off1.selectOption('.modal [name="to_facility_id"]', { label: "Trại giam số 2" }); await off1.fill('.modal [name="reason"]', "Quyết định điều chuyển số 215/QĐ-TG");
  await modalSubmit(off1, "Khởi tạo"); await toast(off1, "Đã khởi tạo phiếu bàn giao");
  await off1.waitForSelector(`.card:has-text("${PT.full_name}")`); await mustContain(off1, `.card:has-text("${PT.full_name}")`, "Chuyển trại", "Chuyển đi", "Chưa có tóm tắt y tế");
  const steps = await off1.$$eval(`.card:has-text("${PT.full_name}") .stepper .step`, (s) => s.length); if (steps !== 4) throw new Error(`chuyển trại phải có 4 bước (có ${steps})`);
});
await T.step("J2 xác nhận khi CHƯA có tóm tắt y tế → bị chặn; khởi tạo phiếu thứ hai cho cùng người → bị chặn", async () => {
  await off1.click(`.card:has-text("${PT.full_name}") button:has-text("Xác nhận bàn giao")`); await modalOpen(off1, "Xác nhận bàn giao");
  await modalSubmit(off1, "Xác nhận đã bàn giao"); await toast(off1, "Chưa có bản tóm tắt y tế");
  await off1.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(off1);
  await off1.click('button:has-text("+ Khởi tạo bàn giao")'); await modalOpen(off1, "Khởi tạo bàn giao");
  await off1.selectOption('.modal [name="stay_id"]', { label: `${PT.full_name} (${PT.code})` }); await off1.selectOption('.modal [name="to_facility_id"]', { label: "Trại giam số 2" });
  await off1.fill('.modal [name="reason"]', "Lập trùng phiếu"); await modalSubmit(off1, "Khởi tạo"); await toast(off1, "Đã có phiếu bàn giao đang chờ");
  await off1.click('.modal-bg footer button:has-text("Hủy")'); await modalGone(off1);
});
await T.step("J3 điều dưỡng soạn tóm tắt y tế; cán bộ chỉ thấy 'đã có tóm tắt' (KHÔNG đọc được nội dung)", async () => {
  await nav(nur, "Chuyển trại & Bàn giao"); await card(nur, PT.full_name).waitFor();
  if (await nur.$(`.card:has-text("${PT.full_name}") button:has-text("Xác nhận bàn giao")`)) throw new Error("điều dưỡng không được xác nhận bàn giao");
  await nur.click(`.card:has-text("${PT.full_name}") button:has-text("Soạn tóm tắt y tế")`); await modalOpen(nur, "Tóm tắt y tế bàn giao");
  await mustContain(nur, ".modal", "lịch hẹn mở");                                                // hiện điều trị đang mở cho người soạn
  await nur.fill('.modal [name="summary"]', SUMMARY); await modalSubmit(nur, "Lưu"); await toast(nur, "Đã lưu tóm tắt bàn giao");
  await mustContain(nur, `.card:has-text("${PT.full_name}")`, "Dùng Paracetamol");
  await off1.reload(); await off1.waitForSelector(".side .nav"); await nav(off1, "Chuyển trại & Bàn giao");
  await mustContain(off1, `.card:has-text("${PT.full_name}")`, "đã lập tóm tắt");
  await mustNotContain(off1, `.card:has-text("${PT.full_name}")`, "Paracetamol", "huyết áp");
  const notes = (await ok("officer1", "GET", "/notifications?limit=100")).items; if (!notes.some((n) => n.kind === "handover.ready")) throw new Error("cán bộ phải nhận thông báo 'sẵn sàng xác nhận'");
});
await T.step("J4 xác nhận khi còn điều trị/lịch mở: phải tick xác nhận đã bàn giao; sau đó đợt tiếp nhận → 'Đã chuyển trại'", async () => {
  await off1.click(`.card:has-text("${PT.full_name}") button:has-text("Xác nhận bàn giao")`); await modalOpen(off1, "Xác nhận bàn giao");
  await off1.fill('.modal [name="receiver_name"]', "Cán bộ tiếp nhận Trại 2");
  await modalSubmit(off1, "Xác nhận đã bàn giao"); await toast(off1, "Còn điều trị/lịch đang mở");
  await off1.check('.modal [name="ack"]'); await modalSubmit(off1, "Xác nhận đã bàn giao"); await toast(off1, "Đã xác nhận bàn giao");
  const stays = await ok("officer1", "GET", `/persons/${PT.id}/stays`); if (stays.at(-1).status !== "transferred") throw new Error("đợt tiếp nhận phải là 'transferred'");
  const apps = (await ok("nurse1", "GET", "/appointments?limit=500")).filter((a) => a.person_id === PT.id);
  if (apps.some((a) => ["scheduled", "due"].includes(a.status))) throw new Error("lịch hẹn mở tại đơn vị cũ phải được hoãn");
  await seg(off1, "Chờ cơ sở nhận tiếp nhận"); await off1.waitForSelector(`.card:has-text("${PT.full_name}")`);
  await mustContain(off1, `.card:has-text("${PT.full_name}")`, "Chờ cơ sở nhận tiếp nhận", "đang chờ cơ sở nhận");
});
await T.step("J5 cơ sở nhận thấy phiếu 'Cần tiếp nhận'; tạo đợt tiếp nhận mới → TỰ lập biên nhận; cơ sở gửi được báo", async () => {
  await nav(off2, "Chuyển trại & Bàn giao"); await seg(off2, "Chờ cơ sở nhận tiếp nhận");
  await off2.waitForSelector(`.card:has-text("${PT.full_name}")`); await mustContain(off2, `.card:has-text("${PT.full_name}")`, "Tiếp nhận đến", "Cần tiếp nhận");
  await nav(off2, "Tiếp nhận & Hồ sơ"); await seg(off2, "Tra cứu hồ sơ"); await off2.fill("input.search", PT.full_name);
  await off2.click(`tbody tr:has-text("${PT.full_name}")`); await off2.waitForSelector(".drawer");
  await off2.click('.drawer button:has-text("+ Tiếp nhận kỳ mới")'); await modalOpen(off2, "Xác nhận tiếp nhận mới"); await modalSubmit(off2, "Lưu"); await toast(off2, "Đã tiếp nhận");
  await off2.click('.drawer-bg header .btn:has-text("Quay lại")');
  await nav(off2, "Chuyển trại & Bàn giao"); await seg(off2, "Đã bàn giao"); await off2.waitForSelector(`.card:has-text("${PT.full_name}")`);
  await mustContain(off2, `.card:has-text("${PT.full_name}")`, "biên nhận hoàn tất");
  const n1 = (await ok("officer1", "GET", "/notifications?limit=100")).items; if (!n1.some((n) => n.kind === "handover.received")) throw new Error("cơ sở gửi phải nhận thông báo đã tiếp nhận");
  const n2 = (await ok("officer2", "GET", "/notifications?limit=100")).items; if (!n2.some((n) => n.kind === "handover.incoming" && n.link_ref === PT.id)) throw new Error("cơ sở nhận phải nhận thông báo 'có người chuyển đến'");
});
await T.step("J6 hồ sơ sức khỏe đi cùng người: bác sĩ Trại 2 thấy lịch sử khám cũ; kỳ ở Trại 1 đã kết thúc (UAT-08)", async () => {
  await pickPatient(doc2, PT.full_name); await nav(doc2, "Hồ sơ sức khỏe");
  await doc2.click('.tabs button:has-text("Lịch sử khám")'); await doc2.waitForSelector("tbody tr");
  await mustContain(doc2, "tbody", "Khám ban đầu");
  await doc2.click('.tabs button:has-text("Đợt tiếp nhận")'); await doc2.waitForFunction(() => document.querySelectorAll("tbody tr").length === 2);
  await mustContain(doc2, "tbody", "Đã chuyển trại", "Mới tiếp nhận");
  const a = await ok("doctor1", "GET", `/persons/${PT.id}/health-summary`), b = await ok("doctor2", "GET", `/persons/${PT.id}/health-summary`);
  if (a.clinical.health_record_id !== b.clinical.health_record_id) throw new Error("hai cơ sở phải dùng CHUNG một hồ sơ sức khỏe");
});
await T.step("J7 kết thúc quản lý (mãn hạn): 3 bước, không có biên nhận; kỳ → 'Đã kết thúc'; không tạo lượt khám mới", async () => {
  await nav(off1, "Chuyển trại & Bàn giao"); await seg(off1, "Chờ xác nhận");
  await off1.click('button:has-text("+ Khởi tạo bàn giao")'); await modalOpen(off1, "Khởi tạo bàn giao");
  await off1.selectOption('.modal [name="stay_id"]', { label: `${PR.full_name} (${PR.code})` }); await off1.selectOption('.modal [name="kind"]', "release");
  await off1.waitForFunction(() => !document.querySelector('.modal [name="to_facility_id"]'));      // kết thúc quản lý không cần cơ sở đích
  await off1.fill('.modal [name="reason"]', "Mãn hạn tù, ra khỏi diện quản lý"); await modalSubmit(off1, "Khởi tạo"); await toast(off1, "Đã khởi tạo phiếu bàn giao");
  const steps = await off1.$$eval(`.card:has-text("${PR.full_name}") .stepper .step`, (s) => s.length); if (steps !== 3) throw new Error(`kết thúc quản lý phải có 3 bước (có ${steps})`);
  await nur.reload(); await nur.waitForSelector(".side .nav"); await nav(nur, "Chuyển trại & Bàn giao");
  await nur.click(`.card:has-text("${PR.full_name}") button:has-text("Soạn tóm tắt y tế")`); await modalOpen(nur, "Tóm tắt y tế bàn giao");
  await nur.fill('.modal [name="summary"]', "Sức khỏe bình thường, đã tư vấn tái khám tại cơ sở y tế địa phương."); await modalSubmit(nur, "Lưu"); await toast(nur, "Đã lưu tóm tắt bàn giao");
  await off1.reload(); await off1.waitForSelector(".side .nav"); await nav(off1, "Chuyển trại & Bàn giao");
  await off1.click(`.card:has-text("${PR.full_name}") button:has-text("Xác nhận bàn giao")`); await modalOpen(off1, "Xác nhận bàn giao");
  await off1.check('.modal [name="ack"]'); await modalSubmit(off1, "Xác nhận đã bàn giao"); await toast(off1, "Đã xác nhận bàn giao");
  const stays = await ok("officer1", "GET", `/persons/${PR.id}/stays`); if (stays.at(-1).status !== "ended") throw new Error("đợt tiếp nhận phải là 'ended'");
  const r = await api("doctor1", "POST", "/encounters", { person_id: PR.id, type: "ad_hoc", reason: "thử" });
  if (r.status !== 409) throw new Error(`không có kỳ hiệu lực thì không tạo được lượt khám (409), nhận ${r.status}`);
  await seg(off1, "Đã bàn giao"); await off1.waitForSelector(`.card:has-text("${PR.full_name}")`); await mustContain(off1, `.card:has-text("${PR.full_name}")`, "Kết thúc quản lý", "Đã bàn giao");
});

process.exit((await T.done()).length ? 1 : 0);
