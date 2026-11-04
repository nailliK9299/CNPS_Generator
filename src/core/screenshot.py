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
    FB_STORAGE_STATE_PATH, launch_browser,
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


class ScreenshotCancelledError(Exception):
    """Người dùng chủ động dừng/hủy quá trình chụp và tạo CNPS."""
    pass


async def _wait_control(control_callback=None) -> None:
    """
    Kiểm tra trạng thái Tạm dừng ('pause') hoặc Hủy ('cancel') từ GUI.
    - Nếu 'cancel' -> raise ScreenshotCancelledError ngay lập tức.
    - Nếu 'pause'  -> tạm dừng tại chỗ (sleep 0.15s) cho đến khi người dùng bấm 'Tiếp tục' hoặc 'Hủy'.
    """
    if not control_callback:
        return
    while True:
        status = control_callback()
        if status == "cancel":
            raise ScreenshotCancelledError("Đã hủy tạo Chứng Nhận Phát Sóng theo yêu cầu người dùng.")
        if status == "pause":
            await asyncio.sleep(0.15)
            continue
        break


async def _run_cancellable(coro, control_callback=None, timeout: float | None = None):
    """
    Chạy một coroutine (như page.goto, page.screenshot) với khả năng hủy tức thì
    ngay khi người dùng bấm nút 'Dừng / Hủy'.
    """
    await _wait_control(control_callback)
    if not control_callback:
        if timeout:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    main_task = asyncio.ensure_future(coro)

    async def _watch_cancel():
        while not main_task.done():
            if control_callback() == "cancel":
                main_task.cancel()
                return
            await asyncio.sleep(0.15)

    watcher_task = asyncio.ensure_future(_watch_cancel())
    try:
        if timeout:
            return await asyncio.wait_for(main_task, timeout=timeout)
        return await main_task
    except asyncio.CancelledError:
        if control_callback() == "cancel":
            raise ScreenshotCancelledError("Đã hủy tạo Chứng Nhận Phát Sóng theo yêu cầu người dùng.")
        raise
    finally:
        watcher_task.cancel()


# ══════════════════════════════════════════════
# API chính — gọi từ GUI
# ══════════════════════════════════════════════

def capture_screenshots(
    url: str,
    article_type: str,
    output_dir: str | Path,
    progress_callback=None,
    control_callback=None,
) -> list[Path]:
    """
    Chụp screenshot bài báo/Facebook, phân trang, trả về danh sách file ảnh.
    
    Args:
        url: URL bài viết
        article_type: "Báo chí" hoặc "Facebook"
        output_dir: Thư mục lưu ảnh tạm
        progress_callback: Hàm callback(message: str) để báo tiến trình
        control_callback: Hàm callback() trả về 'run' | 'pause' | 'cancel'
    
    Returns:
        Danh sách Path đến các file ảnh đã phân trang
    
    Raises:
        SessionExpiredError: Session Facebook hết hạn
        ContentDetectionError: Không xác định được nội dung
        ScreenshotCancelledError: Người dùng bấm hủy
        Exception: Lỗi khác (timeout, 404, ...)
    """
    def _cb(msg):
        if progress_callback:
            progress_callback(msg)
        logger.info(msg)
    
    # Chạy async trong sync context
    return asyncio.run(_capture_async(url, article_type, output_dir, _cb, control_callback))


