// PART 1 – Xác thực, giao diện theo vai trò, phân quyền (RBAC/ABAC)
import { api, ok, tc, must, status, denied, code, login, ui, nav, navLabels, freshPage, uniq, newPerson, managedPerson, startEnc, facilityId, sql, BASE, Blocked } from "./uat-lib.mjs";

export async function part1(S) {
  const U = S.U;
  S.f1 = await facilityId("F01"); S.f2 = await facilityId("F02");
  // dữ liệu dùng chung
  S.pA = await managedPerson(`UAT Phân Quyền A ${U}`);                               // F01, đang quản lý
  S.encA = await startEnc(S.pA.id);                                                  // lượt khám đang mở
  S.pB = await managedPerson(`UAT Phân Quyền B ${U}`, { officer: "officer2", doctor: "doctor2" });   // F02

  // ---------------- AUTH
  await tc({ id: "AUTH-01", mod: "Xác thực", kind: "Positive", role: "Tất cả", title: "13 tài khoản mẫu đăng nhập thành công, nhận đúng vai trò & cơ sở",
    expected: "HTTP 200; /auth/me trả đúng role, tài khoản F01/F02 gắn đúng cơ sở, admin không gắn cơ sở", sev: "Critical" }, async () => {
    const users = ["admin", "officer1", "nurse1", "doctor1", "pharm1", "approver1", "manager1", "officer2", "nurse2", "doctor2", "pharm2", "approver2", "manager2"];
    const roleOf = { officer: "custody_officer", nurse: "nurse", doctor: "doctor", pharm: "pharmacist", approver: "approver", manager: "manager", admin: "sysadmin" };
    for (const u of users) {
      const me = await ok(u, "GET", "/auth/me");
      const want = roleOf[u.replace(/\d/, "")]; must(me.role === want, `${u}: role=${me.role}, mong đợi ${want}`);
      if (u !== "admin") must(me.facility_id === (u.endsWith("1") ? S.f1 : S.f2), `${u}: sai cơ sở`);
    }
    return "13/13 tài khoản đăng nhập, role & cơ sở đúng";
  });

  await tc({ id: "AUTH-02", mod: "Xác thực", kind: "Negative", role: "Anonymous", title: "Sai mật khẩu / tài khoản không tồn tại: từ chối, thông báo không lộ tài khoản có tồn tại hay không",
    expected: "HTTP 401 cho cả hai trường hợp, cùng một thông điệp", sev: "High" }, async (c) => {
    const a = await login("officer1", "SaiMatKhau!123"), b = await login("khong_ton_tai_" + U, "SaiMatKhau!123");
    must(a.status === 401 && b.status === 401, `HTTP ${a.status}/${b.status}`);
    must(a.data?.error?.message === b.data?.error?.message, `Thông điệp khác nhau (lộ user enumeration): “${a.data?.error?.message}” vs “${b.data?.error?.message}”`);
    const page = await freshPage(); await page.fill('input[name="u"]', "officer1"); await page.fill('input[name="p"]', "sai"); await page.click("button.btn.primary");
    await page.waitForTimeout(800); await c.shot(page, "dang-nhap-sai"); await page.close();
  });

  await tc({ id: "AUTH-03", mod: "Xác thực", kind: "Boundary", role: "Tài khoản mới", title: "Khóa tài khoản sau 5 lần sai (15 phút); mật khẩu đúng cũng không vào được khi đang khóa",
    expected: "Sau 5 lần sai → HTTP 423; đăng nhập đúng lúc đang khóa vẫn 423 (BR bảo mật 10.1)", sev: "High" }, async () => {
    const uname = "uat_lock_" + U;
    await ok("admin", "POST", "/users", { username: uname, password: "Uat@Lock2026x", full_name: "UAT Khóa", role: "nurse", facility_id: S.f1 });
    let last; const seen = [];
    for (let i = 0; i < 5; i++) { last = await login(uname, "SaiSai!1234567"); seen.push(last.status); }
    const good = await login(uname, "Uat@Lock2026x");
    must(good.status === 423, `Sau 5 lần sai (HTTP: ${seen}), đăng nhập đúng trả ${good.status}, mong đợi 423`);
    return `5 lần sai trả ${seen.join(",")}; lần đúng tiếp theo: 423`;
  });

  await tc({ id: "AUTH-04", mod: "Xác thực", kind: "Boundary", role: "admin", title: "Chính sách mật khẩu: 9 ký tự / thiếu chữ hoa / thiếu số bị từ chối; 10 ký tự hợp lệ được chấp nhận",
    expected: "Mật khẩu yếu → 422 WEAK_PASSWORD; mật khẩu ≥10 ký tự có hoa, thường, số → 201", sev: "Medium" }, async () => {
    const mk = (pw, n) => api("admin", "POST", "/users", { username: `uat_pw${n}_${U}`, password: pw, full_name: "UAT PW", role: "nurse", facility_id: S.f1 });
    const bad = [await mk("Abcdef1gh", 1), await mk("abcdefgh12345", 2), await mk("ABCDEFGHijklmn", 3), await mk("Phms@2026dev", 9)];   // 9 ký tự; thiếu hoa; thiếu số; (mật khẩu mẫu: hợp lệ về độ mạnh)
    must([bad[0], bad[1], bad[2]].every((r) => r.status === 422), `Mật khẩu yếu không bị từ chối: ${bad.map((r) => r.status)}`);
    const good = await mk("Abcdefgh1j", 4);   // đúng 10 ký tự
    status(good, 201, "Mật khẩu 10 ký tự hợp lệ");
  });

  await tc({ id: "AUTH-05", mod: "Xác thực", kind: "Positive", role: "Tài khoản mới (UI)", title: "Tài khoản do quản trị tạo bị buộc đổi mật khẩu ở lần đăng nhập đầu; đổi xong vào được hệ thống",
    expected: "Hiện màn hình đổi mật khẩu, chưa thấy menu; sau khi đổi hợp lệ vào Bảng điều khiển", sev: "High" }, async (c) => {
    const uname = "uat_first_" + U;
    await ok("admin", "POST", "/users", { username: uname, password: "Uat@First2026", full_name: "UAT Lần Đầu", role: "nurse", facility_id: S.f1 });
    const page = await freshPage(); await page.fill('input[name="u"]', uname); await page.fill('input[name="p"]', "Uat@First2026"); await page.click("button.btn.primary");
    await page.waitForTimeout(1200); await c.shot(page, "buoc-doi-mat-khau");
    must(!(await page.$(".side .nav")), "Vào thẳng hệ thống mà chưa đổi mật khẩu");
    const txt = await page.innerText("body"); must(/đổi mật khẩu/i.test(txt), "Không thấy màn hình đổi mật khẩu");
    const inputs = await page.$$("input[type=password]"); must(inputs.length >= 2, "Thiếu ô nhập mật khẩu mới");
    await inputs[0].fill("Uat@First2026"); await inputs[1].fill("Moi@Pass2026x"); if (inputs[2]) await inputs[2].fill("Moi@Pass2026x");
    await page.click("button.btn.primary"); await page.waitForSelector(".side .nav", { timeout: 8000 }); await c.shot(page, "sau-khi-doi"); await page.close();
  });

  await tc({ id: "AUTH-06", mod: "Xác thực", kind: "Negative", role: "Anonymous", title: "Gọi API không token / token giả mạo / token bị sửa → 401, không lộ dữ liệu",
    expected: "HTTP 401 cho mọi API nghiệp vụ", sev: "Critical" }, async () => {
    const t = await (await import("./uat-lib.mjs")).tok("officer1");
    const forged = t.slice(0, -4) + (t.endsWith("AAAA") ? "BBBB" : "AAAA");
    const r1 = await api(null, "GET", "/persons"), r2 = await api(null, "GET", "/persons", undefined, { authorization: "Bearer " + forged }),
      r3 = await api(null, "GET", "/persons", undefined, { authorization: "Bearer abc.def.ghi" }), r4 = await api(null, "GET", "/audit");
    must([r1, r2, r3, r4].every((r) => r.status === 401), `HTTP: ${[r1, r2, r3, r4].map((r) => r.status)}`);
  });

  await tc({ id: "AUTH-07", mod: "Xác thực", kind: "Negative", role: "admin", title: "Khóa tài khoản đang đăng nhập → phiên hiện tại mất hiệu lực ngay",
    expected: "Sau khi admin khóa, token cũ gọi API trả 401/403", sev: "High" }, async () => {
    const uname = "uat_off_" + U; const u = await ok("admin", "POST", "/users", { username: uname, password: "Uat@Off20260x", full_name: "UAT Khóa Phiên", role: "nurse", facility_id: S.f1 });
    const l = await login(uname, "Uat@Off20260x"); const t = l.data.access_token;
    // đổi mật khẩu lần đầu để có phiên đầy đủ
    await fetch(`${BASE}/api/auth/change-password`, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${t}` }, body: JSON.stringify({ old_password: "Uat@Off20260x", new_password: "Moi@Pass2026y" }) });
    const l2 = await login(uname, "Moi@Pass2026y"); const t2 = l2.data.access_token;
    const before = await fetch(`${BASE}/api/auth/me`, { headers: { authorization: `Bearer ${t2}` } });
    await ok("admin", "PATCH", `/users/${u.id}`, { active: false });
    const after = await fetch(`${BASE}/api/auth/me`, { headers: { authorization: `Bearer ${t2}` } });
    must(before.status === 200, `Trước khi khóa: ${before.status}`); must([401, 403].includes(after.status), `Sau khi khóa token cũ vẫn dùng được (HTTP ${after.status})`);
  });

  // ---------------- Giao diện theo vai trò
  const NAVCASES = [
    ["officer1", "Cán bộ tiếp nhận", ["Bảng điều khiển", "Tiếp nhận & Hồ sơ", "Chuyển trại"], ["Khám ban đầu", "Khám chữa bệnh", "Cấp phát", "Hồ sơ sức khỏe", "Tài liệu y tế", "Báo cáo", "Quản trị", "Cấp cứu", "Chuyển viện"]],
    ["nurse1", "Điều dưỡng", ["Khám chữa bệnh", "Cấp cứu", "Hồ sơ sức khỏe"], ["Báo cáo", "Quản trị"]],
    ["doctor1", "Bác sĩ", ["Khám ban đầu", "Khám chữa bệnh", "Chỉ định & Kê đơn", "Chuyển viện", "Cấp cứu"], ["Báo cáo", "Quản trị"]],
    ["pharm1", "Dược", ["Cấp phát thuốc", "Tiếp nhận & Hồ sơ"], ["Quản trị", "Báo cáo", "Chuyển viện", "Cấp cứu"]],   // REQ-01 (đã chốt): dược được TRA CỨU bệnh nhân như thực hành EMR, không đăng ký/đối soát
    ["approver1", "Người phê duyệt", ["Chuyển viện", "Chuyển trại"], ["Khám ban đầu", "Khám chữa bệnh", "Cấp phát", "Hồ sơ sức khỏe", "Báo cáo", "Quản trị"]],
    ["manager1", "Quản lý y tế", ["Báo cáo", "Khám định kỳ"], ["Quản trị", "Khám ban đầu", "Cấp phát", "Tiếp nhận & Hồ sơ"]],
    ["admin", "Quản trị hệ thống", ["Quản trị"], ["Khám ban đầu", "Khám chữa bệnh", "Hồ sơ sức khỏe", "Cấp phát", "Tiếp nhận & Hồ sơ", "Chuyển viện", "Báo cáo", "Cấp cứu", "Tài liệu y tế"]],
  ];
  for (const [u, label, must_have, must_not] of NAVCASES) {
    await tc({ id: `NAV-${u.replace(/\d/, "")}`, mod: "Phân quyền (UI)", kind: "Permission", role: label, title: `Menu của ${label} chỉ gồm các phân hệ được phép (đối chiếu 04-§2)`,
      expected: `Thấy: ${must_have.join(", ")}. KHÔNG thấy: ${must_not.join(", ")}`, sev: "Critical" }, async (c) => {
      const page = await ui(u); const labels = await navLabels(page); await c.shot(page, "menu");
      if (u === "pharm1") {
        await nav(page, "Tiếp nhận & Hồ sơ"); await page.waitForTimeout(600); await c.shot(page, "tab-tiep-nhan-cua-duoc-si");
        const btns = await page.$$eval("button", (b) => b.map((x) => x.textContent.trim()));
        must(!btns.some((t) => /Tiếp nhận mới|Đối soát|Đề nghị gộp|Tiếp nhận kỳ mới/.test(t)), `Dược thấy nút ghi ở tab tra cứu: ${btns.filter((t) => /Tiếp nhận|Đối soát|gộp/.test(t)).join(", ")}`);
      }
      for (const m of must_have) must(labels.some((l) => l.includes(m)), `${u} thiếu tab “${m}” (có: ${labels.join(" | ")})`);
      for (const m of must_not) must(!labels.some((l) => l.includes(m)), `${u} thấy tab không được phép “${m}”`);
      return `Menu: ${labels.join(" | ")}`;
    });
  }

  // ---------------- RBAC / ABAC qua API
  await tc({ id: "RBAC-01", mod: "Phân quyền", kind: "Permission", role: "custody_officer", title: "Cán bộ tiếp nhận không đọc được dữ liệu lâm sàng (lượt khám, hồ sơ sức khỏe, đơn thuốc, tài liệu y tế)",
    expected: "HTTP 403 ở mọi endpoint lâm sàng (UAT-09)", sev: "Critical" }, async () => {
    const rs = [await api("officer1", "GET", `/encounters/${S.encA.id}`),
      await api("officer1", "GET", `/persons/${S.pA.id}/medication-orders`), await api("officer1", "GET", "/documents?person_id=" + S.pA.id), await api("officer1", "GET", "/encounters")];
    rs.forEach((r, i) => denied(r, `endpoint #${i + 1}`));
    const hs = await api("officer1", "GET", `/persons/${S.pA.id}/health-summary`);   // thiết kế: chỉ danh tính + đợt tiếp nhận, phần lâm sàng bị ẩn
    status(hs, 200, "health-summary (chỉ danh tính)"); must(hs.data.clinical === null && hs.data.clinical_hidden === true, "health-summary của cán bộ tiếp nhận LỘ dữ liệu lâm sàng: " + JSON.stringify(hs.data.clinical).slice(0, 120));
    return "4 endpoint lâm sàng 403; health-summary chỉ trả danh tính + đợt tiếp nhận (clinical=null)";
  });
  await tc({ id: "RBAC-02", mod: "Phân quyền", kind: "Permission", role: "sysadmin", title: "Quản trị hệ thống không được đọc bệnh án / không tiếp nhận / không kê đơn",
    expected: "HTTP 403 (sysadmin không có clinical.read)", sev: "Critical" }, async () => {
    const rs = [await api("admin", "GET", `/persons/${S.pA.id}/health-summary`), await api("admin", "GET", `/encounters/${S.encA.id}`), await api("admin", "GET", "/persons"),
      await api("admin", "POST", "/persons", { full_name: "UAT Admin Tạo" }), await api("admin", "GET", "/reports/encounters")];
    rs.forEach((r, i) => denied(r, `endpoint #${i + 1}`));
  });
  await tc({ id: "RBAC-03", mod: "Phân quyền", kind: "Permission", role: "nurse", title: "Điều dưỡng KHÔNG chẩn đoán, KHÔNG bắt đầu khám, KHÔNG kê đơn, KHÔNG cấp phát (phạm vi hành nghề)",
    expected: "403 cho diagnosis, transition in_progress, medication-orders, dispenses", sev: "Critical" }, async () => {
    const draft = await ok("nurse1", "POST", "/encounters", { person_id: S.pA.id, type: "ad_hoc", reason: "Yêu cầu khám từ điều dưỡng" });
    must(draft.status === "draft", `Yêu cầu khám của điều dưỡng phải ở trạng thái nháp, thực tế ${draft.status}`);
    const r1 = await api("nurse1", "POST", `/encounters/${S.encA.id}/diagnoses`, { text: "Viêm họng cấp", kind: "final" });
    const r2 = await api("nurse1", "POST", `/encounters/${draft.id}/transition`, { to: "in_progress" });
    const r3 = await api("nurse1", "POST", `/encounters/${S.encA.id}/medication-orders`, { drug_name: "Paracetamol 500mg", dose: "1", route: "uống", frequency: "2/ngày", start_date: today0(), duration_days: 5, quantity_prescribed: 10 });
    const rx = await confirmedRxLocal(S);
    const r4 = await api("nurse1", "POST", `/medication-orders/${rx.id}/dispenses`, { quantity: 1 });
    [r1, r2, r3, r4].forEach((r, i) => denied(r, `thao tác #${i + 1}`));
  });
  await tc({ id: "RBAC-04", mod: "Phân quyền", kind: "Permission", role: "pharmacist", title: "Dược sĩ không ghi nhận sử dụng thuốc, không kê/xác nhận đơn, không sửa lượt khám",
    expected: "403", sev: "High" }, async () => {
    const rx = await confirmedRxLocal(S);
    const rs = [await api("pharm1", "POST", `/medication-orders/${rx.id}/administrations`, { administered: true, dispense_id: undefined }),
      await api("pharm1", "POST", `/medication-orders/${rx.id}/revise`, { dose: "2 viên", reason: "x" }), await api("pharm1", "POST", `/medication-orders/${rx.id}/stop`, { outcome: "stopped", reason: "thử quyền" }),
      await api("pharm1", "POST", `/encounters/${S.encA.id}/observations`, { type: "Mạch", value: "80", unit: "l/p" })];
    rs.forEach((r, i) => denied(r, `thao tác #${i + 1}`));
  });
  await tc({ id: "RBAC-05", mod: "Phân quyền", kind: "Permission", role: "doctor", title: "Bác sĩ không phê duyệt/điều phối chuyển viện (tách quyết định chuyên môn – hành chính)",
    expected: "PATCH referral to=coordinated bởi doctor → 403", sev: "Critical" }, async () => {
    const r = await ok("doctor1", "POST", `/encounters/${S.encA.id}/referrals`, { urgency: "routine", reason: "UAT kiểm tra quyền duyệt", destination: "BV X" });
    await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" });
    denied(await api("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated" }), "bác sĩ tự duyệt");
    S.refPerm = r;
  });
  await tc({ id: "RBAC-06", mod: "Phân quyền", kind: "Permission", role: "approver", title: "Người phê duyệt không thấy lý do/kết quả chuyên môn và không thấy tài liệu của chuyển viện",
    expected: "reason/result_note bị ẩn (null/“ẩn”) trong API của approver; GET documents 403", sev: "Critical" }, async () => {
    const r = await ok("approver1", "GET", `/referrals/${S.refPerm.id}`);
    const raw = JSON.stringify(r);
    must(!raw.includes("UAT kiểm tra quyền duyệt"), "approver đọc được lý do chuyên môn của đề nghị chuyển viện");
    denied(await api("approver1", "GET", `/documents?person_id=${S.pA.id}`), "approver đọc tài liệu y tế");
  });
  await tc({ id: "RBAC-07", mod: "Phân quyền", kind: "Permission", role: "manager", title: "Quản lý y tế xem báo cáo nhưng không đọc bệnh án / không tạo đơn thuốc",
    expected: "Báo cáo 200; health-summary, encounters, kê đơn → 403", sev: "Critical" }, async () => {
    status(await api("manager1", "GET", "/reports/encounters"), 200, "báo cáo");
    [await api("manager1", "GET", `/persons/${S.pA.id}/health-summary`), await api("manager1", "GET", `/encounters/${S.encA.id}`), await api("manager1", "POST", `/encounters/${S.encA.id}/medication-orders`, { drug_name: "X", dose: "1", route: "u", frequency: "1", start_date: today0(), duration_days: 1, quantity_prescribed: 1 })].forEach((r, i) => denied(r, `#${i + 1}`));
  });
  await tc({ id: "RBAC-08", mod: "Phân quyền", kind: "Permission", role: "nurse/pharmacist/officer", title: "Báo cáo & nhật ký kiểm toán chỉ dành cho người có quyền (nurse/doctor/pharm/officer/approver bị 403)",
    expected: "403 cho /reports/* và /audit", sev: "High" }, async () => {
    for (const u of ["nurse1", "doctor1", "pharm1", "officer1", "approver1"]) {
      denied(await api(u, "GET", "/reports/encounters"), `${u} báo cáo`); denied(await api(u, "GET", "/audit"), `${u} audit`);
    }
  });
  await tc({ id: "RBAC-09", mod: "Phân quyền", kind: "Permission", role: "nurse/doctor/manager", title: "Chỉ sysadmin quản lý người dùng & danh mục",
    expected: "403 cho POST /users, GET /users, POST /catalogs với mọi vai trò khác", sev: "Critical" }, async () => {
    for (const u of ["officer1", "nurse1", "doctor1", "pharm1", "approver1", "manager1"]) {
      denied(await api(u, "POST", "/users", { username: "hack_" + U, password: "Hack@2026abcd", full_name: "x", role: "sysadmin" }), `${u} tạo user`);
      denied(await api(u, "GET", "/users"), `${u} liệt kê user`);
      denied(await api(u, "POST", "/catalogs", { catalog: "drug", code: "HACK", name: "x" }), `${u} sửa danh mục`);
    }
  });
  await tc({ id: "ABAC-01", mod: "Phân quyền (cơ sở)", kind: "Permission", role: "doctor2 → dữ liệu F01", title: "Cách ly cơ sở: bác sĩ Trại 2 không mở được hồ sơ/lượt khám/đơn thuốc/tài liệu của người Trại 1; sự kiện bị ghi nhật ký access_denied",
    expected: "403 FACILITY_SCOPE; audit có access_denied", sev: "Critical" }, async () => {
    const rs = [await api("doctor2", "GET", `/persons/${S.pA.id}/health-summary`), await api("doctor2", "GET", `/encounters/${S.encA.id}`),
      await api("doctor2", "POST", `/encounters/${S.encA.id}/observations`, { type: "Mạch", value: "80", unit: "l/p" }), await api("nurse2", "GET", `/persons/${S.pA.id}/medication-orders`)];
    rs.forEach((r, i) => denied(r, `#${i + 1}`));
    const a = await ok("admin", "GET", `/audit?action=access_denied&limit=50`); must(a.length > 0, "Không có sự kiện access_denied trong nhật ký");
  });
  await tc({ id: "ABAC-02", mod: "Phân quyền (cơ sở)", kind: "Permission", role: "approver2/manager2", title: "Cách ly cơ sở với chuyển viện/báo cáo: người Trại 2 không thao tác được hồ sơ chuyển viện Trại 1",
    expected: "403 khi approver2 đổi trạng thái referral của F01; báo cáo manager2 chỉ gồm dữ liệu F02", sev: "Critical" }, async () => {
    denied(await api("approver2", "PATCH", `/referrals/${S.refPerm.id}/status`, { to: "coordinated" }), "approver2 duyệt referral F01");
    const rep = await ok("manager2", "GET", "/reports/encounters"); must(rep.facility_id === S.f2, "Báo cáo manager2 không thuộc cơ sở F02");
  });
  await tc({ id: "ABAC-03", mod: "Phân quyền (UI)", kind: "Permission", role: "officer1", title: "Gõ thẳng URL của tab bị cấm (#/record, #/exam, #/admin) → hệ thống đưa về tab được phép",
    expected: "Không hiển thị nội dung tab cấm; active tab = Bảng điều khiển", sev: "High" }, async (c) => {
    const page = await ui("officer1");
    for (const h of ["#/record", "#/exam", "#/admin", "#/reports"]) {
      await page.goto(BASE + "/" + h); await page.waitForTimeout(700);
      const active = (await page.$eval(".side .nav.on", (e) => e.textContent).catch(() => "")); must(/Bảng điều khiển|Tiếp nhận|Chuyển trại/.test(active), `${h} → tab đang hiển thị: “${active}”`);
    }
    await c.shot(page, "url-cam");
  });
}
const today0 = () => new Date().toISOString().slice(0, 10);
async function confirmedRxLocal(S) {
  const d = await ok("doctor1", "POST", `/encounters/${S.encA.id}/medication-orders`, { drug_name: "Paracetamol 500mg", drug_code: "PARA500", dose: "1 viên", route: "uống", frequency: "2 lần/ngày", start_date: today0(), duration_days: 15, quantity_prescribed: 30 });
  return ok("doctor1", "POST", `/medication-orders/${d.id}/confirm`, d.warnings?.length ? { acknowledge_warnings: true, ack_note: "UAT" } : {});
}
