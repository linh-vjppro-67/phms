// E2E đầy đủ: tính năng mức production – đổi/đặt lại mật khẩu, MFA, gộp hồ sơ có duyệt, ưu tiên khám,
// tài liệu bàn giao chuyển viện, sửa kế hoạch theo dõi, CSP. KHÔNG đụng tài khoản mẫu: mọi tài khoản dùng ở đây do bài này tự tạo.
import { BASE, PASS, api, dialogOk, managedPerson, modalGone, modalOpen, modalSubmit, mustContain, mustNotContain, nav, newPerson, ok, pickInModal, pickPatient, start, startEncounter, toast, totp, uniq, uploadDoc } from "./lib.mjs";

const T = await start("Bảo mật & tính năng production");
const U = uniq();
const nm = (s) => `${s} ${U}`;
const seg = (page, label) => page.click(`.seg button:has-text("${label}")`);
const tab = (page, label) => page.click(`button[role="tab"]:has-text("${label}")`);
const NEW = `sec${U}`;
const PW0 = "Tam0Pass2026x", PW1 = "Moi1Pass2026y", PW2 = "Moi2Pass2026z";
const loginApi = (u, p, otp) => fetch(`${BASE}/api/auth/login`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: u, password: p, ...(otp && { otp }) }) });
const uiLogin = async (page, u, p) => { await page.fill('input[name="u"]', u); await page.fill('input[name="p"]', p); await page.click("button.btn.primary"); };
const logout = async (page) => { await page.click('button[aria-label="Đăng xuất"]'); await page.waitForSelector('input[name="u"]'); };

const adm = await T.login("admin");

