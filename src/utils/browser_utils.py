import asyncio
import base64
import json
import os
import random
import re
import time
from typing import Any, List, Optional

from config.app_config import HEADLESS_MODE, JOB_SITE

if JOB_SITE == "indeed":
    from patchright.async_api import Browser, BrowserContext, Page, async_playwright
else:
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from config.constants import BROWSER_STORAGE_STATE, DEBUG_DIR
from config.logger_config import logger

try:  # TODO: add for back compatibility, remove this later
    from config.app_config import DEBUG_MODE
except ImportError:
    DEBUG_MODE = False


async def debug_capture(page: Page, label: str) -> None:
    """Save a screenshot and page HTML to data/debug/ for post-mortem analysis.

    Only runs when DEBUG_MODE=True. Files are timestamped so each failure gets
    its own pair. Share the .png and .html with Claude to diagnose selector issues.
    """
    if not DEBUG_MODE:
        return
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r"[^\w\-]", "_", label)[:60]
        base = os.path.join(DEBUG_DIR, f"{timestamp}_{safe_label}")
        await page.screenshot(path=f"{base}.png", full_page=True)
        html = await page.content()
        with open(f"{base}.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.debug(f"Debug capture saved: {base}.png / .html")
    except Exception as e:
        logger.debug(f"debug_capture failed: {e}")


def ensure_playwright_profile() -> str:
    """Ensure Playwright session directory exists"""
    logger.info(f"Ensuring Playwright session directory exists at: {BROWSER_STORAGE_STATE}")
    session_dir = os.path.dirname(BROWSER_STORAGE_STATE)
    if not os.path.exists(session_dir):  # TODO: add for back compatibility, remove this later
        session_dir_new = os.path.join(
            session_dir, "/".join(BROWSER_STORAGE_STATE.split("/")[:-1]) + "/linkedin_state.json"
        )
        if not os.path.exists(session_dir_new):
            os.makedirs(session_dir)
            logger.debug(f"Created Playwright session directory: {session_dir}")
            return session_dir_new
    return session_dir


def _sanitize_storage_state(path: str) -> dict:
    """Load browser_state.json and sanitize cookies for Playwright's storageState API.

    Playwright requires `cookies[i].partitionKey` to be a URL string or absent.
    Some Chromium versions write it as a dict (CHIPS partitioned cookies with
    {topLevelSite, hasCrossSiteAncestor}). This loader strips the field whenever
    it's not a plain string, so cross-site partitioned cookies from external
    embeds don't crash new_context(). Cookies themselves are preserved; only
    the partition descriptor is dropped.
    """
    try:
        with open(path, "r") as f:
            state = json.loads(f.read() or "{}")
    except Exception as e:
        logger.debug(f"_sanitize_storage_state read failed (non-fatal): {e}")
        return {}
    if not isinstance(state, dict):
        return {}
    cookies = state.get("cookies")
    if isinstance(cookies, list):
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            pk = cookie.get("partitionKey")
            if pk is not None and not isinstance(pk, str):
                cookie.pop("partitionKey", None)
    return state


async def create_playwright_browser() -> tuple[Browser, BrowserContext, Page]:
    """Create Playwright browser, context and page asynchronously (PRIMARY METHOD)

    Uses patchright (Chromium-based) which patches automation detection signals
    to bypass Cloudflare and other bot detection systems.
    Session cookies are persisted via browser_state.json.
    """
    logger.info("Creating Playwright browser (async)")

    try:
        ensure_playwright_profile()
        viewport = {"width": 1920, "height": 1080}
        storage_state = (
            _sanitize_storage_state(BROWSER_STORAGE_STATE)
            if os.path.exists(BROWSER_STORAGE_STATE)
            else None
        )

        args = [
            "--window-position=0,0",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--ignore-certificate-errors",
            "--disable-extensions",
            "--disable-gpu",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-translate",
            "--disable-popup-blocking",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-logging",
            "--disable-autofill",
            "--disable-plugins",
            "--disable-blink-features=AutomationControlled",
        ]

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=HEADLESS_MODE,
            args=args,
        )

        context = await browser.new_context(
            viewport=viewport,
            screen=viewport,
            storage_state=storage_state,
            locale="en-US",
            permissions=["notifications"],
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )

        page = await context.new_page()

        context.on(
            "page",
            lambda p: asyncio.ensure_future(p.set_viewport_size(viewport)),
        )

        if DEBUG_MODE:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            logger.info(
                f"Playwright tracing enabled — trace will be saved to {DEBUG_DIR}/trace.zip"
            )

        logger.info("Playwright browser created successfully")
        return browser, context, page

    except Exception as e:
        logger.error(f"Failed to create Playwright browser: {e}")
        raise


