# -*- coding: utf-8 -*-
"""
Hàm tiện ích dùng chung.
"""
import os
import re
import unicodedata
from datetime import datetime


def sanitize_filename(text: str) -> str:
    """
    Loại bỏ ký tự không hợp lệ trong tên file Windows.
    Giữ lại chữ, số, dấu gạch ngang, gạch dưới, dấu chấm.
    """
    # Bỏ dấu tiếng Việt
    text = remove_vietnamese_diacritics(text)
    # Thay khoảng trắng bằng gạch dưới
    text = text.strip().replace(" ", "_")
    # Loại bỏ ký tự đặc biệt
    text = re.sub(r'[^\w\-.]', '', text)
    # Loại bỏ gạch dưới thừa
    text = re.sub(r'_+', '_', text)
    return text.strip('_')


def remove_vietnamese_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt (giữ nguyên chữ cái gốc)."""
    # Chuẩn hoá Unicode decomposed
    nfkd = unicodedata.normalize('NFKD', text)
    # Bỏ combining characters (dấu)
    no_diacritics = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Xử lý riêng đ/Đ (NFKD không decompose được)
    no_diacritics = no_diacritics.replace('đ', 'd').replace('Đ', 'D')
    return no_diacritics


def generate_output_filename(data: dict) -> str:
    """
    Tạo tên file CNPS theo mẫu:
    CNPS_{TenVietTat}_{HopDong}_{Nhan}_{ChienDich}_{ddMMyyyy}.docx
    
    Ví dụ: CNPS_MMS_QC1900226_SAMSUNG_Miracle_28022026.docx
    """
    parts = [
        "CNPS",
        sanitize_filename(data.get("ten_viet_tat", "")),
        sanitize_filename(data.get("hop_dong", "")),
        sanitize_filename(data.get("nhan_hang", "")),
        sanitize_filename(data.get("chien_dich", "")),
    ]
    
    # Ngày đăng: từ dd/mm/yyyy → ddMMyyyy
    ngay_dang = data.get("ngay_dang", "")
    try:
        dt = datetime.strptime(ngay_dang, "%d/%m/%Y")
        parts.append(dt.strftime("%d%m%Y"))
    except ValueError:
        # Nếu format sai, dùng nguyên giá trị đã sanitize
        parts.append(sanitize_filename(ngay_dang))
    
    filename = "_".join(p for p in parts if p) + ".docx"
    return filename


def open_folder_in_explorer(path: str) -> None:
    """Mở thư mục trong Windows Explorer."""
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    os.startfile(folder)