// ================================================================= mật khẩu
await T.step("S1 quản trị tạo tài khoản → người đó đăng nhập lần đầu bị BUỘC đổi mật khẩu trước khi vào hệ thống", async () => {
  await nav(adm, "Quản trị hệ thống");
  await adm.click('button:has-text("+ Tạo người dùng")'); await modalOpen(adm, "Tạo người dùng");
  await adm.fill('.modal [name="username"]', NEW); await adm.fill('.modal [name="full_name"]', "Điều dưỡng Bảo mật");
  await adm.selectOption('.modal [name="role"]', { label: "Điều dưỡng" }); await adm.selectOption('.modal [name="facility_id"]', { label: "Trại giam số 1" });
  await adm.fill('.modal [name="password"]', PW0); await modalSubmit(adm, "Lưu"); await toast(adm, "Đã tạo tài khoản");
  await adm.waitForSelector(`tbody tr:has-text("${NEW}") .badge:has-text("Chờ đổi mật khẩu")`);

  const u = await T.open("người dùng mới");
  await uiLogin(u, NEW, PW0);
  await u.waitForSelector('h1:has-text("Đổi mật khẩu lần đầu")');
  if (await u.$(".side .nav")) throw new Error("chưa đổi mật khẩu thì không được vào hệ thống");
  const f = (n) => u.locator(`input[name="${n}"]`);
  await f("o").fill(PW0); await f("n").fill(PW1); await f("n2").fill(PW2); await u.click('#pwdform button:has-text("Đổi mật khẩu")');
  await u.waitForSelector('.banner:has-text("không khớp")');
  await f("n").fill("yeu"); await f("n2").fill("yeu"); await u.click('#pwdform button:has-text("Đổi mật khẩu")');          // trình duyệt chặn minLength -> không gửi
  await f("n").fill("khongcoso1234"); await f("n2").fill("khongcoso1234"); await u.click('#pwdform button:has-text("Đổi mật khẩu")');
  await toast(u, "chữ hoa");                                                                                                  // máy chủ từ chối mật khẩu yếu
  await f("n").fill(PW1); await f("n2").fill(PW1); await u.click('#pwdform button:has-text("Đổi mật khẩu")');
  await u.waitForSelector(".side .nav");
  if ((await (await loginApi(NEW, PW0)).status) !== 401) throw new Error("mật khẩu cũ không còn dùng được");
  if ((await loginApi(NEW, PW1)).status !== 200) throw new Error("mật khẩu mới phải đăng nhập được");
  globalThis.userPage = u;
});
await T.step("S2 người dùng tự đổi mật khẩu trong 'Tài khoản của tôi': sai mật khẩu cũ bị từ chối; đúng thì phiên vẫn dùng tiếp được", async () => {
  const u = globalThis.userPage;
  await u.click(".who"); await modalOpen(u, "Tài khoản của tôi");
  if (process.env.SHOTS) await u.screenshot({ path: `${process.env.SHOTS}/DBG-S2.png` });
  const f = (n) => u.locator(`.modal input[name="${n}"]`);
  await f("o").fill("sai-mat-khau-cu"); await f("n").fill(PW2); await f("n2").fill(PW2); await u.click('.modal #pwdform button:has-text("Đổi mật khẩu")');
  await toast(u, "Mật khẩu cũ không đúng");
  await f("o").fill(PW1); await u.click('.modal #pwdform button:has-text("Đổi mật khẩu")'); await toast(u, "Đã đổi mật khẩu");
  await u.keyboard.press("Escape"); await modalGone(u);
  await nav(u, "Bảng điều khiển"); await u.waitForSelector(".kpis");                                                            // token mới còn hiệu lực
  if ((await loginApi(NEW, PW2)).status !== 200) throw new Error("mật khẩu mới (lần 2) phải đăng nhập được");
});
await T.step("S3 xác thực 2 lớp: bật bằng mã QR/khóa → đăng nhập phải nhập OTP; OTP sai bị từ chối; OTP đúng vào được", async () => {
  const u = globalThis.userPage;
  await u.click(".who"); await modalOpen(u, "Tài khoản của tôi"); await tab(u, "Xác thực 2 lớp");
  await u.click('.modal button:has-text("Bật xác thực 2 lớp")');
  await u.waitForSelector(".modal .qr svg"); await u.waitForSelector(".modal code.secret");
  const secret = (await u.textContent(".modal code.secret")).trim();
  await u.fill('.modal input[name="c"]', "000000"); await u.click('.modal form button:has-text("Bật xác thực 2 lớp")'); await toast(u, "Mã xác thực không đúng");
  await u.fill('.modal input[name="c"]', totp(secret)); await u.click('.modal form button:has-text("Bật xác thực 2 lớp")'); await toast(u, "Đã bật xác thực 2 lớp");
  await u.waitForSelector('.modal .banner:has-text("đang bật")');
  await u.keyboard.press("Escape"); await modalGone(u);
  globalThis.mfaSecret = secret;
  if ((await loginApi(NEW, PW2)).status !== 401) throw new Error("đã bật MFA thì đăng nhập chỉ bằng mật khẩu phải bị từ chối");
  await logout(u);
  await uiLogin(u, NEW, PW2);
  await u.waitForSelector('input[name="otp"]');
  await u.fill('input[name="otp"]', "111111"); await u.click("button.btn.primary"); await toast(u, "Mã xác thực không đúng");
  await u.fill('input[name="otp"]', totp(secret, Date.now() + 30000)); await u.click("button.btn.primary");                     // bước kế tiếp (mã bật MFA không dùng lại)
  await u.waitForSelector(".side .nav");
});
await T.step("S4 quản trị đặt lại MFA (mất thiết bị) → người dùng đăng nhập chỉ bằng mật khẩu", async () => {
  await adm.reload(); await adm.waitForSelector(".side .nav"); await nav(adm, "Quản trị hệ thống");
  await adm.waitForSelector(`tbody tr:has-text("${NEW}") .badge:has-text("Bật")`);
  await adm.click(`tbody tr:has-text("${NEW}") button:has-text("Đặt lại MFA")`); await dialogOk(adm); await toast(adm, "Đã đặt lại MFA");
  if ((await loginApi(NEW, PW2)).status !== 200) throw new Error("sau khi đặt lại MFA phải đăng nhập được bằng mật khẩu");
  const u = globalThis.userPage;
  await u.reload();                                                                                                              // token cũ đã bị thu hồi
  await u.waitForSelector('input[name="u"]');
});
await T.step("S5 quản trị đặt lại mật khẩu: mật khẩu tạm hiện MỘT lần; người dùng bị buộc đổi; mật khẩu cũ vô hiệu", async () => {
  await adm.click(`tbody tr:has-text("${NEW}") button:has-text("Đặt lại mật khẩu")`); await modalOpen(adm, "Đặt lại mật khẩu");
  await modalSubmit(adm, "Đặt lại");
  await modalOpen(adm, "Mật khẩu tạm"); await adm.waitForSelector(".modal code.secret");
  const tmp = (await adm.textContent(".modal code.secret")).trim();
  if (tmp.length < 10) throw new Error("mật khẩu tạm phải đạt chính sách");
  await adm.click('.modal button:has-text("Đã ghi lại")'); await modalGone(adm);
  await adm.waitForSelector(`tbody tr:has-text("${NEW}") .badge:has-text("Chờ đổi mật khẩu")`);
  if ((await loginApi(NEW, PW2)).status !== 401) throw new Error("mật khẩu cũ phải vô hiệu sau khi đặt lại");
  const u = await T.open("đăng nhập bằng mật khẩu tạm");
  await uiLogin(u, NEW, tmp);
  await u.waitForSelector('h1:has-text("Đổi mật khẩu lần đầu")');
  await u.fill('input[name="o"]', tmp); await u.fill('input[name="n"]', PW1); await u.fill('input[name="n2"]', PW1); await u.click('#pwdform button:has-text("Đổi mật khẩu")');
  await u.waitForSelector(".side .nav");
});

