# -*- coding: utf-8 -*-
"""Debug script: phân tích content bounds của GenK."""
import sys, asyncio
sys.path.insert(0, 'src')

from playwright.async_api import async_playwright
from config import VIEWPORT_WIDTH, VIEWPORT_HEIGHT, DEVICE_SCALE_FACTOR, HIDE_ADS_CSS

JS_FIND_CANDIDATES = """() => {
    const candidates = document.querySelectorAll(
        'article, main, [itemprop="articleBody"], ' +
        '[class*="content"]:not(footer):not(header):not(nav), ' +
        '[class*="article-body"], [class*="post-content"], ' +
        '[class*="fck_detail"], [class*="the-article-body"]'
    );
    return Array.from(candidates).map(el => {
        const rect = el.getBoundingClientRect();
        return {
            tag: el.tagName,
            cls: (el.className || '').substring(0, 80),
            id: el.id || '',
            top: Math.floor(rect.top + window.scrollY),
            bottom: Math.ceil(rect.bottom + window.scrollY),
            height: Math.ceil(rect.height),
            textLen: el.textContent.length,
        };
    });
}"""

JS_SCROLL = """async () => {
    await new Promise(resolve => {
        let total = 0;
        const d = 400;
        const t = setInterval(() => {
            window.scrollBy(0, d);
            total += d;
            if (total >= document.documentElement.scrollHeight) {
                clearInterval(t);
                window.scrollTo(0, 0);
                resolve();
            }
        }, 250);
    });
}"""

JS_FIX_POSITION = """() => {
    for (const el of document.querySelectorAll('*')) {
        const s = getComputedStyle(el);
        if (s.position === 'fixed' || s.position === 'sticky')
            el.style.setProperty('position', 'static', 'important');
    }
}"""

async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=DEVICE_SCALE_FACTOR,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        url = "https://genk.vn/galaxy-s26-ultra-co-gi-ma-khien-gioi-reviewer-viet-hung-thu-den-vay-165260228115249526.chn"
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        # Scroll
        await page.evaluate(JS_SCROLL)
        
        # Cleanup
        await page.add_style_tag(content=HIDE_ADS_CSS)
        await page.evaluate(JS_FIX_POSITION)
        await page.wait_for_timeout(1000)
        
        # Debug
        full_h = await page.evaluate("document.documentElement.scrollHeight")
        print(f"Full page height: {full_h}px")
        
        info = await page.evaluate(JS_FIND_CANDIDATES)
        print(f"\nFound {len(info)} candidates:")
        for c in info:
            print(f"  {c['tag']} .{c['cls'][:50]} #{c['id']}: "
                  f"top={c['top']}, bottom={c['bottom']}, h={c['height']}, text={c['textLen']}")
        
        # Also check: what's the actual article container in GenK?
        genk_specific = await page.evaluate("""() => {
            const selectors = ['.knc-content', '.content-detail', '.detail-content', 
                               '#ContentDetail', '.ArticleContent', '.knc-wrapper'];
            const results = [];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const rect = el.getBoundingClientRect();
                    results.push({
                        selector: sel,
                        top: Math.floor(rect.top + window.scrollY),
                        bottom: Math.ceil(rect.bottom + window.scrollY),
                        height: Math.ceil(rect.height),
                    });
                }
            }
            return results;
        }""")
        print(f"\nGenK-specific selectors:")
        for r in genk_specific:
            print(f"  {r['selector']}: top={r['top']}, bottom={r['bottom']}, h={r['height']}")
        
        await browser.close()

asyncio.run(debug())
