# -*- coding: utf-8 -*-
"""
Logic chụp screenshot bài báo / bài Facebook bằng Playwright (Python).

Hỗ trợ 2 loại:
- "bao_chi": bài báo điện tử (dùng Readability.js để nhận diện nội dung)
- "facebook": bài Facebook (dùng storage_state để đăng nhập)
"""
import asyncio
import logging
import os
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

from config import (
    VIEWPORT_WIDTH, VIEWPORT_HEIGHT, DEVICE_SCALE_FACTOR,
    TARGET_PAGE_HEIGHT_PX, HIDE_ADS_CSS,
    SCROLL_STEP_PX, SCROLL_DELAY_MS, POST_CLEANUP_WAIT_MS,
    FB_STORAGE_STATE_PATH,
)
from core.image_processor import smart_paginate

logger = logging.getLogger(__name__)

import sys

# ─── Đường dẫn Readability.js bundle ───
_readability_js_cache: str | None = None


def _get_readability_path() -> str:
    """Tìm đường dẫn tới Readability.js hỗ trợ cả dev mode và PyInstaller."""
    candidates = []
    
    # 1. Thư mục chứa file screenshot.py
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(current_dir, "Readability.js"))
    
    # 2. Môi trường PyInstaller (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        meipass = getattr(sys, "_MEIPASS")
        candidates.append(os.path.join(meipass, "core", "Readability.js"))
        candidates.append(os.path.join(meipass, "src", "core", "Readability.js"))
    
    # 3. Môi trường sys.executable (_internal)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "_internal", "core", "Readability.js"))
        candidates.append(os.path.join(exe_dir, "_internal", "src", "core", "Readability.js"))
    
    # 4. Fallback BASE_PATH
    try:
        from config import BASE_PATH
        candidates.append(os.path.join(BASE_PATH, "src", "core", "Readability.js"))
    except Exception:
        pass
    
    for path in candidates:
        if os.path.isfile(path):
            return path
            
    return candidates[0]


def _load_readability_js() -> str:
    """Đọc file Readability.js (cache lần đầu)."""
    global _readability_js_cache
    if _readability_js_cache is None:
        target_path = _get_readability_path()
        with open(target_path, "r", encoding="utf-8") as f:
            _readability_js_cache = f.read()
    return _readability_js_cache


class SessionExpiredError(Exception):
    """Session Facebook đã hết hạn."""
    pass


class ContentDetectionError(Exception):
    """Không xác định được vùng nội dung chính."""
    pass


# ══════════════════════════════════════════════
# API chính — gọi từ GUI
# ══════════════════════════════════════════════

def capture_screenshots(
    url: str,
    article_type: str,
    output_dir: str | Path,
    progress_callback=None,
) -> list[Path]:
    """
    Chụp screenshot bài báo/Facebook, phân trang, trả về danh sách file ảnh.
    
    Args:
        url: URL bài viết
        article_type: "Báo chí" hoặc "Facebook"
        output_dir: Thư mục lưu ảnh tạm
        progress_callback: Hàm callback(message: str) để báo tiến trình
    
    Returns:
        Danh sách Path đến các file ảnh đã phân trang
    
    Raises:
        SessionExpiredError: Session Facebook hết hạn
        ContentDetectionError: Không xác định được nội dung
        Exception: Lỗi khác (timeout, 404, ...)
    """
    def _cb(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)
    
    # Chạy async trong sync context
    return asyncio.run(_capture_async(url, article_type, output_dir, _cb))


