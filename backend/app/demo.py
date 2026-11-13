"""Dữ liệu demo HƯ CẤU nhưng đi đúng luồng nghiệp vụ, để test tính năng.

Mọi bản ghi được tạo qua chính API của hệ thống (đúng phân quyền, đúng máy trạng thái, có audit), không ghi thẳng DB,
nên các quy tắc (cảnh báo dị ứng, cấp phát ≤ số kê, bàn giao cần tóm tắt, …) đều được áp dụng như thật.
Tên, mã phạm nhân, quyết định, bệnh viện... đều là giả lập.

Chạy:  python -m app.seed && python -m app.demo          (DB đang có hồ sơ thì từ chối)
       python -m app.demo --reset                         (XÓA toàn bộ dữ liệu rồi tạo lại)
"""
import argparse
import random
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .db import Base, SessionLocal, engine
from .migrate import ensure_schema
from .main import app
from .models import (Alert, Appointment, AuditEvent, CustodyStay, EmergencyEvent, Encounter, Handover,
                     MedicalDocument, MedicationOrder, Person, Referral)
from .seed import DEFAULT_PASSWORD, seed


# ------------------------------------------------------------------ tiện ích
def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ago(days: float = 0, hours: float = 0, minutes: float = 0) -> str:
    return (now() - timedelta(days=days, hours=hours, minutes=minutes)).replace(microsecond=0).isoformat()


def dstr(delta_days: int = 0) -> str:
    return str(date.today() + timedelta(days=delta_days))


