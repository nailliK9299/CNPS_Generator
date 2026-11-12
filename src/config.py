# -*- coding: utf-8 -*-
"""
Cấu hình chung cho ứng dụng CNPS Generator.
"""
import glob
import os
import subprocess
import sys

# ─── Đường dẫn gốc (khác nhau khi chạy dev vs exe đóng gói) ───
def get_base_path() -> str:
    """Trả về thư mục gốc của ứng dụng."""
    if getattr(sys, 'frozen', False):
        # Đang chạy từ file exe / .app đóng gói bởi PyInstaller
        return os.path.dirname(sys.executable)
    # Đang chạy dev: thư mục cha của src/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_writable_base_path(base_path: str) -> str:
    """
    Trả về thư mục có quyền ghi để lưu output/ và data/fb_storage_state.json.
    Xử lý triệt để trường hợp macOS AppTranslocation (read-only), /Applications,
    bên trong gói .app/Contents/MacOS hoặc C:\\Program Files trên Windows.
    """
    candidates = []
    norm_base = base_path.replace("\\", "/")

    # Nếu đang chạy bên trong CNPS_Generator.app/Contents/MacOS trên macOS
    if ".app/Contents/MacOS" in norm_base:
        app_parent = os.path.abspath(os.path.join(base_path, "..", "..", ".."))
        if "/AppTranslocation/" not in app_parent and not app_parent.startswith("/Applications"):
            candidates.append(app_parent)
    else:
        candidates.append(base_path)

    # Fallback luôn ghi được trên mọi máy Windows / macOS
    candidates.append(os.path.expanduser("~/Documents/CNPS_Generator"))
    candidates.append(os.path.expanduser("~/.cnps_generator"))

    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            test_file = os.path.join(folder, ".cnps_write_test")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test_file)
            return folder
        except Exception:
            continue

    return candidates[-1]


def get_resource_path(relative_path: str) -> str:
    """
    Trả về đường dẫn tuyệt đối đến tài nguyên (template, data file,...).
    Hỗ trợ nạp chính xác trong môi trường PyInstaller (Windows & macOS .app) và Dev mode.
    """
    candidates = []
    
    # 1. Môi trường PyInstaller (_MEIPASS / _internal / Contents/Resources / Contents/Frameworks)
    if hasattr(sys, '_MEIPASS'):
        candidates.append(os.path.join(getattr(sys, '_MEIPASS'), relative_path))
        
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, '_internal', relative_path))
        candidates.append(os.path.join(exe_dir, relative_path))
        candidates.append(os.path.abspath(os.path.join(exe_dir, '..', 'Resources', relative_path)))
        candidates.append(os.path.abspath(os.path.join(exe_dir, '..', 'Frameworks', relative_path)))
        
    # 2. Môi trường Dev (BASE_PATH)
    candidates.append(os.path.join(BASE_PATH, relative_path))
    
    for path in candidates:
        if os.path.exists(path):
            return path
            
    return candidates[0]


BASE_PATH = get_base_path()
WRITABLE_BASE_PATH = get_writable_base_path(BASE_PATH)

# ─── Đường dẫn tài nguyên ───
TEMPLATE_PATH = get_resource_path(os.path.join("data", "CNPS template.docx"))
SAMPLE_XLSX_PATH = get_resource_path(os.path.join("data", "Bang_Ke_Mau.xlsx"))
SAMPLE_CSV_PATH = get_resource_path(os.path.join("data", "Bang_Ke_Mau.csv"))
FB_STORAGE_STATE_PATH = os.path.join(WRITABLE_BASE_PATH, "data", "fb_storage_state.json")
READABILITY_JS_PATH = get_resource_path(os.path.join("src", "core", "Readability.js"))
DEFAULT_OUTPUT_DIR = os.path.join(WRITABLE_BASE_PATH, "output")

# Đảm bảo thư mục output tồn tại (an toàn, không bao giờ văng PermissionError)
try:
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
except Exception:
    pass