async def _capture_async(
    url: str,
    article_type: str,
    output_dir: str | Path,
    cb,
    control_callback=None,
) -> list[Path]:
    """Dispatcher async cho 2 loại bài."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    await _wait_control(control_callback)
    
    if article_type == "Facebook":
        return await _capture_facebook(url, output_dir, cb, control_callback)
    else:
        return await _capture_article(url, output_dir, cb, control_callback)


# ══════════════════════════════════════════════
# Chụp bài báo điện tử
# ══════════════════════════════════════════════

async def _capture_article(
    url: str,
    output_dir: Path,
    cb,
    control_callback=None,
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
    await _wait_control(control_callback)
    async with async_playwright() as p:
        browser = await launch_browser(p, headless=True)
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
            await _wait_control(control_callback)
            cb("Đang mở trang...")
            try:
                await _run_cancellable(
                    page.goto(url, wait_until="domcontentloaded", timeout=25_000),
                    control_callback=control_callback,
                    timeout=26.0,
                )
            except ScreenshotCancelledError:
                raise
            except Exception as e:
                logger.warning(f"domcontentloaded timeout, thử commit: {e}")
                await _run_cancellable(
                    page.goto(url, wait_until="commit", timeout=15_000),
                    control_callback=control_callback,
                    timeout=16.0,
                )
                await page.wait_for_timeout(2000)

            await _wait_control(control_callback)

            # Chờ ngắn networkidle (tối đa 3.5s) để ảnh/font tải thêm nhưng không bị treo bởi quảng cáo
            try:
                await _run_cancellable(
                    page.wait_for_load_state("networkidle", timeout=3_500),
                    control_callback=control_callback,
                    timeout=4.0,
                )
            except ScreenshotCancelledError:
                raise
            except Exception:
                pass
            
            # Kiểm tra trang 404/lỗi
            try:
                page_title = (await asyncio.wait_for(page.title(), timeout=3.0)).lower()
            except Exception:
                page_title = ""
            if page.url.endswith("/404") or "not found" in page_title:
                raise Exception(f"Trang không tồn tại (404): {url}")
            
            # 2. Kích hoạt sớm ảnh lazy-load & ước lượng đáy bài viết trước khi scroll
            await _wait_control(control_callback)
            try:
                await asyncio.wait_for(_force_lazy_images(page), timeout=4.0)
            except Exception:
                pass
            try:
                initial_bounds = await asyncio.wait_for(_detect_content_bounds(page), timeout=5.0)
            except Exception:
                initial_bounds = None
            max_scroll_px = (int(initial_bounds["bottom"]) + 800) if initial_bounds else 6500
            max_scroll_px = max(3000, min(max_scroll_px, 11000))

            # Auto-scroll từng bước từ Python (có giới hạn chiều cao bài viết để không kích hoạt infinite-scroll)
            cb("Đang scroll để tải nội dung...")
            await _auto_scroll(page, max_scroll_px=max_scroll_px, control_callback=control_callback)
            
            # 3. Dọn giao diện & đảm bảo toàn bộ ảnh trong bài đã tải xong
            await _wait_control(control_callback)
            cb("Đang dọn quảng cáo, popup...")
            try:
                await asyncio.wait_for(_cleanup_page(page), timeout=8.0)
            except Exception as e:
                logger.warning(f"_cleanup_page timeout/error: {e}")
            try:
                await asyncio.wait_for(_force_lazy_images(page), timeout=5.0)
            except Exception as e:
                logger.warning(f"_force_lazy_images timeout/error: {e}")
            try:
                await asyncio.wait_for(_fix_relative_dates(page, url), timeout=5.0)
            except Exception as e:
                logger.warning(f"_fix_relative_dates timeout/error: {e}")
            await page.wait_for_timeout(POST_CLEANUP_WAIT_MS)
            
            # 4. Xác định vùng nội dung chính xác sau khi lazy-load ảnh
            await _wait_control(control_callback)
            cb("Đang xác định vùng nội dung bài viết...")
            try:
                content_bounds = await asyncio.wait_for(_detect_content_bounds(page), timeout=10.0)
            except Exception as e:
                logger.warning(f"_detect_content_bounds timeout/error: {e}")
                content_bounds = initial_bounds
            
            # Nếu sau khi cleanup mà bottom quá nhỏ (< 700px) trong khi initial_bounds lớn hơn, ưu tiên dùng giá trị lớn hơn
            if content_bounds and initial_bounds and content_bounds.get("bottom", 0) < 700 and initial_bounds.get("bottom", 0) >= 700:
                content_bounds["bottom"] = initial_bounds["bottom"]

            if content_bounds is None or int(content_bounds.get("bottom", 0)) < 400:
                logger.warning(f"Không xác định được nội dung — chụp full page: {url}")
                cb("⚠️ Không tìm được vùng nội dung — chụp toàn trang")
                # Fallback: chụp full page (giới hạn chiều cao tối đa 12000px để tránh treo bộ nhớ)
                try:
                    full_height = await asyncio.wait_for(
                        page.evaluate("Math.max(document.documentElement.scrollHeight || 0, document.body ? document.body.scrollHeight : 0)"),
                        timeout=5.0,
                    )
                except Exception:
                    full_height = VIEWPORT_HEIGHT * 4
                content_bounds = {
                    "top": 0,
                    "bottom": max(VIEWPORT_HEIGHT, min(int(full_height), 12000)),
                    "left": 0,
                    "width": VIEWPORT_WIDTH,
                }
            else:
                # Giới hạn chiều cao tối đa 15000px để tránh lỗi quá tải texture khi trang quá dài
                content_bounds["bottom"] = min(int(content_bounds["bottom"]), 15000)
            
            # Chờ toàn bộ ảnh <img> nằm trong vùng bài viết tải hoàn tất
            try:
                await asyncio.wait_for(
                    _wait_for_article_images(page, int(content_bounds["bottom"])),
                    timeout=4.5,
                )
            except Exception:
                pass

            # 5. Lấy toạ độ khối nội dung con
            await _wait_control(control_callback)
            cb("Đang phân tích cấu trúc trang...")
            try:
                block_positions = await asyncio.wait_for(
                    _get_block_positions(page, content_bounds),
                    timeout=8.0,
                )
            except Exception as e:
                logger.warning(f"_get_block_positions timeout/error: {e}")
                block_positions = []

            # 6. Chụp ảnh full page rồi crop bằng Pillow
            # LƯU Ý QUAN TRỌNG: Tuyệt đối KHÔNG gán overflow:hidden hay maxHeight lên html/body
            # vì các trang như cafebiz.vn, soha.vn có html,body { height: 100% } (900px) -> nếu gán
            # overflow:hidden sẽ làm Chromium cắt cụt toàn bộ nội dung bên dưới 900px thành màu trắng/xám!
            await _wait_control(control_callback)
            cb("Đang chụp ảnh...")
            try:
                await asyncio.wait_for(page.evaluate("window.scrollTo(0, 0)"), timeout=3.0)
            except Exception:
                pass
            await page.wait_for_timeout(300)
            
            capture_height = max(VIEWPORT_HEIGHT, min(int(content_bounds["bottom"]) + 150, 15000))
            try:
                await asyncio.wait_for(
                    page.evaluate(f"""
                    () => {{
                        // Đảm bảo html và body luôn hiển thị đầy đủ chiều cao, không bị giới hạn 900px
                        for (const rootEl of [document.documentElement, document.body]) {{
                            if (!rootEl) continue;
                            rootEl.style.setProperty('display', 'block', 'important');
                            rootEl.style.setProperty('visibility', 'visible', 'important');
                            rootEl.style.setProperty('height', 'auto', 'important');
                            rootEl.style.setProperty('max-height', 'none', 'important');
                            rootEl.style.setProperty('overflow', 'visible', 'important');
                            rootEl.style.setProperty('overflow-y', 'visible', 'important');
                            rootEl.style.setProperty('overflow-x', 'hidden', 'important');
                        }}
                        // Nếu trang có phần đuôi infinite-scroll quá dài (> capture_height + 1500),
                        // chỉ ẩn các khối con nằm hoàn toàn bên dưới vùng bài viết để giảm chiều cao trang
                        const sh = Math.max(
                            document.documentElement.scrollHeight || 0,
                            document.body ? document.body.scrollHeight : 0
                        );
                        if (sh > {capture_height + 1500}) {{
                            const cutoff = {capture_height + 300};
                            const blocks = document.querySelectorAll('body > *, main > *, div > section, div > div, footer');
                            for (const el of blocks) {{
                                const r = el.getBoundingClientRect();
                                const absTop = r.top + (window.scrollY || 0);
                                if (absTop > cutoff && r.height > 50) {{
                                    el.style.setProperty('display', 'none', 'important');
                                }}
                            }}
                        }}
                    }}
                    """),
                    timeout=4.0,
                )
            except Exception:
                pass

            full_screenshot_bytes = await _run_cancellable(
                page.screenshot(full_page=True, type="png"),
                control_callback=control_callback,
                timeout=30.0,
            )
            
            # Crop ảnh theo content_bounds (tính bằng CSS px → nhân scale)
            from PIL import Image as _Image
            import io as _io
            _full_img = _Image.open(_io.BytesIO(full_screenshot_bytes))
            scale = DEVICE_SCALE_FACTOR
            crop_top = 0
            crop_bottom = min(int(content_bounds["bottom"] * scale), _full_img.height)
            if crop_bottom <= int(300 * scale):
                crop_bottom = _full_img.height
            
            # Giữ chiều rộng chuẩn theo VIEWPORT_WIDTH * scale (tránh dải trắng thừa bên phải nếu trang bị tràn ngang như bongda.com.vn)
            crop_left = 0
            crop_right = min(int(VIEWPORT_WIDTH * scale), _full_img.width)
                
            _cropped = _full_img.crop((crop_left, crop_top, crop_right, crop_bottom))
            _buf = _io.BytesIO()
            _cropped.save(_buf, format="PNG")
            screenshot_bytes = _buf.getvalue()
            del _full_img, _cropped, _buf
            
            # 7. Phân trang thông minh
            await _wait_control(control_callback)
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
            try:
                await browser.close()
            except Exception:
                pass


async def _force_lazy_images(page: Page) -> None:
    """
    Ép toàn bộ ảnh lazy-load (data-src, data-original, data-lazy-src, loading='lazy',...)
    trong trang tải ngay lập tức và hiển thị đầy đủ (tránh mất ảnh giữa bài như trên kenh14.vn).
    """
    await page.evaluate("""
    () => {
        const lazyAttrs = ['data-src', 'data-original', 'data-lazy-src', 'data-lazy', 'data-url', 'data-hi-res-src'];
        const imgs = document.querySelectorAll('img');
        for (const img of imgs) {
            img.loading = 'eager';
            img.removeAttribute('loading');
            img.decoding = 'sync';
            for (const attr of lazyAttrs) {
                const val = img.getAttribute(attr);
                if (val && (val.startsWith('http') || val.startsWith('//'))) {
                    const curSrc = img.getAttribute('src') || '';
                    if (!curSrc || curSrc.startsWith('data:') || curSrc.includes('blank') || curSrc.includes('spacer') || curSrc.includes('1x1')) {
                        img.setAttribute('src', val);
                    }
                    break;
                }
            }
            const dataSrcset = img.getAttribute('data-srcset');
            if (dataSrcset && !img.getAttribute('srcset')) {
                img.setAttribute('srcset', dataSrcset);
            }
            const cs = getComputedStyle(img);
            if (cs.opacity === '0') {
                img.style.setProperty('opacity', '1', 'important');
            }
            if (cs.visibility === 'hidden') {
                img.style.setProperty('visibility', 'visible', 'important');
            }
        }
        const sources = document.querySelectorAll('picture source');
        for (const srcEl of sources) {
            const ds = srcEl.getAttribute('data-srcset') || srcEl.getAttribute('data-src');
            if (ds && !srcEl.getAttribute('srcset')) {
                srcEl.setAttribute('srcset', ds);
            }
        }
    }
    """)


async def _wait_for_article_images(page: Page, max_bottom_px: int) -> None:
    """Chờ các thẻ <img> nằm trong vùng bài viết (0..max_bottom_px) tải xong dữ liệu ảnh."""
    await page.evaluate(f"""
    async () => {{
        const imgs = Array.from(document.querySelectorAll('img')).filter(img => {{
            const r = img.getBoundingClientRect();
            const top = r.top + (window.scrollY || 0);
            return r.width > 40 && r.height > 40 && top >= 0 && top <= {max_bottom_px};
        }});
        await Promise.all(imgs.map(img => {{
            if (img.complete && img.naturalWidth > 0) return Promise.resolve();
            return new Promise(res => {{
                const t = setTimeout(res, 2500);
                img.addEventListener('load', () => {{ clearTimeout(t); res(); }}, {{ once: true }});
                img.addEventListener('error', () => {{ clearTimeout(t); res(); }}, {{ once: true }});
            }});
        }}));
    }}
    """)


async def _auto_scroll(page: Page, max_scroll_px: int = 6000, control_callback=None) -> None:
    """
    Scroll từng bước từ đầu trang xuống vùng đáy bài viết (`max_scroll_px`) để kích hoạt lazy-load ảnh.
    Điều khiển trực tiếp từ Python với giới hạn bước và kiểm tra độ cao để KHÔNG bao giờ
    cuộn vào vùng infinite-scroll dưới chân trang báo (như giadinh.suckhoedoisong.vn).
    """
    max_steps = max(6, min(int(max_scroll_px // SCROLL_STEP_PX) + 3, 28))
    last_scroll_y = -1
    try:
        for step_idx in range(max_steps):
            await _wait_control(control_callback)
            await asyncio.wait_for(
                page.evaluate(f"window.scrollBy(0, {SCROLL_STEP_PX})"),
                timeout=2.5,
            )
            if step_idx % 4 == 0:
                try:
                    await asyncio.wait_for(_force_lazy_images(page), timeout=2.0)
                except Exception:
                    pass
            await page.wait_for_timeout(SCROLL_DELAY_MS)
            state = await asyncio.wait_for(
                page.evaluate(
                    "() => ({ y: window.scrollY || window.pageYOffset || 0, h: Math.max(document.documentElement.scrollHeight || 0, document.body ? document.body.scrollHeight : 0) })"
                ),
                timeout=2.5,
            )
            cur_y = int(state.get("y", 0))
            cur_h = int(state.get("h", 0))
            if cur_y >= max_scroll_px or cur_y + VIEWPORT_HEIGHT >= cur_h or cur_y == last_scroll_y:
                break
            last_scroll_y = cur_y
    except ScreenshotCancelledError:
        raise
    except Exception as e:
        logger.warning(f"_auto_scroll dừng sớm: {e}")
    finally:
        try:
            await asyncio.wait_for(page.evaluate("window.scrollTo(0, 0)"), timeout=2.5)
        except Exception:
            pass


async def _cleanup_page(page: Page) -> None:
    """
    Ẩn quảng cáo/popup, ép fixed/sticky → static, và bảo vệ tuyệt đối
    thẻ html, body cùng các khối tổ tiên chứa bài viết (tránh lỗi mất trang trên
    thanhnien.vn, vtcnews.vn, 2sao.vn và lỗi cắt cụt 900px trên cafebiz.vn, soha.vn).
    """
    # Inject CSS ẩn quảng cáo
    await page.add_style_tag(content=HIDE_ADS_CSS)
    
    # Ép fixed/sticky → static & bảo vệ cấu trúc trang bài viết
    await page.evaluate("""
    () => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const style = getComputedStyle(el);
            if (style.position === 'fixed' || style.position === 'sticky') {
                el.style.setProperty('position', 'static', 'important');
            }
        }

        // Bảo vệ html, body luôn hiển thị đầy đủ chiều cao thực tế
        for (const rootEl of [document.documentElement, document.body]) {
            if (!rootEl) continue;
            rootEl.style.setProperty('display', 'block', 'important');
            rootEl.style.setProperty('visibility', 'visible', 'important');
            rootEl.style.setProperty('height', 'auto', 'important');
            rootEl.style.setProperty('max-height', 'none', 'important');
            rootEl.style.setProperty('overflow', 'visible', 'important');
            rootEl.style.setProperty('overflow-y', 'visible', 'important');
            rootEl.style.setProperty('overflow-x', 'hidden', 'important');
        }

        // Tìm các khối chứa nội dung bài viết và đảm bảo không tổ tiên nào của chúng bị ẩn bởi CSS quảng cáo
        const articleNodes = document.querySelectorAll(
            'article, main, [itemprop="articleBody"], #article_body, #maincontent, ' +
            '.detail-content, .afcbc-body, .fck_detail, .the-article-body, ' +
            '.content-detail, .edittor-content, .nd-detail, .cate-24h-foot-arti-deta-info, ' +
            '.cate-24h-foot-arti-deta-content-main, .singular-content, .cms-body'
        );
        const protectedSet = new Set();
        for (const node of articleNodes) {
            if (node.querySelectorAll('p').length >= 2) {
                let cur = node;
                while (cur && cur !== document.documentElement) {
                    protectedSet.add(cur);
                    cur = cur.parentElement;
                }
            }
        }
        for (const el of protectedSet) {
            const cs = getComputedStyle(el);
            if (cs.display === 'none') {
                el.style.setProperty('display', 'block', 'important');
            }
            if (cs.visibility === 'hidden') {
                el.style.setProperty('visibility', 'visible', 'important');
            }
            if (cs.maxHeight === '0px' || cs.height === '0px') {
                el.style.setProperty('height', 'auto', 'important');
                el.style.setProperty('max-height', 'none', 'important');
            }
            if (cs.overflow === 'hidden' || cs.overflowY === 'hidden') {
                el.style.setProperty('overflow', 'visible', 'important');
                el.style.setProperty('overflow-y', 'visible', 'important');
            }
        }

        // 4. Thu gọn các khung chứa quảng cáo rỗng (placeholder) nằm phía trên tiêu đề bài viết (h1)
        // tránh để lại khoảng trắng lớn giữa thanh menu và tiêu đề bài báo (vd: thanhnien.vn, 2sao.vn)
        const h1 = document.querySelector('h1');
        if (h1) {
            const h1Top = h1.getBoundingClientRect().top + window.scrollY;
            const topBlocks = document.querySelectorAll('div, section, aside, ins');
            for (const blk of topBlocks) {
                if (protectedSet.has(blk) || blk.contains(h1)) continue;
                if (blk.closest('header, nav, .header, #header')) continue;
                const r = blk.getBoundingClientRect();
                const absBottom = r.bottom + window.scrollY;
                if (r.height >= 100 && absBottom <= h1Top + 20) {
                    const txt = (blk.innerText || '').trim();
                    const visibleMedia = Array.from(blk.querySelectorAll('img, svg, video, canvas, input')).some(m => {
                        const mr = m.getBoundingClientRect();
                        const mcs = getComputedStyle(m);
                        return mr.width > 10 && mr.height > 10 && mcs.display !== 'none' && mcs.visibility !== 'hidden';
                    });
                    if (txt.length === 0 && !visibleMedia) {
                        blk.style.setProperty('display', 'none', 'important');
                        blk.style.setProperty('height', '0', 'important');
                        blk.style.setProperty('min-height', '0', 'important');
                        blk.style.setProperty('margin', '0', 'important');
                        blk.style.setProperty('padding', '0', 'important');
                    }
                }
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
    Xác định vùng nội dung bài viết bằng Readability.js kết hợp bộ lọc phần tử bài báo Việt Nam.
    
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
            
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const articleFullText = article && article.textContent ? norm(article.textContent) : '';
            
            // 1. Ưu tiên kiểm tra các selector thân bài báo chuẩn của các báo điện tử Việt Nam
            // (Lưu ý: tuyệt đối loại trừ các class tiện ích flexbox như justify-content-*, align-content-*)
            const prioritySelectors = [
                '[itemprop="articleBody"]',
                '#article_body',
                '.cate-24h-foot-arti-deta-info',
                '.cate-24h-foot-arti-deta-content-main',
                '.detail-content',
                '.afcbc-body',
                '.fck_detail',
                '.the-article-body',
                '.content-detail',
                '.edittor-content',
                '.nd-detail',
                '#maincontent',
                '.singular-content',
                '.cms-body',
                '.article-content',
                '.article-body',
                '.post-content',
                '.entry-content',
                '.knc-content',
                '.detail__cmain',
                'article',
                'main',
                '[class*="content"]:not(footer):not(header):not(nav):not([class*="justify-content"]):not([class*="align-content"])'
            ];

            const candidateSet = new Set();
            for (const sel of prioritySelectors) {
                for (const el of document.querySelectorAll(sel)) {
                    candidateSet.add(el);
                }
            }

            let bestMatch = null;
            let bestScore = 0;

            const articleSample = articleFullText.substring(0, 800);
            const articleWords = new Set(articleSample ? articleSample.split(' ') : []);
            const minRequiredLen = articleFullText.length > 400 ? Math.min(350, Math.floor(articleFullText.length * 0.3)) : 120;

            for (const el of candidateSet) {
                const rect = el.getBoundingClientRect();
                // Bỏ qua các phần tử quá thấp (như thanh breadcrumb 17px, menu, tiêu đề phụ) hoặc ẩn
                if (rect.height < 250 || rect.width < 250) continue;

                // Dùng innerText để không bị lẫn mã nguồn <script>/<style> nội tuyến (như trên 24h.com.vn)
                const elFullText = norm(el.innerText || el.textContent || '');
                const pCount = el.querySelectorAll('p').length;
                if (elFullText.length < minRequiredLen && pCount < 3) continue;

                let score = 0;
                if (articleWords.size > 5) {
                    const elSampleWords = new Set(elFullText.substring(0, 1000).split(' '));
                    let common = 0;
                    for (const w of articleWords) {
                        if (elSampleWords.has(w)) common++;
                    }
                    const overlap = common / Math.max(articleWords.size, 1);

                    // Tỷ lệ bao phủ độ dài bài viết (tránh chọn khối con chỉ chứa sapo hoặc chọn cả trang chứa hàng chục tin liên quan)
                    const lenRatio = Math.min(elFullText.length, Math.max(articleFullText.length, 500)) /
                                     Math.max(elFullText.length, articleFullText.length, 500);
                    score = overlap * 0.7 + lenRatio * 0.3;
                } else {
                    score = Math.min(pCount / 15.0, 1.0);
                }

                // Thưởng điểm cho các phần tử có class/id chuyên biệt của thân bài báo
                const idCls = ((el.id || '') + ' ' + String(el.className || '')).toLowerCase();
                if (
                    el.getAttribute('itemprop') === 'articleBody' ||
                    idCls.includes('detail-content') ||
                    idCls.includes('afcbc-body') ||
                    idCls.includes('fck_detail') ||
                    idCls.includes('arti-deta-info') ||
                    idCls.includes('article_body') ||
                    idCls.includes('content-detail') ||
                    idCls.includes('edittor-content') ||
                    idCls.includes('nd-detail')
                ) {
                    score += 0.25;
                }

                if (score > bestScore) {
                    bestScore = score;
                    bestMatch = el;
                }
            }
            
            // Fallback: tìm khối chứa nhiều <p> hợp lệ nhất (có chiều cao >= 300px)
            if (!bestMatch || bestScore < 0.25) {
                let maxP = 0;
                const divs = document.querySelectorAll('article, section, div, main');
                for (const div of divs) {
                    const r = div.getBoundingClientRect();
                    if (r.height < 300 || r.width < 250) continue;
                    const pCount = div.querySelectorAll(':scope > p').length;
                    if (pCount > maxP) {
                        maxP = pCount;
                        bestMatch = div;
                    }
                }
            }
            
            if (bestMatch) {
                const scrollY = window.scrollY || window.pageYOffset || 0;
                const rect = bestMatch.getBoundingClientRect();
                let bottom = Math.ceil(rect.bottom + scrollY);

                // Đảm bảo bottom bao trùm toàn bộ các thẻ <p>, <figure>, <img> hiển thị bên trong bestMatch
                const innerBlocks = bestMatch.querySelectorAll('p, figure, img, blockquote, table, ul, ol');
                for (const child of innerBlocks) {
                    const cr = child.getBoundingClientRect();
                    if (cr.height > 5 && cr.width > 20) {
                        const cb = Math.ceil(cr.bottom + scrollY);
                        if (cb > bottom && cb < bottom + 4000) {
                            bottom = cb;
                        }
                    }
                }
                
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
                    const elBottom = Math.ceil(elRect.bottom + scrollY);
                    if (elBottom > bottom && elBottom < bottom + 500) {
                        bottom = elBottom;
                    }
                }
                
                // Thêm padding an toàn bên dưới bài viết (80px) để chụp trọn vẹn tag và nút bấm
                bottom += 80;

                const fullScrollHeight = Math.max(
                    document.documentElement.scrollHeight || 0,
                    document.body ? document.body.scrollHeight : 0
                );
                if (fullScrollHeight > 0) {
                    bottom = Math.min(bottom, fullScrollHeight);
                }
                
                // Tính ranh giới chiều ngang chính xác của khối nội dung
                const docWidth = document.documentElement.clientWidth || 1080;
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
    control_callback=None,
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
    await _wait_control(control_callback)
    storage_state_path = _resolve_fb_storage_state_path()
    if not storage_state_path:
        raise SessionExpiredError(
            "Chưa có session Facebook.\n"
            "Vui lòng bấm nút 'Đăng nhập Facebook' trên giao diện để đăng nhập lần đầu."
        )

    clean_url = _normalize_facebook_url(url)

    async with async_playwright() as p:
        browser = await launch_browser(p, headless=True)
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
            await _wait_control(control_callback)
            cb("Đang mở bài Facebook...")
            try:
                await _run_cancellable(
                    page.goto(clean_url, wait_until="domcontentloaded", timeout=30_000),
                    control_callback=control_callback,
                    timeout=31.0,
                )
            except ScreenshotCancelledError:
                raise
            except Exception as e:
                logger.warning(f"Facebook domcontentloaded timeout, thử commit: {e}")
                await _run_cancellable(
                    page.goto(clean_url, wait_until="commit", timeout=20_000),
                    control_callback=control_callback,
                    timeout=21.0,
                )

            # Chờ giao diện Comet của Facebook tải xong bài đăng
            await _wait_control(control_callback)
            cb("Đang chờ tải nội dung bài đăng...")
            await _run_cancellable(
                page.wait_for_timeout(3500),
                control_callback=control_callback,
                timeout=5.0,
            )

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
            await _wait_control(control_callback)
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
            await _wait_control(control_callback)
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
            await _wait_control(control_callback)
            cb("Đang chụp ảnh bài đăng...")
            screenshot_bytes = await _run_cancellable(
                post_element.screenshot(type="png"),
                control_callback=control_callback,
                timeout=25.0,
            )

            # Phân trang nếu ảnh dài
            await _wait_control(control_callback)
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
            try:
                await browser.close()
            except Exception:
                pass