async def stop_tracing(context: BrowserContext) -> None:
    """Stop Playwright tracing and save the trace zip (only when DEBUG_MODE=True).

    Call this in the finally block where you close the browser. The resulting
    trace.zip can be opened at https://trace.playwright.dev to inspect every
    action, DOM snapshot, and network request.
    """
    if not DEBUG_MODE:
        return
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        trace_path = os.path.join(DEBUG_DIR, "trace.zip")
        await context.tracing.stop(path=trace_path)
        logger.info(f"Playwright trace saved to {trace_path}")
    except Exception as e:
        logger.debug(f"stop_tracing failed: {e}")


async def save_browser_session(context: BrowserContext) -> None:
    """Save Playwright session state (async)"""
    try:
        ensure_playwright_profile()
        storage_state = await context.storage_state()

        # Playwright's storage_state() omits empty arrays, but the reader
        # (browser.new_context) is strict and rejects origins without a
        # localStorage key. Normalize before writing.
        for origin in storage_state.get("origins", []):
            origin.setdefault("localStorage", [])
        storage_state.setdefault("cookies", [])

        with open(BROWSER_STORAGE_STATE, "w") as f:
            json.dump(storage_state, f)

        logger.info(f"Playwright session saved to {BROWSER_STORAGE_STATE}")
    except Exception as e:
        logger.error(f"Failed to save Playwright session: {e}")


async def safe_click(
    page: Page, selector: str, timeout: int = 1000, element_number: int = 0
) -> bool:
    """Safely click element with retries (async)"""
    try:
        locator = page.locator(selector)
        element_count = await locator.count()

        if element_count == 0:
            logger.warning(f"Element not found: {selector}")
            await debug_capture(page, "click_not_found")
            return False

        # Select the first matched element (even if multiple)
        target = locator.nth(element_number) if element_count > 1 else locator

        if element_count > 1:
            logger.debug(
                f"Found {element_count} elements for selector '{selector}', using the first match"
            )

        # Ensure visibility and bring into view
        try:
            await target.wait_for(state="visible", timeout=timeout)
        except Exception:
            # Fall back to attached state if not visible
            await target.wait_for(state="attached", timeout=timeout)

        await target.scroll_into_view_if_needed(timeout=500)

        # Human-like pause before clicking
        pause_time = random.uniform(0.1, 0.3)
        await asyncio.sleep(pause_time)

        await target.click(timeout=timeout)
        logger.debug(f"Successfully clicked: {selector}")
        return True

    except Exception as e:
        logger.warning(f"Failed to click element '{selector}': {e}")
        await debug_capture(page, "click_failed")
        return False