# ─── Playwright / Chromium tự hành (Zero-Dependency trên máy mới) ───
def get_chromium_search_dirs() -> list[str]:
    """Danh sách các thư mục có thể chứa trình duyệt Chromium đóng gói kèm hoặc cache."""
    candidates = [
        get_resource_path("chromium"),
        os.path.join(BASE_PATH, "chromium"),
    ]
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.extend([
            os.path.join(exe_dir, "chromium"),
            os.path.join(exe_dir, "_internal", "chromium"),
            os.path.abspath(os.path.join(exe_dir, "..", "Resources", "chromium")),
            os.path.abspath(os.path.join(exe_dir, "..", "Frameworks", "chromium")),
        ])
        if hasattr(sys, '_MEIPASS'):
            candidates.append(os.path.join(getattr(sys, '_MEIPASS'), "chromium"))

    candidates.extend([
        os.path.expanduser("~/.cnps_generator/browsers"),
        os.path.expanduser(r"~\AppData\Local\ms-playwright"),
        os.path.expanduser("~/Library/Caches/ms-playwright"),
        os.path.expanduser("~/.cache/ms-playwright"),
    ])

    seen = set()
    unique = []
    for p in candidates:
        if p and p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _fix_macos_permissions(target_dir: str) -> None:
    """Gỡ cờ com.apple.quarantine và cấp quyền thực thi cho binary đi kèm trên macOS."""
    if sys.platform != "darwin" or not os.path.exists(target_dir):
        return
    try:
        subprocess.run(["xattr", "-cr", target_dir], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["chmod", "-R", "u+rx", target_dir], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def setup_playwright_browsers() -> str | None:
    """
    Thiết lập đường dẫn Playwright Chromium linh hoạt và gỡ chặn Gatekeeper trên macOS.
    Chỉ chọn thư mục thực sự có chứa gói trình duyệt chromium*.
    """
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        _fix_macos_permissions(exe_dir)
        _fix_macos_permissions(os.path.abspath(os.path.join(exe_dir, "..")))

    for path in get_chromium_search_dirs():
        if path and os.path.isdir(path):
            has_browser = bool(glob.glob(os.path.join(path, "chromium*")))
            if has_browser:
                _fix_macos_permissions(path)
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path
                return path

    return None


def find_bundled_chromium_executable(headless: bool = True) -> str | None:
    """
    Tìm đường dẫn tuyệt đối tới file thực thi Chromium đóng gói kèm theo ứng dụng.
    Truyền trực tiếp vào executable_path để không phụ thuộc mã revision của Playwright.
    """
    patterns_win_headless = [
        "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
        "chromium_headless_shell-*/chrome-win/chrome-headless-shell.exe",
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-win/chrome.exe",
    ]
    patterns_win_headed = [
        "chromium-*/chrome-win64/chrome.exe",
        "chromium-*/chrome-win/chrome.exe",
    ]
    patterns_mac_headless = [
        "chromium_headless_shell-*/chrome-*/chrome-headless-shell",
        "chromium-*/chrome-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chromium-*/chrome-*/Chromium.app/Contents/MacOS/Chromium",
    ]
    patterns_mac_headed = [
        "chromium-*/chrome-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chromium-*/chrome-*/Chromium.app/Contents/MacOS/Chromium",
    ]

    if sys.platform == "win32":
        patterns = patterns_win_headless if headless else patterns_win_headed
    elif sys.platform == "darwin":
        patterns = patterns_mac_headless if headless else patterns_mac_headed
    else:
        patterns = ["chromium_headless_shell-*/chrome-*/chrome-headless-shell", "chromium-*/chrome-*/chrome"]

    for base_dir in get_chromium_search_dirs():
        if not base_dir or not os.path.isdir(base_dir):
            continue
        for pat in patterns:
            matches = sorted(glob.glob(os.path.join(base_dir, pat)), reverse=True)
            for m in matches:
                if os.path.isfile(m):
                    _fix_macos_permissions(m)
                    return m
    return None


def find_system_browser_executables() -> list[str]:
    """
    Tìm các trình duyệt Chromium có sẵn trên hệ điều hành (Google Chrome, Microsoft Edge, Brave, Cốc Cốc).
    Giúp ứng dụng chạy được trên mọi máy tính mới kể cả khi thư mục chromium đi kèm bị thiếu/chặn.
    """
    candidates = []
    if sys.platform == "win32":
        prog_files = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
        ]
        rel_paths = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"CocCoc\Browser\Application\browser.exe",
        ]
        for root in prog_files:
            if root:
                for rel in rel_paths:
                    candidates.append(os.path.join(root, rel))
    elif sys.platform == "darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/CocCoc.app/Contents/MacOS/CocCoc",
        ])
    else:
        candidates.extend([
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/usr/bin/microsoft-edge",
        ])

    return [p for p in candidates if p and os.path.isfile(p)]


def install_chromium_via_bundled_driver() -> str | None:
    """
    Tự động tải Chromium bằng chính Node driver đóng gói sẵn bên trong ứng dụng
    (không cần máy người dùng cài sẵn Python, pip hay Playwright CLI).
    """
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env

        driver_executable, driver_cli = compute_driver_executable()
        target_dir = os.path.expanduser("~/.cnps_generator/browsers")
        os.makedirs(target_dir, exist_ok=True)
        env = get_driver_env()
        env["PLAYWRIGHT_BROWSERS_PATH"] = target_dir

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        subprocess.run(
            [str(driver_executable), str(driver_cli), "install", "chromium"],
            env=env,
            check=True,
            creationflags=creationflags,
        )
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = target_dir
        return target_dir
    except Exception:
        return None


