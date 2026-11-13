import os
import tempfile
from datetime import date

os.environ["PHMS_DB_URL"] = os.environ.get("PHMS_TEST_DB_URL", "sqlite://")   # PHMS_TEST_DB_URL=postgresql+psycopg://... để chạy bộ test trên PostgreSQL
os.environ["PHMS_PBKDF2_ITER"] = "1000"
os.environ["PHMS_SCHEDULER"] = "0"
os.environ["PHMS_DOC_DIR"] = tempfile.mkdtemp(prefix="phms-docs-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEFAULT_PASSWORD, seed  # noqa: E402


class Api:
    def __init__(self, client: TestClient):
        self.c = client
        self._tok: dict[str, str] = {}
        f = {x["code"]: x["id"] for x in self.get("admin", "/api/facilities").json()}
        self.f1, self.f2 = f["F01"], f["F02"]

    def h(self, user: str, **extra) -> dict:
        if user not in self._tok:
            r = self.c.post("/api/auth/login", json={"username": user, "password": DEFAULT_PASSWORD})
            assert r.status_code == 200, r.text
            self._tok[user] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self._tok[user]}", **extra}

    def get(self, user, path, **kw):
        return self.c.get(path, headers=self.h(user, **kw.pop("headers", {})), **kw)

    def post(self, user, path, json=None, headers=None, **kw):
        return self.c.post(path, json=json, headers=self.h(user, **(headers or {})), **kw)

    def patch(self, user, path, json=None, headers=None):
        return self.c.patch(path, json=json, headers=self.h(user, **(headers or {})))

    def put(self, user, path, json=None):
        return self.c.put(path, json=json, headers=self.h(user))

    # ---- builders
    def person(self, ext="P001", name="Nguyễn Văn A", dob="1985-05-05", user="officer1"):
        r = self.post(user, "/api/persons", {"full_name": name, "date_of_birth": dob,
                                              "source_system": "QLPN", "external_id": ext,
                                              "confirm_distinct": True})
        assert r.status_code == 201, r.text
        return r.json()

    def stay(self, pid, user="officer1"):
        r = self.post(user, f"/api/persons/{pid}/stays", {})
        assert r.status_code == 201, r.text
        return r.json()

    def patient(self, ext="P001", name="Nguyễn Văn A"):
        p = self.person(ext, name)
        s = self.stay(p["id"])
        return p, s

    def managed(self, ext="P001", name="Nguyễn Văn A"):
        """Người đã khám ban đầu xong -> đợt tiếp nhận 'Đang quản lý'."""
        p, s = self.patient(ext, name)
        e = self.encounter(p["id"], "initial")
        r = self.post("doctor1", f"/api/encounters/{e['id']}/transition", {"to": "completed"})
        assert r.status_code == 200, r.text
        return p, s

    def encounter(self, pid, type="ad_hoc", user="doctor1", start=True, **extra):
        r = self.post(user, "/api/encounters", {"person_id": pid, "type": type, "reason": "test", **extra})
        assert r.status_code == 201, r.text
        e = r.json()
        if start:
            r = self.post(user, f"/api/encounters/{e['id']}/transition", {"to": "in_progress"})
            assert r.status_code == 200, r.text
            e = r.json()
        return e

    def med_order(self, enc_id, user="doctor1", **kw):
        body = {"drug_name": "Paracetamol 500mg", "drug_code": "PARA500", "dose": "1 viên", "route": "uống",
                "frequency": "2 lần/ngày", "start_date": str(date.today()), "duration_days": 15,
                "quantity_prescribed": 30, **kw}
        r = self.post(user, f"/api/encounters/{enc_id}/medication-orders", body)
        assert r.status_code == 201, r.text
        return r.json()

    def confirmed_order(self, enc_id, **kw):
        o = self.med_order(enc_id, **kw)
        r = self.post("doctor1", f"/api/medication-orders/{o['id']}/confirm", {})
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed(s)
    yield


@pytest.fixture()
def api():
    return Api(TestClient(app))
