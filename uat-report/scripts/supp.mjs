// Lượt BỔ SUNG: chạy lại EXP-01 theo 5 lần thử (lỗi tranh chấp có tính ngẫu nhiên) và DC-12, thay thế bản ghi cũ trong results.json
import fs from "node:fs";
import { api, tc, must, sql, results, newPerson, uniq, OUT } from "./uat-lib.mjs";
const old = JSON.parse(fs.readFileSync(OUT + "/results.json", "utf8"));
fs.writeFileSync(OUT + "/results.run6-original.json", JSON.stringify(old, null, 1));
const REPLACE = ["EXP-01", "DC-12"];
results.push(...old.filter((r) => !REPLACE.includes(r.id)));
const U = uniq(); const par = (n, f) => Promise.all(Array.from({ length: n }, (_, i) => f(i)));
await tc({ id: "EXP-01", mod: "Đồng thời", kind: "Concurrency", role: "doctor1/officer1", title: "6 yêu cầu ĐỒNG THỜI tạo khám ban đầu cho cùng một đợt tiếp nhận (lặp 5 lần thử): chỉ 1 thành công mỗi lần (không nhân đôi lượt khám ban đầu)",
  expected: "Mỗi lần thử: đúng 1 lượt khám ban đầu không hủy trong DB", sev: "High", supplement: true }, async () => {
  const counts = [];
  for (let t = 0; t < 5; t++) { const p = await newPerson(`UAT Đồng Thời Khám ${t} ${U}`); await par(6, () => api("doctor1", "POST", "/encounters", { person_id: p.id, type: "initial", reason: "Khám ban đầu song song" }));
    counts.push(sql(`select count(*) n from encounter where person_id='${p.id}' and type='initial' and status!='cancelled'`)[0].n); }
  must(counts.every((n) => n === 1), `Số lượt khám ban đầu tạo ra mỗi lần thử: ${counts.join(", ")} (kỳ vọng luôn 1). Lượt chạy chính (run6) tình cờ đạt; các lượt chạy trước và 10 lần đo riêng cho thấy tái hiện 8/10.`);
});
await tc({ id: "DC-12", mod: "Nhất quán dữ liệu", kind: "Data-consistency", role: "DB (SQL)", title: "Mỗi đợt tiếp nhận chỉ có tối đa 1 lượt khám ban đầu không bị hủy (WF-01, B5) – kiểm lại sau lượt bổ sung",
  expected: "Không stay nào có >1 encounter initial chưa hủy", sev: "High", supplement: true }, async () => {
  const r = sql("select stay_id, count(*) n from encounter where type='initial' and status!='cancelled' group by stay_id having n>1"); must(!r.length, `${r.length} đợt tiếp nhận có nhiều hơn 1 lượt khám ban đầu: ${JSON.stringify(r.slice(0, 4))}`);
});
console.log(results.filter(r => r.status === "FAIL").length, "FAIL tổng");