// ================================================================= gộp hồ sơ có duyệt
const nameDup = nm("Hồ Sơ Trùng Nhau");
const keep = await newPerson(nameDup, { dob: "1987-07-07" });                                                                    // hồ sơ chính (có mã + đợt tiếp nhận)
const ghost = await ok("officer1", "POST", "/persons", { full_name: nameDup, date_of_birth: "1987-07-07", confirm_distinct: true });   // bản nhập trùng, không mã
await ok("nurse1", "GET", "/auth/me");
const encKeep = await startEncounter(keep.id);
await ok("nurse1", "POST", `/encounters/${encKeep.id}/observations`, { type: "Mạch", value: "76", unit: "lần/phút" });
const offc = await T.login("officer1");
const appr = await T.login("approver1");

await T.step("S6 cán bộ lập đề nghị gộp từ hồ sơ nghi trùng; KHÔNG tự duyệt được; dữ liệu CHƯA bị đụng", async () => {
  await nav(offc, "Tiếp nhận & Hồ sơ"); await seg(offc, "Chờ đối soát danh tính");
  await offc.click(`tbody tr:has-text("${nameDup}"):has-text("Nghi trùng")`); await offc.waitForSelector(".drawer");
  await offc.click('.drawer button:has-text("Đề nghị gộp hồ sơ")'); await modalOpen(offc, "Đề nghị gộp hồ sơ trùng");
  await offc.click(`.modal input[type="radio"]`);
  await offc.fill('.modal [name="reason"]', "Cùng họ tên, ngày sinh; bản không mã nhập lúc tiếp nhận (E2E)");
  await modalSubmit(offc, "Gửi đề nghị"); await toast(offc, "Đã gửi đề nghị");
  await offc.keyboard.press("Escape");
  await seg(offc, "Đề nghị gộp hồ sơ");
  await offc.click(`tbody tr:has-text("${nameDup}")`); await modalOpen(offc, "Đề nghị gộp hồ sơ");
  await mustContain(offc, ".modal-bg", "Chờ duyệt", "bốn mắt");
  if (await offc.$('.modal-bg footer button:has-text("Duyệt & gộp")')) throw new Error("người lập không được thấy nút duyệt");
  await offc.keyboard.press("Escape");
  const g = await ok("officer1", "GET", `/persons/${ghost.id}`);
  if (g.status === "merged") throw new Error("chưa duyệt mà đã gộp");
});
await T.step("S7 người điều phối nhận thông báo → xem 2 hồ sơ → DUYỆT & gộp: dữ liệu sang hồ sơ giữ lại, hồ sơ cũ 'Đã gộp'", async () => {
  await appr.reload(); await appr.waitForSelector(".side .nav");
  await appr.click(".btn.bell"); await appr.waitForSelector('.np:has-text("Đề nghị gộp hồ sơ trùng chờ duyệt")');
  await appr.click('.np :text("Đề nghị gộp hồ sơ trùng chờ duyệt")');                                                           // liên kết sâu mở đúng đề nghị
  await modalOpen(appr, "Đề nghị gộp hồ sơ");
  await mustContain(appr, ".modal-bg", "Hồ sơ BỊ GỘP", "Hồ sơ GIỮ LẠI", nameDup);
  await appr.click('.modal-bg footer button:has-text("Duyệt & gộp")');
  await appr.locator('.modal-bg').last().locator('footer button:has-text("Duyệt & gộp")').click(); await toast(appr, "Đã gộp hồ sơ");
  await appr.waitForSelector('.modal-bg:has-text("Đã chuyển")');
  const g = await ok("officer1", "GET", `/persons/${ghost.id}`);
  if (g.status !== "merged" || g.merged_into_id !== keep.id) throw new Error("hồ sơ nguồn phải ở trạng thái merged");
  const k = await ok("officer1", "GET", `/persons/${keep.id}/stays`);
  if (!k.length) throw new Error("đợt tiếp nhận phải còn ở hồ sơ giữ lại");
  const r = await api("officer1", "POST", `/persons/${ghost.id}/stays`, {});
  if (r.status !== 409) throw new Error("hồ sơ đã gộp không được tạo kỳ mới");
  const notes = (await ok("officer1", "GET", "/notifications")).items.map((n) => n.title);
  if (!notes.some((t) => t.includes("đã được duyệt"))) throw new Error("người lập phải nhận thông báo kết quả duyệt");
});

