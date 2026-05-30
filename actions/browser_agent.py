import json
import re
import time

import google.genai as genai


def _get_api_key():
    from pathlib import Path
    import sys
    base = Path(__file__).resolve().parent.parent
    config_path = base / "config" / "api_keys.json"
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))["gemini_api_key"]
    except Exception:
        from core.security import security
        keys = security.decrypt_keys()
        return keys.get("gemini_api_key", "")


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=_get_api_key(), http_options={"api_version": "v1beta"})
    return _client


MAX_STEPS = 30


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

    from actions.screen_processor import _capture_screen, detect_ui_elements
    from actions.computer_control import computer_control as cc
    from actions.browser_control import browser_control as bc

    client = _get_client()
    model = "models/gemini-2.5-flash"

    sys_prompt = (
        "You are an autonomous browser agent. Your goal is to accomplish a task "
        "by analyzing screenshots and deciding what actions to take.\n\n"
        "Available actions, return as JSON:\n"
        '{"action": "navigate", "url": "https://..."}\n'
        '{"action": "click", "target": "description of element to click"}\n'
        '{"action": "type", "target": "description of input field", "text": "text to type"}\n'
        '{"action": "scroll", "direction": "down|up"}\n'
        '{"action": "done", "result": "summary of what was accomplished"}\n'
        '{"action": "fail", "reason": "why the goal cannot be completed"}\n\n'
        "You MUST call vision_navigate tool to find elements before clicking. "
        "Return ONLY valid JSON."
    )

    conversation = [
        {"role": "user", "parts": [{"text": f"Goal: {goal}\n\nStart by navigating to the relevant website. {sys_prompt}"}]}
    ]

    step = 0
    last_action = None

    while step < MAX_STEPS:
        step += 1
        if player:
            player.write_log(f"BROWSER_AGENT: Step {step}/{MAX_STEPS} — deciding next action")
            player.set_state("THINKING")

        # Capture current screen
        try:
            image_bytes, mime_type = _capture_screen()
            if player:
                player.write_log(f"BROWSER_AGENT: Screen captured ({len(image_bytes)} bytes)")
        except Exception as e:
            return f"Browser agent failed at step {step}: screen capture error - {e}"

        import base64
        b64 = base64.b64encode(image_bytes).decode("ascii")

        # Get UI elements
        try:
            elements = detect_ui_elements()
        except Exception:
            elements = []

        elements_text = f"\nDetected UI elements: {json.dumps(elements[:20])}" if elements else ""

        # Get visible text on page via Playwright or OCR fallback
        page_text = ""
        try:
            from actions.browser_playwright import browser_playwright_action, browser_session
            page_text = browser_playwright_action({"action": "extract"}, player)
            if not page_text or "No browser page open" in page_text or "extraction failed" in page_text:
                page_text = ""
                # OCR fallback from screenshot
                try:
                    import pytesseract
                    from PIL import Image
                    import io
                    text = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))
                    page_text = text[:2000].strip()
                except Exception:
                    pass
        except Exception:
            pass

        page_context = f"\nExtracted page content: {page_text[:500]}" if page_text else ""

        # Build prompt
        history_text = ""
        if last_action:
            history_text = f"\nLast action taken: {json.dumps(last_action)}"

        prompt = (
            f"Goal: {goal}\n"
            f"Current step: {step}/{MAX_STEPS}"
            f"{history_text}"
            f"{elements_text}"
            f"{page_context}"
            f"\n\nAnalyze the screenshot and decide the NEXT action. "
            f"Return ONLY a JSON object with your decision."
        )

        conversation.append({
            "role": "user",
            "parts": [{"text": prompt}, {"inline_data": {"mime_type": mime_type, "data": b64}}]
        })

        try:
            response = client.models.generate_content(model=model, contents=conversation)
            text = response.text.strip()
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

        # Execute action
        try:
            if player:
                player.write_log(f"BROWSER_AGENT: Executing {action}...")
            if action == "navigate":
                url = decision.get("url", "")
                if url:
                    if player:
                        player.write_log(f"BROWSER_AGENT: Navigating to {url}")
                    bc({"action": "go_to", "url": url}, player)
                    time.sleep(2)
                    try:
                        from actions.browser_playwright import browser_playwright_action
                        browser_playwright_action({"action": "goto", "url": url}, player)
                    except Exception:
                        pass
                    if player:
                        player.write_log(f"BROWSER_AGENT: Navigated to {url}")

            elif action == "click":
                target = decision.get("target", "")
                if target:
                    if player:
                        player.write_log(f"BROWSER_AGENT: Looking for '{target}' on screen...")
                    from actions.screen_processor import vision_find_and_click
                    result = vision_find_and_click(target)
                    try:
                        data = json.loads(result) if isinstance(result, str) else result
                    except json.JSONDecodeError:
                        data = {"found": False, "error": result[:100]}
                    if data.get("found"):
                        import pyautogui
                        import mss
                        with mss.mss() as sct:
                            monitors = sct.monitors
                            mon = monitors[1] if len(monitors) > 1 else monitors[0]
                            screen_w, screen_h = mon["width"], mon["height"]
                        from actions.screen_processor import _IMG_MAX_W, _IMG_MAX_H, _PIL, _capture_screen
                        img_w, img_h = _IMG_MAX_W, _IMG_MAX_H
                        if _PIL:
                            try:
                                from PIL import Image
                                import io
                                raw, _ = _capture_screen()
                                tmp = Image.open(io.BytesIO(raw))
                                img_w, img_h = tmp.size
                            except Exception:
                                pass
                        scale_x = screen_w / img_w if img_w > 0 else 1.0
                        scale_y = screen_h / img_h if img_h > 0 else 1.0
                        click_x = int(data["x"] * scale_x)
                        click_y = int(data["y"] * scale_y)
                        if player:
                            player.write_log(f"BROWSER_AGENT: Clicking at ({click_x}, {click_y}) (scaled from img {img_w}x{img_h} to screen {screen_w}x{screen_h})")
                        pyautogui.click(click_x, click_y)
                    else:
                        if player:
                            player.write_log(f"BROWSER_AGENT: Could not find target: {data.get('error', 'unknown')}")
                    time.sleep(1)

            elif action == "type":
                target = decision.get("target", "")
                text = decision.get("text", "")
                if target and text:
                    if player:
                        player.write_log(f"BROWSER_AGENT: Finding '{target}' to type...")
                    from actions.screen_processor import vision_find_and_click
                    result = vision_find_and_click(target)
                    try:
                        data = json.loads(result) if isinstance(result, str) else result
                    except json.JSONDecodeError:
                        data = {"found": False, "error": result[:100]}
                    if data.get("found"):
                        import pyautogui
                        import mss
                        with mss.mss() as sct:
                            monitors = sct.monitors
                            mon = monitors[1] if len(monitors) > 1 else monitors[0]
                            screen_w, screen_h = mon["width"], mon["height"]
                        from actions.screen_processor import _IMG_MAX_W, _IMG_MAX_H, _PIL, _capture_screen
                        img_w, img_h = _IMG_MAX_W, _IMG_MAX_H
                        if _PIL:
                            try:
                                from PIL import Image
                                import io
                                raw, _ = _capture_screen()
                                tmp = Image.open(io.BytesIO(raw))
                                img_w, img_h = tmp.size
                            except Exception:
                                pass
                        scale_x = screen_w / img_w if img_w > 0 else 1.0
                        scale_y = screen_h / img_h if img_h > 0 else 1.0
                        click_x = int(data["x"] * scale_x)
                        click_y = int(data["y"] * scale_y)
                        pyautogui.click(click_x, click_y)
                        time.sleep(0.5)
                        pyautogui.write(text, interval=0.05)
                    time.sleep(1)

            elif action == "scroll":
                direction = decision.get("direction", "down")
                cc({"action": "scroll", "direction": direction, "amount": 3}, player)
                time.sleep(1)

            elif action == "wait":
                time.sleep(2)

        except Exception as e:
            if player:
                player.write_log(f"BROWSER_AGENT: Action error: {e}")
            time.sleep(1)

        # Keep only last 4 messages to manage context window
        if len(conversation) > 6:
            conversation = [conversation[0]] + conversation[-4:]

    return f"Browser agent: Reached maximum steps ({MAX_STEPS}) without completing the goal."