async def _capture_async(
    url: str,
    article_type: str,
    output_dir: str | Path,
    cb,
) -> list[Path]:
    """Dispatcher async cho 2 loại bài."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if article_type == "Facebook":
        return await _capture_facebook(url, output_dir, cb)
    else:
        return await _capture_article(url, output_dir, cb)


# ══════════════════════════════════════════════
# Chụp bài báo điện tử
# ══════════════════════════════════════════════

async def _capture_article(
    url: str,
    output_dir: Path,
    cb,
) -> list[Path]:
    """
    Flow chụp bài báo:
    1. Mở trang (viewport desktop, scale 2x)
    2. Auto-scroll kích lazy-load
    3. Dọn giao diện (ẩn ads, ép fixed→static)
    4. Xác định vùng nội dung (Readability.js)
    5. Chụp ảnh dài (clip)
    6. Lấy toạ độ khối nội dung con
    7. Phân trang thông minh (Pillow)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                device_scale_factor=DEVICE_SCALE_FACTOR,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            
            # 1. Navigate
            cb("Đang mở trang...")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception as e:
                # Thử lại với wait_until="domcontentloaded" nếu networkidle timeout
                logger.warning(f"networkidle timeout, thử domcontentloaded: {e}")
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            
            # Kiểm tra trang 404/lỗi
            if page.url.endswith("/404") or "not found" in (await page.title()).lower():
                raise Exception(f"Trang không tồn tại (404): {url}")
            
            # 2. Auto-scroll
            cb("Đang scroll để tải nội dung...")
            await _auto_scroll(page)
            
            # 3. Dọn giao diện
            cb("Đang dọn quảng cáo, popup...")
            await _cleanup_page(page)
            await _fix_relative_dates(page, url)
            await page.wait_for_timeout(POST_CLEANUP_WAIT_MS)
            
            # 4. Xác định vùng nội dung
            cb("Đang xác định vùng nội dung bài viết...")
            content_bounds = await _detect_content_bounds(page)
            
            if content_bounds is None:
                logger.warning(f"Không xác định được nội dung — chụp full page: {url}")
                cb("⚠️ Không tìm được vùng nội dung — chụp toàn trang")
                # Fallback: chụp full page
                full_height = await page.evaluate("document.documentElement.scrollHeight")
                content_bounds = {
                    "top": 0,
                    "bottom": full_height,
                    "left": 0,
                    "width": VIEWPORT_WIDTH,
                }
            
            # 5. Chụp ảnh full page rồi crop bằng Pillow
            cb("Đang chụp ảnh...")
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)
            
            full_screenshot_bytes = await page.screenshot(
                full_page=True,
                type="png",
            )
            
            # Crop ảnh theo content_bounds (tính bằng CSS px → nhân scale)
            from PIL import Image as _Image
            import io as _io
            _full_img = _Image.open(_io.BytesIO(full_screenshot_bytes))
            scale = DEVICE_SCALE_FACTOR
            crop_top = 0
            crop_bottom = min(int(content_bounds["bottom"] * scale), _full_img.height)
            
            # Luôn giữ trọn vẹn toàn bộ chiều rộng trang (x=0 -> full width) để không cắt xén lề trái và đảm bảo tỷ lệ vừa khít khổ A4
            crop_left = 0
            crop_right = _full_img.width
                
            _cropped = _full_img.crop((crop_left, crop_top, crop_right, crop_bottom))
            _buf = _io.BytesIO()
            _cropped.save(_buf, format="PNG")
            screenshot_bytes = _buf.getvalue()
            del _full_img, _cropped, _buf
            
            # 6. Lấy toạ độ khối nội dung con
            cb("Đang phân tích cấu trúc trang...")
            block_positions = await _get_block_positions(page, content_bounds)
            
            # 7. Phân trang thông minh
            cb("Đang phân trang ảnh...")
            page_images = smart_paginate(
                screenshot_bytes=screenshot_bytes,
                block_positions=block_positions,
                target_page_height=TARGET_PAGE_HEIGHT_PX,
                output_dir=output_dir,
                device_scale_factor=DEVICE_SCALE_FACTOR,
            )
            
            cb(f"✅ Đã chụp {len(page_images)} trang")
            return page_images
            
        finally:
            await browser.close()


async def _auto_scroll(page: Page) -> None:
    """Scroll từ đầu đến cuối trang để kích lazy-load."""
    await page.evaluate(f"""
    async () => {{
        await new Promise((resolve) => {{
            let totalHeight = 0;
            const distance = {SCROLL_STEP_PX};
            const delay = {SCROLL_DELAY_MS};
            const timer = setInterval(() => {{
                const scrollHeight = document.documentElement.scrollHeight;
                window.scrollBy(0, distance);
                totalHeight += distance;
                if (totalHeight >= scrollHeight) {{
                    clearInterval(timer);
                    window.scrollTo(0, 0);  // Scroll về đầu trang
                    resolve();
                }}
            }}, delay);
        }});
    }}
    """)