async def safe_fill(
    page: Page,
    selector: str,
    text: str,
    timeout: int = 10000,
    wait_for_timeout: Optional[int] = None,
) -> bool:
    """Safely fill text input with human-like behavior (async)"""
    try:
        locator = page.locator(selector)

        if wait_for_timeout is not None:
            try:
                await locator.first.wait_for(state="attached", timeout=wait_for_timeout)
            except Exception:
                return False

        element_count = await locator.count()

        if element_count == 0:
            logger.warning(f"No elements found for selector: {selector}")
            await debug_capture(page, "fill_not_found")
            return False

        if element_count > 1:
            logger.debug(
                f"Found {element_count} elements for selector '{selector}', trying each one"
            )

        targets = [locator.nth(i) for i in range(element_count)] if element_count > 1 else [locator]
        fill_timeout = 2000 if element_count > 1 else timeout

        for i, target in enumerate(targets):
            try:
                try:
                    await target.wait_for(state="visible", timeout=fill_timeout)
                except Exception:
                    await target.wait_for(state="attached", timeout=fill_timeout)

                await target.scroll_into_view_if_needed(timeout=500)

                try:
                    await target.clear()
                except Exception:
                    pass

                await async_pause(1, 2)

                await target.fill(text)

                if "password" in selector:
                    logger.debug(
                        f"Successfully filled '{selector}'"
                        + (f" (element {i})" if element_count > 1 else "")
                    )
                else:
                    logger.debug(
                        f"Successfully filled '{selector}' with text {text}"
                        + (f" (element {i})" if element_count > 1 else "")
                    )
                return True
            except Exception as e:
                if element_count > 1:
                    logger.debug(f"Element {i} not fillable for '{selector}': {e}, trying next")
                    continue
                raise

    except Exception as e:
        logger.warning(f"Failed to fill element '{selector}': {e}")
        await debug_capture(page, "fill_failed")
        return False


async def get_element_text(page: Page, selector: str, timeout: int = 5000) -> Optional[str]:
    """Get text content from element (async)"""
    try:
        locator = page.locator(selector)
        if await locator.count() == 0:
            return None

        await locator.wait_for(state="visible", timeout=timeout)
        text = await locator.text_content()
        if text:
            text = re.sub(r"\s+", " ", text).strip()
        else:
            text = None
        return text

    except Exception as e:
        logger.warning(f"Failed to get text from '{selector}': {e}")
        return None


async def get_clean_text(element):
    """Extract clean text from element, targeting the actual text span (async)"""
    try:
        # Try to find the specific span with text content first
        if hasattr(element, "locator"):
            text_locator = element.locator("span.text-body-small").first
            if await text_locator.count() > 0:
                text = await text_locator.text_content() or ""
                return text.strip()
        else:
            # Fallback for non-Playwright elements (should not happen in async context)
            text_span = element.find_element("css selector", "span.text-body-small")
            if text_span:
                return text_span.text.strip()
    except Exception:
        pass

    # Fallback to getting text from entire element and cleaning it
    try:
        if hasattr(element, "text_content"):
            if callable(element.text_content):
                raw = await element.text_content() or ""
            else:
                raw = element.text_content or ""
            text = raw.strip()
        else:
            text = element.text.strip()
    except Exception:
        text = ""
    # Remove extra whitespace and newlines
    text = re.sub(r"\s+", " ", text)
    return text


async def get_element_attribute(
    page: Page, selector: str, attribute: str, timeout: int = 5000
) -> Optional[str]:
    """Get attribute value from element (async)"""
    try:
        locator = page.locator(selector)
        if await locator.count() == 0:
            return None

        await locator.wait_for(state="attached", timeout=timeout)
        return await locator.get_attribute(attribute)

    except Exception as e:
        logger.warning(f"Failed to get attribute '{attribute}' from '{selector}': {e}")
        return None


# Utility function to pause execution (keep from original utils)
def pause(low: float = 0.5, high: float = 1) -> None:
    """Hold a random pause between low and high seconds"""
    pause_time = round(random.uniform(low, high), 1)
    time.sleep(pause_time)


async def async_pause(low: float = 0.5, high: float = 1) -> None:
    """Hold a random pause without blocking the asyncio event loop."""
    pause_time = round(random.uniform(low, high), 1)
    await asyncio.sleep(pause_time)


async def get_current_page_testid(page: Page, testids: list[str]) -> Optional[str]:
    """Return the first matching data-testid from the given list that is present on the page.

    Useful before clicking a multi-step form's Continue button so that
    ``wait_for_page_transition`` knows which element to watch for detachment.
    Returns None when none of the known testids are found (e.g. a generic question page).
    """
    for testid in testids:
        el = await find_element_safely(page, f"[data-testid='{testid}']", timeout=500)
        if el:
            return testid
    return None