// ================================================================= ưu tiên yêu cầu khám
const pLow = await managedPerson(nm("Khám Thường")), pHigh = await managedPerson(nm("Khám Khẩn"));
await startEncounter(pLow.id);
const doc = await T.login("doctor1");
await T.step("S8 bác sĩ nhận yêu cầu khám với mức ưu tiên 'Khẩn cấp' → được xếp lên đầu danh sách, có nhãn", async () => {
  await nav(doc, "Khám chữa bệnh");
  await doc.click('button:has-text("+ Lượt khám mới")'); await modalOpen(doc, "Lượt khám mới");
  await doc.click('.modal button:has-text("Chọn người…")'); await pickInModal(doc, pHigh.full_name);
  await doc.selectOption('.modal [name="priority"]', "emergent"); await doc.fill('.modal [name="reason"]', "Đau ngực, vã mồ hôi");
  await modalSubmit(doc, "Tạo & bắt đầu khám"); await doc.waitForSelector(".drawer");
  await doc.click('.drawer-bg header .btn:has-text("Quay lại")');
  await doc.waitForSelector("tbody tr");
  const first = await doc.textContent("tbody tr:first-child");
  if (!first.includes(pHigh.full_name) || !first.includes("Khẩn cấp")) throw new Error(`ca khẩn phải đứng đầu, thấy: ${first.slice(0, 80)}`);
});

