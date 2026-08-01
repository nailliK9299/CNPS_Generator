# -*- coding: utf-8 -*-
"""
Module trích xuất và mapping dữ liệu Bảng kê Booking Quảng cáo (từ Google Sheet/Excel/CSV/Clipboard).
"""
import re
import csv
from datetime import datetime
from pathlib import Path
from utils.helpers import remove_vietnamese_diacritics

# Các từ khóa alias để nhận diện cột (theo đúng thứ tự ưu tiên)
COLUMN_ALIASES = {
    "hop_dong": ["hợp đồng", "mã hợp đồng", "hop dong", "ma hop dong", "mã hd", "hd"],
    "so_ht": ["số ht", "so ht"],
    "nhan_hang": ["nhãn", "nhãn hàng", "nhan", "nhan hang", "brand"],
    "chien_dich": ["chiến dịch", "chien dich", "campaign"],
    "noi_dung_khoan_muc": [
        "nội dung quảng cáo", "nội dung", "khoản mục", "noi dung quang cao",
        "noi dung", "khoan muc", "tên bài", "bài viết", "hạng mục",
        "tên khoản mục", "diễn giải", "bài pr", "tiêu đề", "nội dung bài", "tên nội dung"
    ],
    "ngay_dang": ["lịch đăng", "ngày đăng", "lich dang", "ngay dang", "ngày", "ngay", "date", "thời gian"],
    "so_luong": ["số lượng", "so luong", "sl", "qty"],
    "don_vi": ["đvt", "đơn vị", "don vi", "unit"],
    "link_bai": ["link bài", "link", "url", "link bai", "đường dẫn", "duong dan", "link bài viết", "link bài đăng"],
    "loai": ["loại", "loai", "loại bài", "kênh", "kenh", "loại tin", "type"],
}


def normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi text để so sánh alias."""
    if not text:
        return ""
    t = remove_vietnamese_diacritics(str(text)).strip().lower()
    t = re.sub(r'\s+', ' ', t)
    return t


def map_column_name(header_name: str) -> str | None:
    """Map tên cột trong file/clipboard sang field key chuẩn."""
    norm = normalize_text(header_name)
    if not norm or len(norm) > 30 or "http" in norm or ".com" in norm or ".vn" in norm:
        return None

    words = norm.split()
    if len(words) > 5:
        return None

    for field_key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = remove_vietnamese_diacritics(alias).strip().lower()
            if norm_alias == norm:
                return field_key
            if norm.startswith(norm_alias) and len(norm) <= len(norm_alias) + 8:
                return field_key
    return None


def format_date_string(date_val: str) -> str:
    """
    Chuẩn hóa các định dạng ngày về dd/mm/yyyy.
    Ví dụ: '2/4/2026' -> '02/04/2026', '2026-02-04' -> '04/02/2026'.
    """
    if not date_val:
        return datetime.now().strftime("%d/%m/%Y")
    
    date_str = str(date_val).strip()
    if " " in date_str:
        date_str = date_str.split(" ")[0]
        
    formats = [
        "%d/%m/%Y", "%d-%m-%Y",
        "%d/%m/%y", "%d-%m-%y",
        "%Y-%m-%d", "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
            
    parts = re.split(r'[/\-.]', date_str)
    if len(parts) == 3:
        try:
            p1, p2, p3 = int(parts[0]), int(parts[1]), int(parts[2])
            if p3 > 1000: # d/m/yyyy
                d, m, y = p1, p2, p3
            elif p1 > 1000: # yyyy-m-d
                y, m, d = p1, p2, p3
            else:
                d, m, y = p1, p2, (p3 + 2000 if p3 < 100 else p3)
            return f"{d:02d}/{m:02d}/{y:04d}"
        except Exception:
            pass
            
    return date_str


def detect_article_type(url: str) -> str:
    """Tự động nhận diện loại bài Báo chí hay Facebook dựa vào URL."""
    url_lower = str(url).lower()
    if any(domain in url_lower for domain in ["facebook.com", "fb.com", "fb.watch", "fb.gg"]):
        return "Facebook"
    return "Báo chí"


def extract_header_metadata(lines_or_rows: list[list[str]]) -> dict:
    """
    Trích xuất các thông tin chung từ các dòng tiêu đề trên của Bảng kê:
    Bên A: ..., Nhãn: ..., Chiến dịch: ...
    """
    meta = {}
    for row in lines_or_rows[:15]:  # Chỉ tìm 15 dòng đầu
        row_str = " ".join([str(c) for c in row if c])
        
        # Bên A (Khách hàng)
        if "Bên A:" in row_str or "Ben A:" in row_str:
            m = re.search(r'Bên A:\s*(.+)', row_str, re.IGNORECASE)
            if m:
                meta["ten_khach_hang"] = m.group(1).split("Bên B")[0].split("Người đại diện")[0].strip()
                
        # Nhãn
        if "Nhãn:" in row_str or "Nhan:" in row_str:
            m = re.search(r'Nhãn:\s*(.+)', row_str, re.IGNORECASE)
            if m:
                meta["nhan_hang"] = m.group(1).split("Chiến dịch")[0].strip()
                
        # Chiến dịch
        if "Chiến dịch:" in row_str or "Chien dich:" in row_str:
            m = re.search(r'Chiến dịch:\s*(.+)', row_str, re.IGNORECASE)
            if m:
                meta["chien_dich"] = m.group(1).strip()
                
    return meta


def parse_rows_data(rows: list[dict]) -> list[dict]:
    """
    Chuyển đổi các dòng dict thô thành danh sách khoản mục chuẩn cho CNPS.
    """
    items = []
    for row in rows:
        item_mapped = {}
        for col_name, val in row.items():
            field_key = map_column_name(col_name)
            if field_key and val is not None and str(val).strip():
                if field_key not in item_mapped:
                    item_mapped[field_key] = str(val).strip()
        
        if "hop_dong" not in item_mapped and "so_ht" in item_mapped:
            item_mapped["hop_dong"] = item_mapped["so_ht"]
            
        link = item_mapped.get("link_bai", "").strip()
        noi_dung = item_mapped.get("noi_dung_khoan_muc", "").strip()
        
        if not link and not noi_dung:
            continue
            
        item = {
            "hop_dong": item_mapped.get("hop_dong", ""),
            "nhan_hang": item_mapped.get("nhan_hang", ""),
            "chien_dich": item_mapped.get("chien_dich", ""),
            "noi_dung_khoan_muc": noi_dung or link,
            "link_bai": link or noi_dung,
            "loai": item_mapped.get("loai") or detect_article_type(link),
            "don_vi": item_mapped.get("don_vi") or "Bài",
            "so_luong": item_mapped.get("so_luong") or "1",
            "ngay_dang": format_date_string(item_mapped.get("ngay_dang", "")),
        }
        items.append(item)
    return items


def parse_csv_or_excel_file(filepath: str | Path) -> tuple[list[dict], dict]:
    """
    Đọc file CSV, TSV hoặc Excel (.xlsx, .xls) của Bảng kê Booking.
    Returns:
        (items, metadata)
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()
    
    all_rows = []
    metadata = {}
    
    if ext in [".xlsx", ".xls"]:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(filepath), data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(values_only=True):
                all_rows.append([str(c) if c is not None else "" for c in row])
        except Exception as e:
            raise ValueError(f"Lỗi đọc file Excel: {e}")
    else: # CSV / TSV
        encodings = ["utf-8-sig", "utf-8", "cp1252", "utf-16", "utf-16-le"]
        content = None
        for enc in encodings:
            try:
                with open(filepath, "r", encoding=enc) as f:
                    content = f.read()
                break
            except Exception:
                continue
                
        if not content:
            raise ValueError("Không đọc được mã hóa file CSV/TSV.")
            
        delimiter = "\t" if "\t" in content and content.count("\t") > content.count(",") else ","
        lines = content.splitlines()
        reader = csv.reader(lines, delimiter=delimiter)
        all_rows = list(reader)

    if not all_rows:
        return [], {}

    metadata = extract_header_metadata(all_rows)

    header_idx = -1
    best_matches = 0
    for idx, row in enumerate(all_rows[:10]):
        matches = 0
        for cell in row:
            if map_column_name(cell) is not None:
                matches += 1
        if matches > best_matches:
            best_matches = matches
            header_idx = idx

    raw_dict_rows = []
    if header_idx != -1 and best_matches >= 1:
        headers = all_rows[header_idx]
        for row in all_rows[header_idx + 1:]:
            if any(str(cell).strip() for cell in row):
                row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                raw_dict_rows.append(row_dict)
        items = parse_rows_data(raw_dict_rows)
    else:
        items = parse_rows_without_headers(all_rows, metadata)

    return items, metadata


