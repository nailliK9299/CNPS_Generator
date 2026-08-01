# -*- coding: utf-8 -*-
"""
Cấu hình chung cho ứng dụng CNPS Generator.
"""
import os
import sys

# ─── Đường dẫn gốc (khác nhau khi chạy dev vs exe đóng gói) ───
def get_base_path() -> str:
    """Trả về thư mục gốc của ứng dụng."""
    if getattr(sys, 'frozen', False):
        # Đang chạy từ file exe đóng gói bởi PyInstaller
        return os.path.dirname(sys.executable)
    # Đang chạy dev: thư mục cha của src/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str) -> str:
    """
    Trả về đường dẫn tuyệt đối đến tài nguyên (template, data file,...).
    Hỗ trợ nạp chính xác trong môi trường PyInstaller và Dev mode.
    """
    candidates = []
    
    # 1. Môi trường PyInstaller (_MEIPASS / _internal)
    if hasattr(sys, '_MEIPASS'):
        candidates.append(os.path.join(getattr(sys, '_MEIPASS'), relative_path))
        
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, '_internal', relative_path))
        candidates.append(os.path.join(exe_dir, relative_path))
        
    # 2. Môi trường Dev (BASE_PATH)
    candidates.append(os.path.join(BASE_PATH, relative_path))
    
    for path in candidates:
        if os.path.exists(path):
            return path
            
    return candidates[0]


BASE_PATH = get_base_path()

# ─── Đường dẫn tài nguyên ───
TEMPLATE_PATH = get_resource_path(os.path.join("data", "CNPS template.docx"))
SAMPLE_XLSX_PATH = get_resource_path(os.path.join("data", "Bang_Ke_Mau.xlsx"))
SAMPLE_CSV_PATH = get_resource_path(os.path.join("data", "Bang_Ke_Mau.csv"))
FB_STORAGE_STATE_PATH = os.path.join(BASE_PATH, "data", "fb_storage_state.json")
READABILITY_JS_PATH = get_resource_path(os.path.join("src", "core", "Readability.js"))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_PATH, "output")

# Đảm bảo thư mục output tồn tại
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

# ─── Playwright / Chromium ───
def setup_playwright_browsers() -> str | None:
    """
    Thiết lập đường dẫn Playwright Chromium linh hoạt:
    1. Thư mục chromium bên cạnh exe / dev workspace
    2. Thư mục ms-playwright chuẩn trong %USERPROFILE%/AppData/Local/ms-playwright
    """
    candidates = [
        get_resource_path("chromium"),
        os.path.join(BASE_PATH, "chromium"),
    ]
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "chromium"))
        candidates.append(os.path.join(exe_dir, "_internal", "chromium"))
        
    user_appdata_playwright = os.path.expanduser(r"~\AppData\Local\ms-playwright")
    candidates.append(user_appdata_playwright)
    
    for path in candidates:
        if path and os.path.isdir(path):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path
            return path
            
    return None


CHROMIUM_PATH = setup_playwright_browsers()

# ─── Viewport & Screenshot ───
VIEWPORT_WIDTH = 1080          # px — tối ưu cho bài báo, chữ to rõ nét khi in ấn A4
VIEWPORT_HEIGHT = 900          # px — chiều cao cửa sổ ban đầu
DEVICE_SCALE_FACTOR = 3        # 3x Retina — ảnh sắc nét 3K siêu mịn khi in A4
A4_RATIO = 1.4142              # Tỷ lệ chiều cao / chiều rộng khổ A4

# Chiều cao tối đa mỗi "trang" ảnh, tính bằng px CSS (đảm bảo không bao giờ tràn vùng in A4 25.5cm)
TARGET_PAGE_HEIGHT_PX = int(VIEWPORT_WIDTH * 1.50)  # ~1620px

# ─── Kích thước ảnh trong DOCX ───
# Trang A4: 21.0cm rộng, margin trái+phải = 2.54 + 2.54 = 5.08cm → vùng in = 15.92cm
IMAGE_WIDTH_CM = 15.92

# ─── Scroll settings ───
SCROLL_STEP_PX = 400           # Khoảng cách mỗi bước scroll (px)
SCROLL_DELAY_MS = 250          # Delay giữa mỗi bước scroll (ms)
POST_CLEANUP_WAIT_MS = 1000    # Chờ sau khi dọn giao diện trước khi chụp

# ─── CSS ẩn quảng cáo / popup / widget (áp dụng chung mọi domain) ───
HIDE_ADS_CSS = """
/* Quảng cáo */
[class*="ads"], [class*="advertisement"], [id*="ads"],
[class*="adsbygoogle"], [class*="ad-"], [id*="ad-"],
iframe[src*="doubleclick"], iframe[src*="googlesyndication"],
iframe[src*="facebook.com/plugins"],

/* Banner */
[class*="banner"]:not(header):not([class*="header"]),

/* Popup / Modal / Floating */
.popup, .modal, [class*="popup"], [class*="modal"],
[class*="floating"], [class*="overlay"],
[class*="cookie"], [class*="gdpr"], [class*="consent"],

/* Feedback / Widget */
[class*="feedback"], [id*="feedback"],
[class*="social-share"], [class*="share-bar"],
[class*="widget"]:not([class*="content"]),

/* Bài liên quan / Bình luận / Footer trang web (không ẩn footer bài viết) */
[class*="related"], [id*="related"],
[class*="comment"], [id*="comment"], .comment-section,
.site-footer, .page-footer, #site-footer, #footer-site
{
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    max-height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: hidden !important;
}
"""

# ─── Tên ứng dụng ───
APP_TITLE = "CNPS Generator — Chứng Nhận Phát Sóng"
APP_VERSION = "1.0.0"