async def _cleanup_page(page: Page) -> None:
    """Ẩn quảng cáo/popup và ép fixed/sticky → static."""
    # Inject CSS ẩn quảng cáo
    await page.add_style_tag(content=HIDE_ADS_CSS)
    
    # Ép fixed/sticky → static
    await page.evaluate("""
    () => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const style = getComputedStyle(el);
            if (style.position === 'fixed' || style.position === 'sticky') {
                el.style.setProperty('position', 'static', 'important');
            }
        }
    }
    """)


async def _fix_relative_dates(page: Page, url: str) -> None:
    """
    Chuẩn hoá các chuỗi thời gian tương đối (vd: '6 tháng trước', '2 giờ trước')
    về định dạng dd/mm/yyyy HH:mm dựa vào attribute datetime/title hoặc ISO format.
    """
    await page.evaluate("""
    () => {
        function formatDate(dt) {
            const dd = String(dt.getDate()).padStart(2, '0');
            const mm = String(dt.getMonth() + 1).padStart(2, '0');
            const yyyy = dt.getFullYear();
            const hh = String(dt.getHours()).padStart(2, '0');
            const mi = String(dt.getMinutes()).padStart(2, '0');
            return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
        }

        // 1. Tất cả thẻ <time> có attribute datetime hoặc title
        const timeElements = document.querySelectorAll('time[datetime], time[title], [itemprop="datePublished"]');
        for (const el of timeElements) {
            const dtStr = el.getAttribute('datetime') || el.getAttribute('title');
            if (dtStr) {
                const dt = new Date(dtStr);
                if (!isNaN(dt.getTime())) {
                    el.textContent = formatDate(dt);
                }
            }
        }

        // 2. Các phần tử chứa text thời gian tương đối (vd: '6 tháng trước', '10 phút trước')
        const relativeRegex = /(\\d+)\\s*(giây|phút|giờ|ngày|tuần|tháng|năm)\\s*trước/i;
        const allCandidates = document.querySelectorAll('span, div, time, p, small, a');
        for (const el of allCandidates) {
            if (el.children.length === 0 && relativeRegex.test(el.textContent.trim())) {
                const dtStr = el.getAttribute('datetime') || el.getAttribute('title') ||
                              el.parentElement?.getAttribute('datetime') || el.parentElement?.getAttribute('title');
                if (dtStr) {
                    const dt = new Date(dtStr);
                    if (!isNaN(dt.getTime())) {
                        el.textContent = formatDate(dt);
                        continue;
                    }
                }
                const closestTime = el.closest('time') || el.parentElement?.querySelector('time');
                if (closestTime) {
                    const cDtStr = closestTime.getAttribute('datetime') || closestTime.getAttribute('title');
                    if (cDtStr) {
                        const dt = new Date(cDtStr);
                        if (!isNaN(dt.getTime())) {
                            el.textContent = formatDate(dt);
                        }
                    }
                }
            }
        }
    }
    """)