def _is_url(val: str) -> bool:
    if not val:
        return False
    v = val.strip().lower()
    if v.startswith(("http://", "https://", "www.")):
        return True
    if any(domain in v for domain in [
        "facebook.com", "fb.com", "fb.watch", "kenh14.vn", "vnexpress.net",
        "dantri.com.vn", "znews.vn", "tuoitre.vn", "thanhnien.vn",
        "vietnamnet.vn", "vtv.vn", "24h.com.vn", "laodong.vn", "tienphong.vn"
    ]):
        return True
    if re.search(r'https?://[^\s]+', val, re.I):
        return True
    if re.search(r'\b[\w\-]+\.(com|vn|net|org|gov|edu|me|co|info|tv|io|site|online)(?:/[^\s]*)?$', v):
        return True
    return False


def _is_date(val: str) -> bool:
    if not val:
        return False
    v = val.strip()
    return bool(re.search(r'^\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\s*$', v) or re.search(r'^\s*\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}\s*$', v))


def _is_unit(val: str) -> bool:
    if not val:
        return False
    v = remove_vietnamese_diacritics(val).strip().lower()
    return v in ["bai", "post", "suat", "goi", "tap", "lan", "clip", "video", "banner", "trang", "unit"]


def _is_type(val: str) -> bool:
    if not val:
        return False
    v = remove_vietnamese_diacritics(val).strip().lower()
    return v in ["bao chi", "facebook", "fb", "social", "fanpage", "group", "youtube", "tiktok"]


def _is_qty(val: str) -> bool:
    if not val:
        return False
    v = val.strip()
    return v.isdigit() and 1 <= int(v) <= 999