async def launch_browser(playwright_instance, headless: bool = True):
    """
    Khởi chạy trình duyệt với chuỗi dự phòng 5 lớp, đảm bảo chạy được trên MỌI máy tính
    Windows / macOS mà không cần cài sẵn Python hay Playwright:
      1. Trình duyệt Chromium đóng gói kèm theo ứng dụng (executable_path trực tiếp)
      2. Trình duyệt mặc định qua PLAYWRIGHT_BROWSERS_PATH
      3. Trình duyệt có sẵn trên máy (Google Chrome / Microsoft Edge / Brave / Cốc Cốc)
      4. Playwright channel ('chrome' / 'msedge')
      5. Tự động tải Chromium qua Node driver đóng gói sẵn rồi khởi chạy
    """
    setup_playwright_browsers()
    common_args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    errors = []

    # Lớp 1: Bundled Chromium executable_path
    bundled_exe = find_bundled_chromium_executable(headless=headless)
    if bundled_exe:
        try:
            return await playwright_instance.chromium.launch(
                headless=headless,
                executable_path=bundled_exe,
                args=common_args,
            )
        except Exception as e:
            errors.append(f"Bundled({bundled_exe}): {e}")

    # Lớp 2: Default Playwright Chromium
    try:
        return await playwright_instance.chromium.launch(
            headless=headless,
            args=common_args,
        )
    except Exception as e:
        errors.append(f"Default: {e}")

    # Lớp 3: System browser executables (Chrome / Edge / Brave / Cốc Cốc)
    for sys_exe in find_system_browser_executables():
        try:
            return await playwright_instance.chromium.launch(
                headless=headless,
                executable_path=sys_exe,
                args=common_args,
            )
        except Exception as e:
            errors.append(f"System({sys_exe}): {e}")

    # Lớp 4: Playwright channels
    for channel in ("chrome", "msedge"):
        try:
            return await playwright_instance.chromium.launch(
                headless=headless,
                channel=channel,
                args=common_args,
            )
        except Exception as e:
            errors.append(f"Channel({channel}): {e}")

    # Lớp 5: Tự động tải Chromium bằng bundled driver (không cần Python/pip)
    installed_dir = install_chromium_via_bundled_driver()
    if installed_dir:
        bundled_exe = find_bundled_chromium_executable(headless=headless)
        if bundled_exe:
            return await playwright_instance.chromium.launch(
                headless=headless,
                executable_path=bundled_exe,
                args=common_args,
            )
        return await playwright_instance.chromium.launch(
            headless=headless,
            args=common_args,
        )

    raise RuntimeError(
        "Không thể khởi chạy trình duyệt để chụp ảnh.\n"
        "Vui lòng cài đặt Google Chrome hoặc Microsoft Edge trên máy tính.\n"
        f"Chi tiết: {'; '.join(errors[:2])}"
    )


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
# Lưu ý quan trọng: KHÔNG dùng [class*="ads"] hay [class*="ad-"] trực tiếp mà không loại trừ
# html/body/main/article vì nhiều báo (thanhnien.vn, vtcnews.vn, 2sao.vn) gắn class
# 'backgroundads', 'isads', 'load-news-detail', 'vads-desktop' ngay trên thẻ <html> hoặc <body>!
HIDE_ADS_CSS = """
/* Quảng cáo chuyên biệt (loại trừ html, body, main, article, section) */
ins.adsbygoogle,
[class*="adsbygoogle"]:not(html):not(body):not(main):not(article),
[class*="advertisement"]:not(html):not(body):not(main):not(article),
[id^="div-gpt-ad"], [id^="google_ads"], [id^="admzone"], [id^="ads_"],
[class^="ads-"]:not(html):not(body):not(main):not(article),
.ads-box, .box-ads, .banner-ads, .ad-container, .ad-slot, .ad-banner,
iframe[src*="doubleclick"], iframe[src*="googlesyndication"],
iframe[src*="facebook.com/plugins"], iframe[id*="google_ads"],

/* Popup / Modal / Floating / Cookie / Tooltip che tiêu đề (loại trừ html, body, main, article) */
.popup:not(html):not(body):not(main):not(article),
.modal:not(html):not(body):not(main):not(article),
[class*="popup"]:not(html):not(body):not(main):not(article),
[class*="cookie"]:not(html):not(body):not(main):not(article),
[class*="gdpr"]:not(html):not(body):not(main):not(article),
[class*="consent"]:not(html):not(body):not(main):not(article),
.k14topic-tooltip-wrapper,
[class*="k14topic-tooltip"],
[class*="tooltip-wrapper"],
[class*="hover-card"],
[class*="popover"]:not(html):not(body):not(main):not(article),

/* Bình luận / Footer trang web (không ẩn footer bài viết) */
.comment-section, #ykcb-form, .box-comment,
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