async def _detect_content_bounds(page: Page) -> dict | None:
    """
    Xác định vùng nội dung bài viết bằng Readability.js.
    
    Returns:
        {"top": 0, "bottom": int, "left": 0, "width": int} hoặc None nếu thất bại.
        top luôn = 0 (bắt đầu từ header trang) để giữ header/masthead.
    """
    readability_js = _load_readability_js()
    
    result = await page.evaluate("""
    (readabilityCode) => {
        try {
            // Inject Readability vào global scope
            const fn = new Function(readabilityCode + '; return Readability;');
            const Readability = fn();
            
            // Parse bằng Readability (clone DOM)
            const clone = document.cloneNode(true);
            const article = new Readability(clone).parse();
            
            if (!article || !article.textContent || article.textContent.length < 100) {
                return null;
            }
            
            // Lấy 500 ký tự đầu để so sánh
            const articleText = article.textContent.substring(0, 500).trim();
            
            // Tìm phần tử DOM gốc match tốt nhất
            const candidates = document.querySelectorAll(
                'article, main, [itemprop="articleBody"], ' +
                '[class*="content"]:not(footer):not(header):not(nav), ' +
                '[class*="article-body"], [class*="post-content"], ' +
                '[class*="entry-content"], [class*="detail-content"], ' +
                '[class*="fck_detail"], [class*="the-article-body"]'
            );
            
            let bestMatch = null;
            let bestScore = 0;
            
            for (const el of candidates) {
                const elText = el.textContent.substring(0, 500).trim();
                if (elText.length < 50) continue;
                
                // Tính overlap đơn giản: số từ chung / tổng từ
                const articleWords = new Set(articleText.split(/\\s+/));
                const elWords = elText.split(/\\s+/);
                let common = 0;
                for (const w of elWords) {
                    if (articleWords.has(w)) common++;
                }
                const score = common / Math.max(articleWords.size, 1);
                
                if (score > bestScore) {
                    bestScore = score;
                    bestMatch = el;
                }
            }
            
            // Fallback: tìm div chứa nhiều <p> nhất
            if (!bestMatch || bestScore < 0.3) {
                let maxP = 0;
                const divs = document.querySelectorAll('div, section, article');
                for (const div of divs) {
                    const pCount = div.querySelectorAll(':scope > p').length;
                    if (pCount > maxP) {
                        maxP = pCount;
                        bestMatch = div;
                    }
                }
            }
            
            if (bestMatch) {
                const rect = bestMatch.getBoundingClientRect();
                let bottom = Math.ceil(rect.bottom + window.scrollY);
                
                // Mở rộng bottom bao gồm các phần tử footer/meta ngay dưới bài (tags, nguồn bài, copy link, tác giả...)
                const parent = bestMatch.parentElement || document.body;
                const footerCandidates = parent.querySelectorAll(
                    '.tags, .tag, [class*="tag"], [class*="source"], [class*="author"], ' +
                    '[class*="footer-article"], [class*="detail-footer"], [class*="foot"], ' +
                    '[class*="copy-link"], [class*="like-share"], [class*="meta"], ' +
                    '.ps-detail-footer, .cate-24h-foot-detail, [class*="hashtags"]'
                );
                for (const el of footerCandidates) {
                    const elRect = el.getBoundingClientRect();
                    const elBottom = Math.ceil(elRect.bottom + window.scrollY);
                    if (elBottom > bottom && elBottom < bottom + 500) {
                        bottom = elBottom;
                    }
                }
                
                // Thêm padding an toàn bên dưới bài viết (80px) để chụp trọn vẹn tag và nút bấm
                bottom += 80;

                const fullScrollHeight = document.documentElement.scrollHeight;
                bottom = Math.min(bottom, fullScrollHeight);
                
                // Tính ranh giới chiều ngang chính xác của khối nội dung
                const docWidth = document.documentElement.clientWidth;
                let left = 0;
                let right = Math.min(docWidth, Math.ceil(rect.right) + 20);

                return {
                    top: 0,  // Bắt đầu từ đầu trang (giữ header)
                    bottom: bottom,
                    left: 0,
                    right: right,
                    width: right,
                };
            }
            
            return null;
        } catch (e) {
            console.error('Readability error:', e);
            return null;
        }
    }
    """, readability_js)
    
    return result


