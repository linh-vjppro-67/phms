"""Danh mục thuốc thiết yếu thường dùng ở cơ sở y tế Việt Nam, xếp theo nhóm điều trị.

GIỚI HẠN (đọc kỹ): đây là bộ thuốc *chọn lọc* (hoạt chất + hàm lượng phổ biến) để kê đơn nhanh, theo tinh thần Danh mục thuốc thiết yếu và
Danh mục thuốc bảo hiểm y tế, KHÔNG phải bản sao đầy đủ danh mục thuốc BHYT của Bộ Y tế (hàng nghìn mục, mã và hạng bệnh viện riêng).
Mã (`code`) ở đây là mã nội bộ của PHMS, không phải mã thuốc của Bộ Y tế. Muốn dùng danh mục chính thức: nạp ở Quản trị → Danh mục
(có phiên bản) hoặc bổ sung bộ dữ liệu do khách cung cấp. Dược sĩ/hội đồng thuốc của cơ sở cần rà soát trước khi dùng thực tế.

Mỗi dòng: (hoạt chất, [hàm lượng/dạng…], nhóm điều trị, đường dùng mặc định, dạng bào chế).
Tên thuốc = "<hoạt chất> <hàm lượng>"; 14 mục gốc giữ nguyên mã. Nạp vào CSDL đang chạy:  python -m app.catalog_import
"""
import re
import unicodedata

# 14 mục gốc: giữ nguyên tên + mã (demo và đơn cũ tham chiếu các mã này)
LEGACY: dict[str, str] = {
    "Paracetamol 500mg": "PARA500", "Amoxicillin 500mg": "AMOX500", "Metformin 850mg": "MET850", "Amlodipine 5mg": "AMLO5",
    "Omeprazole 20mg": "OMEP20", "Losartan 50mg": "LOSA50", "Rifampicin 150mg": "RIFA150", "Isoniazid 100mg": "INH100",
    "Cetirizine 10mg": "CETI10", "Ibuprofen 400mg": "IBU400", "Metronidazole 250mg": "METRO250", "Ciprofloxacin 500mg": "CIPRO500",
    "Gliclazide 30mg": "GLIC30", "Oresol gói": "ORS",
}
LEGACY_GROUP = {"PARA500": "Giảm đau, hạ sốt", "AMOX500": "Kháng sinh", "MET850": "Đái tháo đường", "AMLO5": "Tim mạch - huyết áp", "OMEP20": "Tiêu hóa",
                "LOSA50": "Tim mạch - huyết áp", "RIFA150": "Thuốc lao", "INH100": "Thuốc lao", "CETI10": "Dị ứng - hô hấp", "IBU400": "Giảm đau, hạ sốt",
                "METRO250": "Kháng sinh", "CIPRO500": "Kháng sinh", "GLIC30": "Đái tháo đường", "ORS": "Tiêu hóa"}

U, TB, TTM, TDD, NGOAI, MAT, HIT, NGAM = "uống", "tiêm bắp", "tiêm tĩnh mạch", "tiêm dưới da", "bôi ngoài da", "nhỏ mắt", "hít", "ngậm dưới lưỡi"
VIEN, TIEM, NGOAI_F, GOI, XIT = "viên", "thuốc tiêm", "dùng ngoài", "gói/dung dịch uống", "xịt/khí dung"