async def wait_for_page_transition(
    page: Page, old_testid: Optional[str], timeout: float = 10.0
) -> None:
    """Wait until the named page element detaches, confirming a multi-step form advanced.

    Pass the testid returned by ``get_current_page_testid`` before clicking Continue.
    When *old_testid* is None (generic page with no known testid anchor) this is a no-op;
    the caller's fixed pause is sufficient.
    """
    if not old_testid:
        return
    try:
        await page.wait_for_selector(
            f"[data-testid='{old_testid}']",
            state="detached",
            timeout=int(timeout * 1000),
        )
        logger.debug(f"Page transitioned away from '{old_testid}'")
    except Exception:
        logger.debug(f"Timed out waiting for '{old_testid}' to detach; proceeding anyway")


async def find_element_safely(
    page: Page, selector: str, by: str = "css selector", timeout: Optional[int] = None
):
    """Find element using optimal method for browser type (async)"""
    try:
        # Normalize selector for Playwright
        final_selector = (
            selector if by == "css selector" else f"xpath={selector}" if by == "xpath" else selector
        )
        element = page.locator(final_selector).first

        if timeout is not None:
            try:
                await element.wait_for(state="attached", timeout=timeout)
            except Exception:
                return None

        if await element.count() > 0:
            return element
        else:
            return None
    except Exception as e:
        logger.debug(f"Element finding failed for '{selector}': {e}")
        return None


async def find_elements_safely(
    page: Page, selector: str, by: str = "css selector", timeout: Optional[int] = None
) -> List[Any]:
    """Find elements using optimal method for browser type (async)"""
    try:
        final_selector = (
            selector if by == "css selector" else f"xpath={selector}" if by == "xpath" else selector
        )
        elements = await page.locator(final_selector).all()

        if timeout is not None:
            try:
                await elements.wait_for(state="attached", timeout=timeout)
            except Exception:
                return []

        if len(elements) > 0:
            return elements
        else:
            return []

    except Exception as e:
        logger.debug(f"Elements finding failed for '{selector}': {e}")
        return []


async def send_keys_to_element(page: Page, element: Any, keys: str) -> bool:
    """Send keys to element with framework compatibility (async)"""
    try:
        if keys == "Enter":
            # Handle Enter key specifically
            await page.keyboard.press("Enter")
        else:
            try:
                # Prefer locator typing when available
                if hasattr(element, "fill"):
                    try:
                        # best-effort to clear then type
                        await element.fill(str(keys))
                    except Exception:
                        await element.type(str(keys))
                else:
                    await page.keyboard.type(str(keys))
            except Exception:
                await page.keyboard.type(str(keys))
        return True
    except Exception as e:
        logger.warning(f"Failed to send keys: {e}")
        return False


async def get_element_attribute_safely(
    element: Any, selector: str, attribute: str, by: str = "css selector", timeout: int = 1000
) -> str:
    """Get element attribute using optimal method for browser type (async)"""
    try:
        # Handle Playwright Locator objects
        if hasattr(element, "evaluate"):
            child_locator = element.locator(selector)
        elif hasattr(element, "locator"):
            parent = element.locator() if callable(element.locator) else element.locator
            child_locator = parent.locator(selector)
        else:
            return ""
        # Without an explicit timeout a missing element costs Playwright's 30s
        # default, which multiplies across every selector of a fallback chain
        return await child_locator.first.get_attribute(attribute, timeout=timeout) or ""
    except Exception as e:
        logger.debug(f"Failed to get attribute {attribute} from element {selector}: {e}")
        return ""