def make_pdf(lines: list[str]) -> bytes:
    """PDF 1 trang hợp lệ (font Helvetica nên bỏ dấu tiếng Việt trong nội dung tệp)."""
    def plain(s: str) -> str:
        s = unicodedata.normalize("NFD", s.replace("Đ", "D").replace("đ", "d"))
        return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

    def esc(s: str) -> str:
        return plain(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "BT /F1 12 Tf 50 790 Td 18 TL\n" + "".join(f"({esc(x)}) Tj T*\n" for x in lines) + "ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()


HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh", "Trương"]
DEM_NAM = ["Văn", "Hữu", "Minh", "Quốc", "Đình", "Thanh", "Công", "Xuân", "Ngọc", "Đức", "Anh", "Trọng"]
TEN_NAM = ["An", "Bình", "Cường", "Dũng", "Đạt", "Hải", "Hùng", "Khánh", "Long", "Nam", "Phong", "Quân", "Sơn", "Thắng", "Tuấn", "Việt",
           "Trung", "Hiếu", "Lộc", "Tâm", "Kiên", "Thành", "Huy", "Toàn", "Phúc", "Vinh", "Đông", "Tài", "Hoà", "Bảo", "Lâm", "Nghĩa"]
DEM_NU = ["Thị", "Ngọc", "Thu", "Kim", "Hồng"]
TEN_NU = ["Hoa", "Lan", "Mai", "Nhung", "Thủy", "Hạnh", "Yến", "Linh", "Trang", "Loan"]

# Hồ sơ chỉ số sinh hiệu theo tình trạng bệnh (min, max)
PROF = {
    "normal": dict(sys=(104, 124), dia=(64, 80), pulse=(60, 82), temp=(36.4, 36.9), spo2=(97, 99), weight=(52, 74)),
    "htn": dict(sys=(142, 168), dia=(90, 102), pulse=(72, 92), temp=(36.5, 37.0), spo2=(96, 99), weight=(64, 86)),
    "htn_ok": dict(sys=(122, 136), dia=(78, 86), pulse=(66, 82), temp=(36.5, 37.0), spo2=(97, 99), weight=(64, 86)),
    "dm": dict(sys=(120, 138), dia=(76, 88), pulse=(68, 88), temp=(36.5, 37.0), spo2=(96, 99), weight=(60, 82), glu=(9.0, 14.5)),
    "dm_ok": dict(sys=(116, 132), dia=(72, 84), pulse=(66, 84), temp=(36.5, 37.0), spo2=(97, 99), weight=(60, 82), glu=(5.8, 7.8)),
    "tb": dict(sys=(98, 116), dia=(60, 74), pulse=(86, 106), temp=(37.5, 38.4), spo2=(92, 96), weight=(44, 54)),
    "fever": dict(sys=(108, 128), dia=(66, 80), pulse=(94, 114), temp=(38.3, 39.4), spo2=(95, 98), weight=(52, 74)),
}


class Demo:
    def __init__(self) -> None:
        self.c = TestClient(app)
        self.tok: dict[str, str] = {}
        self.uid: dict[str, str] = {}
        self.r = random.Random(2026)
        self.n = 0
        self.used: set[str] = set()
        self.wt: dict[str, float] = {}
        self.prof: dict[str, str] = {}
        self.f = {x["code"]: x["id"] for x in self.get("admin", "/api/facilities")}

    # ---- http
    def h(self, u: str) -> dict:
        if u not in self.tok:
            r = self.c.post("/api/auth/login", json={"username": u, "password": DEFAULT_PASSWORD})
            assert r.status_code == 200, (u, r.text)
            self.tok[u], self.uid[u] = r.json()["access_token"], r.json()["user"]["id"]
        return {"Authorization": f"Bearer {self.tok[u]}"}

    def call(self, m: str, u: str, p: str, j=None, headers=None, **kw):
        r = self.c.request(m, p, json=j, headers={**self.h(u), **(headers or {})}, **kw)
        if r.status_code >= 300:
            raise RuntimeError(f"{m} {p} [{u}] -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content and "json" in r.headers.get("content-type", "") else r.content

    def get(self, u, p, **kw): return self.call("GET", u, p, **kw)
    def post(self, u, p, j=None, **kw): return self.call("POST", u, p, j, **kw)
    def patch(self, u, p, j=None, **kw): return self.call("PATCH", u, p, j, **kw)
    def put(self, u, p, j=None, **kw): return self.call("PUT", u, p, j, **kw)

    # ---- nhân thân
    def name(self, female=False) -> str:
        while True:
            n = f"{self.r.choice(HO)} {self.r.choice(DEM_NU if female else DEM_NAM)} {self.r.choice(TEN_NU if female else TEN_NAM)}"
            if n not in self.used:
                self.used.add(n)
                return n

    def person(self, officer="officer1", female=False, code=True, stay=True, dob=None, name=None, since=None, prof="normal") -> dict:
        self.n += 1
        body = {"full_name": name or self.name(female), "gender": "Nữ" if female else "Nam",
                "date_of_birth": dob or str(date(self.r.randint(1962, 2003), self.r.randint(1, 12), self.r.randint(1, 28)))}
        if code:
            body.update(source_system="QLPN", external_id=f"PN-26-{self.n:04d}")
        body["confirm_distinct"] = True      # kịch bản demo chủ động tạo cặp nghi trùng
        p = self.post(officer, "/api/persons", body)
        if stay:
            st = self.post(officer, f"/api/persons/{p['id']}/stays", {
                "start_date": str(date.today() - timedelta(days=since if since is not None else self.r.randint(3, 30))),
                "source_ref": f"QĐ {self.r.randint(100, 999)}/TG-{date.today().year}"})
            p["stay"] = st
        self.prof[p["id"]] = prof
        return p

    # ---- lâm sàng
    def vitals(self, nurse, enc_id, pid, prof, when, only=None):
        p = PROF[prof]
        base_w = self.wt.setdefault(pid, self.r.uniform(*p["weight"]))
        items = [("Mạch", "pulse", "lần/phút", 0), ("Huyết áp tâm thu", "sys", "mmHg", 0), ("Huyết áp tâm trương", "dia", "mmHg", 0),
                 ("Nhiệt độ", "temp", "°C", 1), ("SpO2", "spo2", "%", 0)]
        if "glu" in p:
            items.append(("Đường huyết", "glu", "mmol/L", 1))
        for t, k, u, dec in items:
            if only and t not in only:
                continue
            self.post(nurse, f"/api/encounters/{enc_id}/observations", {"type": t, "value": f"{self.r.uniform(*p[k]):.{dec}f}", "unit": u, "occurred_at": when})
        if not only:
            self.post(nurse, f"/api/encounters/{enc_id}/observations", {"type": "Cân nặng", "value": f"{base_w + self.r.uniform(-1, 1):.1f}", "unit": "kg", "occurred_at": when})

    def enc(self, doc, pid, typ, reason, when=None, start=True, **extra):
        e = self.post(doc, "/api/encounters", {"person_id": pid, "type": typ, "reason": reason, "occurred_at": when or ago(), **extra})
        if start:
            self.post(doc, f"/api/encounters/{e['id']}/transition", {"to": "in_progress"})
        return e

    def dx(self, doc, eid, code, text, kind="final"):
        return self.post(doc, f"/api/encounters/{eid}/diagnoses", {"code": code, "text": text, "kind": kind})

    def done(self, doc, eid):
        return self.post(doc, f"/api/encounters/{eid}/transition", {"to": "completed"})

    def rx(self, doc, enc, code, name, dose, freq, days, qty, start=0, route="uống", strength=None, supervised=False,
           ack=None, confirm=True, note=None):
        o = self.post(doc, f"/api/encounters/{enc}/medication-orders", {
            "drug_code": code, "drug_name": name, "strength": strength, "dose": dose, "route": route, "frequency": freq,
            "start_date": dstr(-start), "duration_days": days, "quantity_prescribed": qty, "supervised": supervised, "instructions": note})
        if confirm:
            o = self.post(doc, f"/api/medication-orders/{o['id']}/confirm", {"acknowledge_warnings": True, "ack_note": ack} if o["warnings"] else {})
        return o

    def dispense_course(self, user, o, elapsed, per=30):
        given, t = 0, elapsed
        while t >= 0 and given < o["quantity_prescribed"]:
            q = min(per, o["quantity_prescribed"] - given)
            self.post(user, f"/api/medication-orders/{o['id']}/dispenses", {"quantity": q, "occurred_at": ago(t)})
            given, t = given + q, t - 30
        return given

    def administer(self, nurse, o, days=6):
        for t in range(days, 0, -1):
            miss = t == 3
            self.post(nurse, f"/api/medication-orders/{o['id']}/administrations", {
                "administered": not miss, "occurred_at": ago(t, hours=-0), **({"reason": "Từ chối uống thuốc, đã giáo dục và theo dõi"} if miss else {})})

    def initial_exam(self, p, days, prof, allergy=None, dxs=(), rxs=(), summary=None, complete=True, doc="doctor1", nurse="nurse1", only_vitals=False):
        when = ago(days)
        e = self.enc(doc, p["id"], "initial", "Khám sức khỏe ban đầu khi tiếp nhận", when)
        if allergy:
            for sub, rea, sev in allergy:
                self.post(nurse, f"/api/persons/{p['id']}/allergies", {"substance": sub, "reaction": rea, "severity": sev, "confirmed": True, "source": "Khai báo khi tiếp nhận"})
        elif not only_vitals:
            self.post(doc, f"/api/persons/{p['id']}/allergy-status/none-confirmed")
        self.vitals(nurse, e["id"], p["id"], prof, when)
        if only_vitals:
            return e, []
        for code, text in dxs:
            self.dx(doc, e["id"], code, text)
        if summary:
            self.patch(doc, f"/api/encounters/{e['id']}", {"summary": summary})
        orders = [self.rx(doc, e["id"], **r) for r in rxs]
        if complete:
            self.done(doc, e["id"])
        return e, orders

    def problem_plan(self, doc, p, name, code, goals, measures, interval, elapsed, since, nurse="nurse1"):
        prob = self.post(doc, f"/api/persons/{p['id']}/problems", {"name": name, "code": code, "effective_from": dstr(-since)})
        cp = self.post(doc, f"/api/persons/{p['id']}/care-plans", {
            "problem_id": prob["id"], "goals": goals, "measures": [{"name": a, "unit": b} for a, b in measures],
            "review_interval_days": interval, "start_date": dstr(-elapsed), "responsible_user_id": self.uid.get(nurse) or (self.h(nurse) and self.uid[nurse])})
        return prob, cp

    def follow_up(self, doc, nurse, p, days_ago, prof, reason="Tái khám theo kế hoạch theo dõi bệnh mạn tính", extra=None):
        when = ago(days_ago)
        e = self.enc(doc, p["id"], "periodic", reason, when)
        self.vitals(nurse, e["id"], p["id"], prof, when)
        if extra:
            extra(e)
        self.done(doc, e["id"])
        return e

    def document(self, user, pid, doc_type, lines, filename, source, referral_id=None, encounter_id=None, issued=None):
        r = self.c.post("/api/documents", headers=self.h(user), data={k: v for k, v in {
            "doc_type": doc_type, "person_id": pid, "referral_id": referral_id, "encounter_id": encounter_id, "source": source, "issued_date": issued or dstr()}.items() if v},
            files={"file": (filename, make_pdf(lines), "application/pdf")})
        assert r.status_code == 201, r.text
        return r.json()

    def referral(self, doc, enc, person, urgency, reason, dest, upto, result=None, plan=None, left_days=2, appr="approver1", nurse="nurse1"):
        order = ["draft", "pending", "coordinated", "in_external_treatment", "result_received", "completed"]
        r = self.post(doc, f"/api/encounters/{enc}/referrals", {"urgency": urgency, "reason": reason, "destination": dest})
        rid = r["id"]
        st = lambda u, **b: self.patch(u, f"/api/referrals/{rid}/status", b)  # noqa: E731
        if upto == "cancelled":
            st(doc, to="pending"); return st(doc, to="cancelled", note=plan or "Bệnh nhân ổn định, không còn chỉ định chuyển viện")
        i = order.index(upto)
        if urgency == "emergency" and i == 3:  # cấp cứu: đi tắt, không chờ duyệt -> bắt buộc hậu kiểm
            st(nurse, to="in_external_treatment", left_at=ago(left_days), note="Chuyển viện cấp cứu, xe ưu tiên – hồ sơ bổ sung sau")
            self.document(nurse, person, "referral_letter", ["GIAY CHUYEN VIEN CAP CUU", f"Co so tiep nhan: {dest}", f"Ly do: {reason}"],
                          "giay_chuyen_vien_cap_cuu.pdf", "Bộ phận Y tế trại giam", referral_id=rid)
            return r
        if i >= 1: st(doc, to="pending")
        if i >= 2: st(appr, to="coordinated", note="Đã liên hệ bệnh viện, bố trí xe và quản giáo áp giải", destination=dest)
        if i >= 3:
            st(nurse, to="in_external_treatment", left_at=ago(left_days), note="Bàn giao hồ sơ, thuốc đang dùng cho đoàn áp giải")
            self.document(nurse, person, "referral_letter", ["GIAY CHUYEN VIEN", f"Co so tiep nhan: {dest}", f"Ly do: {reason}", "Giam thi trai giam - Bo phan Y te"],
                          "giay_chuyen_vien.pdf", "Bộ phận Y tế trại giam", referral_id=rid)
        if i >= 4:
            self.document(nurse, person, "discharge_summary", ["GIAY RA VIEN", f"Don vi: {dest}", result or "Dieu tri on dinh", "Tai kham theo hen"],
                          "giay_ra_vien.pdf", dest, referral_id=rid)
            st(nurse, to="result_received", result_note=result or "Điều trị ổn định, ra viện theo hẹn")
        if i >= 5:
            st(doc, to="completed", post_referral_plan=plan or "Tái khám sau 7 ngày, tiếp tục thuốc theo đơn bệnh viện", outcome="returned")
        return r

    def round(self, mgr, doc, nurse, name, due, complete_n, postpone_n=0, notdone_n=0, lock=False, days_range=(1, 10)):
        rd = self.post(mgr, "/api/checkup-rounds", {"name": name, "due_date": dstr(due)})
        received = {s["person_id"] for s in self.get(nurse, "/api/stays?status=received")}
        tasks = self.get(nurse, f"/api/appointments?round_id={rd['id']}&limit=500")
        self.r.shuffle(tasks)
        done = 0
        for t in tasks:
            if t["person_id"] in received:
                self.post(nurse, f"/api/appointments/{t['id']}/status", {"to": "postponed", "reason": "Chưa hoàn tất khám ban đầu – khám định kỳ sau", "new_due_date": dstr(7)})
            elif done < complete_n:
                when = ago(self.r.randint(*days_range), hours=self.r.randint(0, 5))
                e = self.enc(doc, t["person_id"], "periodic", f"Khám định kỳ – {name}", when, appointment_id=t["id"])
                self.vitals(nurse, e["id"], t["person_id"], self.prof.get(t["person_id"], "normal"), when)
                self.done(doc, e["id"]); done += 1
            elif postpone_n > 0:
                postpone_n -= 1
                self.post(nurse, f"/api/appointments/{t['id']}/status", {"to": "postponed", "reason": "Đang lao động ngoài trại, hẹn lại", "new_due_date": dstr(5)})
            elif notdone_n > 0:
                notdone_n -= 1
                self.post(nurse, f"/api/appointments/{t['id']}/status", {"to": "not_done", "reason": "Người bệnh từ chối khám, đã lập biên bản"})
        if lock:
            self.post(mgr, f"/api/checkup-rounds/{rd['id']}/lock")
        return rd

    def handover(self, officer, nurse, stay_id, kind, reason, to=None, summary=None, confirm=False):
        h = self.post(officer, f"/api/stays/{stay_id}/handover", {"kind": kind, "reason": reason, **({"to_facility_id": to} if to else {})})
        if summary:
            self.put(nurse, f"/api/handovers/{h['id']}/summary", {"summary": summary})
        if confirm:
            self.post(officer, f"/api/handovers/{h['id']}/confirm", {"acknowledge_open_items": True, "receiver_name": "Cán bộ tiếp nhận trại nhận"})
        return h


def run(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    ensure_schema(engine)
    with SessionLocal() as s:
        seed(s)
        if s.scalar(select(func.count()).select_from(Person)):
            sys.exit("DB đã có hồ sơ. Dùng --reset nếu muốn XÓA hết và tạo lại dữ liệu demo.")
    D = Demo()
    f1, f2 = D.f["F01"], D.f["F02"]
    print("• Trại 1: nhóm bệnh mạn tính…")

    # ============ F01: tăng huyết áp (5) ============
    htn: list[dict] = []
    htn_orders: list[list[dict]] = []
    for i in range(5):
        days = D.r.randint(70, 160)
        p = D.person(since=days + 1, prof="htn")
        allergy = [("Aspirin", "Khó thở, co thắt phế quản", "Nặng")] if i == 0 else None
        drugs = [dict(code="AMLO5", name="Amlodipine 5mg", dose="1 viên", freq="1 lần/ngày", days=days + 60, qty=days + 60, start=days, supervised=True, strength="5mg", note="Uống buổi sáng")]
        if i in (1, 3):
            drugs.append(dict(code="LOSA50", name="Losartan 50mg", dose="1 viên", freq="1 lần/ngày", days=days + 60, qty=days + 60, start=days, supervised=True, strength="50mg"))
        e, orders = D.initial_exam(p, days, "htn", allergy, [("I10", "Tăng huyết áp vô căn")], drugs,
                                   summary="Tăng huyết áp độ 2, chưa điều trị trước khi vào trại. Khởi trị, hẹn tái khám theo kế hoạch.")
        for o in orders:
            D.dispense_course("pharm1", o, days)
        D.administer("nurse1", orders[0])
        interval = 14 if i % 2 == 0 else 30
        elapsed = interval + 9 if i in (1, 4) else D.r.randint(3, interval - 3)  # i=1,4: lịch theo dõi đã quá hạn
        D.problem_plan("doctor1", p, "Tăng huyết áp vô căn", "I10", "Huyết áp < 140/90 mmHg",
                       [("Huyết áp tâm thu", "mmHg"), ("Huyết áp tâm trương", "mmHg")], interval, elapsed, days - 1)
        for k, pf in ((interval + 8, "htn"), (interval - 2, "htn_ok")):
            if days > k + 5:
                D.follow_up("doctor1", "nurse1", p, min(days - 5, k + interval), pf)
        D.prof[p["id"]] = "htn_ok"
        htn.append(p)
        htn_orders.append(orders)

    # ============ F01: đái tháo đường (3) ============
    dm: list[dict] = []
    for i in range(3):
        days = D.r.randint(60, 140)
        p = D.person(since=days + 1, prof="dm")
        allergy = [("Sulfonamide", "Mề đay", "Trung bình")] if i == 0 else None
        e, orders = D.initial_exam(p, days, "dm", allergy, [("E11", "Đái tháo đường típ 2")], [
            dict(code="MET850", name="Metformin 850mg", dose="1 viên", freq="2 lần/ngày", days=(days + 2) if i == 2 else days + 60,
                 qty=2 * ((days + 2) if i == 2 else days + 60), start=days, strength="850mg", note="Uống sau ăn"),   # i==2: sắp hết liệu trình
        ] + ([dict(code="GLIC30", name="Gliclazide 30mg", dose="1 viên", freq="1 lần/ngày", days=days + 60, qty=days + 60, start=days, strength="30mg")] if i == 1 else []),
            summary="Đường huyết đói cao, HbA1c 8.9%. Khởi trị metformin, tư vấn chế độ ăn.")
        for o in orders:
            D.dispense_course("pharm1", o, days, per=60 if o["drug_name"].startswith("Metformin") else 30)
        interval = 30
        D.problem_plan("doctor1", p, "Đái tháo đường típ 2", "E11", "HbA1c < 7%, đường huyết đói 4.4–7.2 mmol/L",
                       [("Đường huyết", "mmol/L"), ("Cân nặng", "kg")], interval, 40 if i == 2 else D.r.randint(5, 25), days - 1)
        if days > 45:
            D.follow_up("doctor1", "nurse1", p, 30 + D.r.randint(0, 8), "dm_ok")
        D.prof[p["id"]] = "dm_ok"
        dm.append(p)

    # ============ F01: lao phổi (2) – điều trị có giám sát ============
    tb: list[dict] = []
    for i in range(2):
        days = 75 + i * 20
        p = D.person(since=days + 1, prof="tb")
        e = D.enc("doctor1", p["id"], "initial", "Khám sức khỏe ban đầu khi tiếp nhận", ago(days))
        D.post("doctor1", f"/api/persons/{p['id']}/allergy-status/none-confirmed")
        D.vitals("nurse1", e["id"], p["id"], "tb", ago(days))
        D.dx("doctor1", e["id"], "R50", "Sốt kéo dài, ho ra máu, sụt cân", "preliminary")
        for desc in ("X-quang phổi thẳng", "Xét nghiệm đờm tìm AFB (3 mẫu)"):
            o = D.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": desc})
            D.post("nurse1", f"/api/orders/{o['id']}/result", {"result_text": "Hình ảnh tổn thương thâm nhiễm đỉnh phổi phải, hang nhỏ" if "X-quang" in desc else "AFB (+++) cả 3 mẫu"})
        D.dx("doctor1", e["id"], "A15", "Lao phổi AFB dương tính", "final")
        ords = [D.rx("doctor1", e["id"], code=c, name=n, dose=dz, freq="1 lần/ngày", days=180, qty=180, start=days - 3, supervised=True, strength=s, note="Uống lúc đói, có giám sát trực tiếp")
                for c, n, dz, s in (("RIFA150", "Rifampicin 150mg", "3 viên", "150mg"), ("INH100", "Isoniazid 100mg", "3 viên", "100mg"))]
        D.done("doctor1", e["id"])
        for o in ords:
            D.dispense_course("pharm1", o, days - 3, per=30)
            D.administer("nurse1", o)
        D.problem_plan("doctor1", p, "Lao phổi", "A15", "Hoàn thành phác đồ 6 tháng, AFB âm tính tháng thứ 2 và 5",
                       [("Cân nặng", "kg"), ("Nhiệt độ", "°C")], 14, 22 if i == 1 else D.r.randint(3, 10), days - 3)
        D.prof[p["id"]] = "tb"
        tb.append(p)

    # ============ F01: khỏe mạnh (4) + dị ứng amoxicillin (1) ============
    print("• Trại 1: khám ban đầu, chờ khám, chờ đối soát…")
    healthy = []
    for i in range(4):
        days = D.r.randint(20, 90)
        p = D.person(since=days + 1)
        D.initial_exam(p, days, "normal", [("Amoxicillin", "Phát ban toàn thân", "Trung bình")] if i == 0 else None,
                       [("Z00", "Khám sức khỏe tổng quát – bình thường")], summary="Sức khỏe bình thường, không phát hiện bất thường.")
        healthy.append(p)
    pen = healthy[0]
    # chờ khám ban đầu (5), đang khám dở (2), chờ đối soát (3)
    waiting = [D.person(since=D.r.randint(0, 3)) for _ in range(5)]
    wip_draft = D.person(since=1)
    D.enc("doctor1", wip_draft["id"], "initial", "Khám sức khỏe ban đầu khi tiếp nhận", start=False)
    wip = D.person(since=1)
    e = D.enc("doctor1", wip["id"], "initial", "Khám sức khỏe ban đầu khi tiếp nhận", ago(hours=2))
    D.vitals("nurse1", e["id"], wip["id"], "normal", ago(hours=2))
    dup1 = D.person(name="Lê Minh Tuấn", dob="1990-02-02", since=4)
    dup2 = D.person(name="Lê Minh Tuấn", dob="1990-02-02", since=1)           # nghi trùng -> chờ đối soát, KHÔNG tự gộp
    nocode = D.person(code=False, since=1)                                       # thiếu mã nguồn -> chờ đối soát
    D.person(stay=False)                                                         # hồ sơ mới đăng ký, chưa có đợt tiếp nhận
    # hồ sơ nhập trùng (không mã) + hồ sơ chính thức -> đã có ĐỀ NGHỊ GỘP chờ người điều phối duyệt (BR-01, bốn mắt)
    keep = D.person(name="Phạm Quốc Khánh", dob="1985-09-09", since=6)
    ghost = D.person(name="Phạm Quốc Khánh", dob="1985-09-09", code=False, stay=False)
    D.post("officer1", "/api/person-merges", {"source_id": ghost["id"], "target_id": keep["id"],
                                              "reason": "Cùng họ tên, ngày sinh; hồ sơ không mã nhập lúc tiếp nhận, trùng với hồ sơ đã có mã PN."})

    # ============ Đợt khám định kỳ Quý 3 (đã khóa) ============
    print("• Đợt khám định kỳ Quý 3 (đã khóa), Quý 4…")
    D.round("manager1", "doctor1", "nurse1", "Khám sức khỏe định kỳ Quý 3/2026", -15, complete_n=11, postpone_n=2, notdone_n=2, lock=True)

    # ============ Khám phát sinh ============
    print("• Khám phát sinh, thuốc, cấp phát…")
    pool = [D.person(since=D.r.randint(15, 60)) for _ in range(6)]
    for p in pool:
        D.initial_exam(p, D.r.randint(10, 14), "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")])
    a_pen, a_gas, a_back, a_fever, a_diar, a_cet = pool

    # (a) viêm họng + dị ứng Amoxicillin: có cảnh báo, bác sĩ ghi nhận xử lý, cấp một phần
    e = D.enc("doctor1", pen["id"], "ad_hoc", "Đau họng, sốt nhẹ 2 ngày", ago(hours=5))
    D.vitals("nurse1", e["id"], pen["id"], "fever", ago(hours=5))
    D.dx("doctor1", e["id"], "J06", "Nhiễm khuẩn hô hấp trên cấp")
    o = D.rx("doctor1", e["id"], code="AMOX500", name="Amoxicillin 500mg", dose="1 viên", freq="3 lần/ngày", days=7, qty=21, strength="500mg",
             ack="Cân nhắc lợi ích/nguy cơ: phản ứng cũ nhẹ, theo dõi sát 24h đầu, sẵn sàng thuốc cấp cứu dị ứng")
    D.dispense_course("pharm1", o, 0, per=9)
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_treatment"})
    # (b) viêm dạ dày: thuốc đã xác nhận, chưa cấp (hàng đợi cấp phát)
    e = D.enc("doctor1", a_gas["id"], "ad_hoc", "Đau thượng vị sau ăn, ợ chua 1 tuần", ago(hours=3))
    D.dx("doctor1", e["id"], "K29", "Viêm dạ dày")
    D.rx("doctor1", e["id"], code="OMEP20", name="Omeprazole 20mg", dose="1 viên", freq="1 lần/ngày", days=14, qty=14, strength="20mg", note="Uống trước ăn sáng 30 phút")
    D.done("doctor1", e["id"])
    # (c) đau lưng: đơn nháp chờ bác sĩ xác nhận
    e = D.enc("doctor1", a_back["id"], "ad_hoc", "Đau lưng sau lao động nặng", ago(hours=1))
    D.dx("doctor1", e["id"], "M54", "Đau lưng cơ học", "preliminary")
    D.rx("doctor1", e["id"], code="IBU400", name="Ibuprofen 400mg", dose="1 viên", freq="2 lần/ngày", days=5, qty=10, strength="400mg", confirm=False, note="Uống sau ăn")
    # (d) sốt: chờ kết quả xét nghiệm
    e = D.enc("doctor1", a_fever["id"], "ad_hoc", "Sốt cao 3 ngày, đau đầu, ớn lạnh", ago(hours=4))
    D.vitals("nurse1", e["id"], a_fever["id"], "fever", ago(hours=4))
    D.dx("doctor1", e["id"], "R50", "Sốt chưa rõ nguyên nhân", "preliminary")
    D.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Công thức máu"})
    D.post("doctor1", f"/api/encounters/{e['id']}/orders", {"kind": "lab", "description": "Xét nghiệm ký sinh trùng sốt rét"})
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "awaiting_results"})
    # (e) tiêu chảy: cấp đủ, giám sát uống thuốc
    e = D.enc("doctor1", a_diar["id"], "ad_hoc", "Tiêu chảy 4 lần/ngày, đau quặn bụng", ago(days=6))
    D.dx("doctor1", e["id"], "A09", "Tiêu chảy nhiễm khuẩn")
    o = D.rx("doctor1", e["id"], code="METRO250", name="Metronidazole 250mg", dose="2 viên", freq="3 lần/ngày", days=5, qty=30, start=6, strength="250mg", supervised=True)
    D.dispense_course("pharm1", o, 6, per=30)
    D.administer("nurse1", o, days=5)
    D.done("doctor1", e["id"])
    D.post("doctor1", f"/api/medication-orders/{o['id']}/stop", {"outcome": "completed", "reason": "Hoàn thành liệu trình 5 ngày, hết tiêu chảy"})
    # (f) trả thuốc một phần (hoàn trả có lý do) + lượt khám nhập nhầm bị hủy
    e = D.enc("doctor1", a_cet["id"], "ad_hoc", "Ngứa, nổi mề đay", ago(days=2))
    o = D.rx("doctor1", e["id"], code="CETI10", name="Cetirizine 10mg", dose="1 viên", freq="1 lần/ngày", days=10, qty=10, start=2, strength="10mg")
    d1 = D.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"quantity": 10, "occurred_at": ago(days=2)})
    D.post("pharm1", f"/api/medication-orders/{o['id']}/dispenses", {"kind": "return", "quantity": 4, "ref_dispense_id": d1["id"], "note": "Người nhận trả lại do hết triệu chứng"})
    D.post("doctor1", f"/api/medication-orders/{o['id']}/stop", {"outcome": "stopped", "reason": "Hết triệu chứng sau 2 ngày, ngừng thuốc"})
    D.done("doctor1", e["id"])
    # điều chỉnh liều đơn đã xác nhận = phiên bản mới (bản cũ bị thay thế, lịch sử vẫn giữ)
    e = D.enc("doctor1", htn[0]["id"], "periodic", "Tái khám: huyết áp chưa đạt mục tiêu sau 1 tháng điều trị", ago(days=2))
    D.vitals("nurse1", e["id"], htn[0]["id"], "htn", ago(days=2))
    v2 = D.post("doctor1", f"/api/medication-orders/{htn_orders[0][0]['id']}/revise", {"dose": "2 viên", "quantity_prescribed": 120, "encounter_id": e["id"], "reason": "Huyết áp chưa đạt mục tiêu, tăng liều Amlodipine"})
    D.post("doctor1", f"/api/medication-orders/{v2['id']}/confirm", {})
    D.done("doctor1", e["id"])
    e = D.enc("doctor1", a_back["id"], "ad_hoc", "Nhập nhầm người bệnh", ago(hours=6))
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "cancelled", "reason": "Nhập nhầm hồ sơ, đã tạo lượt khám đúng người"})

    # ============ Chuyển viện đủ các trạng thái ============
    print("• Chuyển viện…")
    ref_people = [D.person(since=D.r.randint(30, 80)) for _ in range(5)]
    for p in ref_people:
        D.initial_exam(p, D.r.randint(25, 29), "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")])
    r_app, r_cardio, r_eye, r_wait, r_pend = ref_people

    def ref_enc(p, reason):
        return D.enc("doctor1", p["id"], "ad_hoc", reason, ago(days=D.r.randint(1, 6)))

    e = ref_enc(r_app, "Đau hố chậu phải dữ dội, sốt, phản ứng thành bụng")
    D.dx("doctor1", e["id"], "K35", "Viêm ruột thừa cấp")
    D.referral("doctor1", e["id"], r_app["id"], "urgent", "Viêm ruột thừa cấp, chỉ định phẫu thuật", "Bệnh viện Đa khoa tỉnh", "completed", result="Đã phẫu thuật nội soi cắt ruột thừa, hậu phẫu ổn", plan="Cắt chỉ sau 7 ngày, kháng sinh theo đơn bệnh viện, tránh lao động nặng 2 tuần", left_days=9)
    D.done("doctor1", e["id"])
    e = ref_enc(tb[0], "Cần hội chẩn chuyên khoa lao đánh giá kháng thuốc")
    D.referral("doctor1", e["id"], tb[0]["id"], "routine", "Hội chẩn chuyên khoa lao, đánh giá kháng thuốc", "Bệnh viện Phổi tỉnh", "completed", result="Chưa ghi nhận kháng thuốc, tiếp tục phác đồ", plan="Tiếp tục phác đồ hiện tại, xét nghiệm đờm tháng thứ 2", left_days=12)
    D.done("doctor1", e["id"])
    e = ref_enc(htn[1], "Tăng huyết áp khó kiểm soát, cần siêu âm tim")
    D.referral("doctor1", e["id"], htn[1]["id"], "routine", "Đánh giá biến chứng tim do tăng huyết áp (siêu âm tim)", "Bệnh viện Tim mạch tỉnh", "in_external_treatment", left_days=1)
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_treatment"})
    e = ref_enc(dm[0], "Giảm thị lực mắt phải, đái tháo đường 5 năm")
    D.referral("doctor1", e["id"], dm[0]["id"], "routine", "Khám đáy mắt, tầm soát bệnh võng mạc đái tháo đường", "Bệnh viện Mắt tỉnh", "result_received", result="Bệnh võng mạc đái tháo đường không tăng sinh giai đoạn sớm", left_days=4)
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_treatment"})
    e = ref_enc(r_wait, "Đau khớp gối kéo dài, nghi thoái hóa")
    D.referral("doctor1", e["id"], r_wait["id"], "routine", "Chụp MRI khớp gối, khám cơ xương khớp", "Bệnh viện Chấn thương chỉnh hình", "coordinated")
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_treatment"})
    e = ref_enc(r_pend, "Nổi hạch cổ 2 tuần, không đau")
    D.referral("doctor1", e["id"], r_pend["id"], "urgent", "Hạch cổ nghi lao hạch/u, cần sinh thiết", "Bệnh viện Ung bướu tỉnh", "pending")
    D.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "in_treatment"})
    e = ref_enc(healthy[1], "Đau tai phải, nghi viêm tai giữa")
    D.referral("doctor1", e["id"], healthy[1]["id"], "routine", "Khám tai mũi họng chuyên khoa", "Bệnh viện Đa khoa tỉnh", "draft")
    e = ref_enc(healthy[2], "Đau ngực nhẹ khi gắng sức")
    D.referral("doctor1", e["id"], healthy[2]["id"], "routine", "Đo điện tim gắng sức", "Bệnh viện Tim mạch tỉnh", "cancelled", plan="Điện tim và men tim bình thường, không còn chỉ định chuyển viện")
    D.done("doctor1", e["id"])

    # ============ Cấp cứu ============
    print("• Cấp cứu…")
    # E1: cơn tăng huyết áp, đã hoàn thiện & đóng
    ev = D.post("nurse1", "/api/emergency-events", {"person_id": htn[2]["id"], "occurred_at": ago(minutes=10), "location": "Buồng 7, khu A", "reporter": "Quản giáo Trần Văn Thành", "description": "Đau đầu dữ dội, nôn, huyết áp tăng cao"})
    for act in ("Đo huyết áp 210/120 mmHg, mạch 108", "Cho nằm đầu cao, thở oxy 3 L/phút", "Dùng thuốc hạ áp theo y lệnh bác sĩ", "Theo dõi 30 phút: huyết áp 170/100, tỉnh táo"):
        D.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": act, "performer": "Điều dưỡng 1"})
    D.vitals("nurse1", ev["encounter_id"], htn[2]["id"], "htn", ago(minutes=8), only=["Mạch", "Huyết áp tâm thu", "Huyết áp tâm trương", "SpO2"])
    D.dx("doctor1", ev["encounter_id"], "I10", "Cơn tăng huyết áp", "final")
    D.done("doctor1", ev["encounter_id"])
    D.post("doctor1", f"/api/emergency-events/{ev['id']}/close", {"note": "Ổn định, tiếp tục theo dõi tại trại", "follow_up_date": dstr(2)})
    # E2: ghi muộn (mất điện), đã đóng
    ev = D.post("nurse1", "/api/emergency-events", {"person_id": healthy[3]["id"], "occurred_at": ago(hours=20), "late_entry_reason": "Mất điện khu B, ghi bổ sung sau khi có điện", "location": "Sân lao động", "description": "Ngất tại chỗ khi lao động"})
    D.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": "Cho nằm nghỉ, kê cao chân, uống nước đường", "occurred_at": ago(hours=20)})
    D.dx("doctor1", ev["encounter_id"], "R55", "Ngất do hạ đường huyết, mất nước", "final")
    D.done("doctor1", ev["encounter_id"])
    D.post("doctor1", f"/api/emergency-events/{ev['id']}/close", {"note": "Đã hoàn thiện hồ sơ sau sự cố mất điện"})
    # E3: chưa rõ danh tính -> đối soát -> đóng
    ev = D.post("nurse1", "/api/emergency-events", {"temp_identity": "Nam khoảng 40 tuổi, áo số 12, buồng 5", "occurred_at": ago(hours=6), "late_entry_reason": "Đang xử trí cấp cứu, nhập hồ sơ sau", "location": "Buồng 5, khu B", "reporter": "Quản giáo Lê Quốc Việt", "description": "Co giật toàn thân, tiền sử động kinh"})
    D.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": "Đặt tư thế an toàn, bảo vệ đường thở", "occurred_at": ago(hours=6)})
    D.dx("doctor1", ev["encounter_id"], "G40", "Cơn động kinh toàn thể", "final")
    D.done("doctor1", ev["encounter_id"])
    D.post("officer1", f"/api/persons/{ev['person_id']}/verify", {"full_name": D.name(), "date_of_birth": "1984-08-19", "source_system": "QLPN", "external_id": f"PN-26-{D.n + 100:04d}", "note": "Đối chiếu ảnh và hồ sơ giấy với quản giáo buồng"})
    D.post("doctor1", f"/api/emergency-events/{ev['id']}/close", {"note": "Đã đối soát danh tính, hồ sơ hoàn tất", "follow_up_date": dstr(7)})
    # E4: ĐANG MỞ, đau ngực -> chuyển viện cấp cứu đi tắt (chờ hậu kiểm)
    ev = D.post("nurse1", "/api/emergency-events", {"person_id": htn[4]["id"], "occurred_at": ago(minutes=25), "late_entry_reason": "Ưu tiên sơ cấp cứu, nhập sau", "location": "Buồng 3, khu A", "reporter": "Quản giáo Phạm Văn Hậu", "description": "Đau thắt ngực lan tay trái, vã mồ hôi"})
    for act in ("Cho nằm nghỉ, thở oxy, đo điện tim", "Ngậm nitroglycerin dưới lưỡi theo y lệnh", "Liên hệ bệnh viện, chuẩn bị chuyển viện"):
        D.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": act})
    D.vitals("nurse1", ev["encounter_id"], htn[4]["id"], "htn", ago(minutes=20), only=["Mạch", "Huyết áp tâm thu", "Huyết áp tâm trương", "SpO2"])
    D.dx("doctor1", ev["encounter_id"], "I20", "Đau thắt ngực không ổn định, nghi hội chứng vành cấp", "preliminary")
    D.referral("doctor1", ev["encounter_id"], htn[4]["id"], "emergency", "Nghi hội chứng vành cấp, cần can thiệp tim mạch khẩn", "Bệnh viện Tim mạch tỉnh", "in_external_treatment", left_days=0)
    # E5: ĐANG MỞ, chưa rõ danh tính
    ev = D.post("nurse1", "/api/emergency-events", {"temp_identity": "Nam khoảng 30 tuổi, xăm hình rồng cánh tay trái", "occurred_at": ago(minutes=5), "location": "Nhà ăn", "description": "Nghẹn, tím tái"})
    D.post("nurse1", f"/api/emergency-events/{ev['id']}/interventions", {"action": "Nghiệm pháp Heimlich, dị vật được đẩy ra"})

    # ============ Trại 2 ============
    print("• Trại 2…")
    f2_htn = D.person("officer2", since=90, prof="htn")
    e, orders = D.initial_exam(f2_htn, 85, "htn", [("Penicillin", "Sốc phản vệ", "Nặng")], [("I10", "Tăng huyết áp vô căn")],
                               [dict(code="AMLO5", name="Amlodipine 5mg", dose="1 viên", freq="1 lần/ngày", days=87, qty=87, start=85, supervised=True, strength="5mg")],   # còn 2 ngày -> nhắc hết liệu trình
                               doc="doctor2", nurse="nurse2", summary="Tăng huyết áp độ 1, dị ứng penicillin (sốc phản vệ) – lưu ý tuyệt đối.")
    D.dispense_course("pharm2", orders[0], 85)
    D.administer("nurse2", orders[0])
    D.problem_plan("doctor2", f2_htn, "Tăng huyết áp vô căn", "I10", "Huyết áp < 140/90 mmHg", [("Huyết áp tâm thu", "mmHg")], 14, 6, 84, nurse="nurse2")
    f2_healthy = [D.person("officer2", since=40) for _ in range(2)]
    for p in f2_healthy:
        D.initial_exam(p, 38, "normal", None, [("Z00", "Khám sức khỏe tổng quát – bình thường")], doc="doctor2", nurse="nurse2")
    f2_wait = [D.person("officer2", since=D.r.randint(0, 2)) for _ in range(2)]
    e = D.enc("doctor2", f2_healthy[0]["id"], "ad_hoc", "Đau bụng quanh rốn, buồn nôn", ago(hours=2))
    D.dx("doctor2", e["id"], "K29", "Viêm dạ dày", "preliminary")
    D.referral("doctor2", e["id"], f2_healthy[0]["id"], "urgent", "Nghi viêm ruột thừa giai đoạn sớm", "Bệnh viện Đa khoa huyện", "pending")
    dm2 = D.person("officer2", since=70, prof="dm")
    e, orders = D.initial_exam(dm2, 65, "dm", None, [("E11", "Đái tháo đường típ 2")],
                               [dict(code="MET850", name="Metformin 850mg", dose="1 viên", freq="2 lần/ngày", days=130, qty=260, start=65, strength="850mg")],
                               doc="doctor2", nurse="nurse2")
    D.dispense_course("pharm2", orders[0], 65, per=60)
    D.problem_plan("doctor2", dm2, "Đái tháo đường típ 2", "E11", "HbA1c < 7%", [("Đường huyết", "mmol/L")], 30, 28, 64, nurse="nurse2")

    # ============ Chuyển trại / bàn giao ============
    print("• Chuyển trại & bàn giao…")
    stay_of = lambda p: D.get("officer1", f"/api/persons/{p['id']}/stays")[-1]  # noqa: E731
    # H1: chờ tóm tắt y tế (healthy[1] đang có chuyển viện nháp -> cố ý để thấy 'điều trị đang mở')
    D.handover("officer1", "nurse1", stay_of(healthy[1])["id"], "transfer", "Quyết định điều chuyển số 215/QĐ-TG", to=f2)
    # H2: đã có tóm tắt, chờ xác nhận (htn[3] có kế hoạch theo dõi + thuốc đang dùng)
    D.handover("officer1", "nurse1", stay_of(htn[3])["id"], "transfer", "Quyết định điều chuyển số 231/QĐ-TG", to=f2,
               summary="Tăng huyết áp đang điều trị Amlodipine 5mg + Losartan 50mg (giám sát uống thuốc). Huyết áp gần đây 130/82. Tái khám mỗi 30 ngày. Không dị ứng thuốc. Đề nghị tiếp tục giám sát uống thuốc.")
    # H3: đã chuyển F01 -> F02, tiếp tục khám ở F02 (cùng hồ sơ sức khỏe)
    h3 = D.handover("officer1", "nurse1", stay_of(dm[1])["id"], "transfer", "Quyết định điều chuyển số 198/QĐ-TG", to=f2, confirm=False,
                    summary="Đái tháo đường típ 2: Metformin 850mg x2/ngày + Gliclazide 30mg. Đường huyết đói gần đây 7.2 mmol/L. Tái khám định kỳ 30 ngày, theo dõi cân nặng. Dị ứng: không.")
    D.post("officer1", f"/api/handovers/{h3['id']}/confirm", {"acknowledge_open_items": True, "receiver_name": "Cán bộ tiếp nhận Trại 2"})
    D.post("officer2", f"/api/persons/{dm[1]['id']}/stays", {"start_date": dstr(-6), "source_ref": "Tiếp nhận chuyển trại, QĐ 198/QĐ-TG"})
    e = D.enc("doctor2", dm[1]["id"], "periodic", "Khám sau chuyển trại, rà soát thuốc và kế hoạch theo dõi", ago(days=5))
    D.vitals("nurse2", e["id"], dm[1]["id"], "dm_ok", ago(days=5))
    D.dx("doctor2", e["id"], "E11", "Đái tháo đường típ 2 – ổn định")
    D.done("doctor2", e["id"])
    # H4: kết thúc quản lý (mãn hạn)
    h4 = D.handover("officer1", "nurse1", stay_of(healthy[3])["id"], "release", "Mãn hạn tù, ra khỏi diện quản lý", summary="Sức khỏe bình thường. Đã tư vấn tái khám tại cơ sở y tế địa phương.", confirm=True)
    # H5: F02 -> F01 (chiều ngược lại), F01 tiếp nhận kỳ mới
    stay2 = D.get("officer2", f"/api/persons/{f2_healthy[1]['id']}/stays")[-1]
    h5 = D.handover("officer2", "nurse2", stay2["id"], "transfer", "Quyết định điều chuyển số 77/QĐ-TG", to=f1, summary="Sức khỏe bình thường, không bệnh nền, không dị ứng.", confirm=True)
    D.post("officer1", f"/api/persons/{f2_healthy[1]['id']}/stays", {"start_date": dstr(-1), "source_ref": "Tiếp nhận chuyển trại, QĐ 77/QĐ-TG"})

    # ============ Đợt khám Quý 4 (sau khi đã có người ở bệnh viện / chờ chuyển trại -> bị loại trừ) ============
    D.round("manager1", "doctor1", "nurse1", "Khám sức khỏe định kỳ Quý 4/2026", 12, complete_n=5, days_range=(0, 2))
    D.round("manager2", "doctor2", "nurse2", "Khám sức khỏe định kỳ Quý 4/2026 – Trại 2", 10, complete_n=1, days_range=(0, 1))

    # ============ Scheduler, cảnh báo, truy cập khẩn cấp, từ chối ============
    print("• Cảnh báo, break-glass, nhật ký…")
    D.post("admin", "/api/scheduler/run")
    new_alerts = [a for a in D.get("nurse1", "/api/alerts?status=new") if a["kind"] == "appointment_overdue"]
    for i, al in enumerate(new_alerts[:2]):
        D.post("nurse1", f"/api/alerts/{al['id']}/acknowledge")
        if i == 0:
            D.post("nurse1", f"/api/alerts/{al['id']}/resolve", {"note": "Đã sắp xếp khám trong tuần, cập nhật lịch"})
    D.post("admin", "/api/scheduler/run?escalate_after_hours=0")
    # break-glass: bác sĩ Trại 2 xem hồ sơ người ở Trại 1 trong tình huống cấp cứu
    D.get("doctor2", f"/api/persons/{htn[0]['id']}/health-summary",
          headers={"X-Break-Glass-Reason": quote("Bệnh nhân nghi ngộ độc đang chờ chuyển sang trại tôi, cần tiền sử dị ứng gấp")})
    # các sự kiện bị từ chối & đăng nhập sai (để thấy trong nhật ký kiểm toán)
    enc_id = D.get("doctor1", f"/api/persons/{htn[0]['id']}/encounters")[0]["id"]
    D.c.get(f"/api/encounters/{enc_id}", headers=D.h("officer1"))
    D.c.get(f"/api/encounters/{enc_id}", headers=D.h("doctor2"))
    for _ in range(2):
        D.c.post("/api/auth/login", json={"username": "nurse2", "password": "sai-mat-khau"})

    # Hộp thư thực tế: nhóm số lượng lớn (tiếp nhận, đơn chờ cấp phát, đợt khám) coi như đã đọc; chỉ việc cần xử lý còn chưa đọc
    for u in ("officer1", "nurse1", "doctor1", "pharm1", "approver1", "manager1", "officer2", "nurse2", "doctor2", "pharm2", "approver2", "manager2"):
        for cat in ("intake", "medication"):
            D.post(u, f"/api/notifications/read-all?category={cat}")

    with SessionLocal() as s:
        cnt = lambda m: s.scalar(select(func.count()).select_from(m))  # noqa: E731
        print("\n=== Demo xong ===")
        print(f"Hồ sơ: {cnt(Person)} · Đợt tiếp nhận: {cnt(CustodyStay)} · Lượt khám: {cnt(Encounter)} · Đơn thuốc: {cnt(MedicationOrder)}")
        print(f"Chuyển viện: {cnt(Referral)} · Cấp cứu: {cnt(EmergencyEvent)} · Bàn giao: {cnt(Handover)} · Lịch hẹn: {cnt(Appointment)} · Cảnh báo: {cnt(Alert)}")
        print(f"Tài liệu: {cnt(MedicalDocument)} · Bản ghi nhật ký: {cnt(AuditEvent)}")
    print(f"Đăng nhập: admin / officer1 / nurse1 / doctor1 / pharm1 / approver1 / manager1 (Trại 1) và officer2 / nurse2 / doctor2 / pharm2 / approver2 / manager2 (Trại 2), mật khẩu: {DEFAULT_PASSWORD}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tạo dữ liệu demo hư cấu đi qua đúng luồng nghiệp vụ")
    ap.add_argument("--reset", action="store_true", help="XÓA toàn bộ dữ liệu hiện có rồi tạo lại")
    run(ap.parse_args().reset)
