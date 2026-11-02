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


def get_unique_output_path(
    output_dir: str,
    filename: str,
    used_paths: set[str] | None = None,
    force_index: int | None = None,
) -> str:
    """
    Đảm bảo đường dẫn file đầu ra là duy nhất, không bao giờ ghi đè lên file
    đã tồn tại trên ổ đĩa hoặc file vừa tạo trong cùng đợt chạy.
    """
    stem, ext = os.path.splitext(filename)
    if not ext:
        ext = ".docx"

    def _is_taken(path_str: str) -> bool:
        norm = os.path.normcase(os.path.abspath(path_str))
        if used_paths is not None and norm in used_paths:
            return True
        return os.path.exists(path_str)

    if force_index is not None:
        counter = max(1, force_index)
        while True:
            candidate = os.path.join(output_dir, f"{stem}_{counter:02d}{ext}")
            if not _is_taken(candidate):
                if used_paths is not None:
                    used_paths.add(os.path.normcase(os.path.abspath(candidate)))
                return candidate
            counter += 1

    candidate = os.path.join(output_dir, f"{stem}{ext}")
    if not _is_taken(candidate):
        if used_paths is not None:
            used_paths.add(os.path.normcase(os.path.abspath(candidate)))
        return candidate

    counter = 2
    while True:
        candidate = os.path.join(output_dir, f"{stem}_{counter:02d}{ext}")
        if not _is_taken(candidate):
            if used_paths is not None:
                used_paths.add(os.path.normcase(os.path.abspath(candidate)))
            return candidate
        counter += 1


def open_folder_in_explorer(path: str) -> None:
    """Mở thư mục hoặc file trong Windows Explorer / Finder (macOS)."""
    import subprocess
    import sys

    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if sys.platform == "darwin":
        subprocess.run(["open", folder], check=False)
    elif hasattr(os, "startfile"):
        os.startfile(folder)
    else:
        subprocess.run(["xdg-open", folder], check=False)
