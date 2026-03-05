"""
HTML → PDF resume renderer using Playwright headless Chromium.

Converts rendered HTML strings into A4 PDF bytes with pixel-perfect
CSS support (flexbox, grid, @font-face, etc.).

Falls back to ReportLab if Playwright/Chromium is unavailable.
"""
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_browser = None
_browser_lock = threading.Lock()
_playwright_ctx = None

# Where fonts live — used for file:// references in templates
FONTS_DIR = Path(__file__).resolve().parent.parent / 'static' / 'fonts'


def _get_browser():
    """
    Return a singleton Chromium browser instance.

    Thread-safe via lock. Restarts browser if it was closed/crashed.
    """
    global _browser, _playwright_ctx

    if _browser and _browser.is_connected():
        return _browser

    with _browser_lock:
        # Double-check after acquiring lock
        if _browser and _browser.is_connected():
            return _browser

        try:
            from playwright.sync_api import sync_playwright

            _playwright_ctx = sync_playwright().start()
            _browser = _playwright_ctx.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ],
            )
            logger.info('Playwright Chromium browser launched')
            return _browser
        except Exception:
            logger.exception('Failed to launch Playwright Chromium')
            raise


def render_html_to_pdf(html: str, *, timeout_ms: int = 30_000) -> bytes:
    """
    Convert an HTML string to A4 PDF bytes via headless Chromium.

    Args:
        html: Complete HTML document string (with embedded CSS/fonts).
        timeout_ms: Page load + PDF render timeout in milliseconds.

    Returns:
        PDF file contents as bytes.

    Raises:
        RuntimeError: If Playwright/Chromium is not available.
    """
    browser = _get_browser()
    page = browser.new_page()
    try:
        page.set_content(html, wait_until='networkidle', timeout=timeout_ms)
        pdf_bytes = page.pdf(
            format='A4',
            print_background=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
        )
        return pdf_bytes
    finally:
        page.close()


def is_playwright_available() -> bool:
    """Check if Playwright + Chromium are available for PDF rendering."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def shutdown_browser():
    """Gracefully close the browser (call on app shutdown)."""
    global _browser, _playwright_ctx
    with _browser_lock:
        if _browser:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright_ctx:
            try:
                _playwright_ctx.stop()
            except Exception:
                pass
            _playwright_ctx = None
