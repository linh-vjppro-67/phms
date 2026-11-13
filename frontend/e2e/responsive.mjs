// E2E giao diện đáp ứng: điện thoại (390px) và máy tính bảng (820px) – không tràn ngang, menu thu gọn dùng được,
// hộp thoại/ngăn kéo/thông báo nằm trọn trong màn hình. Tự dựng dữ liệu qua API.
import { managedPerson, nav, start, startEncounter, uniq } from "./lib.mjs";

const T = await start("Giao diện đáp ứng (điện thoại / máy tính bảng)");
const U = uniq();
const P = await managedPerson(`Đáp Ứng ${U}`);
await startEncounter(P.id);
const VIEWS = { "điện thoại 390×844": { width: 390, height: 844 }, "máy tính bảng 820×1180": { width: 820, height: 1180 } };
const openMenu = async (page) => { if (!(await page.$(".side.open"))) await page.click(".menu-btn"); await page.waitForSelector(".side.open"); };
const closeMenu = async (page) => { await page.click(".side-bg.open", { position: { x: 380, y: 400 } }); await page.waitForFunction(() => !document.querySelector(".side.open")); };
const overflow = (page) => page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
const fits = async (page, sel, label) => {
  const r = await page.$eval(sel, (e) => { const b = e.getBoundingClientRect(); return { l: b.left, r: b.right, w: innerWidth, t: b.top, bt: b.bottom, h: innerHeight }; });
  if (r.l < -1 || r.r > r.w + 1) throw new Error(`${label} tràn ngang: ${Math.round(r.l)}..${Math.round(r.r)} / ${r.w}`);
};

for (const [vname, vp] of Object.entries(VIEWS)) {
  const mobile = vp.width < 980;
  for (const user of ["doctor1", "officer1", "manager1"]) {
    const page = await T.login(user, vp);
    await T.step(`${vname} · ${user}: mọi tab không tràn ngang`, async () => {
      if (mobile) await openMenu(page);
      const labels = await page.$$eval(".side .nav", (e) => e.map((x) => x.textContent.trim()));
      if (mobile) await closeMenu(page);
      for (let i = 0; i < labels.length; i++) {
        if (mobile) await openMenu(page);
        await (await page.$$(".side .nav"))[i].click(); await page.waitForTimeout(500);
        const o = await overflow(page);
        if (o.sw > o.iw + 2) throw new Error(`tab “${labels[i]}” tràn ngang (${o.sw} > ${o.iw})`);
        if (mobile && (await page.$(".side.open"))) throw new Error("menu phải tự đóng sau khi chọn tab");
      }
    });
    if (user === "doctor1") {
      await T.step(`${vname}: menu thu gọn mở/đóng; thanh trên không vỡ`, async () => {
        const open = !!(await page.$(".side.open"));
        if (open) throw new Error("menu không được mở sẵn");
        if (mobile) {
          await openMenu(page); await page.waitForTimeout(400); await fits(page, ".side", "menu");   // chờ hết hiệu ứng trượt
          await page.keyboard.press("Escape"); await page.waitForFunction(() => !document.querySelector(".side.open"));   // Esc đóng menu
          await openMenu(page); await closeMenu(page);                                                                     // bấm ra ngoài đóng menu
        }
        await fits(page, ".top", "thanh trên");
      });
      await T.step(`${vname}: thông báo, hộp thoại và ngăn kéo nằm trọn trong màn hình`, async () => {
        await page.click(".btn.bell"); await page.waitForSelector(".np"); await fits(page, ".np", "bảng thông báo"); await page.click(".btn.bell");
        await nav(page, "Khám chữa bệnh");
        await page.click(`tbody tr.click:has-text("${P.full_name}")`); await page.waitForSelector(".drawer"); await fits(page, ".drawer", "ngăn kéo lượt khám");
        const o = await overflow(page); if (o.sw > o.iw + 2) throw new Error("ngăn kéo gây tràn ngang");
        await page.click('.drawer button[role="tab"]:has-text("Đơn thuốc")'); await page.click('.drawer button:has-text("+ Kê đơn")'); await page.waitForSelector(".modal");
        await fits(page, ".modal", "hộp thoại kê đơn");
        const inside = await page.$eval(".modal > footer", (f) => { const b = f.getBoundingClientRect(); return b.bottom <= innerHeight + 1; });
        if (!inside) throw new Error("nút của hộp thoại bị đẩy ra ngoài màn hình");
        await page.keyboard.press("Escape"); await page.keyboard.press("Escape");
      });
      await T.step(`${vname}: bảng dữ liệu cuộn trong khung, không làm tràn trang`, async () => {
        await nav(page, "Khám chữa bệnh"); await page.click('.seg button:has-text("Tất cả")');
        const o = await overflow(page); if (o.sw > o.iw + 2) throw new Error("bảng làm tràn trang");
        await nav(page, "Bảng điều khiển"); await page.waitForSelector(".kpis");
        const cols = await page.$eval(".kpis", (e) => getComputedStyle(e).gridTemplateColumns.split(" ").length);
        if (vp.width < 560 && cols > 2) throw new Error(`thẻ số liệu trên điện thoại phải ≤2 cột (có ${cols})`);
      });
    }
    await page.context().close();
  }
}
process.exit((await T.done()).length ? 1 : 0);