// ================================================================= tài liệu bàn giao chuyển viện
const pRef = await managedPerson(nm("Chuyển Viện Tài Liệu"));
const eRef = await startEncounter(pRef.id);
const d1 = await uploadDoc("nurse1", pRef.id, `ketqua-xn-${U}.pdf`), d2 = await uploadDoc("nurse1", pRef.id, `sieu-am-${U}.pdf`, "imaging");
await T.step("S9 bác sĩ lập đề nghị chuyển viện và CHỌN tài liệu bàn giao kèm; đổi lựa chọn khi chưa chuyển đi", async () => {
  await nav(doc, "Chuyển viện");
  await doc.click('button:has-text("+ Lập đề nghị chuyển viện")'); await modalOpen(doc, "chọn lượt khám");
  await pickInModal(doc, pRef.full_name); await doc.click('.modal-bg tr.click:has-text("Đang khám")');
  await modalOpen(doc, "Lập đề nghị chuyển viện");
  await doc.fill('.modal [name="reason"]', "Nghi viêm ruột thừa, cần phẫu thuật"); await doc.fill('.modal [name="destination"]', "BV Đa khoa tỉnh");
  await doc.check(`.modal label:has-text("ketqua-xn-${U}.pdf") input`);
  await modalSubmit(doc, "Lưu dự thảo"); await toast(doc, "Đã lập đề nghị chuyển viện"); await doc.waitForSelector(".drawer");
  await mustContain(doc, '.drawer .card:has-text("Tài liệu bàn giao kèm")', `ketqua-xn-${U}.pdf`);
  if ((await doc.textContent('.drawer .card:has-text("Tài liệu bàn giao kèm")')).includes(`sieu-am-${U}`)) throw new Error("chưa chọn siêu âm");
  await doc.click('.drawer .card:has-text("Tài liệu bàn giao kèm") button:has-text("Chọn tài liệu")'); await modalOpen(doc, "Tài liệu bàn giao kèm");
  await doc.check(`.modal label:has-text("sieu-am-${U}.pdf") input`); await modalSubmit(doc, "Lưu"); await toast(doc, "Đã cập nhật tài liệu bàn giao");
  await mustContain(doc, '.drawer .card:has-text("Tài liệu bàn giao kèm")', `ketqua-xn-${U}.pdf`, `sieu-am-${U}.pdf`);
  const refs = await ok("doctor1", "GET", "/referrals");
  const r = refs.find((x) => x.person_id === pRef.id);
  if (r.handover_docs.length !== 2) throw new Error("máy chủ phải lưu 2 tài liệu");
  globalThis.refId = r.id;
});
await T.step("S10 tài liệu của NGƯỜI KHÁC hoặc bản đã thay thế bị chặn; người điều phối chỉ biết CÓ tài liệu, không thấy tên tệp", async () => {
  const other = await managedPerson(nm("Người Khác Tài Liệu")), dx = await uploadDoc("nurse1", other.id, `khac-${U}.pdf`);
  await doc.keyboard.press("Escape");
  const bad = await api("doctor1", "PUT", `/referrals/${globalThis.refId}/handover-docs`, { handover_docs: [dx.id] });
  if (bad.status !== 422) throw new Error(`tài liệu người khác phải bị chặn, nhận ${bad.status}`);
  await ok("doctor1", "PATCH", `/referrals/${globalThis.refId}/status`, { to: "pending" });          // gửi duyệt để người điều phối thấy
  await appr.keyboard.press("Escape"); await modalGone(appr); await nav(appr, "Chuyển viện");
  await appr.click(`.kcard:has-text("${pRef.full_name}")`); await appr.waitForSelector(".drawer");
  const t = await appr.textContent('.drawer .card:has-text("Tài liệu bàn giao kèm")');
  if (t.includes(`ketqua-xn-${U}`)) throw new Error("người điều phối không được thấy tên tệp");
  if (!(await appr.$('.drawer .card:has-text("Tài liệu bàn giao kèm") li'))) throw new Error("phải thấy có tài liệu kèm");
  if (await appr.$('.drawer .card:has-text("Tài liệu bàn giao kèm") button:has-text("Chọn tài liệu")')) throw new Error("người điều phối không được sửa tài liệu");
});

