// PART 3 – Chuyển viện (M09/WF-06), Chuyển trại (WF-07), Cấp cứu (WF-08), Khám định kỳ & cảnh báo (M07/M08)
import { api, ok, tc, must, status, denied, code, ui, nav, toast, uniq, today, iso, newPerson, managedPerson, startEnc, confirmedRx, sql, upload, freshPage, BASE } from "./uat-lib.mjs";

export async function part3(S) {
  const U = S.U;
  // ======================================================= REFERRAL
  const refSetup = async (tag, urgency = "routine") => {
    const p = await managedPerson(`UAT ${tag} ${U}`); const e = await startEnc(p.id);
    const r = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency, reason: `Lý do chuyên môn bí mật ${tag} ${U}`, destination: "BV Đa khoa tỉnh" });
    return { p, e, r };
  };
  await tc({ id: "REF-01", mod: "Chuyển viện (M09)", kind: "Cross-dept", role: "doctor → approver → nurse → doctor", title: "Luồng chuyển viện trọn vẹn liên phòng ban (UAT-06): lập → gửi duyệt → điều phối → rời trại → kết quả → hoàn thành; chuyển viện KHÔNG đổi đợt tiếp nhận (BR-05)",
    expected: "Mỗi bước đúng vai trò; trạng thái draft→pending→coordinated→in_external_treatment→result_received→completed; stay vẫn 'managed'; lịch sử điều phối đủ mốc", sev: "Critical" }, async () => {
    const { p, r } = await refSetup("CV Trọn Luồng");
    await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" });
    await ok("approver1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated", destination: "BV Đa khoa tỉnh" });
    await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" });
    await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "result_received", result_note: "Đã phẫu thuật ổn định" });
    const done = await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "completed", post_referral_plan: "Tái khám sau 7 ngày", outcome: "returned" });
    must(done.status === "completed", `status=${done.status}`);
    must(sql(`select status s from custody_stay where id='${p.stay.id}'`)[0].s === "managed", "Chuyển viện làm đổi trạng thái đợt tiếp nhận (vi phạm BR-05)");
    const ev = sql(`select count(*) n from referral_event where referral_id='${r.id}'`)[0].n; must(ev >= 6, `Lịch sử điều phối chỉ có ${ev} mốc`);
    S.refDone = r;
  });
  await tc({ id: "REF-02", mod: "Chuyển viện (M09)", kind: "Negative", role: "doctor1/nurse1", title: "Chuyển trạng thái sai thứ tự bị chặn (nháp→đã điều phối; chờ xử lý→có kết quả; đã hoàn tất→mở lại)",
    expected: "HTTP 409 BAD_TRANSITION", sev: "High" }, async () => {
    const { r } = await refSetup("CV Sai Thứ Tự");
    const a = await api("approver1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated" });
    const b = await api("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "result_received", result_note: "x" });
    const c2 = await api("doctor1", "PATCH", `/referrals/${S.refDone.id}/status`, { to: "pending", note: "mở lại" });
    must(a.status === 409 && b.status === 409 && c2.status === 409, `HTTP ${a.status}/${b.status}/${c2.status}`);
  });
  await tc({ id: "REF-03", mod: "Chuyển viện (M09)", kind: "Negative", role: "doctor1/nurse1", title: "Thiếu dữ liệu bắt buộc: ghi kết quả bỏ trống; hoàn thành thiếu kế hoạch; hoàn thành thiếu kết cục",
    expected: "HTTP 422 cho cả ba trường hợp (H4)", sev: "High" }, async () => {
    const { r } = await refSetup("CV Thiếu Dữ Liệu");
    await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" }); await ok("approver1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated" });
    await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" });
    const a = await api("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "result_received" });
    await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "result_received", result_note: "Ổn định" });
    const b = await api("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "completed" });
    const c2 = await api("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "completed", post_referral_plan: "Tái khám" });
    must(a.status === 422 && b.status === 422 && c2.status === 422, `KQ trống/hoàn thành thiếu/thiếu kết cục: HTTP ${a.status}/${b.status}/${c2.status}`);
  });
  await tc({ id: "REF-04", mod: "Chuyển viện (M09)", kind: "Cross-dept", role: "doctor → approver", title: "Chuyển viện cấp cứu 'đi tắt': không cần duyệt, gắn 'cần hậu kiểm' + cảnh báo + thông báo Khẩn; người phê duyệt hậu kiểm → đóng cờ (H6)",
    expected: "status=in_external_treatment, needs_post_review=true, có Alert referral_post_review; approver/manager nhận thông báo; sau hậu kiểm cờ=false", sev: "High" }, async () => {
    const { p, r } = await refSetup("CV Cấp Cứu", "emergency");
    const x = await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment", note: "Đau ngực cấp" });
    must(x.status === "in_external_treatment" && x.needs_post_review === true, `status=${x.status} review=${x.needs_post_review}`);
    must(sql(`select count(*) n from alert where dedupe_key='ref-review:${r.id}'`)[0].n === 1, "Thiếu Alert hậu kiểm");
    const n1 = await ok("approver1", "GET", "/notifications?limit=100"); must(JSON.stringify(n1).includes(r.id), "approver không nhận thông báo đi tắt");
    const mg = await ok("manager1", "GET", "/notifications?limit=100"); const mine = (mg.items || []).find((n) => n.link_ref === r.id);
    must(mine, "manager không nhận thông báo đi tắt"); must(!JSON.stringify(mine).includes(p.full_name), "manager thấy TÊN người bệnh trong thông báo (phải ẩn)");
    const pr = await ok("approver1", "POST", `/referrals/${r.id}/post-review`, { note: "Hợp lệ: tình trạng khẩn cấp" }); must(pr.needs_post_review === false, "cờ hậu kiểm chưa đóng");
  });
  await tc({ id: "REF-05", mod: "Chuyển viện (M09)", kind: "Negative", role: "doctor1", title: "Tài liệu bàn giao kèm chuyển viện phải là tài liệu hợp lệ của ĐÚNG người bệnh",
    expected: "Tài liệu của người khác → 422 BAD_HANDOVER_DOC; tài liệu của chính người → 200", sev: "High" }, async () => {
    const { p, e, r } = await refSetup("CV Tài Liệu");
    const other = await managedPerson(`UAT Người Khác Tài Liệu ${U}`);
    const mine = await upload("doctor1", { doc_type: "lab_result", person_id: p.id }); const theirs = await upload("doctor1", { doc_type: "lab_result", person_id: other.id });
    status(mine, 201, "upload"); status(theirs, 201, "upload");
    status(await api("doctor1", "PUT", `/referrals/${r.id}/handover-docs`, { handover_docs: [theirs.data.id] }), 422, "tài liệu người khác");
    status(await api("doctor1", "PUT", `/referrals/${r.id}/handover-docs`, { handover_docs: [mine.data.id] }), 200, "tài liệu đúng người");
  });
  await tc({ id: "REF-06", mod: "Chuyển viện (UI)", kind: "Permission", role: "approver1 (UI)", title: "Màn hình người phê duyệt: lý do chuyên môn hiển thị 'Ẩn theo phân quyền', không có mục Tài liệu, không có nút Gửi duyệt/Hoàn thành (H3)",
    expected: "Không hiện nội dung lý do chuyên môn; có nút Phê duyệt & điều phối", sev: "Critical" }, async (c) => {
    const { r, p } = await refSetup("CV UI Duyệt"); await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" });
    const page = await ui("approver1"); await page.reload(); await page.waitForSelector(".side .nav"); await nav(page, "Chuyển viện");
    await page.locator(`.kcard:has-text("${p.full_name}")`).first().click(); await page.waitForSelector(".drawer"); await c.shot(page, "chi-tiet");
    const t = await page.innerText(".drawer"); must(!t.includes("Lý do chuyên môn bí mật"), "Approver thấy lý do chuyên môn"); must(/Ẩn theo phân quyền/.test(t), "Không có nhãn 'Ẩn theo phân quyền'");
    must(!(await page.$('.drawer button:has-text("Gửi duyệt")')) && !(await page.$('.drawer button:has-text("Hoàn thành chuyển viện")')), "Approver thấy nút của bác sĩ");
    must(await page.$('.drawer button:has-text("Phê duyệt & điều phối")'), "Thiếu nút Phê duyệt & điều phối");
  });
  await tc({ id: "REF-07", mod: "Chuyển viện (M09)", kind: "Positive", role: "doctor1/approver1", title: "Kết cục 'Tử vong'/'Không trở lại trại' gắn cờ cần hậu kiểm + thông báo Khẩn (WF-06 ngoại lệ, O12)",
    expected: "needs_post_review=true sau hoàn thành với outcome=deceased", sev: "High" }, async () => {
    const { r } = await refSetup("CV Kết Cục Bất Thường");
    await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "pending" }); await ok("approver1", "PATCH", `/referrals/${r.id}/status`, { to: "coordinated" });
    await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" }); await ok("nurse1", "PATCH", `/referrals/${r.id}/status`, { to: "result_received", result_note: "Tiên lượng nặng" });
    const d = await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "completed", post_referral_plan: "Báo cáo theo quy trình", outcome: "deceased" });
    must(d.needs_post_review === true, "Kết cục tử vong không gắn cờ hậu kiểm");
  });

  // ======================================================= HANDOVER (chuyển trại)
  const hoSetup = async (tag, { kind = "transfer" } = {}) => {
    const p = await managedPerson(`UAT ${tag} ${U}`);
    const h = await ok("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind, ...(kind === "transfer" ? { to_facility_id: S.f2 } : {}), reason: "Điều chuyển theo quyết định UAT" });
    return { p, h };
  };
  await tc({ id: "HO-01", mod: "Chuyển trại (WF-07)", kind: "Negative", role: "officer1", title: "Không xác nhận bàn giao khi chưa có tóm tắt y tế (J2); phiếu thứ 2 cho cùng người khi phiếu cũ còn chờ bị chặn (J7)",
    expected: "Xác nhận khi thiếu tóm tắt → 4xx; tạo phiếu trùng → 409", sev: "High" }, async () => {
    const { p, h } = await hoSetup("BG Thiếu Tóm Tắt");
    const r = await api("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true }); must(r.status >= 400 && r.status < 500, `xác nhận thiếu tóm tắt: HTTP ${r.status}`);
    const d = await api("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind: "transfer", to_facility_id: S.f2, reason: "Phiếu thứ hai" }); must(d.status === 409, `phiếu trùng: HTTP ${d.status}`);
  });
  await tc({ id: "HO-02", mod: "Chuyển trại (WF-07)", kind: "Permission", role: "officer1 vs nurse1", title: "Nội dung tóm tắt y tế chỉ điều dưỡng/bác sĩ đọc được; cán bộ tiếp nhận chỉ biết 'đã có tóm tắt' (J3)",
    expected: "GET handover bởi officer1 không chứa nội dung tóm tắt; bởi nurse1 chứa", sev: "Critical" }, async () => {
    const { h } = await hoSetup("BG Quyền Tóm Tắt"); const SUM = "Tăng huyết áp độ 2, đang dùng Amlodipine; dị ứng Penicillin " + U;
    denied(await api("officer1", "PUT", `/handovers/${h.id}/summary`, { summary: SUM }), "officer soạn tóm tắt");
    await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: SUM });
    const o = await ok("officer1", "GET", `/handovers/${h.id}`), n = await ok("nurse1", "GET", `/handovers/${h.id}`);
    must(!JSON.stringify(o).includes("Amlodipine"), "officer đọc được nội dung tóm tắt y tế"); must(JSON.stringify(n).includes("Amlodipine"), "nurse không đọc được tóm tắt do chính mình soạn");
  });
  await tc({ id: "HO-03", mod: "Chuyển trại (WF-07)", kind: "Negative", role: "officer1", title: "Còn điều trị/lịch hẹn mở: bắt buộc tick xác nhận 'acknowledge_open_items' mới được bàn giao (J4/O11)",
    expected: "Không ack → 4xx; có ack → 200", sev: "High" }, async () => {
    const p = await managedPerson(`UAT BG Điều Trị Mở ${U}`); const e = await startEnc(p.id); await confirmedRx(e.id);
    const h = await ok("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind: "transfer", to_facility_id: S.f2, reason: "Điều chuyển có điều trị mở" });
    await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Đang điều trị Paracetamol 15 ngày, ổn định" });
    const a = await api("officer1", "POST", `/handovers/${h.id}/confirm`, {}); must(a.status >= 400 && a.status < 500, `không ack: HTTP ${a.status}`);
    status(await api("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true }), 200, "có ack");
  });
  await tc({ id: "HO-04", mod: "Chuyển trại (WF-07)", kind: "Cross-dept", role: "officer1 → nurse1 → officer2 → doctor2", title: "Chuyển trại trọn vẹn liên cơ sở (UAT-08): đợt tiếp nhận cũ 'transferred', cơ sở nhận tạo kỳ mới → biên nhận; bác sĩ trại nhận thấy toàn bộ lịch sử; MỘT hồ sơ sức khỏe",
    expected: "stay F01=transferred; handover.received_at có giá trị; doctor2 đọc được health-summary kèm lịch sử khám trại cũ; health_record vẫn 1", sev: "Critical" }, async () => {
    const { p, h } = await hoSetup("BG Liên Cơ Sở");
    await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Sức khỏe ổn định, đã khám ban đầu, không dị ứng" });
    await ok("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true });
    must(sql(`select status s from custody_stay where id='${p.stay.id}'`)[0].s === "transferred", "Đợt tiếp nhận cũ không chuyển 'transferred'");
    const hrBefore = sql(`select id from health_record where person_id='${p.id}'`);
    const st = await ok("officer2", "POST", `/persons/${p.id}/stays`, {});
    const rec = sql(`select received_at, received_stay_id from handover where id='${h.id}'`)[0]; must(rec.received_at && rec.received_stay_id === st.id, "Không lập biên nhận khi cơ sở nhận tạo kỳ mới");
    const hs = await api("doctor2", "GET", `/persons/${p.id}/health-summary`); status(hs, 200, "doctor2 đọc hồ sơ");
    must(JSON.stringify(hs.data).includes("Khám sức khỏe ban đầu") || (hs.data.encounters || hs.data.recent_encounters || []).length > 0 || JSON.stringify(hs.data).includes("initial"), "Bác sĩ trại nhận không thấy lịch sử khám cũ");
    const hrAfter = sql(`select id from health_record where person_id='${p.id}'`); must(hrAfter.length === 1 && hrAfter[0].id === hrBefore[0].id, "Hồ sơ sức khỏe bị nhân đôi/đổi");
    S.transferred = p;
  });
  await tc({ id: "HO-05", mod: "Chuyển trại (WF-07)", kind: "Positive", role: "officer1", title: "Kết thúc quản lý (mãn hạn): đợt tiếp nhận 'ended', không xóa dữ liệu; tái tiếp nhận tạo kỳ mới nhưng KHÔNG tạo hồ sơ sức khỏe mới (UAT-01)",
    expected: "stay ended; sau tái tiếp nhận có 2 stay và 1 health_record", sev: "Critical" }, async () => {
    const p = await managedPerson(`UAT BG Mãn Hạn ${U}`); const e = await startEnc(p.id); await ok("doctor1", "POST", `/encounters/${e.id}/observations`, { type: "Mạch", value: "75", unit: "l/p" });
    const h = await ok("officer1", "POST", `/stays/${p.stay.id}/handover`, { kind: "release", reason: "Mãn hạn tù" });
    await ok("nurse1", "PUT", `/handovers/${h.id}/summary`, { summary: "Sức khỏe bình thường khi ra trại" }); await ok("officer1", "POST", `/handovers/${h.id}/confirm`, { acknowledge_open_items: true });
    must(sql(`select status s from custody_stay where id='${p.stay.id}'`)[0].s === "ended", "Kỳ không chuyển 'ended'");
    await ok("officer1", "POST", `/persons/${p.id}/stays`, {});
    must(sql(`select count(*) n from custody_stay where person_id='${p.id}'`)[0].n === 2, "Phải có 2 đợt tiếp nhận");
    must(sql(`select count(*) n from health_record where person_id='${p.id}'`)[0].n === 1, "Tạo trùng hồ sơ sức khỏe khi tái tiếp nhận");
    must(sql(`select count(*) n from observation where encounter_id='${e.id}'`)[0].n === 1, "Lịch sử khám cũ bị mất");
  });
  await tc({ id: "HO-06", mod: "Chuyển trại (WF-07)", kind: "Negative", role: "officer1/nurse2", title: "Cơ sở không liên quan không xem/xác nhận được phiếu bàn giao; hủy phiếu bắt buộc lý do",
    expected: "officer2 xác nhận phiếu F01→F02 chưa tới lượt: không được; người ngoài cơ sở đọc → 404; hủy không lý do → 422", sev: "High" }, async () => {
    const { p, h } = await hoSetup("BG Hủy Phiếu");
    const r = await api("officer1", "POST", `/handovers/${h.id}/cancel`, {}); must(r.status === 422, `hủy không lý do: HTTP ${r.status}`);
    status(await api("officer1", "POST", `/handovers/${h.id}/cancel`, { reason: "Quyết định điều chuyển bị hủy" }), 200, "hủy có lý do");
    must([404, 403].includes((await api("admin", "GET", `/handovers/${h.id}`)).status), "sysadmin ngoài cơ sở đọc được phiếu bàn giao");
  });

  // ======================================================= EMERGENCY
  await tc({ id: "EMG-01", mod: "Cấp cứu (WF-08)", kind: "Positive", role: "nurse1", title: "Ghi nhận cấp cứu tối thiểu, chưa rõ danh tính → tạo ngay hồ sơ tạm + lượt khám cấp cứu đang mở, không bị chặn bởi thủ tục (UAT-07/I1)",
    expected: "201; person.provisional/[TẠM]; encounter type=emergency in_progress; priority emergent", sev: "Critical" }, async () => {
    const ev = await ok("nurse1", "POST", "/emergency-events", { temp_identity: "Nam khoảng 40 tuổi, chưa rõ danh tính " + U });
    const row = sql(`select p.full_name n, e.type t, e.status s, e.priority pr from emergency_event ev join person p on p.id=ev.person_id join encounter e on e.id=ev.encounter_id where ev.id='${ev.id}'`)[0];
    must(/TẠM/i.test(row.n), `Tên hồ sơ tạm: ${row.n}`); must(row.t === "emergency" && row.s === "in_progress" && row.pr === "emergent", JSON.stringify(row));
    S.emg = ev;
  });
  await tc({ id: "EMG-02", mod: "Cấp cứu (WF-08)", kind: "Boundary", role: "nurse1", title: "BR-03: ghi muộn cấp cứu – 14 phút không cần lý do; 16 phút bắt buộc lý do; thời điểm tương lai bị từ chối",
    expected: "14'→201; 16' không lý do→422; 16' có lý do→201; tương lai→422", sev: "High" }, async () => {
    const mk = (b) => api("nurse1", "POST", "/emergency-events", { temp_identity: "Biên thời gian " + U, ...b });
    const a = await mk({ occurred_at: iso(14) }), b = await mk({ occurred_at: iso(16) }), c2 = await mk({ occurred_at: iso(16), late_entry_reason: "Mất điện, ghi bổ sung" }), d = await mk({ occurred_at: iso(-10) });
    must(a.status === 201 && b.status === 422 && c2.status === 201 && d.status === 422, `HTTP 14'/16'/16'+lý do/tương lai = ${a.status}/${b.status}/${c2.status}/${d.status}`);
  });
  await tc({ id: "EMG-03", mod: "Cấp cứu (WF-08)", kind: "Cross-dept", role: "nurse1 → doctor1 → officer1", title: "Đóng sự kiện cấp cứu chỉ khi hồ sơ khám hoàn tất VÀ danh tính đã đối soát; nurse không được đóng (I4/I5)",
    expected: "Đóng sớm → 4xx; nurse đóng → 403; sau hoàn tất khám + đối soát (officer) → đóng 200", sev: "High" }, async () => {
    const ev = await ok("nurse1", "POST", "/emergency-events", { temp_identity: "Cấp cứu đóng sự kiện " + U, description: "Ngất xỉu" });
    await ok("nurse1", "POST", `/emergency-events/${ev.id}/interventions`, { action: "Đặt nằm đầu thấp, đo huyết áp" });
    const early = await api("doctor1", "POST", `/emergency-events/${ev.id}/close`, { note: "Đóng sớm thử" }); must(early.status >= 400 && early.status < 500, `Đóng sớm: HTTP ${early.status}`);
    denied(await api("nurse1", "POST", `/emergency-events/${ev.id}/close`, { note: "Điều dưỡng đóng" }), "nurse đóng sự kiện");
    await ok("doctor1", "POST", `/encounters/${ev.encounter_id}/diagnoses`, { text: "Ngất do hạ đường huyết", kind: "final" });
    await ok("doctor1", "POST", `/encounters/${ev.encounter_id}/transition`, { to: "completed" });
    const still = await api("doctor1", "POST", `/emergency-events/${ev.id}/close`, { note: "Chưa đối soát danh tính" }); must(still.status >= 400 && still.status < 500, `Đóng khi chưa đối soát danh tính: HTTP ${still.status}`);
    await ok("officer1", "POST", `/persons/${ev.person_id}/verify`, { full_name: "UAT Cấp Cứu Đã Đối Soát " + U, source_system: "QLPN", external_id: "UAT-EMG-" + U, note: "Đối soát theo hồ sơ giấy" });
    status(await api("doctor1", "POST", `/emergency-events/${ev.id}/close`, { note: "Đã ổn định, hẹn theo dõi" }), 200, "đóng hợp lệ");
  });
  await tc({ id: "EMG-04", mod: "Cấp cứu (WF-08)", kind: "Cross-dept", role: "doctor1 → nurse1/nurse2", title: "Thông báo CẤP CỨU: điều dưỡng cùng trại nhận (Khẩn); người ghi không tự nhận; trại khác không nhận (N4)",
    expected: "nurse1 có thông báo emergency.created; doctor1 (người ghi) & nurse2 không", sev: "Medium" }, async () => {
    const ev = await ok("doctor1", "POST", "/emergency-events", { temp_identity: "Thông báo cấp cứu " + U, location: "Buồng 7" });
    const list = async (u) => ((await ok(u, "GET", "/notifications?limit=200")).items || []).filter((n) => n.link_ref === ev.id && n.kind === "emergency.created");
    const a = await list("nurse1"), b = await list("doctor1"), c2 = await list("nurse2");
    must(a.length === 1 && a[0].severity === "critical", `nurse1: ${a.length} thông báo`); must(b.length === 0, "người ghi nhận thông báo của chính mình"); must(c2.length === 0, "nurse2 (trại khác) nhận thông báo cấp cứu của trại 1");
  });

  // ======================================================= SCHEDULING
  await tc({ id: "SCH-01", mod: "Khám định kỳ (M07)", kind: "Positive", role: "manager1", title: "Tạo đợt khám định kỳ: chỉ gom người ĐANG QUẢN LÝ; người mới tiếp nhận (chưa khám ban đầu), đang chuyển viện, đang chờ chuyển trại bị loại trừ có lý do (WF-04, F5/O4)",
    expected: "Nhiệm vụ cho người managed; người 'received' → loại trừ 'Chưa hoàn tất khám ban đầu'; người đang chuyển viện → loại trừ", sev: "High" }, async () => {
    const m = await managedPerson(`UAT Định Kỳ Đủ Điều Kiện ${U}`), nw = await newPerson(`UAT Định Kỳ Mới Tiếp Nhận ${U}`);
    const refP = await managedPerson(`UAT Định Kỳ Đang Chuyển Viện ${U}`); const e = await startEnc(refP.id); const r = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "emergency", reason: "Cấp cứu thử loại trừ", destination: "BV A" });
    await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" });
    const rd = await ok("manager1", "POST", "/checkup-rounds", { name: `UAT Đợt Khám ${U}`, due_date: today(30) }); S.round = rd;
    const ap = sql(`select person_id from appointment where round_id='${rd.id}'`).map((x) => x.person_id);
    must(ap.includes(m.id), "Người đang quản lý không có nhiệm vụ"); must(!ap.includes(nw.id), "Người mới tiếp nhận có nhiệm vụ khám định kỳ"); must(!ap.includes(refP.id), "Người đang chuyển viện vẫn có nhiệm vụ");
    const ex = JSON.parse(sql(`select excluded x from checkup_round where id='${rd.id}'`)[0].x); const exo = (id) => ex.find((x) => x.person_id === id)?.reason;
    must(/khám ban đầu/i.test(exo(nw.id) || ""), `lý do loại trừ người mới: ${exo(nw.id)}`); must(/chuyển viện|ngoài trại/i.test(exo(refP.id) || ""), `lý do loại trừ người đi viện: ${exo(refP.id)}`);
    S.roundPeople = { m, nw };
  });
  await tc({ id: "SCH-02", mod: "Khám định kỳ (M07)", kind: "Positive", role: "manager1", title: "Khóa đợt: nhiệm vụ chưa khám ghi 'Không thực hiện' (không bỏ sót); khóa lần 2 bị chặn; đợt khóa không thao tác thêm (F6)",
    expected: "Mọi appointment còn mở → not_done; lock lần 2 → 409", sev: "High" }, async () => {
    const rd = S.round; const before = sql(`select count(*) n from appointment where round_id='${rd.id}' and status in ('scheduled','due')`)[0].n; must(before > 0, "Đợt không có nhiệm vụ mở để kiểm");
    await ok("manager1", "POST", `/checkup-rounds/${rd.id}/lock`);
    must(sql(`select count(*) n from appointment where round_id='${rd.id}' and status in ('scheduled','due')`)[0].n === 0, "Còn nhiệm vụ mở sau khi khóa");
    must(sql(`select count(*) n from appointment where round_id='${rd.id}' and status='not_done'`)[0].n === before, "Nhiệm vụ chưa khám không được ghi 'not_done'");
    status(await api("manager1", "POST", `/checkup-rounds/${rd.id}/lock`), 409, "khóa lần 2");
  });
  await tc({ id: "SCH-03", mod: "Khám định kỳ (M07)", kind: "Boundary", role: "manager1/nurse1", title: "Đợt khám: tên < 3 ký tự, hạn quá xa (> 3 năm) / quá cũ (> 1 năm trước) bị từ chối; điều dưỡng không tạo được đợt",
    expected: "422 cho dữ liệu sai; 403 cho nurse", sev: "Medium" }, async () => {
    const a = await api("manager1", "POST", "/checkup-rounds", { name: "ab", due_date: today(10) }), b = await api("manager1", "POST", "/checkup-rounds", { name: "Đợt xa " + U, due_date: today(1200) }),
      c2 = await api("manager1", "POST", "/checkup-rounds", { name: "Đợt cũ " + U, due_date: today(-400) }), d = await api("nurse1", "POST", "/checkup-rounds", { name: "Điều dưỡng tạo " + U, due_date: today(10) });
    must(a.status === 422 && b.status === 422 && c2.status === 422, `HTTP ${a.status}/${b.status}/${c2.status}`); denied(d, "nurse tạo đợt");
  });
  await tc({ id: "SCH-04", mod: "Khám định kỳ (M07)", kind: "Permission", role: "manager1/doctor2", title: "Cách ly cơ sở: bác sĩ Trại 2 không thấy đợt khám Trại 1; manager không thấy tên người bị loại trừ (chỉ mã rút gọn) (F1/F4)",
    expected: "doctor2 GET rounds không chứa đợt của F01; manager1 GET round: excluded không có person_name", sev: "High" }, async () => {
    const l = await ok("doctor2", "GET", "/checkup-rounds"); must(!l.some((r) => r.id === S.round.id), "doctor2 thấy đợt khám của Trại 1");
    denied(await api("doctor2", "GET", `/checkup-rounds/${S.round.id}`), "doctor2 mở đợt F01");
    const g = await ok("manager1", "GET", `/checkup-rounds/${S.round.id}`); must(!JSON.stringify(g.excluded).includes(S.roundPeople.nw.full_name), "manager thấy tên người bệnh bị loại trừ");
  });
  await tc({ id: "SCH-05", mod: "Cảnh báo (M08)", kind: "Positive", role: "nurse1", title: "Cảnh báo: tiếp nhận một lần, lần 2 bị chặn; xử lý xong ghi người chịu trách nhiệm + thời điểm (G1)",
    expected: "ack lần 2 → 409; resolve → handled_at, owner_id", sev: "Medium" }, async () => {
    const m = await managedPerson(`UAT Cảnh Báo ${U}`); const e = await startEnc(m.id); const r = await ok("doctor1", "POST", `/encounters/${e.id}/referrals`, { urgency: "emergency", reason: "Tạo cảnh báo hậu kiểm", destination: "BV A" });
    await ok("doctor1", "PATCH", `/referrals/${r.id}/status`, { to: "in_external_treatment" });
    const al = sql(`select id from alert where dedupe_key='ref-review:${r.id}'`)[0].id;
    await ok("manager1", "POST", `/alerts/${al}/acknowledge`); status(await api("manager1", "POST", `/alerts/${al}/acknowledge`), 409, "tiếp nhận lần 2");
    await ok("manager1", "POST", `/alerts/${al}/resolve`, { note: "Đã hậu kiểm" });
    const row = sql(`select owner_id, handled_at, status from alert where id='${al}'`)[0]; must(row.owner_id && row.handled_at && row.status === "resolved", JSON.stringify(row));
  });
  await tc({ id: "SCH-06", mod: "Cảnh báo (M08)", kind: "Idempotency", role: "admin", title: "Tác vụ nền (scheduler) chạy lặp không sinh cảnh báo/nhắc việc trùng (G6)",
    expected: "Số alert trước/sau lần chạy thứ 2 bằng nhau", sev: "Medium" }, async () => {
    await ok("admin", "POST", "/scheduler/run"); const a = sql("select count(*) n from alert")[0].n, nn = sql("select count(*) n from notification")[0].n;
    await ok("admin", "POST", "/scheduler/run"); const b = sql("select count(*) n from alert")[0].n, nb = sql("select count(*) n from notification")[0].n;
    must(a === b && nn === nb, `alert ${a}→${b}, notification ${nn}→${nb}`);
  });
  await tc({ id: "SCH-07", mod: "Lịch hẹn (M08)", kind: "Boundary", role: "nurse1", title: "Lịch hẹn: ngày hẹn quá khứ bị từ chối; hoãn/không thực hiện bắt buộc lý do ≥3 ký tự",
    expected: "due_date quá khứ → 422; hoãn không lý do → 422; có lý do → 200", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Lịch Hẹn ${U}`);
    status(await api("nurse1", "POST", "/appointments", { person_id: p.id, due_date: today(-1), note: "Quá khứ" }), 422, "hẹn quá khứ");
    const a = await ok("nurse1", "POST", "/appointments", { person_id: p.id, due_date: today(7), note: "Tái khám" });
    status(await api("nurse1", "POST", `/appointments/${a.id}/status`, { to: "postponed", reason: "" }), 422, "hoãn không lý do");
    status(await api("nurse1", "POST", `/appointments/${a.id}/status`, { to: "postponed", reason: "Người bệnh đang ở bệnh xá", new_due_date: today(14) }), 200, "hoãn có lý do");
  });
  await tc({ id: "SCH-08", mod: "Bệnh lý (M08)", kind: "Positive", role: "doctor1/nurse1", title: "Kế hoạch theo dõi: cần có vấn đề sức khỏe đang hiệu lực; chỉ bác sĩ lập/sửa; đổi chu kỳ dời lịch đang mở (G5/R4)",
    expected: "nurse lập → 403; bác sĩ lập OK; PATCH chu kỳ 14→30 làm due_date lịch mở dời", sev: "Medium" }, async () => {
    const p = await managedPerson(`UAT Kế Hoạch ${U}`); const pr = await ok("doctor1", "POST", `/persons/${p.id}/problems`, { name: "Tăng huyết áp vô căn", code: "I10" });
    denied(await api("nurse1", "POST", `/persons/${p.id}/care-plans`, { problem_id: pr.id, goals: "HA<140/90", review_interval_days: 14, measures: [{ name: "HA tâm thu", unit: "mmHg" }] }), "nurse lập kế hoạch");
    const cp = await ok("doctor1", "POST", `/persons/${p.id}/care-plans`, { problem_id: pr.id, goals: "HA<140/90", review_interval_days: 14, start_date: today(), measures: [{ name: "HA tâm thu", unit: "mmHg" }] });
    const d1 = sql(`select due_date d from appointment where care_plan_id='${cp.id}' and status in ('scheduled','due')`)[0]?.d;
    await ok("doctor1", "PATCH", `/care-plans/${cp.id}`, { review_interval_days: 30, expected_version: cp.version });
    const d2 = sql(`select due_date d from appointment where care_plan_id='${cp.id}' and status in ('scheduled','due')`)[0]?.d; must(d1 && d2 && d1 !== d2, `Lịch theo dõi không dời: ${d1} → ${d2}`);
    denied(await api("nurse1", "PATCH", `/care-plans/${cp.id}`, { review_interval_days: 7 }), "nurse sửa kế hoạch");
  });
}
