"""Danh mục ICD-10 (mức 3 ký tự) thường gặp ở bệnh viện/cơ sở y tế Việt Nam, tên theo cách gọi của ngành y tế Việt Nam.
16 mục đầu giữ nguyên như bản seed ban đầu (dữ liệu demo tham chiếu các mã này). Danh sách này là điểm khởi đầu để chọn nhanh,
KHÔNG thay thế bộ ICD-10 đầy đủ của Bộ Y tế: nhập thêm/cập nhật ở Quản trị → Danh mục (có phiên bản) hoặc nạp bộ đầy đủ khi khách cung cấp.
Nạp thêm vào CSDL đang chạy (idempotent, chỉ thêm mã còn thiếu):  python -m app.catalog_import
"""

ICD_VN: list[tuple[str, str]] = [
    # --- 16 mục gốc (giữ nguyên)
    ("I10", "Tăng huyết áp vô căn"), ("E11", "Đái tháo đường típ 2"), ("A15", "Lao phổi"),
    ("J06", "Nhiễm khuẩn hô hấp trên cấp"), ("B20", "Bệnh do HIV"), ("J20", "Viêm phế quản cấp"),
    ("K29", "Viêm dạ dày"), ("M54", "Đau lưng"), ("L03", "Viêm mô tế bào"), ("A09", "Tiêu chảy nhiễm khuẩn"),
    ("R50", "Sốt chưa rõ nguyên nhân"), ("I20", "Đau thắt ngực"), ("K35", "Viêm ruột thừa cấp"),
    ("G40", "Động kinh"), ("R55", "Ngất"), ("Z00", "Khám sức khỏe tổng quát"),
    # --- Bệnh nhiễm trùng và ký sinh trùng (A00–B99)
    ("A00", "Bệnh tả"), ("A01", "Thương hàn và phó thương hàn"), ("A03", "Lỵ trực khuẩn"), ("A06", "Lỵ amíp"),
    ("A16", "Lao hô hấp, không xác nhận bằng vi khuẩn học hay mô bệnh học"), ("A18", "Lao các cơ quan khác"),
    ("A39", "Nhiễm não mô cầu"), ("A41", "Nhiễm khuẩn huyết"), ("A51", "Giang mai sớm"), ("A53", "Giang mai khác và chưa xác định"),
    ("A54", "Nhiễm lậu cầu"), ("A56", "Nhiễm Chlamydia đường sinh dục"), ("A90", "Sốt Dengue"), ("A91", "Sốt xuất huyết Dengue"),
    ("B01", "Thủy đậu"), ("B02", "Zona (Herpes zoster)"), ("B05", "Sởi"), ("B15", "Viêm gan virus A cấp"), ("B16", "Viêm gan virus B cấp"),
    ("B18", "Viêm gan virus mạn"), ("B24", "Bệnh HIV, không đặc hiệu"), ("B34", "Nhiễm virus, vị trí không xác định"),
    ("B35", "Nấm da (Dermatophytosis)"), ("B37", "Nhiễm Candida"), ("B50", "Sốt rét do Plasmodium falciparum"), ("B51", "Sốt rét do Plasmodium vivax"),
    ("B54", "Sốt rét, không xác định"), ("B86", "Ghẻ"), ("B82", "Ký sinh trùng đường ruột, không xác định"), ("B76", "Bệnh giun móc"),
    # --- U và bệnh máu (C00–D89)
    ("C16", "Ung thư dạ dày"), ("C18", "Ung thư đại tràng"), ("C22", "Ung thư gan và đường mật trong gan"), ("C34", "Ung thư phế quản và phổi"),
    ("C50", "Ung thư vú"), ("C53", "Ung thư cổ tử cung"), ("C61", "Ung thư tuyến tiền liệt"), ("D50", "Thiếu máu do thiếu sắt"),
    ("D64", "Thiếu máu khác"), ("D69", "Ban xuất huyết và các tình trạng chảy máu khác"),
    # --- Nội tiết, dinh dưỡng, chuyển hóa (E00–E90)
    ("E03", "Suy giáp khác"), ("E05", "Nhiễm độc giáp (cường giáp)"), ("E10", "Đái tháo đường típ 1"), ("E14", "Đái tháo đường không xác định"),
    ("E46", "Suy dinh dưỡng protein-năng lượng, không xác định"), ("E66", "Béo phì"), ("E78", "Rối loạn chuyển hóa lipoprotein (rối loạn mỡ máu)"),
    ("E86", "Mất nước"), ("E87", "Rối loạn cân bằng nước, điện giải và toan kiềm"), ("E79", "Rối loạn chuyển hóa purin và pyrimidin (tăng acid uric)"),
    # --- Rối loạn tâm thần và hành vi (F00–F99)
    ("F10", "Rối loạn tâm thần và hành vi do rượu"), ("F11", "Rối loạn do sử dụng opioid (heroin, thuốc phiện)"), ("F12", "Rối loạn do sử dụng cần sa"),
    ("F15", "Rối loạn do sử dụng chất kích thích khác (ma túy tổng hợp)"), ("F17", "Rối loạn do sử dụng thuốc lá"), ("F19", "Rối loạn do sử dụng nhiều loại ma túy"),
    ("F20", "Tâm thần phân liệt"), ("F29", "Loạn thần không thực tổn, không xác định"), ("F31", "Rối loạn cảm xúc lưỡng cực"),
    ("F32", "Giai đoạn trầm cảm"), ("F41", "Rối loạn lo âu khác"), ("F43", "Phản ứng với stress nặng và rối loạn thích ứng"),
    ("F45", "Rối loạn dạng cơ thể"), ("F51", "Mất ngủ không do nguyên nhân thực tổn"), ("F60", "Rối loạn nhân cách đặc hiệu"),
    # --- Thần kinh (G00–G99)
    ("G43", "Đau nửa đầu (Migraine)"), ("G44", "Hội chứng đau đầu khác"), ("G45", "Cơn thiếu máu não thoáng qua"), ("G47", "Rối loạn giấc ngủ"),
    ("G51", "Rối loạn dây thần kinh mặt (liệt dây VII)"), ("G62", "Bệnh đa dây thần kinh khác"), ("G81", "Liệt nửa người"),
    # --- Mắt, tai (H00–H95)
    ("H10", "Viêm kết mạc"), ("H25", "Đục thể thủy tinh tuổi già"), ("H40", "Glôcôm (tăng nhãn áp)"), ("H52", "Rối loạn khúc xạ và điều tiết"),
    ("H66", "Viêm tai giữa có mủ và không xác định"), ("H61", "Bệnh khác của tai ngoài"), ("H91", "Giảm thính lực khác"),
    # --- Tuần hoàn (I00–I99)
    ("I11", "Bệnh tim do tăng huyết áp"), ("I21", "Nhồi máu cơ tim cấp"), ("I25", "Bệnh tim thiếu máu cục bộ mạn"), ("I26", "Thuyên tắc phổi"),
    ("I42", "Bệnh cơ tim"), ("I47", "Nhịp nhanh kịch phát"), ("I48", "Rung nhĩ và cuồng nhĩ"), ("I49", "Rối loạn nhịp tim khác"), ("I50", "Suy tim"),
    ("I61", "Xuất huyết trong não"), ("I63", "Nhồi máu não"), ("I64", "Đột quỵ, không xác định xuất huyết hay nhồi máu"), ("I69", "Di chứng bệnh mạch máu não"),
    ("I73", "Bệnh mạch máu ngoại vi khác"), ("I80", "Viêm tĩnh mạch và viêm tĩnh mạch huyết khối"), ("I83", "Giãn tĩnh mạch chi dưới"),
    ("I84", "Trĩ"), ("I95", "Hạ huyết áp"),
    # --- Hô hấp (J00–J99)
    ("J00", "Viêm mũi họng cấp (cảm thường)"), ("J02", "Viêm họng cấp"), ("J03", "Viêm amiđan cấp"), ("J11", "Cúm, virus không xác định"),
    ("J15", "Viêm phổi do vi khuẩn, chưa phân loại nơi khác"), ("J18", "Viêm phổi, tác nhân không xác định"), ("J30", "Viêm mũi dị ứng"),
    ("J31", "Viêm mũi, viêm mũi họng và viêm họng mạn"), ("J32", "Viêm xoang mạn"), ("J40", "Viêm phế quản, không xác định cấp hay mạn"),
    ("J44", "Bệnh phổi tắc nghẽn mạn tính (COPD)"), ("J45", "Hen phế quản"), ("J90", "Tràn dịch màng phổi"), ("J93", "Tràn khí màng phổi"),
    # --- Tiêu hóa (K00–K93)
    ("K02", "Sâu răng"), ("K04", "Bệnh tủy răng và tổ chức quanh chóp răng"), ("K05", "Viêm lợi và bệnh nha chu"), ("K21", "Bệnh trào ngược dạ dày - thực quản"),
    ("K25", "Loét dạ dày"), ("K26", "Loét tá tràng"), ("K30", "Khó tiêu chức năng"), ("K40", "Thoát vị bẹn"), ("K52", "Viêm dạ dày - ruột và viêm đại tràng không nhiễm khuẩn khác"),
    ("K57", "Bệnh túi thừa của ruột"), ("K58", "Hội chứng ruột kích thích"), ("K59", "Rối loạn chức năng ruột khác (táo bón)"), ("K70", "Bệnh gan do rượu"),
    ("K74", "Xơ gan"), ("K76", "Bệnh gan khác (gan nhiễm mỡ)"), ("K80", "Sỏi mật"), ("K81", "Viêm túi mật"), ("K85", "Viêm tụy cấp"), ("K92", "Bệnh khác của hệ tiêu hóa (xuất huyết tiêu hóa)"),
    # --- Da và mô dưới da (L00–L99)
    ("L02", "Áp xe da, nhọt, nhọt cụm"), ("L20", "Viêm da cơ địa"), ("L23", "Viêm da tiếp xúc dị ứng"), ("L30", "Viêm da khác"), ("L40", "Bệnh vảy nến"),
    ("L50", "Mày đay"), ("L70", "Trứng cá"), ("L89", "Loét do tì đè"), ("L08", "Nhiễm khuẩn khác của da và mô dưới da"),
    # --- Cơ, xương, khớp (M00–M99)
    ("M05", "Viêm khớp dạng thấp huyết thanh dương tính"), ("M10", "Bệnh gút"), ("M16", "Hư khớp háng"), ("M17", "Hư khớp gối"), ("M19", "Hư khớp khác (thoái hóa khớp)"),
    ("M25", "Rối loạn khớp khác (đau khớp, tràn dịch khớp)"), ("M32", "Lupus ban đỏ hệ thống"), ("M47", "Thoái hóa cột sống"), ("M51", "Thoát vị đĩa đệm"),
    ("M75", "Tổn thương vai"), ("M79", "Bệnh mô mềm khác (đau cơ)"), ("M81", "Loãng xương không có gãy xương bệnh lý"),
    # --- Tiết niệu - sinh dục (N00–N99)
    ("N10", "Viêm thận - bể thận cấp"), ("N18", "Bệnh thận mạn"), ("N20", "Sỏi thận và sỏi niệu quản"), ("N23", "Cơn đau quặn thận"), ("N30", "Viêm bàng quang"),
    ("N39", "Rối loạn khác của hệ tiết niệu (nhiễm khuẩn tiết niệu)"), ("N40", "Phì đại tuyến tiền liệt"), ("N41", "Bệnh viêm tuyến tiền liệt"),
    ("N45", "Viêm tinh hoàn và mào tinh hoàn"), ("N76", "Viêm âm đạo và âm hộ khác"), ("N92", "Kinh nguyệt nhiều, thường xuyên và không đều"),
    # --- Thai nghén (O00–O99), Z34
    ("O20", "Chảy máu sớm khi mang thai (dọa sảy)"), ("Z34", "Giám sát thai nghén bình thường"),
    # --- Triệu chứng, dấu hiệu (R00–R99)
    ("R00", "Bất thường nhịp tim"), ("R03", "Huyết áp tăng không có chẩn đoán tăng huyết áp"), ("R05", "Ho"), ("R06", "Bất thường về thở (khó thở)"),
    ("R07", "Đau họng và đau ngực"), ("R10", "Đau bụng và vùng chậu"), ("R11", "Buồn nôn và nôn"), ("R42", "Chóng mặt và rối loạn thăng bằng"),
    ("R51", "Đau đầu"), ("R52", "Đau, không phân loại nơi khác"), ("R53", "Mệt mỏi, khó chịu"), ("R56", "Co giật, không phân loại nơi khác"),
    ("R60", "Phù, không phân loại nơi khác"), ("R73", "Tăng đường huyết"),
    # --- Chấn thương, ngộ độc (S00–T98)
    ("S00", "Chấn thương nông ở đầu"), ("S01", "Vết thương hở ở đầu"), ("S06", "Chấn thương nội sọ"), ("S42", "Gãy xương vai và cánh tay"),
    ("S52", "Gãy xương cẳng tay"), ("S62", "Gãy xương cổ tay và bàn tay"), ("S72", "Gãy xương đùi"), ("S82", "Gãy xương cẳng chân"), ("S92", "Gãy xương bàn chân"),
    ("S93", "Trật khớp, bong gân cổ chân và bàn chân"), ("T14", "Chấn thương ở vùng cơ thể không xác định"), ("T30", "Bỏng, không xác định vị trí"),
    ("T39", "Ngộ độc thuốc giảm đau, hạ sốt, chống viêm không steroid"), ("T50", "Ngộ độc thuốc và chế phẩm sinh học khác"), ("T71", "Ngạt thở"),
    ("T78", "Tác dụng bất lợi, không phân loại nơi khác (dị ứng, sốc phản vệ)"),
    # --- Yếu tố ảnh hưởng tình trạng sức khỏe (Z00–Z99), mã đặc biệt
    ("Z02", "Khám vì mục đích hành chính"), ("Z03", "Theo dõi và đánh giá y tế đối với nghi ngờ bệnh"), ("Z09", "Khám theo dõi sau điều trị"),
    ("Z23", "Cần tiêm chủng"), ("Z51", "Chăm sóc y tế khác"), ("Z71", "Tư vấn và khuyến cáo y tế"), ("U07", "COVID-19"),
]

# Chất gây dị ứng thường gặp (gợi ý khi nhập dị ứng; vẫn cho nhập tự do)
COMMON_ALLERGENS: list[str] = [
    "Penicillin", "Amoxicillin", "Ampicillin", "Cephalosporin", "Sulfonamid (Cotrimoxazol)", "Aspirin", "Ibuprofen", "Diclofenac",
    "Paracetamol", "Tetracyclin", "Quinolon", "Macrolid", "Thuốc gây tê (Lidocain)", "Thuốc cản quang chứa iod", "Insulin",
    "Hải sản (tôm, cua)", "Cá", "Sữa", "Trứng", "Đậu phộng", "Gluten (lúa mì)", "Phấn hoa", "Bụi nhà / mạt bụi", "Lông chó mèo",
    "Latex (cao su)", "Nọc côn trùng (ong, kiến)", "Kim loại (Nickel)",
]