async def _get_block_positions(page: Page, content_bounds: dict) -> list[dict]:
    """
    Lấy toạ độ từng khối nội dung con cấp 1 trong vùng nội dung.
    Lọc bỏ khối rỗng/ẩn.
    """
    blocks = await page.evaluate("""
    (bounds) => {
        const results = [];
        
        // Lấy tất cả phần tử con trực tiếp trong body, lọc theo vùng nội dung
        const allElements = document.querySelectorAll(
            'p, h1, h2, h3, h4, h5, h6, img, figure, blockquote, ' +
            'table, ul, ol, pre, video, iframe, picture, .wp-caption, ' +
            '.tags, .tag, [class*="tag"], [class*="source"], [class*="author"], ' +
            '[class*="footer-article"], [class*="detail-footer"], [class*="copy-link"]'
        );
        
        for (const el of allElements) {
            const rect = el.getBoundingClientRect();
            const absTop = rect.top + window.scrollY;
            const absBottom = rect.bottom + window.scrollY;
            
            // Chỉ lấy phần tử nằm trong vùng nội dung
            if (absBottom < bounds.top || absTop > bounds.bottom) continue;
            
            // Lọc bỏ phần tử ẩn/rỗng
            const style = getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            if (rect.height < 2) continue;
            
            // Lọc bỏ phần tử rỗng (không có text hoặc ảnh)
            const hasText = el.textContent.trim().length > 0;
            const hasImage = el.tagName === 'IMG' || el.querySelector('img') !== null;
            const hasVideo = el.tagName === 'VIDEO' || el.tagName === 'IFRAME';
            if (!hasText && !hasImage && !hasVideo) continue;
            
            results.push({
                top: Math.floor(absTop),
                bottom: Math.ceil(absBottom),
                tag: el.tagName.toLowerCase(),
            });
        }
        
        // Sắp xếp theo vị trí
        results.sort((a, b) => a.top - b.top);
        
        return results;
    }
    """, content_bounds)
    
    return blocks or []


# ══════════════════════════════════════════════
# Chụp bài Facebook
# ══════════════════════════════════════════════

def _normalize_facebook_url(url: str) -> str:
    """Chuẩn hoá URL Facebook (loại bỏ dấu '/' thừa ở cuối path như /share/p/xxx//)."""
    import re
    u = (url or "").strip()
    m = re.match(r"^(https?://[^/]+)(/.*)$", u, flags=re.IGNORECASE)
    if m:
        prefix, rest = m.group(1), m.group(2)
        if "?" in rest:
            path_part, query_part = rest.split("?", 1)
            path_part = re.sub(r"/+", "/", path_part)
            return f"{prefix}{path_part}?{query_part}"
        else:
            path_part = re.sub(r"/+", "/", rest)
            return f"{prefix}{path_part}"
    return u


def _resolve_fb_storage_state_path() -> str | None:
    """Tìm đường dẫn file fb_storage_state.json ở các vị trí hợp lệ."""
    candidates = [FB_STORAGE_STATE_PATH]
    try:
        from config import BASE_PATH
        candidates.append(os.path.join(BASE_PATH, "data", "fb_storage_state.json"))
        candidates.append(os.path.join(BASE_PATH, "dist", "CNPS_Generator", "data", "fb_storage_state.json"))
    except Exception:
        pass
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates.append(os.path.join(repo_root, "data", "fb_storage_state.json"))
    candidates.append(os.path.join(repo_root, "dist", "CNPS_Generator", "data", "fb_storage_state.json"))

    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