// ================================================================= sửa kế hoạch theo dõi
const pPlan = await managedPerson(nm("Kế Hoạch Sửa"));
const prob = await ok("doctor1", "POST", `/persons/${pPlan.id}/problems`, { name: "Tăng huyết áp vô căn", code: "I10" });
await ok("doctor1", "POST", `/persons/${pPlan.id}/care-plans`, { problem_id: prob.id, goals: "Huyết áp < 140/90", measures: [{ name: "Huyết áp tâm thu", unit: "mmHg" }], review_interval_days: 14 });
await T.step("S11 bác sĩ SỬA kế hoạch theo dõi (mục tiêu, chỉ số, chu kỳ) → lịch đang mở dời theo; điều dưỡng không có nút Sửa", async () => {
  await doc.keyboard.press("Escape"); await doc.waitForTimeout(200);
  await nav(doc, "Bệnh lý & Cảnh báo"); await tab(doc, "Kế hoạch theo dõi");
  await doc.waitForSelector(`tbody tr:has-text("${pPlan.full_name}")`);
  await doc.click(`tbody tr:has-text("${pPlan.full_name}") button:has-text("Sửa")`); await modalOpen(doc, "Sửa kế hoạch theo dõi");
  await doc.fill('.modal [name="goals"]', "Huyết áp < 130/80"); await doc.fill('.modal [name="review_interval_days"]', "30");
  await doc.fill('.modal [name="measures"]', "Huyết áp tâm thu | mmHg\nMạch | lần/phút");
  await modalSubmit(doc, "Lưu"); await toast(doc, "Đã cập nhật kế hoạch");
  await doc.waitForSelector(`tbody tr:has-text("${pPlan.full_name}"):has-text("30 ngày")`);
  await mustContain(doc, `tbody tr:has-text("${pPlan.full_name}")`, "Huyết áp < 130/80");
  const appts = (await ok("doctor1", "GET", "/appointments?kind=care_plan")).filter((a) => a.person_id === pPlan.id);
  const want = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
  if (appts.length !== 1 || appts[0].due_date !== want) throw new Error(`lịch phải dời sang ${want}, thấy ${JSON.stringify(appts.map((a) => a.due_date))}`);
  const nurse = await T.login("nurse1"); await nav(nurse, "Bệnh lý & Cảnh báo"); await tab(nurse, "Kế hoạch theo dõi");
  await nurse.waitForSelector(`tbody tr:has-text("${pPlan.full_name}")`);
  if (await nurse.$(`tbody tr:has-text("${pPlan.full_name}") button:has-text("Sửa")`)) throw new Error("điều dưỡng không có quyền sửa kế hoạch");
});

