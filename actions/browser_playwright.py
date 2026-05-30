"""
browser_playwright.py — MARK XL Advanced Browser Control
Persistent Playwright Chromium session with full hands-free automation:
  - Navigation (goto, back, forward, reload)
  - Scrolling (scroll up/down/to element)
  - Clicking by text, selector, or coordinates
  - Form filling
  - DOM extraction for LLM navigation
  - Screenshots
  - YouTube playback
  - Web scraping
"""

import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import (
        sync_playwright, TimeoutError as PlaywrightTimeout,
        Browser, BrowserContext, Page
    )
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


class PersistentBrowser:
    def __init__(self):
        self._pw = None
        self.browser: Optional["Browser"] = None
        self.context: Optional["BrowserContext"] = None
        self.page: Optional["Page"] = None

    def start(self, headless: bool = False):
        """Start or ensure the browser is running (sync)."""
        self.stop()
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not installed. Run: pip install playwright && playwright install chromium")
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=headless,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir="memory/browser_videos/",
            record_video_size={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self.page = self.context.new_page()

    def stop(self):
        """Close the browser session."""
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None
        self.browser = None
        self.context = None
        self.page = None

    def _ensure_page(self):
        if self.page and self.browser and self.browser.is_connected():
            return
        self.start()

    def goto(self, url: str) -> str:
        self._ensure_page()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return self.page.title()

    def get_title(self) -> str:
        if not self.page:
            return "No page open"
        return self.page.title()

    def get_url(self) -> str:
        if not self.page:
            return ""
        return self.page.url

    def scroll(self, direction: str = "down", amount: int = 500):
        self._ensure_page()
        if direction == "down":
            self.page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            self.page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "top":
            self.page.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    def click_text(self, text: str) -> bool:
        self._ensure_page()
        try:
            for selector in [
                f"text={text}",
                f"a:has-text('{text}')",
                f"button:has-text('{text}')",
                f"[aria-label*='{text}']",
                f"*:has-text('{text}')",
            ]:
                try:
                    el = self.page.locator(selector).first
                    if el.is_visible(timeout=1000):
                        el.click()
                        self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def click_selector(self, selector: str) -> bool:
        self._ensure_page()
        try:
            self.page.click(selector, timeout=5000)
            return True
        except Exception:
            return False

    def type_text(self, selector: str, text: str, clear: bool = True):
        self._ensure_page()
        el = self.page.locator(selector).first
        if clear:
            el.fill("")
        el.type(text, delay=20)

    def press_key(self, key: str):
        self._ensure_page()
        self.page.keyboard.press(key)

    def search_google(self, query: str) -> str:
        self.goto(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return self.page.title()

    def extract_text(self, max_chars: int = 5000) -> str:
        if not self.page:
            return "No browser page open — navigate to a URL first."
        self._ensure_page()
        try:
            text = self.page.evaluate("""
                () => {
                    const body = document.body;
                    const walker = document.createTreeWalker(
                        body,
                        NodeFilter.SHOW_TEXT,
                        {
                            acceptNode(node) {
                                const parent = node.parentElement;
                                if (!parent) return NodeFilter.FILTER_REJECT;
                                const style = window.getComputedStyle(parent);
                                if (style.display === 'none' || style.visibility === 'hidden') return NodeFilter.FILTER_REJECT;
                                const tag = parent.tagName.toLowerCase();
                                if (['script', 'style', 'noscript', 'svg'].includes(tag)) return NodeFilter.FILTER_REJECT;
                                return NodeFilter.FILTER_ACCEPT;
                            }
                        }
                    );
                    let text = '';
                    let node;
                    while ((node = walker.nextNode())) {
                        const t = node.textContent.trim();
                        if (t.length > 2) text += t + '\\n';
                    }
                    return text;
                }
            """)
            return text[:max_chars].strip()
        except Exception as e:
            return f"Text extraction failed: {e}"

    def get_links(self, limit: int = 20) -> list[dict]:
        self._ensure_page()
        try:
            links = self.page.evaluate(f"""
                () => {{
                    const anchors = document.querySelectorAll('a[href]');
                    return Array.from(anchors).slice(0, {limit}).map(a => ({{
                        text: a.innerText.trim().slice(0, 80),
                        href: a.href,
                        visible: a.offsetParent !== null
                    }}));
                }}
            """)
            return [l for l in links if l["text"]]
        except Exception:
            return []

    def screenshot(self, path: Optional[str] = None) -> Optional[bytes]:
        self._ensure_page()
        save_path = path or str(BASE_DIR / "memory" / "browser_screenshots" / "latest.png")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        self.page.screenshot(path=save_path, full_page=False)
        if path is None:
            with open(save_path, "rb") as f:
                return f.read()
        return None

    def play_youtube(self, query: str) -> str:
        self.goto(f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}")
        try:
            first = self.page.locator("ytd-video-renderer a#thumbnail").first
            if first.is_visible(timeout=5000):
                first.click()
                time.sleep(2)
                return f"Playing YouTube video for '{query}'"
            return f"No results found for '{query}'"
        except Exception:
            return f"Could not play '{query}'"

    def new_tab(self, url: str = "about:blank") -> str:
        self._ensure_page()
        new_page = self.context.new_page()
        self.page = new_page
        if url != "about:blank":
            return self.goto(url)
        return "about:blank"

    def back(self):
        self._ensure_page()
        self.page.go_back()

    def forward(self):
        self._ensure_page()
        self.page.go_forward()

    def reload(self):
        self._ensure_page()
        self.page.reload()


# Global persistent session
browser_session = PersistentBrowser()


def _log(msg, player=None):
    print(f"[Browser] {msg}")
    if player:
        try:
            player.write_log(f"[Browser] {msg}")
        except Exception:
            pass


def browser_playwright_action(parameters: dict, player=None, speak=None) -> str:
    """
    Main action dispatcher for advanced browser control.

    parameters:
      - action: goto|scroll|click|type|search|extract|screenshot|youtube|links|back|forward|reload|stop
      - url: str
      - query: str (for search/youtube)
      - text: str (for click by text)
      - selector: str (for click by selector, type)
      - direction: up|down|top|bottom (for scroll)
      - amount: int (scroll pixels)
      - value: str (text to type)
    """
    action = parameters.get("action", "goto").lower().strip()
    _log(f"Action: {action} | params: {parameters}", player)

    try:
        if action == "goto":
            url = parameters.get("url", "")
            if not url:
                return "No URL provided."
            title = browser_session.goto(url)
            _log(f"Page: {title}", player)
            return f"Navigated to {url}. Page: {title}"

        elif action == "scroll":
            direction = parameters.get("direction", "down")
            amount = int(parameters.get("amount", 500))
            browser_session.scroll(direction, amount)
            return f"Scrolled {direction} by {amount}px"

        elif action == "click":
            text = parameters.get("text", "")
            selector = parameters.get("selector", "")
            if text:
                clicked = browser_session.click_text(text)
                return f"Clicked text '{text}': {clicked}"
            elif selector:
                clicked = browser_session.click_selector(selector)
                return f"Clicked selector '{selector}': {clicked}"
            return "Provide 'text' or 'selector' to click."

        elif action == "type":
            selector = parameters.get("selector", "")
            value = parameters.get("value", "")
            if selector and value:
                browser_session.type_text(selector, value)
                return f"Typed '{value[:50]}' into '{selector}'"
            return "Provide 'selector' and 'value' to type."

        elif action == "press":
            key = parameters.get("key", "Enter")
            browser_session.press_key(key)
            return f"Pressed key: {key}"

        elif action == "search":
            query = parameters.get("query", "")
            if not query:
                return "Please provide a search query."
            title = browser_session.search_google(query)
            return f"Searched Google for: '{query}'. Page: {title}"

        elif action == "youtube":
            query = parameters.get("query", "")
            if not query:
                return "Please provide a YouTube search query."
            return browser_session.play_youtube(query)

        elif action in ("extract", "scrape"):
            text = browser_session.extract_text(5000)
            return text

        elif action == "links":
            links = browser_session.get_links(20)
            return json.dumps(links, indent=2)

        elif action == "screenshot":
            path = parameters.get("path")
            browser_session.screenshot(path)
            loc = path or "memory/browser_screenshots/latest.png"
            return f"Screenshot saved to {loc}"

        elif action in ("back", "previous"):
            browser_session.back()
            return "Went back"

        elif action in ("forward", "next"):
            browser_session.forward()
            return "Went forward"

        elif action == "reload":
            browser_session.reload()
            return "Reloaded page"

        elif action in ("new_tab", "tab"):
            url = parameters.get("url", "about:blank")
            browser_session.new_tab(url)
            return f"Opened new tab: {url}"

        elif action == "stop":
            browser_session.stop()
            return "Browser session closed."

        else:
            return (
                f"Unknown action '{action}'. "
                "Available: goto, search, youtube, scroll, click, type, extract, links, screenshot, back, forward, reload, stop"
            )

    except Exception as e:
        _log(f"Browser action '{action}' failed: {e}", player)
        traceback.print_exc()
        return f"Playwright error: {e}"