async def _capture_facebook(
    url: str,
    output_dir: Path,
    cb,
) -> list[Path]:
    """
    Flow chụp bài Facebook:
    1. Mở trang với storage_state (session đã đăng nhập), dùng domcontentloaded
       (tránh networkidle vì Facebook duy trì kết nối realtime liên tục)
    2. Kiểm tra redirect → session hết hạn
    3. Chờ load nội dung & tự động bấm "Xem thêm" / "See more"
    4. Tìm khung bài đăng ([role="dialog"] của bài viết hoặc [role="article"] chính)
    5. Chụp element
    6. Phân trang nếu cần
    """
    storage_state_path = _resolve_fb_storage_state_path()
    if not storage_state_path:
        raise SessionExpiredError(
            "Chưa có session Facebook.\n"
            "Vui lòng bấm nút 'Đăng nhập Facebook' trên giao diện để đăng nhập lần đầu."
        )

    clean_url = _normalize_facebook_url(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                storage_state=storage_state_path,
                viewport={"width": VIEWPORT_WIDTH, "height": 1400},
                device_scale_factor=DEVICE_SCALE_FACTOR,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # Mở URL (dùng domcontentloaded vì Facebook không bao giờ đạt networkidle)
            cb("Đang mở bài Facebook...")
            try:
                await page.goto(clean_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                logger.warning(f"Facebook domcontentloaded timeout, thử commit: {e}")
                await page.goto(clean_url, wait_until="commit", timeout=20_000)

            # Chờ giao diện Comet của Facebook tải xong bài đăng
            cb("Đang chờ tải nội dung bài đăng...")
            await page.wait_for_timeout(3500)

            # Kiểm tra redirect → trang login/checkpoint
            current_url_lower = page.url.lower()
            if "/login" in current_url_lower or "checkpoint" in current_url_lower:
                raise SessionExpiredError(
                    "Session Facebook đã hết hạn.\n"
                    "Vui lòng bấm nút 'Đăng nhập Facebook' để đăng nhập lại."
                )

            # Kiểm tra bài viết bị lỗi / không tồn tại
            body_text = await page.evaluate("() => (document.body && document.body.innerText) || ''")
            unavailable_phrases = [
                "this page isn't available",
                "this content isn't available",
                "trang này hiện không hiển thị",
                "bạn hiện không xem được nội dung này",
                "nội dung này hiện không hiển thị",
            ]
            if any(phrase in body_text.lower() for phrase in unavailable_phrases):
                raise ContentDetectionError(
                    f"Bài đăng Facebook không khả dụng hoặc liên kết bị hỏng:\n{clean_url}"
                )

            # Tự động mở rộng nội dung bài viết ("Xem thêm" / "See more")
            await page.evaluate("""
            () => {
                const buttons = Array.from(
                    document.querySelectorAll('div[role="button"], span[role="button"]')
                );
                for (const btn of buttons) {
                    const txt = (btn.innerText || '').trim();
                    if (txt === 'See more' || txt === 'Xem thêm') {
                        const commentAncestor = btn.closest('[aria-label^="Comment"], [aria-label^="Bình luận"], [aria-label^="Phản hồi"]');
                        if (!commentAncestor) {
                            try { btn.click(); } catch (_) {}
                        }
                    }
                }
            }
            """)
            await page.wait_for_timeout(800)

            # Tìm khung bài đăng Facebook:
            # 1. Ưu tiên modal dialog bài đăng (chiều rộng ~500-950px ở giữa trang)
            cb("Đang xác định khung bài đăng...")
            post_element = None
            dialogs = await page.query_selector_all('[role="dialog"]')
            for dlg in dialogs:
                box = await dlg.bounding_box()
                if box and 400 <= box["width"] <= 980 and box["height"] >= 200:
                    post_element = dlg

            # 2. Nếu bài đăng không nằm trong modal dialog, tìm FeedUnit hoặc article chính (không phải comment/skeleton)
            if not post_element:
                post_element = await page.query_selector('[data-pagelet*="FeedUnit"]')

            if not post_element:
                articles = await page.query_selector_all('[role="article"]')
                for art in articles:
                    aria = (await art.get_attribute("aria-label") or "").lower()
                    if aria.startswith(("comment", "bình luận", "phản hồi")):
                        continue
                    box = await art.bounding_box()
                    if not box or box["height"] < 120 or box["width"] < 300:
                        continue
                    txt = (await art.inner_text() or "").strip()
                    has_img = await art.query_selector("img") is not None
                    if txt or has_img:
                        post_element = art
                        break

            # 3. Fallback: chụp phần chính [role="main"]
            if not post_element:
                post_element = await page.query_selector('[role="main"]')

            if not post_element:
                raise ContentDetectionError(
                    "Không tìm được khung bài đăng Facebook.\n"
                    "Có thể bài đã bị xoá hoặc tài khoản không có quyền xem."
                )

            # Chụp element
            cb("Đang chụp ảnh bài đăng...")
            screenshot_bytes = await post_element.screenshot(type="png")

            # Phân trang nếu ảnh dài
            cb("Đang phân trang ảnh...")
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(screenshot_bytes))
            img_height_css = img.height // DEVICE_SCALE_FACTOR

            if img_height_css > TARGET_PAGE_HEIGHT_PX:
                page_images = smart_paginate(
                    screenshot_bytes=screenshot_bytes,
                    block_positions=[],
                    target_page_height=TARGET_PAGE_HEIGHT_PX,
                    output_dir=output_dir,
                    device_scale_factor=DEVICE_SCALE_FACTOR,
                )
            else:
                single_path = output_dir / "page_001.png"
                img.save(str(single_path), "PNG")
                page_images = [single_path]

            cb(f"✅ Đã chụp {len(page_images)} trang")
            return page_images

        finally:
            await browser.close()
