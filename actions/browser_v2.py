import asyncio
import traceback
from pathlib import Path

from core.utils import get_api_key

_client = None
_browser_session = None

def _get_client():
    global _client
    if _client is None:
        import google.genai as genai
        key = get_api_key()
        if key:
            _client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    return _client


async def _ensure_browser():
    global _browser_session
    if _browser_session is None:
        try:
            from browser_use import Browser, BrowserConfig
            config = BrowserConfig(
                headless=False,
                disable_security=True,
                extra_chromium_args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            _browser_session = Browser(config=config)
        except ImportError:
            raise RuntimeError("browser-use not installed. Run: pip install browser-use")
    return _browser_session


def _clean_result(output) -> str:
    """Extract readable text from browser-use result."""
    if hasattr(output, "final_result") and output.final_result:
        return str(output.final_result)
    if hasattr(output, "result") and output.result:
        return str(output.result)
    if hasattr(output, "extracted_content") and output.extracted_content:
        return str(output.extracted_content)
    if hasattr(output, "all_results") and output.all_results:
        parts = [str(r) for r in output.all_results if r]
        return "\n".join(parts[-5:])
    return str(output)[:2000]


def browser_ai_task(parameters: dict, player=None, speak=None) -> str:
    goal = parameters.get("goal", "").strip()
    if not goal:
        return "No goal specified."

    mode = parameters.get("mode", "auto").strip().lower()
    url = parameters.get("url", "").strip()

    if player:
        player.write_log(f"BROWSER_AI: {goal[:120]}")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_run_browser_ai(goal, mode, url, speak))
        loop.close()
        return result
    except Exception as e:
        traceback.print_exc()
        return f"Browser AI task failed: {e}"


async def _run_browser_ai(goal: str, mode: str, url: str, speak) -> str:
    browser = await _ensure_browser()

    if mode == "extract":
        return await _extract_data(goal, url, browser)

    if mode == "screenshot":
        return await _take_screenshot(url, browser)

    if mode == "crawl":
        return await _crawl_website(goal, url)

    return await _run_agent(goal, browser, speak)


async def _run_agent(goal: str, browser, speak) -> str:
    try:
        from browser_use import Agent
        from browser_use.controller import Controller

        controller = Controller()

        if speak:
            speak(f"Browsing for you, sir.")

        agent = Agent(
            task=goal,
            browser=browser,
            controller=controller,
            use_vision=True,
            max_actions_per_step=10,
        )

        history = await agent.run(max_steps=50)
        return _clean_result(history)

    except Exception as e:
        raise RuntimeError(f"Browser agent failed: {e}")


async def _extract_data(goal: str, url: str, browser) -> str:
    if not url:
        return "URL required for extract mode."

    try:
        from browser_use.telepathy import Extractor
        extractor = Extractor()
        data = await extractor.extract(url=url, instruction=goal)
        if isinstance(data, dict):
            return "\n".join(f"{k}: {v}" for k, v in data.items())
        return str(data)
    except ImportError:
        import json
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler() as crawler:
            result = await crawler.run(url=url, word_count_threshold=50)
            markdown = result.markdown[:4000] if hasattr(result, "markdown") else str(result)[:4000]
            return f"Extracted content from {url}:\n\n{markdown}"
    except Exception as e:
        raise RuntimeError(f"Data extraction failed: {e}")


async def _take_screenshot(url: str, browser) -> str:
    if not url:
        return "URL required for screenshot mode."
    try:
        page = await browser.get_current_page()
        await page.goto(url, wait_until="networkidle")
        screenshot_path = str(Path.home() / "Pictures" / "browser_screenshot.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        return f"Screenshot saved: {screenshot_path}"
    except Exception as e:
        raise RuntimeError(f"Screenshot failed: {e}")


async def _crawl_website(goal: str, url: str) -> str:
    if not url:
        return "URL required for crawl mode."
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as crawler:
            result = await crawler.run(
                url=url,
                word_count_threshold=50,
                extraction_strategy=None,
                chunking_strategy=None,
            )
            if hasattr(result, "markdown"):
                return f"Markdown from {url}:\n\n{result.markdown[:4000]}"
            return f"Content from {url}:\n\n{str(result)[:4000]}"
    except Exception as e:
        raise RuntimeError(f"Crawl failed: {e}")