DRUG_TABLE: list[tuple[str, list[str], str, str, str]] = [
    # --- Giảm đau, hạ sốt, kháng viêm
    ("Paracetamol", ["500mg", "650mg", "150mg gói"], "Giảm đau, hạ sốt", U, VIEN), ("Ibuprofen", ["400mg", "200mg"], "Giảm đau, hạ sốt", U, VIEN),
    ("Diclofenac", ["50mg", "75mg/3ml"], "Giảm đau, hạ sốt", U, VIEN), ("Meloxicam", ["7.5mg", "15mg"], "Giảm đau, hạ sốt", U, VIEN),
    ("Celecoxib", ["200mg"], "Giảm đau, hạ sốt", U, VIEN), ("Etoricoxib", ["60mg", "90mg"], "Giảm đau, hạ sốt", U, VIEN),
    ("Naproxen", ["250mg"], "Giảm đau, hạ sốt", U, VIEN), ("Tramadol", ["50mg"], "Giảm đau, hạ sốt", U, VIEN),
    ("Paracetamol + Codein", ["500mg+30mg"], "Giảm đau, hạ sốt", U, VIEN), ("Aspirin", ["81mg", "100mg", "500mg"], "Giảm đau, hạ sốt", U, VIEN),
    ("Morphin", ["10mg/ml"], "Giảm đau, hạ sốt", TDD, TIEM), ("Pethidin", ["100mg/2ml"], "Giảm đau, hạ sốt", TB, TIEM),
    # --- Kháng sinh
    ("Amoxicillin", ["250mg"], "Kháng sinh", U, VIEN), ("Amoxicillin + Acid clavulanic", ["500mg+125mg", "875mg+125mg"], "Kháng sinh", U, VIEN),
    ("Ampicillin", ["500mg", "1g"], "Kháng sinh", TB, TIEM), ("Phenoxymethylpenicillin (Penicillin V)", ["1.000.000IU"], "Kháng sinh", U, VIEN),
    ("Benzathin benzylpenicillin", ["1.200.000IU"], "Kháng sinh", TB, TIEM), ("Cefalexin", ["500mg"], "Kháng sinh", U, VIEN),
    ("Cefuroxim", ["500mg"], "Kháng sinh", U, VIEN), ("Cefixim", ["200mg"], "Kháng sinh", U, VIEN), ("Cefpodoxim", ["100mg"], "Kháng sinh", U, VIEN),
    ("Cefotaxim", ["1g"], "Kháng sinh", TTM, TIEM), ("Ceftriaxon", ["1g"], "Kháng sinh", TTM, TIEM), ("Ceftazidim", ["1g"], "Kháng sinh", TTM, TIEM),
    ("Azithromycin", ["250mg", "500mg"], "Kháng sinh", U, VIEN), ("Clarithromycin", ["500mg"], "Kháng sinh", U, VIEN),
    ("Erythromycin", ["500mg"], "Kháng sinh", U, VIEN), ("Spiramycin", ["3MIU"], "Kháng sinh", U, VIEN),
    ("Levofloxacin", ["500mg"], "Kháng sinh", U, VIEN), ("Ofloxacin", ["200mg"], "Kháng sinh", U, VIEN), ("Moxifloxacin", ["400mg"], "Kháng sinh", U, VIEN),
    ("Sulfamethoxazol + Trimethoprim (Cotrimoxazol)", ["400mg+80mg", "800mg+160mg"], "Kháng sinh", U, VIEN),
    ("Doxycyclin", ["100mg"], "Kháng sinh", U, VIEN), ("Gentamicin", ["80mg/2ml"], "Kháng sinh", TB, TIEM), ("Amikacin", ["500mg/2ml"], "Kháng sinh", TB, TIEM),
    ("Clindamycin", ["300mg"], "Kháng sinh", U, VIEN), ("Lincomycin", ["500mg"], "Kháng sinh", U, VIEN), ("Vancomycin", ["500mg"], "Kháng sinh", TTM, TIEM),
    ("Meropenem", ["1g"], "Kháng sinh", TTM, TIEM), ("Metronidazole", ["500mg"], "Kháng sinh", U, VIEN),
    # --- Thuốc lao
    ("Rifampicin", ["300mg"], "Thuốc lao", U, VIEN), ("Isoniazid", ["300mg"], "Thuốc lao", U, VIEN), ("Pyrazinamid", ["500mg"], "Thuốc lao", U, VIEN),
    ("Ethambutol", ["400mg"], "Thuốc lao", U, VIEN), ("Streptomycin", ["1g"], "Thuốc lao", TB, TIEM),
    ("Rifampicin + Isoniazid (RH)", ["150mg+75mg"], "Thuốc lao", U, VIEN), ("Rifampicin + Isoniazid + Pyrazinamid + Ethambutol (RHZE)", ["150mg+75mg+400mg+275mg"], "Thuốc lao", U, VIEN),
    # --- Kháng virus (HIV, viêm gan B, herpes, cúm)
    ("Tenofovir (TDF)", ["300mg"], "Kháng virus", U, VIEN), ("Lamivudin (3TC)", ["150mg", "300mg"], "Kháng virus", U, VIEN), ("Efavirenz (EFV)", ["600mg"], "Kháng virus", U, VIEN),
    ("Dolutegravir (DTG)", ["50mg"], "Kháng virus", U, VIEN), ("Zidovudin (AZT)", ["300mg"], "Kháng virus", U, VIEN), ("Nevirapin (NVP)", ["200mg"], "Kháng virus", U, VIEN),
    ("Tenofovir + Lamivudin + Efavirenz (TLE)", ["300mg+300mg+600mg"], "Kháng virus", U, VIEN), ("Tenofovir + Lamivudin + Dolutegravir (TLD)", ["300mg+300mg+50mg"], "Kháng virus", U, VIEN),
    ("Entecavir", ["0.5mg"], "Kháng virus", U, VIEN), ("Acyclovir", ["200mg", "400mg"], "Kháng virus", U, VIEN), ("Oseltamivir", ["75mg"], "Kháng virus", U, VIEN),
    # --- Kháng nấm, ký sinh trùng, sốt rét
    ("Fluconazol", ["150mg"], "Kháng nấm, ký sinh trùng", U, VIEN), ("Itraconazol", ["100mg"], "Kháng nấm, ký sinh trùng", U, VIEN),
    ("Ketoconazol", ["200mg"], "Kháng nấm, ký sinh trùng", U, VIEN), ("Griseofulvin", ["500mg"], "Kháng nấm, ký sinh trùng", U, VIEN),
    ("Nystatin", ["500.000IU"], "Kháng nấm, ký sinh trùng", U, VIEN), ("Albendazol", ["400mg"], "Kháng nấm, ký sinh trùng", U, VIEN),
    ("Mebendazol", ["500mg"], "Kháng nấm, ký sinh trùng", U, VIEN), ("Ivermectin", ["3mg"], "Kháng nấm, ký sinh trùng", U, VIEN),
    ("Praziquantel", ["600mg"], "Kháng nấm, ký sinh trùng", U, VIEN), ("Artesunat", ["60mg"], "Kháng nấm, ký sinh trùng", TTM, TIEM),
    ("Artemether + Lumefantrin", ["20mg+120mg"], "Kháng nấm, ký sinh trùng", U, VIEN), ("Chloroquin", ["250mg"], "Kháng nấm, ký sinh trùng", U, VIEN),
    ("Primaquin", ["15mg"], "Kháng nấm, ký sinh trùng", U, VIEN),
    # --- Tim mạch, huyết áp, mỡ máu, chống đông
    ("Amlodipine", ["10mg"], "Tim mạch - huyết áp", U, VIEN), ("Nifedipin", ["20mg"], "Tim mạch - huyết áp", U, VIEN), ("Felodipin", ["5mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Losartan", ["100mg"], "Tim mạch - huyết áp", U, VIEN), ("Valsartan", ["80mg", "160mg"], "Tim mạch - huyết áp", U, VIEN), ("Irbesartan", ["150mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Telmisartan", ["40mg"], "Tim mạch - huyết áp", U, VIEN), ("Enalapril", ["5mg", "10mg"], "Tim mạch - huyết áp", U, VIEN), ("Captopril", ["25mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Perindopril", ["4mg"], "Tim mạch - huyết áp", U, VIEN), ("Lisinopril", ["10mg"], "Tim mạch - huyết áp", U, VIEN), ("Bisoprolol", ["2.5mg", "5mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Metoprolol", ["50mg"], "Tim mạch - huyết áp", U, VIEN), ("Atenolol", ["50mg"], "Tim mạch - huyết áp", U, VIEN), ("Propranolol", ["40mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Carvedilol", ["6.25mg"], "Tim mạch - huyết áp", U, VIEN), ("Hydrochlorothiazid", ["25mg"], "Tim mạch - huyết áp", U, VIEN), ("Furosemid", ["40mg", "20mg/2ml"], "Tim mạch - huyết áp", U, VIEN),
    ("Spironolacton", ["25mg"], "Tim mạch - huyết áp", U, VIEN), ("Indapamid", ["1.5mg"], "Tim mạch - huyết áp", U, VIEN), ("Methyldopa", ["250mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Amlodipine + Losartan", ["5mg+50mg"], "Tim mạch - huyết áp", U, VIEN), ("Diltiazem", ["60mg"], "Tim mạch - huyết áp", U, VIEN), ("Verapamil", ["80mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Isosorbid dinitrat", ["10mg"], "Tim mạch - huyết áp", U, VIEN), ("Isosorbid mononitrat", ["60mg"], "Tim mạch - huyết áp", U, VIEN), ("Nitroglycerin", ["0.5mg"], "Tim mạch - huyết áp", NGAM, VIEN),
    ("Digoxin", ["0.25mg"], "Tim mạch - huyết áp", U, VIEN), ("Amiodaron", ["200mg"], "Tim mạch - huyết áp", U, VIEN), ("Trimetazidin", ["35mg"], "Tim mạch - huyết áp", U, VIEN),
    ("Atorvastatin", ["10mg", "20mg", "40mg"], "Mỡ máu", U, VIEN), ("Rosuvastatin", ["10mg", "20mg"], "Mỡ máu", U, VIEN), ("Simvastatin", ["20mg"], "Mỡ máu", U, VIEN),
    ("Fenofibrat", ["160mg"], "Mỡ máu", U, VIEN), ("Clopidogrel", ["75mg"], "Chống đông, chống kết tập tiểu cầu", U, VIEN), ("Warfarin", ["5mg"], "Chống đông, chống kết tập tiểu cầu", U, VIEN),
    ("Rivaroxaban", ["20mg"], "Chống đông, chống kết tập tiểu cầu", U, VIEN), ("Enoxaparin", ["40mg/0.4ml"], "Chống đông, chống kết tập tiểu cầu", TDD, TIEM),
    # --- Tiêu hóa
    ("Omeprazole", ["40mg"], "Tiêu hóa", U, VIEN), ("Esomeprazol", ["40mg"], "Tiêu hóa", U, VIEN), ("Pantoprazol", ["40mg"], "Tiêu hóa", U, VIEN), ("Lansoprazol", ["30mg"], "Tiêu hóa", U, VIEN),
    ("Famotidin", ["20mg", "40mg"], "Tiêu hóa", U, VIEN), ("Sucralfat", ["1g"], "Tiêu hóa", U, GOI), ("Domperidon", ["10mg"], "Tiêu hóa", U, VIEN), ("Metoclopramid", ["10mg"], "Tiêu hóa", U, VIEN),
    ("Ondansetron", ["4mg", "8mg"], "Tiêu hóa", U, VIEN), ("Hyoscin butylbromid", ["10mg"], "Tiêu hóa", U, VIEN), ("Drotaverin", ["40mg"], "Tiêu hóa", U, VIEN),
    ("Loperamid", ["2mg"], "Tiêu hóa", U, VIEN), ("Racecadotril", ["100mg"], "Tiêu hóa", U, VIEN), ("Bisacodyl", ["5mg"], "Tiêu hóa", U, VIEN),
    ("Lactulose", ["10g/15ml"], "Tiêu hóa", U, GOI), ("Simethicon", ["40mg"], "Tiêu hóa", U, VIEN), ("Diosmectit", ["3g"], "Tiêu hóa", U, GOI),
    ("Attapulgit", ["3g"], "Tiêu hóa", U, GOI), ("Berberin", ["100mg"], "Tiêu hóa", U, VIEN), ("Bacillus subtilis (men vi sinh)", ["gói"], "Tiêu hóa", U, GOI),
    ("Ursodeoxycholic acid", ["250mg"], "Tiêu hóa", U, VIEN), ("Silymarin", ["140mg"], "Tiêu hóa", U, VIEN), ("Nhôm hydroxyd + Magnesi hydroxyd", ["gói"], "Tiêu hóa", U, GOI),
    ("Mebeverin", ["135mg"], "Tiêu hóa", U, VIEN),
    # --- Hô hấp, dị ứng, corticoid
    ("Salbutamol", ["2mg", "100mcg xịt", "5mg/2.5ml khí dung"], "Dị ứng - hô hấp", HIT, XIT), ("Budesonid", ["200mcg xịt"], "Dị ứng - hô hấp", HIT, XIT),
    ("Salmeterol + Fluticason", ["25mcg+125mcg xịt"], "Dị ứng - hô hấp", HIT, XIT), ("Ipratropium", ["0.5mg/2ml khí dung"], "Dị ứng - hô hấp", HIT, XIT),
    ("Theophyllin", ["100mg"], "Dị ứng - hô hấp", U, VIEN), ("Montelukast", ["10mg"], "Dị ứng - hô hấp", U, VIEN), ("Acetylcystein", ["200mg"], "Dị ứng - hô hấp", U, GOI),
    ("Bromhexin", ["8mg"], "Dị ứng - hô hấp", U, VIEN), ("Ambroxol", ["30mg"], "Dị ứng - hô hấp", U, VIEN), ("Dextromethorphan", ["15mg"], "Dị ứng - hô hấp", U, VIEN),
    ("Loratadin", ["10mg"], "Dị ứng - hô hấp", U, VIEN), ("Fexofenadin", ["120mg"], "Dị ứng - hô hấp", U, VIEN), ("Chlorpheniramin", ["4mg"], "Dị ứng - hô hấp", U, VIEN),
    ("Desloratadin", ["5mg"], "Dị ứng - hô hấp", U, VIEN), ("Prednisolon", ["5mg"], "Corticoid", U, VIEN), ("Methylprednisolon", ["4mg", "16mg"], "Corticoid", U, VIEN),
    ("Dexamethason", ["0.5mg", "4mg/ml"], "Corticoid", U, VIEN), ("Hydrocortison", ["100mg"], "Corticoid", TTM, TIEM),
    ("Oxymetazolin", ["0.05% xịt mũi"], "Dị ứng - hô hấp", HIT, XIT), ("Natri clorid", ["0.9% nhỏ mũi"], "Dị ứng - hô hấp", HIT, XIT),
    # --- Đái tháo đường, nội tiết
    ("Metformin", ["500mg", "1000mg"], "Đái tháo đường", U, VIEN), ("Gliclazide", ["80mg"], "Đái tháo đường", U, VIEN), ("Glimepirid", ["2mg", "4mg"], "Đái tháo đường", U, VIEN),
    ("Glibenclamid", ["5mg"], "Đái tháo đường", U, VIEN), ("Pioglitazon", ["15mg"], "Đái tháo đường", U, VIEN), ("Sitagliptin", ["100mg"], "Đái tháo đường", U, VIEN),
    ("Vildagliptin", ["50mg"], "Đái tháo đường", U, VIEN), ("Insulin người tác dụng nhanh (regular)", ["100IU/ml"], "Đái tháo đường", TDD, TIEM),
    ("Insulin NPH (tác dụng trung bình)", ["100IU/ml"], "Đái tháo đường", TDD, TIEM), ("Insulin trộn 30/70", ["100IU/ml"], "Đái tháo đường", TDD, TIEM),
    ("Levothyroxin", ["50mcg", "100mcg"], "Nội tiết", U, VIEN), ("Thiamazol", ["5mg"], "Nội tiết", U, VIEN), ("Propylthiouracil", ["50mg"], "Nội tiết", U, VIEN),
    ("Alendronat", ["70mg"], "Nội tiết", U, VIEN), ("Calcitriol", ["0.25mcg"], "Nội tiết", U, VIEN),
    # --- Thần kinh, tâm thần, nghiện chất
    ("Diazepam", ["5mg", "10mg/2ml"], "Thần kinh - tâm thần", U, VIEN), ("Phenobarbital", ["100mg"], "Thần kinh - tâm thần", U, VIEN), ("Phenytoin", ["100mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Carbamazepin", ["200mg"], "Thần kinh - tâm thần", U, VIEN), ("Natri valproat", ["500mg"], "Thần kinh - tâm thần", U, VIEN), ("Levetiracetam", ["500mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Gabapentin", ["300mg"], "Thần kinh - tâm thần", U, VIEN), ("Pregabalin", ["75mg"], "Thần kinh - tâm thần", U, VIEN), ("Amitriptylin", ["25mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Fluoxetin", ["20mg"], "Thần kinh - tâm thần", U, VIEN), ("Sertralin", ["50mg"], "Thần kinh - tâm thần", U, VIEN), ("Escitalopram", ["10mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Mirtazapin", ["30mg"], "Thần kinh - tâm thần", U, VIEN), ("Haloperidol", ["5mg", "5mg/ml"], "Thần kinh - tâm thần", U, VIEN), ("Risperidon", ["2mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Olanzapin", ["10mg"], "Thần kinh - tâm thần", U, VIEN), ("Clozapin", ["100mg"], "Thần kinh - tâm thần", U, VIEN), ("Clorpromazin", ["25mg", "100mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Levomepromazin", ["25mg"], "Thần kinh - tâm thần", U, VIEN), ("Lorazepam", ["1mg"], "Thần kinh - tâm thần", U, VIEN), ("Alprazolam", ["0.5mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Zolpidem", ["10mg"], "Thần kinh - tâm thần", U, VIEN), ("Rotundin", ["30mg"], "Thần kinh - tâm thần", U, VIEN), ("Piracetam", ["800mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Cinnarizin", ["25mg"], "Thần kinh - tâm thần", U, VIEN), ("Betahistin", ["16mg"], "Thần kinh - tâm thần", U, VIEN), ("Flunarizin", ["5mg"], "Thần kinh - tâm thần", U, VIEN),
    ("Methadon", ["10mg"], "Điều trị nghiện chất", U, GOI), ("Naloxon", ["0.4mg/ml"], "Điều trị nghiện chất", TB, TIEM),
    # --- Vitamin, khoáng chất, máu
    ("Vitamin C", ["500mg"], "Vitamin - khoáng chất", U, VIEN), ("Vitamin B1", ["100mg"], "Vitamin - khoáng chất", U, VIEN), ("Vitamin B6", ["250mg"], "Vitamin - khoáng chất", U, VIEN),
    ("Vitamin B1 + B6 + B12", ["viên"], "Vitamin - khoáng chất", U, VIEN), ("Vitamin B12 (Cyanocobalamin)", ["1000mcg/ml"], "Vitamin - khoáng chất", TB, TIEM),
    ("Vitamin D3", ["1000IU"], "Vitamin - khoáng chất", U, VIEN), ("Vitamin K1 (Phytomenadion)", ["10mg/ml"], "Vitamin - khoáng chất", TB, TIEM),
    ("Acid folic", ["5mg"], "Vitamin - khoáng chất", U, VIEN), ("Sắt sulfat + Acid folic", ["80mg+0.35mg"], "Vitamin - khoáng chất", U, VIEN),
    ("Kẽm gluconat", ["70mg"], "Vitamin - khoáng chất", U, VIEN), ("Calci carbonat", ["500mg"], "Vitamin - khoáng chất", U, VIEN), ("Calci gluconat", ["10% 10ml"], "Vitamin - khoáng chất", TTM, TIEM),
    ("Magnesi sulfat", ["15% 10ml"], "Vitamin - khoáng chất", TTM, TIEM), ("Kali clorid", ["500mg"], "Vitamin - khoáng chất", U, VIEN), ("Tranexamic acid", ["250mg", "500mg"], "Cầm máu", U, VIEN),
    # --- Da liễu, mắt, tai (dùng ngoài)
    ("Mupirocin", ["2% mỡ"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Betamethason", ["0.064% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Clotrimazol", ["1% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F),
    ("Acid fusidic", ["2% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Silver sulfadiazin", ["1% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Povidon iod", ["10% dung dịch"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F),
    ("Cồn 70 độ", ["dung dịch"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Nước oxy già", ["3%"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Permethrin", ["5% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F),
    ("Benzyl benzoat", ["25% lotion"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Miconazol", ["2% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Acyclovir", ["5% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F),
    ("Terbinafin", ["1% kem"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Calamin", ["lotion"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Tetracyclin", ["1% mỡ tra mắt"], "Dùng ngoài, mắt, tai", MAT, NGOAI_F),
    ("Ciprofloxacin", ["0.3% nhỏ mắt"], "Dùng ngoài, mắt, tai", MAT, NGOAI_F), ("Cloramphenicol", ["0.4% nhỏ mắt"], "Dùng ngoài, mắt, tai", MAT, NGOAI_F), ("Natri clorid", ["0.9% rửa mắt/vết thương"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F),
    ("Neomycin + Polymyxin B + Dexamethason", ["nhỏ tai"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F), ("Lidocain", ["2% gel"], "Dùng ngoài, mắt, tai", NGOAI, NGOAI_F),
    # --- Dịch truyền, thuốc cấp cứu, gây tê
    ("Natri clorid", ["0.9% 500ml truyền"], "Dịch truyền - cấp cứu", TTM, TIEM), ("Glucose", ["5% 500ml truyền", "30% 5ml"], "Dịch truyền - cấp cứu", TTM, TIEM),
    ("Ringer lactat", ["500ml truyền"], "Dịch truyền - cấp cứu", TTM, TIEM), ("Adrenalin", ["1mg/ml"], "Dịch truyền - cấp cứu", TB, TIEM), ("Atropin", ["0.25mg/ml"], "Dịch truyền - cấp cứu", TB, TIEM),
    ("Noradrenalin", ["4mg/4ml"], "Dịch truyền - cấp cứu", TTM, TIEM), ("Dopamin", ["200mg/5ml"], "Dịch truyền - cấp cứu", TTM, TIEM), ("Lidocain", ["2% 2ml tiêm"], "Dịch truyền - cấp cứu", TB, TIEM),
    ("Ketamin", ["500mg/10ml"], "Dịch truyền - cấp cứu", TTM, TIEM), ("Midazolam", ["5mg/ml"], "Dịch truyền - cấp cứu", TB, TIEM), ("Oxytocin", ["5IU/ml"], "Dịch truyền - cấp cứu", TB, TIEM),
    ("Huyết thanh kháng uốn ván (SAT)", ["1500IU"], "Dịch truyền - cấp cứu", TB, TIEM), ("Vắc xin uốn ván hấp phụ (TT)", ["0.5ml"], "Dịch truyền - cấp cứu", TB, TIEM),
]


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^A-Za-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn")).upper()


def build() -> list[dict]:
    """Sinh danh sách {code,name,extra} xác định (ổn định giữa các lần chạy); không trùng mã/tên; mục gốc giữ nguyên mã."""
    out, codes, names = [], set(), set()
    for name, code in LEGACY.items():
        form_route = ("gói/dung dịch uống", "uống") if code == "ORS" else ("viên", "uống")
        out.append({"code": code, "name": name, "extra": {"group": LEGACY_GROUP[code], "form": form_route[0], "route": form_route[1],
                                                           **({} if code == "ORS" else {"strength": name.split()[-1]})}})
        codes.add(code); names.add(name.lower())
    for ingr, strengths, group, route, form in DRUG_TABLE:
        for st in strengths:
            name = f"{ingr} {st}"
            if name.lower() in names:
                continue
            base = _slug(ingr.split(" (")[0].split(" + ")[0])[:5] + _slug(st)[:7]
            code, n = base, 2
            while code in codes:
                code, n = f"{base}{n}", n + 1
            out.append({"code": code, "name": name, "extra": {"group": group, "form": form, "route": route, "strength": st}})
            codes.add(code); names.add(name.lower())
    return out


DRUGS_VN = build()