def parse_rows_without_headers(all_rows: list[list[str]], metadata: dict) -> list[dict]:
    """
    Phân tích thông minh các dòng dữ liệu không chứa tiêu đề (dán từ Clipboard hoặc file không header).
    Tự động phân tích kiểu dữ liệu và vị trí các cột để trích xuất chính xác.
    """
    if not all_rows:
        return []

    data_rows = []
    for row in all_rows:
        cells = [str(c).strip() for c in row]
        if not any(cells):
            continue
        
        # Bỏ qua nếu là dòng header thực sự
        has_url = any(_is_url(c) for c in cells)
        header_matches = sum(1 for c in cells if map_column_name(c) is not None)
        if not has_url and header_matches >= 2:
            continue

        # Bỏ qua dòng metadata chung
        row_str = " ".join(cells)
        if any(k in row_str for k in ["Bên A:", "Ben A:", "Bên B:", "Người đại diện"]):
            continue
        data_rows.append(row)

    if not data_rows:
        return []

    max_cols = max(len(r) for r in data_rows)

    # Phân tích từng cột
    col_info = {}
    for c in range(max_cols):
        vals = [r[c].strip() for r in data_rows if c < len(r) and r[c].strip()]
        n_v = len(vals)
        if n_v == 0:
            col_info[c] = {"empty": True}
            continue

        url_cnt = sum(1 for v in vals if _is_url(v))
        date_cnt = sum(1 for v in vals if _is_date(v))
        unit_cnt = sum(1 for v in vals if _is_unit(v))
        type_cnt = sum(1 for v in vals if _is_type(v))
        qty_cnt = sum(1 for v in vals if _is_qty(v))
        pct_cnt = sum(1 for v in vals if v.endswith("%") or ("%" in v))
        large_num_cnt = sum(1 for v in vals if v.isdigit() and int(v) >= 1000)
        avg_len = sum(len(v) for v in vals) / n_v

        col_info[c] = {
            "empty": False,
            "vals": vals,
            "url_ratio": url_cnt / n_v,
            "date_ratio": date_cnt / n_v,
            "unit_ratio": unit_cnt / n_v,
            "type_ratio": type_cnt / n_v,
            "qty_ratio": qty_cnt / n_v,
            "is_finance": (pct_cnt / n_v > 0.3) or (large_num_cnt / n_v > 0.3),
            "avg_len": avg_len,
        }

    link_col = None
    date_col = None
    unit_col = None
    type_col = None
    qty_col = None
    stt_col = None

    best_url_r = 0
    for c, info in col_info.items():
        if not info.get("empty") and info["url_ratio"] > best_url_r and info["url_ratio"] >= 0.3:
            best_url_r = info["url_ratio"]
            link_col = c

    best_date_r = 0
    for c, info in col_info.items():
        if c == link_col or info.get("empty"):
            continue
        if info["date_ratio"] > best_date_r and info["date_ratio"] >= 0.3:
            best_date_r = info["date_ratio"]
            date_col = c

    best_unit_r = 0
    for c, info in col_info.items():
        if c in {link_col, date_col} or info.get("empty"):
            continue
        if info["unit_ratio"] > best_unit_r and info["unit_ratio"] >= 0.3:
            best_unit_r = info["unit_ratio"]
            unit_col = c

    best_type_r = 0
    for c, info in col_info.items():
        if c in {link_col, date_col, unit_col} or info.get("empty"):
            continue
        if info["type_ratio"] > best_type_r and info["type_ratio"] >= 0.3:
            best_type_r = info["type_ratio"]
            type_col = c

    if 0 in col_info and not col_info[0].get("empty"):
        v0 = col_info[0]["vals"]
        if all(v.isdigit() for v in v0) and len(v0) > 0:
            stt_col = 0

    best_qty_r = 0
    for c, info in col_info.items():
        if c in {link_col, date_col, unit_col, type_col, stt_col} or info.get("empty"):
            continue
        if info["qty_ratio"] > best_qty_r and info["qty_ratio"] >= 0.3:
            best_qty_r = info["qty_ratio"]
            qty_col = c

    assigned_cols = {c for c in [link_col, date_col, unit_col, type_col, qty_col, stt_col] if c is not None}

    text_cols = []
    for c in range(max_cols):
        if c in assigned_cols:
            continue
        info = col_info.get(c, {})
        if info.get("empty") or info.get("is_finance"):
            continue
        text_cols.append(c)

    hop_dong_col = None
    nhan_hang_col = None
    chien_dich_col = None
    noi_dung_col = None

    if text_cols:
        if date_col is not None and (date_col - 1) in text_cols:
            noi_dung_col = date_col - 1
        elif 5 in text_cols:
            noi_dung_col = 5
        elif 4 in text_cols and stt_col is None:
            noi_dung_col = 4
        else:
            noi_dung_col = max(text_cols, key=lambda c: col_info[c]["avg_len"])

        remaining_text_cols = [c for c in text_cols if c != noi_dung_col]

        if stt_col == 0:
            if 1 in remaining_text_cols:
                hop_dong_col = 1
            if 3 in remaining_text_cols:
                nhan_hang_col = 3
            if 4 in remaining_text_cols and noi_dung_col != 4:
                chien_dich_col = 4
        elif stt_col is None:
            if 0 in remaining_text_cols:
                hop_dong_col = 0
            if 2 in remaining_text_cols:
                nhan_hang_col = 2
            if 3 in remaining_text_cols and noi_dung_col != 3:
                chien_dich_col = 3

        unassigned_text = [c for c in remaining_text_cols if c not in {hop_dong_col, nhan_hang_col, chien_dich_col}]
        for c in unassigned_text:
            if hop_dong_col is None:
                hop_dong_col = c
            elif nhan_hang_col is None:
                nhan_hang_col = c
            elif chien_dich_col is None:
                chien_dich_col = c

    items = []
    for r in data_rows:
        def get_val(col_idx):
            if col_idx is not None and col_idx < len(r):
                return r[col_idx].strip()
            return ""

        link = get_val(link_col)
        noi_dung = get_val(noi_dung_col)
        hop_dong = get_val(hop_dong_col)
        nhan_hang = get_val(nhan_hang_col)
        chien_dich = get_val(chien_dich_col)
        ngay = get_val(date_col)
        don_vi = get_val(unit_col)
        so_luong = get_val(qty_col)
        loai = get_val(type_col)

        if not link and not noi_dung:
            for cell in r:
                c_str = str(cell).strip()
                if _is_url(c_str):
                    link = c_str
                elif len(c_str) > 2 and not _is_date(c_str) and not c_str.isdigit():
                    if not noi_dung:
                        noi_dung = c_str

        if not link and not noi_dung:
            continue

        item = {
            "hop_dong": hop_dong or metadata.get("hop_dong", ""),
            "nhan_hang": nhan_hang or metadata.get("nhan_hang", ""),
            "chien_dich": chien_dich or metadata.get("chien_dich", ""),
            "noi_dung_khoan_muc": noi_dung or link,
            "link_bai": link or noi_dung,
            "loai": loai or detect_article_type(link),
            "don_vi": don_vi or "Bài",
            "so_luong": so_luong or "1",
            "ngay_dang": format_date_string(ngay),
        }
        items.append(item)

    return items


