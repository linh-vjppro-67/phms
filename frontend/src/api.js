const KEY = "phms_token";
export const getToken = () => sessionStorage.getItem(KEY);
export const setToken = (t) => (t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY));

export class ApiError extends Error {
  constructor(status, data) {
    super(data?.message || `Lỗi ${status}`);
    this.status = status;
    this.data = data || {};
  }
}

async function send(path, opt) {
  const t = getToken();
  opt.headers = { ...(opt.headers || {}) };
  if (t) opt.headers.Authorization = `Bearer ${t}`;
  const r = await fetch(`/api${path}`, opt);
  if (!r.ok) {
    let err;
    try { err = (await r.json()).error; } catch { /* body không phải JSON */ }
    // chỉ coi là hết phiên khi token không hợp lệ; 401 do sai mật khẩu cũ/mã OTP là lỗi nhập liệu bình thường
    if (r.status === 401 && ["UNAUTHENTICATED", "INVALID_TOKEN"].includes(err?.code)) window.dispatchEvent(new Event("phms-unauthorized"));
    throw new ApiError(r.status, err);
  }
  return r;
}

// API tạo bản ghi: luôn gửi Idempotency-Key (BR-06) để bấm lặp/thử lại không tạo bản ghi trùng
const CREATE = /^\/(persons|encounters|appointments|emergency-events|person-merges)$|^\/persons\/[^/]+\/(stays|allergies|problems|care-plans)$|^\/encounters\/[^/]+\/(observations|diagnoses|orders|medication-orders|referrals|addenda)$|^\/medication-orders\/[^/]+\/(dispenses|administrations)$/;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

export async function api(method, path, body, headers = {}) {
  const opt = { method, headers: { ...headers } };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const safeRetry = method === "POST" && CREATE.test(path.split("?")[0]);
  if (safeRetry && !opt.headers["Idempotency-Key"]) opt.headers["Idempotency-Key"] = crypto.randomUUID();
  let r;
  for (let attempt = 0; ; attempt++) {
    try { r = await send(path, opt); break; }
    catch (e) {
      const transient = !(e instanceof ApiError) || e.status === 503;     // mất mạng / máy chủ bận: thử lại CÙNG khóa -> không tạo trùng
      if (!safeRetry || !transient || attempt >= 2) throw e;
      await wait(600 * (attempt + 1));
    }
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

/** Upload multipart (tài liệu y tế). */
export async function upload(path, fields, file) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => v && fd.append(k, v));
  fd.append("file", file);
  return (await send(path, { method: "POST", body: fd })).json();
}

/** Tải tệp có Authorization -> lưu xuống máy. */
export async function download(path, filename) {
  const r = await send(path, { method: "GET" });
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const qs = (o) => {
  const p = new URLSearchParams();
  Object.entries(o).forEach(([k, v]) => v !== undefined && v !== "" && v !== null && v !== false && p.set(k, v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
export const idem = () => ({ "Idempotency-Key": crypto.randomUUID() });