async def is_scrollable(element) -> bool:
    """
    Check if an element is scrollable (Playwright compatible) - async

    Works with:
    - PlaywrightElementWrapper
    - Playwright Locator objects
    - Page elements

    Args:
        element: Element to check for scrollability

    Returns:
        bool: True if element is scrollable vertically or horizontally
    """
    try:
        # Handle different element types
        if hasattr(element, "evaluate"):
            # Direct Playwright Locator - use it directly
            locator = element
        elif hasattr(element, "locator") and not callable(element.locator):
            # PlaywrightElementWrapper with locator property
            locator = element.locator
        else:
            logger.warning(f"Unsupported element type for scrollability check: {type(element)}")
            return False

        # Use JavaScript to get scroll properties directly from DOM
        is_scrollable_result = await locator.evaluate(
            """
            (element) => {
                const verticalScrollable = element.scrollHeight > element.clientHeight;
                const horizontalScrollable = element.scrollWidth > element.clientWidth;
                return verticalScrollable || horizontalScrollable;
            }
        """
        )

        return bool(is_scrollable_result)

    except Exception as e:
        logger.warning(f"Error checking if element is scrollable: {e}")
        return False


async def scroll_slowly(
    locator: Any, direction: str = "down", time_to_scroll_sec: float = 1.5, delay: float = 0.01
) -> bool:
    """
    Scroll an element in the specified direction (Playwright compatible) - async

    Args:
        locator: Element to scroll (PlaywrightElementWrapper or Playwright Locator)
        direction: "down", "up"
        time_to_scroll_sec: Total time to spend scrolling
        delay: Delay between scroll steps (unused, kept for API compatibility)

    Returns:
        bool: True if scrolling was successful, False otherwise
    """
    try:
        result = await locator.evaluate(
            """
            (element, args) => new Promise((resolve) => {
                const scrollHeight = element.scrollHeight;
                const clientHeight = element.clientHeight;
                let distance = scrollHeight - clientHeight;
                if (distance <= 30) { resolve(false); return; }
                distance += 500;

                const startTop = element.scrollTop;
                const durationMs = args.durationMs;
                const goDown = args.direction === 'down';
                const target = goDown
                    ? Math.min(startTop + distance, scrollHeight - clientHeight)
                    : Math.max(startTop - distance, 0);

                const startTime = performance.now();
                function step(now) {
                    const elapsed = now - startTime;
                    const progress = Math.min(elapsed / durationMs, 1);
                    element.scrollTop = startTop + (target - startTop) * progress;
                    if (progress < 1) {
                        requestAnimationFrame(step);
                    } else {
                        resolve(true);
                    }
                }
                requestAnimationFrame(step);
            })
            """,
            {"durationMs": int(time_to_scroll_sec * 1000), "direction": direction},
        )

        if not result:
            logger.debug("Element has no scrollable content or distance is too short")
        return bool(result)

    except Exception as e:
        logger.warning(f"Error scrolling element {direction}: {e}")
        return False


async def HTML_to_PDF(FilePath):
    """Convert HTML file to PDF using Playwright (async)"""
    if not os.path.isfile(FilePath):
        raise FileNotFoundError(f"File not found: {FilePath}")

    file_url = f"file:///{os.path.abspath(FilePath).replace(os.sep, '/')}"
    playwright = await async_playwright().start()

    # Use headless mode for PDF generation to avoid display issues
    launch_options = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    }

    browser = await playwright.chromium.launch(**launch_options)

    try:
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page = await context.new_page()

        # Wait for the page and all network resources to load
        await page.goto(file_url, wait_until="networkidle")
        logger.info(f"Page loaded: {file_url}")

        # Wait for fonts to load
        await page.evaluate(
            """
            () => document.fonts.ready
        """
        )

        # Additional wait to ensure all styles are applied
        await asyncio.sleep(1)

        pdf_bytes = await page.pdf(
            print_background=True,
            width="8.27in",  # A4 width
            height="11.69in",  # A4 height
            margin={
                "top": "0.8in",
                "bottom": "0.8in",
                "left": "0.5in",
                "right": "0.5in",
            },
            prefer_css_page_size=True,
        )

        # Convert to base64 to match original function signature
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        return pdf_base64

    except Exception as e:
        raise RuntimeError(f"Error with Playwright browser: {e}")
    finally:
        await browser.close()
        await playwright.stop()