// ================================================================= ICD ↔ tên bệnh, bố cục form
const pIcd = await managedPerson(nm("Liên Kết ICD"));
await T.step("S14 vấn đề sức khỏe: tên bệnh ↔ mã ICD liên kết HAI CHIỀU; tắt tự điền trình duyệt; nút 'Thêm' thẳng hàng với ô nhập; danh mục đủ rộng", async () => {
  const d = await T.login("doctor1"); await pickPatient(d, pIcd.full_name);
  await nav(d, "Bệnh lý & Cảnh báo"); await tab(d, "Theo dõi người đang chọn");
  const form = d.locator('form:has(input[name="code"])').first();
  const nameIn = form.locator('input[name="name"]'), codeIn = form.locator('input[name="code"]');
  await nameIn.waitFor();
  if ((await nameIn.getAttribute("autocomplete")) !== "off" || (await codeIn.getAttribute("autocomplete")) !== "off") throw new Error("phải tắt tự điền của trình duyệt (autocomplete=off)");
  let nOpts = 0;
  for (let i = 0; i < 30 && nOpts < 200; i++) { nOpts = await form.locator("datalist").first().locator("option").count(); if (nOpts < 200) await d.waitForTimeout(200); }   // danh mục tải bất đồng bộ
  if (nOpts < 200) throw new Error(`danh mục ICD quá ít (${nOpts} mục)`);
  await nameIn.fill("Tăng huyết áp vô căn");
  if ((await codeIn.inputValue()) !== "I10") throw new Error(`chọn tên → mã phải tự điền I10, thấy "${await codeIn.inputValue()}"`);
  await codeIn.fill("E11");
  if ((await nameIn.inputValue()) !== "Đái tháo đường típ 2") throw new Error(`nhập mã → tên phải tự điền, thấy "${await nameIn.inputValue()}"`);
  await nameIn.fill("Bệnh chưa có trong danh mục");
  if ((await codeIn.inputValue()) !== "") throw new Error("đổi sang tên tự do thì mã tự điền trước đó phải được bỏ");
  const dim = async (sel) => (await form.locator(sel).first().boundingBox());
  const input = await dim('input[name="name"]'), btn = await dim("button.btn.primary");
  if (Math.abs((input.y + input.height) - (btn.y + btn.height)) > 4) throw new Error(`nút "Thêm" lệch hàng: đáy ô ${Math.round(input.y + input.height)} / đáy nút ${Math.round(btn.y + btn.height)}`);
  await nameIn.fill("Tăng huyết áp vô căn"); await form.locator("button.btn.primary").click(); await toast(d, "Đã ghi nhận vấn đề sức khỏe");
  const probs = (await ok("doctor1", "GET", `/persons/${pIcd.id}/health-summary`)).clinical.problems;
  if (!probs.some((p) => p.name === "Tăng huyết áp vô căn" && p.code === "I10")) throw new Error("vấn đề phải lưu kèm mã I10");
});

// ================================================================= gỡ dị ứng ghi nhầm
const pAl = await managedPerson(nm("Dị Ứng Khai Sai"));
await ok("nurse1", "POST", `/persons/${pAl.id}/allergies`, { substance: `thuốc trừ sâu ${U}` });
await ok("doctor1", "POST", `/persons/${pAl.id}/allergies`, { substance: `Penicillin ${U}`, confirmed: true });
await T.step("S15 gỡ dị ứng ghi nhầm: bắt buộc lý do, hết cảnh báo, vẫn còn dấu vết; điều dưỡng không gỡ được dị ứng ĐÃ XÁC NHẬN", async () => {
  const d = await T.login("doctor1"); await pickPatient(d, pAl.full_name); await nav(d, "Hồ sơ sức khỏe"); await tab(d, "Dị ứng & vấn đề sức khỏe");
  await d.waitForSelector(`tbody tr:has-text("thuốc trừ sâu ${U}")`);
  await d.click(`tbody tr:has-text("thuốc trừ sâu ${U}") button:has-text("Gỡ")`); await modalOpen(d, "Gỡ dị ứng");
  await d.fill(".modal [name=\"v\"]", "Sai"); await dialogOk(d); await toast(d, "tối thiểu 5 ký tự");            // lý do quá ngắn bị máy chủ từ chối
  await d.click(`tbody tr:has-text("thuốc trừ sâu ${U}") button:has-text("Gỡ")`); await modalOpen(d, "Gỡ dị ứng");
  await d.fill('.modal [name="v"]', "Nhập nhầm từ hồ sơ người khác"); await dialogOk(d); await toast(d, "Đã gỡ dị ứng");
  await d.waitForFunction((n) => !document.body.innerText.includes(n), `thuốc trừ sâu ${U}`);
  await mustContain(d, "body", `Penicillin ${U}`);                                                            // dị ứng khác còn nguyên
  const log = JSON.stringify(await ok("admin", "GET", "/audit?limit=100"));
  if (!log.includes("allergy_retracted") || !log.includes("Nhập nhầm từ hồ sơ người khác")) throw new Error("phải còn nhật ký gỡ dị ứng kèm lý do");
  const nurse = await T.login("nurse1"); await pickPatient(nurse, pAl.full_name); await nav(nurse, "Hồ sơ sức khỏe"); await tab(nurse, "Dị ứng & vấn đề sức khỏe");
  await nurse.waitForSelector(`tbody tr:has-text("Penicillin ${U}")`);
  if (await nurse.$(`tbody tr:has-text("Penicillin ${U}") button:has-text("Gỡ")`)) throw new Error("điều dưỡng không được thấy nút gỡ dị ứng đã xác nhận");
});

