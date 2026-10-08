"""
Shared playwright browser helpers.
One browser instance is created at startup and reused across requests.
"""
from __future__ import annotations

import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


_browser: Optional[Browser] = None
_playwright = None


async def get_browser() -> Browser:
    global _browser, _playwright
    if _browser is None or not _browser.is_connected():
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
    return _browser


async def close_browser():
    global _browser, _playwright
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _browser = None
    _playwright = None


async def new_page(timeout_ms: int = 60_000, stealth: bool = True) -> tuple[BrowserContext, Page]:
    browser = await get_browser()
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        viewport={"width": 390, "height": 844},
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
        ignore_https_errors=True,
    )
    if stealth:
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
    page = await context.new_page()
    page.set_default_timeout(timeout_ms)
    return context, page


async def auto_scroll(page: Page, max_scrolls: int = 10, pause_ms: int = 600):
    """Scroll down step by step to trigger lazy-loaded images/products."""
    for _ in range(max_scrolls):
        prev_height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(pause_ms / 1000)
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break
    # Scroll back to top so screenshots are consistent
    await page.evaluate("window.scrollTo(0, 0)")
