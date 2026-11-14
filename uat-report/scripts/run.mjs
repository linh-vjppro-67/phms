import { uniq, results, closeBrowser, OUT } from "./uat-lib.mjs";
import { part1 } from "./part1.mjs";
import { part2 } from "./part2.mjs";
import { part3 } from "./part3.mjs";
import { part4 } from "./part4.mjs";
import { part5 } from "./part5.mjs";
import { part6 } from "./part6.mjs";
const only = process.argv[2];
const S = { U: uniq() };
console.log("UAT staging – run id", S.U);
const parts = { 1: part1, 2: part2, 3: part3, 4: part4 };
try {
  await part1(S);
  if (!only || only >= 2) await part2(S);
  if (!only || only >= 3) await part3(S);
  if (!only || only >= 4) await part4(S);
  await part5(S);
  await part6(S);   // kiểm tra nhất quán dữ liệu TOÀN CSDL – chạy sau cùng
} finally { await closeBrowser(); }
const c = (s) => results.filter((r) => r.status === s).length;
console.log(`\nTỔNG ${results.length}: PASS ${c("PASS")} · FAIL ${c("FAIL")} · BLOCKED ${c("BLOCKED")}`);