// ================================================================= chống bấm lặp từ giao diện + CSP
await T.step("S12 bấm 'Gửi' nhiều lần liên tiếp chỉ tạo MỘT bản ghi (Idempotency-Key tự động)", async () => {
  const p = await managedPerson(nm("Bấm Lặp"));
  const e = await startEncounter(p.id);
  const nurse = await T.login("nurse1"); await pickPatient(nurse, p.full_name);
  const calls = [];
  nurse.on("request", (r) => r.method() === "POST" && r.url().includes("/observations") && calls.push(r.headers()["idempotency-key"]));
  await nav(nurse, "Khám chữa bệnh"); await nurse.click(`tbody tr:has-text("${p.full_name}")`); await nurse.waitForSelector(".drawer");
  await nurse.click('.drawer button[role="tab"]:has-text("Sinh hiệu")');
  await nurse.fill('.drawer [name="pulse"]', "72");
  await nurse.dblclick('.drawer button:has-text("Ghi nhận sinh hiệu")');
  await nurse.waitForTimeout(1200);
  const obs = (await ok("doctor1", "GET", `/encounters/${e.id}`)).observations;
  if (obs.length !== 1) throw new Error(`bấm đúp phải ra 1 sinh hiệu, thực tế ${obs.length}`);
  if (!calls.length || calls.some((k) => !k)) throw new Error("mọi yêu cầu tạo bản ghi phải có Idempotency-Key");
});
await T.step("S13 CSP bật nguyên: duyệt mọi tab không vi phạm; header bảo mật đủ; HSTS chỉ khi HTTPS", async () => {
  const before = T.errs.length;
  const page = await T.open("kiểm CSP", { width: 1440, height: 950 }, { enforceCsp: true });
  await uiLogin(page, "doctor1", PASS); await page.waitForSelector(".side .nav");
  const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
  for (let i = 0; i < labels.length; i++) { await (await page.$$(".side .nav"))[i].click(); await page.waitForTimeout(400); }
  await page.click(".btn.bell"); await page.waitForTimeout(300);
  const viol = T.errs.slice(before).filter((e) => /Content Security Policy|CSP|unsafe-inline|unsafe-eval/i.test(e));
  if (viol.length) throw new Error("vi phạm CSP: " + viol[0].slice(0, 200));
  const h = (await fetch(`${BASE}/`)).headers;
  for (const [k, re] of [["content-security-policy", /default-src 'self'.*frame-ancestors 'none'/], ["x-content-type-options", /nosniff/], ["x-frame-options", /DENY/], ["referrer-policy", /no-referrer/], ["permissions-policy", /camera=\(\)/]])
    if (!re.test(h.get(k) || "")) throw new Error(`thiếu/sai header ${k}`);
  if (h.get("strict-transport-security")) throw new Error("HTTP thường không được gửi HSTS");
  const hs = (await fetch(`${BASE}/api/health`, { headers: { "x-forwarded-proto": "https" } })).headers.get("strict-transport-security");
  if (!/max-age=\d+/.test(hs || "")) throw new Error("sau proxy HTTPS phải có HSTS");
});

process.exit((await T.done()).length ? 1 : 0);
