import json
import re
import time

MAX_STEPS = 8


def browser_agent(parameters: dict, player=None, speak=None) -> str:
    goal = parameters.get("goal", "").strip()
    if not goal:
        return "No goal specified for browser agent."

    if player:
        player.write_log(f"BROWSER_AGENT: Starting -- '{goal[:80]}'")

    import sys
    from pathlib import Path
    base = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(base))

    from core.model_router import router

    step = 0
    last_action = None
    last_result = ""

    while step < MAX_STEPS:
        step += 1
        if player:
            player.write_log(f"BROWSER_AGENT: Step {step}/{MAX_STEPS}")

        # Get page state via Playwright (no screenshots, no Gemini)
        try:
            from actions.browser_playwright import browser_playwright_action, browser_session
            page_title = browser_session.get_title() if hasattr(browser_session, 'page') and browser_session.page else "No browser page open"
            page_url = browser_session.get_url() if hasattr(browser_session, 'page') and browser_session.page else ""
            page_text = browser_playwright_action({"action": "extract"}, player)
            page_links = browser_playwright_action({"action": "links"}, player)
        except Exception as e:
            if player:
                player.write_log(f"BROWSER_AGENT: Playwright error: {e}")
            return f"Browser agent failed at step {step}: Playwright error - {e}"

        if not page_title or "No browser page open" in str(page_title):
            decision = {"action": "navigate", "url": goal if goal.startswith("http") else f"https://www.google.com/search?q={goal.replace(' ', '+')}"}
        else:
            history = ""
            if last_action:
                history = f"\nLast action: {json.dumps(last_action)}\nLast result: {last_result[:200]}"

            context = (
                f"Goal: {goal}\n"
                f"Step: {step}/{MAX_STEPS}\n"
                f"Current URL: {page_url}\n"
                f"Page Title: {page_title}\n"
                f"Page Text (first 2000 chars): {(page_text or '')[:2000]}\n"
                f"Links on page: {(page_links or '')[:1000]}"
                f"{history}\n\n"
                "Decide the next action. Available actions:\n"
                '{"action": "navigate", "url": "https://..."}\n'
                '{"action": "click", "target": "exact visible text of element"}\n'
                '{"action": "type", "target": "css selector or label text", "text": "text to type"}\n'
                '{"action": "scroll", "direction": "down|up"}\n'
                '{"action": "done", "result": "summary of what was accomplished"}\n'
                '{"action": "fail", "reason": "why the goal cannot be completed"}\n\n'
                "Return ONLY valid JSON."
            )

            try:
                response = router.smart_route(context, task_type="reasoning")
                text = response.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                decision = json.loads(text)
            except Exception as e:
                if player:
                    player.write_log(f"BROWSER_AGENT: Decision error: {e}")
                continue

        action = decision.get("action", "")
        last_action = decision

        if player:
            player.write_log(f"BROWSER_AGENT: Decision -- {json.dumps(decision)}")

        if action == "done":
            result = decision.get("result", "Task completed.")
            if player:
                player.write_log(f"BROWSER_AGENT: Done -- {result}")
            return f"Browser agent completed: {result}"

        if action == "fail":
            reason = decision.get("reason", "Unknown failure")
            if player:
                player.write_log(f"BROWSER_AGENT: Failed -- {reason}")
            return f"Browser agent failed: {reason}"

        try:
            if player:
                player.write_log(f"BROWSER_AGENT: Executing {action}...")

            if action == "navigate":
                url = decision.get("url", "")
                if url:
                    result = browser_playwright_action({"action": "goto", "url": url}, player)
                    last_result = str(result)
                    time.sleep(2)

            elif action == "click":
                target = decision.get("target", "")
                if target:
                    result = browser_playwright_action({"action": "click", "text": target}, player)
                    if "not found" in str(result).lower() or "failed" in str(result).lower():
                        result = browser_playwright_action({"action": "click", "selector": target}, player)
                    last_result = str(result)
                    time.sleep(1)

            elif action == "type":
                target = decision.get("target", "")
                text = decision.get("text", "")
                if target and text:
                    result = browser_playwright_action({"action": "type", "selector": target, "value": text}, player)
                    last_result = str(result)
                    time.sleep(1)

            elif action == "scroll":
                direction = decision.get("direction", "down")
                result = browser_playwright_action({"action": "scroll", "direction": direction, "amount": 500}, player)
                last_result = str(result)
                time.sleep(1)

        except Exception as e:
            last_result = f"Error: {e}"
            if player:
                player.write_log(f"BROWSER_AGENT: Action error: {e}")
            time.sleep(1)

    return f"Browser agent: Reached maximum steps ({MAX_STEPS}) without completing the goal."
