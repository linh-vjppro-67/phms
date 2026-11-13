"""Hồi quy cho các lỗi do đợt QC độc lập phát hiện (nhập liệu bất khả thi, dị ứng chéo nhóm, đổi mật khẩu)."""
import pytest

from app.seed import DEFAULT_PASSWORD


@pytest.mark.parametrize("dob", ["2999-01-01", "1800-01-01"])
def test_person_date_of_birth_must_be_plausible(api, dob):
    r = api.post("officer1", "/api/persons", {"full_name": "Sai Ngày Sinh", "date_of_birth": dob})
    assert r.status_code == 422


@pytest.mark.parametrize("typ,val,code", [("Mạch", "abc", "OBS_NOT_NUMERIC"), ("Mạch", "500", "OBS_OUT_OF_RANGE"),
                                          ("Nhiệt độ", "99", "OBS_OUT_OF_RANGE"), ("SpO2", "130", "OBS_OUT_OF_RANGE")])
def test_vital_signs_reject_impossible_values(api, typ, val, code):
    p, _ = api.patient("QC1", "Sinh Hiệu")
    e = api.encounter(p["id"])
    r = api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": typ, "value": val, "unit": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_vital_signs_accept_valid_and_comma_decimal_and_free_text_types(api):
    p, _ = api.patient("QC2", "Sinh Hiệu Hợp Lệ")
    e = api.encounter(p["id"])
    for typ, val in [("Mạch", "78"), ("Nhiệt độ", "36,8"), ("Ghi chú khác", "tùy ý")]:
        r = api.post("nurse1", f"/api/encounters/{e['id']}/observations", {"type": typ, "value": val, "unit": "-"})
        assert r.status_code == 201, r.text
    assert api.get("nurse1", f"/api/encounters/{e['id']}").status_code == 200


def test_cross_allergy_warns_for_same_drug_class_but_not_unrelated_drug(api):
    p, _ = api.patient("QC3", "Dị Ứng Chéo")
    e = api.encounter(p["id"])
    assert api.post("doctor1", f"/api/persons/{p['id']}/allergies",
                    {"substance": "Penicillin", "severity": "severe", "reaction": "mề đay"}).status_code == 201
    same = api.med_order(e["id"], drug_name="Amoxicillin 500mg", drug_code="AMOX500")
    assert any(w["type"] == "allergy" and "cùng nhóm" in w["message"] for w in same["warnings"])
    other = api.med_order(e["id"], drug_name="Paracetamol 500mg", drug_code="PARA500")
    assert not any(w["type"] == "allergy" for w in other["warnings"])
    # cảnh báo dị ứng vẫn buộc xác nhận có lý do
    assert api.post("doctor1", f"/api/medication-orders/{same['id']}/confirm", {}).status_code == 409


def test_change_password_rejects_same_password(api):
    r = api.post("nurse2", "/api/auth/change-password", {"old_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SAME_PASSWORD"