def parse_clipboard_text(text: str) -> tuple[list[dict], dict]:
    """
    Đọc dữ liệu dán trực tiếp từ Clipboard (Google Sheet / Excel).
    Hỗ trợ cả trường hợp bôi đen có Dòng Header hoặc chỉ bôi đen các Dòng Dữ Liệu thuần.
    Returns:
        (items, metadata)
    """
    if not text or not text.strip():
        return [], {}

    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return [], {}

    sample_line = lines[0]
    delimiter = "\t"
    if "\t" not in sample_line:
        if "," in sample_line:
            delimiter = ","
        elif ";" in sample_line:
            delimiter = ";"

    reader = csv.reader(lines, delimiter=delimiter)
    all_rows = list(reader)
    if not all_rows:
        return [], {}

    metadata = extract_header_metadata(all_rows)

    # 1. Tìm dòng header tốt nhất dựa trên các từ khóa alias
    header_idx = -1
    best_matches = 0
    for idx, row in enumerate(all_rows[:10]):
        matches = 0
        for cell in row:
            if map_column_name(cell) is not None:
                matches += 1
        if matches > best_matches:
            best_matches = matches
            header_idx = idx

    # Nếu tìm thấy dòng header hợp lệ
    if header_idx != -1 and best_matches >= 1:
        headers = all_rows[header_idx]
        raw_dict_rows = []
        for row in all_rows[header_idx + 1:]:
            if any(str(cell).strip() for cell in row):
                row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                raw_dict_rows.append(row_dict)
        items = parse_rows_data(raw_dict_rows)
        if items and any(i.get("link_bai") and ("http" in i["link_bai"] or "." in i["link_bai"]) for i in items):
            return items, metadata

    # 2. Phân tích tự động các dòng dữ liệu không có dòng tiêu đề
    items = parse_rows_without_headers(all_rows, metadata)
    return items, metadata
