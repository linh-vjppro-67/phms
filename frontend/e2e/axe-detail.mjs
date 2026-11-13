// Công cụ chẩn đoán: liệt kê chi tiết vi phạm axe (cặp màu tương phản, phần tử thiếu nhãn) trên mọi tab của một số vai trò.
// Chạy: BASE=http://localhost:8000 node e2e/axe-detail.mjs [vai_trò…]
import fs from "node:fs";
import { createRequire } from "node:module";
import { nav, start } from "./lib.mjs";

const require = createRequire(import.meta.url);
const AXE = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const T = await start("axe – chi tiết vi phạm");
const roles = process.argv.slice(2).length ? process.argv.slice(2) : ["doctor1", "officer1", "manager1", "admin", "pharm1"];
const contrast = new Map(), other = new Map();

const scan = async (page, where) => {
  await page.evaluate(AXE);
  const r = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } })).violations
    .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => ({ t: n.target.join(" ").slice(0, 100), d: n.any[0]?.data, html: n.html.slice(0, 130) })) })));
  for (const v of r) for (const n of v.nodes) {
    if (v.id === "color-contrast") { const k = `${n.d?.fgColor} trên ${n.d?.bgColor} (${n.d?.contrastRatio}, cỡ ${n.d?.fontSize})`; if (!contrast.has(k)) contrast.set(k, `${where} :: ${n.t}`); }
    else { const k = `${v.id}[${v.impact}] ${n.html}`; if (!other.has(k)) other.set(k, where); }
  }
};

for (const role of roles) {
  const page = await T.login(role);
  if (process.env.THEME) await page.evaluate((t) => { document.documentElement.dataset.theme = t; }, process.env.THEME);
  const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
  for (let i = 0; i < labels.length; i++) { await (await page.$$(".side .nav"))[i].click(); await page.waitForTimeout(500); await scan(page, `${role} › ${labels[i].slice(0, 18)}`); }
  await page.context().close();
}
console.log("--- TƯƠNG PHẢN MÀU"); for (const [k, v] of contrast) console.log(k, "\n     ", v);
console.log("--- KHÁC"); for (const [k, v] of other) console.log(k, "\n     ", v);
await T.done();
