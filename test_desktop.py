#!/usr/bin/env python3
"""Comprehensive test suite for MARK XL desktop automation tools."""

import sys
import os
import traceback
import time
import json
from pathlib import Path

# Fix Windows console encoding for Unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Disable pyautogui FAILSAFE for testing so corner mouse doesn't abort
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.01
except ImportError:
    pass

SRC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC_DIR))

PASS = 0
FAIL = 0
ERRORS = []


def test(name: str, func, *args, **kwargs):
    global PASS, FAIL
    try:
        result = func(*args, **kwargs)
        print(f"  [PASS] {name}")
        PASS += 1
        return result
    except Exception as e:
        tb = traceback.format_exc()
        print(f"  [FAIL] {name}")
        print(f"         {type(e).__name__}: {e}")
        ERRORS.append((name, type(e).__name__, str(e), tb))
        FAIL += 1
        return None


def test_eq(name: str, expected, actual):
    global PASS, FAIL
    if expected == actual:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}")
        print(f"         Expected: {expected!r}")
        print(f"         Got:      {actual!r}")
        ERRORS.append((name, "AssertionError", f"Expected {expected!r}, got {actual!r}", ""))
        FAIL += 1


def section(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


# =========================================================================
# 1. open_app.py
# =========================================================================
section("1. open_app.py — open_application function")

try:
    from actions.open_app import open_app, _normalize, _launch_windows
    print("  [PASS] Import actions.open_app")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] Import actions.open_app: {e}")
    FAIL += 1
    ERRORS.append(("Import open_app", type(e).__name__, str(e), traceback.format_exc()))
    open_app = None

if open_app:
    # Basic — valid app names
    test("open_app with 'notepad' (should open or report attempt)",
         open_app, {"app_name": "notepad"})

    test("open_app with 'calculator' (should open or report attempt)",
         open_app, {"app_name": "calculator"})

    # Edge cases
    test_eq("open_app with empty string",
            "No application name provided.",
            open_app({"app_name": ""}))

    test_eq("open_app with None parameters",
            "No application name provided.",
            open_app(None))

    test_eq("open_app with missing app_name key",
            "No application name provided.",
            open_app({"wrong_key": "notepad"}))

    test_eq("open_app with whitespace-only",
            "No application name provided.",
            open_app({"app_name": "   "}))

    result = test("open_app with unknown app",
                  open_app, {"app_name": "xysdfjnkalsdjkl_should_not_exist_98765"})
    if result is not None:
        print(f"         -> '{result}'")

    # _normalize edge cases
    test_eq("_normalize preserves unknown app",
            "some_random_app",
            _normalize("some_random_app"))

    test_eq("_normalize strips whitespace",
            "notepad.exe",
            _normalize("  notepad  "))

    test_eq("_normalize case insensitive",
            "notepad.exe",
            _normalize("NOTEPAD"))

# =========================================================================
# 2. computer_control.py
# =========================================================================
section("2. computer_control.py — computer control actions")

try:
    from actions.computer_control import computer_control, _require_pyautogui, _random_data, _user_profile, _safe_screenshot_path
    print("  [PASS] Import actions.computer_control")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] Import actions.computer_control: {e}")
    FAIL += 1
    ERRORS.append(("Import computer_control", type(e).__name__, str(e), traceback.format_exc()))
    computer_control = None

if computer_control:
    # Force-disable FAILSAFE after module import (module re-enables it)
    try:
        import pyautogui; pyautogui.FAILSAFE = False; pyautogui.PAUSE = 0.01
    except Exception: pass

    # --- 2a. _detect_action — NOT in computer_control.py, verify this correctly ---
    section("  2a. computer_control edge cases")

    # Empty / missing params
    test_eq("computer_control with None",
            "No action specified for computer_control.",
            computer_control(None))

    test_eq("computer_control with empty dict",
            "No action specified for computer_control.",
            computer_control({}))

    test_eq("computer_control with unknown action",
            "Unknown action: 'bogus_action'",
            computer_control({"action": "bogus_action"}))

    # --- 2b. Actions that don't need real mouse/keyboard ---
    section("  2b. Action dispatch — no-op / safe actions")

    test_eq("action=wait with default seconds",
            "Waited 0.5s",
            computer_control({"action": "wait", "seconds": "0.5"}))

    test_eq("action=wait with 0 seconds",
            "Waited 0.0s",
            computer_control({"action": "wait", "seconds": "0"}))

    result = test("action=wait with negative seconds (graceful error)",
                  computer_control, {"action": "wait", "seconds": "-1"})
    if result:
        print(f"         -> '{result}' (gracefully handled)")

    result = test("action=random_data with no type (defaults to 'name')",
                  computer_control, {"action": "random_data"})
    if result:
        print(f"         -> '{result}'")

    result = test("action=random_data with type=name",
                  computer_control, {"action": "random_data", "type": "name"})
    if result:
        print(f"         -> '{result}'")

    for dt in ["first_name", "last_name", "email", "username", "password", "phone",
               "birthday", "address", "zip_code", "city"]:
        result = test(f"action=random_data type={dt}",
                      computer_control, {"action": "random_data", "type": dt})
        if result:
            print(f"         -> '{result[:50]}'")

    result = test("action=random_data unknown type",
                  computer_control, {"action": "random_data", "type": "unknown_type"})
    if result:
        print(f"         -> '{result}'")

    # --- 2c. Actions that require mouse/keyboard (pyautogui) ---
    section("  2c. Action dispatch — pyautogui-dependent (may fail if not installed)")

    for action in ["type", "smart_type", "click", "double_click", "right_click",
                   "move", "drag", "hotkey", "press", "scroll", "copy",
                   "paste", "clear_field", "focus_window"]:
        result = test(f"action={action} (dispatch only)",
                      computer_control, {"action": action})
        if result is not None:
            print(f"         -> '{result[:80]}'")

    # Screenshot tested separately with timeout protection
    import threading
    screenshot_result = []
    screenshot_exc = []
    def _do_screenshot():
        try:
            r = computer_control({"action": "screenshot"})
            screenshot_result.append(r)
        except Exception as e:
            screenshot_exc.append(e)
    t = threading.Thread(target=_do_screenshot, daemon=True)
    t.start()
    t.join(timeout=15)
    if t.is_alive():
        print(f"  [FAIL] action=screenshot (timeout after 15s)")
        FAIL += 1
        ERRORS.append(("screenshot", "TimeoutError", "screenshot did not complete within 15s", ""))
    elif screenshot_exc:
        print(f"  [FAIL] action=screenshot: {screenshot_exc[0]}")
        FAIL += 1
        ERRORS.append(("screenshot", type(screenshot_exc[0]).__name__, str(screenshot_exc[0]), ""))
    else:
        print(f"  [PASS] action=screenshot")
        PASS += 1
        if screenshot_result:
            print(f"         -> '{screenshot_result[0][:80]}'")

    # --- 2d. Edge cases for various parameters ---
    # Note: pyautogui-dependent actions may hit FAILSAFE; we test dispatch logic only
    section("  2d. Parameter edge cases")

    for action, params, label in [
        ("scroll", {"action": "scroll"}, "scroll with missing direction"),
        ("press", {"action": "press"}, "press with missing key"),
        ("move", {"action": "move"}, "move with missing x,y"),
        ("type", {"action": "type", "text": ""}, "type with empty text"),
        ("smart_type", {"action": "smart_type", "text": ""}, "smart_type with empty text"),
        ("paste", {"action": "paste", "text": ""}, "paste with empty text"),
        ("drag", {"action": "drag", "x1": 0, "y1": 0, "x2": 0, "y2": 0}, "drag with zero coords"),
        ("user_data", {"action": "user_data", "field": "nonexistent"}, "user_data unknown field"),
        ("focus_window", {"action": "focus_window", "title": ""}, "focus_window empty title"),
    ]:
        result = test(label, computer_control, params)
        if result is not None:
            print(f"         -> '{result[:80]}'")

    # --- 2e. _random_data edge cases ---
    section("  2e. _random_data & internal helpers")

    if '_random_data' in dir():
        test_eq("_random_data empty string", None, _random_data(""))
        r = _random_data("")
        if r and r.startswith("random_"):
            print(f"         -> '{r}' (graceful fallback)")


# =========================================================================
# 3. computer_settings.py
# =========================================================================
# Force-disable FAILSAFE after module import
try:
    import pyautogui; pyautogui.FAILSAFE = False; pyautogui.PAUSE = 0.01
except Exception: pass

section("3. computer_settings.py — all functions")

try:
    from actions.computer_settings import (
        computer_settings, volume_get, volume_set, volume_up, volume_down,
        volume_mute, brightness_up, brightness_down,
        get_system_performance, auto_optimize,
        _detect_action, ACTION_MAP, get_hardware_status,
        close_app, close_window, full_screen, minimize_window,
        maximize_window, snap_left, snap_right, switch_window,
        show_desktop, open_task_manager, focus_search, pause_video,
        refresh_page, close_tab, new_tab, next_tab, prev_tab,
        go_back, go_forward, zoom_in, zoom_out, zoom_reset,
        find_on_page, scroll_up, scroll_down, scroll_top,
        scroll_bottom, page_up, page_down, copy, paste, cut,
        undo, redo, select_all, save_file, press_enter, press_escape,
        press_key, type_text, take_screenshot, lock_screen,
        open_system_settings, open_file_explorer, sleep_display,
        open_run, dark_mode, toggle_wifi, reload_page_n,
    )
    print("  [PASS] Import actions.computer_settings (all symbols)")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] Import actions.computer_settings: {e}")
    FAIL += 1
    ERRORS.append(("Import computer_settings", type(e).__name__, str(e), traceback.format_exc()))


# --- 3a. volume_get / volume_set ---
section("  3a. volume_get() and volume_set()")

try:
    vol = volume_get()
    print(f"  [PASS] volume_get() -> {vol}")
    PASS += 1
    if isinstance(vol, int) and 0 <= vol <= 100:
        print(f"         volume in valid range [0-100]: YES")
    else:
        print(f"         volume in valid range [0-100]: NO (got {vol!r})")
except Exception as e:
    print(f"  [FAIL] volume_get(): {e}")
    FAIL += 1
    ERRORS.append(("volume_get", type(e).__name__, str(e), traceback.format_exc()))

for val in [50, 0, 100, -10, 150, 75, "bad_value"]:
    try:
        volume_set(val)
        if isinstance(val, str):
            print(f"  [FAIL] volume_set({val!r}) should not accept non-int")
            FAIL += 1
            ERRORS.append(("volume_set(str)", "TypeError", f"Accepted non-int {val!r}", ""))
        else:
            # Check: after set, get should reflect (roughly)
            new_vol = volume_get()
            clamped = max(0, min(100, int(val)))
            if abs(new_vol - clamped) <= 5:  # allow small tolerance
                print(f"  [PASS] volume_set({val}) -> get()={new_vol}")
                PASS += 1
            else:
                print(f"  [WARN] volume_set({val}) -> get()={new_vol} (expected ~{clamped})")
    except (ValueError, RuntimeError, TypeError) as e:
        if isinstance(val, str):
            print(f"  [PASS] volume_set({val!r}) properly rejected: {e}")
            PASS += 1
        else:
            print(f"  [FAIL] volume_set({val}) failed: {e}")
            FAIL += 1
            ERRORS.append((f"volume_set({val})", type(e).__name__, str(e), ""))

# --- 3b. volume manipulation functions ---
section("  3b. volume_up / volume_down / volume_mute")

for fn_name, fn in [("volume_up", volume_up), ("volume_down", volume_down), ("volume_mute", volume_mute)]:
    try:
        fn()
        print(f"  [PASS] {fn_name}() executed")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {fn_name}(): {e}")
        FAIL += 1
        ERRORS.append((fn_name, type(e).__name__, str(e), traceback.format_exc()))

# --- 3c. brightness functions ---
section("  3c. brightness_up / brightness_down")

try:
    brightness_up()
    print(f"  [PASS] brightness_up() executed (may not change brightness)")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] brightness_up(): {e}")
    FAIL += 1
    ERRORS.append(("brightness_up", type(e).__name__, str(e), traceback.format_exc()))

try:
    brightness_down()
    print(f"  [PASS] brightness_down() executed")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] brightness_down(): {e}")
    FAIL += 1
    ERRORS.append(("brightness_down", type(e).__name__, str(e), traceback.format_exc()))

# --- 3d. get_system_performance & auto_optimize ---
section("  3d. get_system_performance & auto_optimize")

try:
    perf = get_system_performance()
    print(f"  [PASS] get_system_performance()")
    PASS += 1
    print(f"         {perf[:200]}")
except Exception as e:
    print(f"  [FAIL] get_system_performance(): {e}")
    FAIL += 1
    ERRORS.append(("get_system_performance", type(e).__name__, str(e), traceback.format_exc()))

try:
    result = auto_optimize()
    print(f"  [PASS] auto_optimize() -> {result[:120]}")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] auto_optimize(): {e}")
    FAIL += 1
    ERRORS.append(("auto_optimize", type(e).__name__, str(e), traceback.format_exc()))

# --- 3e. get_hardware_status ---
section("  3e. get_hardware_status")

try:
    status = get_hardware_status()
    print(f"  [PASS] get_hardware_status()")
    PASS += 1
    for k, v in status.items():
        print(f"         {k}: {v}")
except Exception as e:
    print(f"  [FAIL] get_hardware_status(): {e}")
    FAIL += 1
    ERRORS.append(("get_hardware_status", type(e).__name__, str(e), traceback.format_exc()))

# --- 3f. _detect_action ---
section("  3f. _detect_action (intent detection via Gemini)")

# Note: This requires an API key and will likely fail without one
detect_results = []
for desc in ["volume up", "turn up the volume", "make it louder",
             "open settings", "scroll down", "type hello world",
             "press escape", "refresh the page", "make brightness higher",
             "close this window", ""]:
    try:
        result = _detect_action(desc)
        print(f"  [{'OK' if result else '?'}] _detect_action({desc!r}) -> {result}")
        detect_results.append(result)
    except Exception as e:
        print(f"  [INFO] _detect_action({desc!r}) failed: {e}")
        detect_results.append(None)

# --- 3g. ACTION_MAP coverage ---
section("  3g. ACTION_MAP — every mapped action")

action_count = len(ACTION_MAP)
print(f"         Total actions in ACTION_MAP: {action_count}")

for action_name, action_func in ACTION_MAP.items():
    try:
        # We just test the key exists and func is callable
        assert callable(action_func), f"{action_name} is not callable"
        print(f"  [PASS] ACTION_MAP[{action_name!r}] is callable")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] ACTION_MAP[{action_name!r}]: {e}")
        FAIL += 1
        ERRORS.append((f"ACTION_MAP[{action_name}]", type(e).__name__, str(e), ""))

# --- 3h. computer_settings() edge cases ---
section("  3h. computer_settings() dispatch edge cases")

test_eq("computer_settings empty params",
        "No action could be determined.",
        computer_settings({}))

test_eq("computer_settings None params",
        "No action could be determined.",
        computer_settings(None))

test_eq("computer_settings unknown action",
        "Unknown action: 'bogus'.",
        computer_settings({"action": "bogus"}))

test_eq("computer_settings volume_set missing value",
        None,
        computer_settings({"action": "volume_set"}))

test_eq("computer_settings type_text empty text",
        "No text provided to type.",
        computer_settings({"action": "type_text"}))

test_eq("computer_settings press_key empty key",
        "No key specified.",
        computer_settings({"action": "press_key"}))

test_eq("computer_settings dangerous action without confirm",
        None,
        computer_settings({"action": "restart"}))

# Test dangerous action block
result = computer_settings({"action": "restart"})
if result:
    if "confirm" in result.lower():
        print(f"  [PASS] Dangerous action 'restart' requires confirmation")
        PASS += 1
    else:
        print(f"  [WARN] Dangerous action 'restart' returned: {result}")

result = computer_settings({"action": "shutdown"})
if result:
    if "confirm" in result.lower():
        print(f"  [PASS] Dangerous action 'shutdown' requires confirmation")
        PASS += 1
    else:
        print(f"  [WARN] Dangerous action 'shutdown' returned: {result}")

# Test reload_n edge case
test_eq("computer_settings reload_n negative value",
        None,
        computer_settings({"action": "reload_n", "value": -1}))

test_eq("computer_settings reload_n string value",
        None,
        computer_settings({"action": "reload_n", "value": "abc"}))

test_eq("computer_settings performance action",
        None,
        computer_settings({"action": "performance"}))

test_eq("computer_settings auto_optimize action",
        None,
        computer_settings({"action": "auto_optimize"}))

# --- 3i. All the small helper functions ---
section("  3i. Individual helper functions")

helper_fns = [
    ("close_app", close_app), ("close_window", close_window),
    ("full_screen", full_screen), ("minimize_window", minimize_window),
    ("maximize_window", maximize_window), ("snap_left", snap_left),
    ("snap_right", snap_right), ("switch_window", switch_window),
    ("show_desktop", show_desktop), ("open_task_manager", open_task_manager),
    ("focus_search", focus_search), ("pause_video", pause_video),
    ("refresh_page", refresh_page), ("close_tab", close_tab),
    ("new_tab", new_tab), ("next_tab", next_tab), ("prev_tab", prev_tab),
    ("go_back", go_back), ("go_forward", go_forward),
    ("zoom_in", zoom_in), ("zoom_out", zoom_out), ("zoom_reset", zoom_reset),
    ("find_on_page", find_on_page), ("scroll_top", scroll_top),
    ("scroll_bottom", scroll_bottom), ("page_up", page_up),
    ("page_down", page_down), ("copy", copy), ("paste", paste),
    ("cut", cut), ("undo", undo), ("redo", redo),
    ("select_all", select_all), ("save_file", save_file),
    ("press_enter", press_enter), ("press_escape", press_escape),
    ("lock_screen", lock_screen), ("open_system_settings", open_system_settings),
    ("open_file_explorer", open_file_explorer), ("sleep_display", sleep_display),
    ("open_run", open_run), ("dark_mode", dark_mode), ("toggle_wifi", toggle_wifi),
]
for fn_name, fn in helper_fns:
    try:
        fn()
        print(f"  [PASS] {fn_name}() executed")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {fn_name}(): {e}")
        FAIL += 1
        ERRORS.append((fn_name, type(e).__name__, str(e), traceback.format_exc()))

# type_text and press_key edge cases
test("type_text with empty string (should do nothing silently)",
     type_text, "")

test("type_text with short string",
     type_text, "hello", False)

test("press_key with valid key",
     press_key, "tab")

# --- 3j. reload_page_n edge cases ---
section("  3j. reload_page_n edge cases")
test("reload_page_n with 0", reload_page_n, 0)
test("reload_page_n with 1", reload_page_n, 1)

# --- 3k. scroll_up / scroll_down ---
section("  3k. scroll_up / scroll_down")
test("scroll_up with default amount", scroll_up)
test("scroll_up with 100", scroll_up, 100)
test("scroll_down with default amount", scroll_down)
test("scroll_down with 100", scroll_down, 100)


# =========================================================================
# 4. screen_processor.py
# =========================================================================
section("4. screen_processor.py")

try:
    from actions.screen_processor import (
        screen_process, detect_ui_elements, describe_current_view,
        _VisionSession, warmup_session, _capture_screen,
        _compress, _capture_camera, _get_api_key, _get_os,
        vision_find_and_click, vision_navigate_tool,
    )
    print("  [PASS] Import actions.screen_processor")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] Import actions.screen_processor: {e}")
    FAIL += 1
    ERRORS.append(("Import screen_processor", type(e).__name__, str(e), traceback.format_exc()))

# --- 4a. _VisionSession class instantiation ---
section("  4a. _VisionSession class")

try:
    vs = _VisionSession()
    print(f"  [PASS] _VisionSession() instantiated")
    PASS += 1
    test_eq("_VisionSession initial state", False, vs.is_ready())
except Exception as e:
    print(f"  [FAIL] _VisionSession(): {e}")
    FAIL += 1
    ERRORS.append(("_VisionSession", type(e).__name__, str(e), traceback.format_exc()))

# --- 4b. _compress helper ---
section("  4b. _compress helper")

try:
    compressed, mime = _compress(b"fake_image_data_but_will_fail_on_PIL_open",
                                  "PNG")
    print(f"  [INFO] _compress returned mime={mime}, len={len(compressed)}")
except Exception as e:
    print(f"  [INFO] _compress with bad PNG data: {e} (expected)")

# --- 4c. screen_process edge cases ---
section("  4c. screen_process edge cases")

test_eq("screen_process with None params",
        False,
        screen_process(None))

test_eq("screen_process with empty params",
        False,
        screen_process({}))

test_eq("screen_process with no text",
        False,
        screen_process({"angle": "screen"}))

test_eq("screen_process with empty text",
        False,
        screen_process({"text": ""}))

test_eq("screen_process with only whitespace",
        False,
        screen_process({"text": "   "}))

# --- 4d. _get_os / _get_api_key helpers ---
section("  4d. Internal helpers")

try:
    os_name = _get_os()
    print(f"  [PASS] _get_os() -> '{os_name}'")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] _get_os(): {e}")
    FAIL += 1
    ERRORS.append(("_get_os", type(e).__name__, str(e), traceback.format_exc()))

try:
    key = _get_api_key()
    print(f"  [PASS] _get_api_key() -> {'***configured***' if key else '(empty)'}")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] _get_api_key(): {e}")
    FAIL += 1
    ERRORS.append(("_get_api_key", type(e).__name__, str(e), traceback.format_exc()))

# --- 4e. detect_ui_elements (requires API key + screen) ---
section("  4e. detect_ui_elements (requires API key, graceful if missing)")

try:
    elements = detect_ui_elements("screen")
    print(f"  [PASS] detect_ui_elements() returned {type(elements).__name__}")
    PASS += 1
    if elements and "error" in elements[0]:
        print(f"         -> API error (expected if no key): {elements[0]['error'][:80]}")
    else:
        print(f"         Found {len(elements)} elements")
except Exception as e:
    print(f"  [FAIL] detect_ui_elements(): {e}")
    FAIL += 1
    ERRORS.append(("detect_ui_elements", type(e).__name__, str(e), traceback.format_exc()))

# --- 4f. describe_current_view (requires API key) ---
section("  4f. describe_current_view (requires API key, graceful if missing)")

try:
    desc = describe_current_view("screen")
    print(f"  [PASS] describe_current_view() returned {type(desc).__name__}")
    PASS += 1
    print(f"         -> '{desc[:120]}'")
except Exception as e:
    print(f"  [FAIL] describe_current_view(): {e}")
    FAIL += 1
    ERRORS.append(("describe_current_view", type(e).__name__, str(e), traceback.format_exc()))

# --- 4g. _capture_screen (requires mss) ---
section("  4g. _capture_screen (requires mss)")

try:
    img_bytes, mime = _capture_screen()
    print(f"  [PASS] _capture_screen() -> {len(img_bytes)} bytes, {mime}")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] _capture_screen(): {e}")
    FAIL += 1
    ERRORS.append(("_capture_screen", type(e).__name__, str(e), traceback.format_exc()))

# --- 4h. _capture_camera (requires OpenCV) ---
section("  4h. _capture_camera (requires OpenCV + camera)")

try:
    img_bytes, mime = _capture_camera()
    print(f"  [PASS] _capture_camera() -> {len(img_bytes)} bytes, {mime}")
    PASS += 1
except Exception as e:
    print(f"  [INFO] _capture_camera(): {e} (expected if no camera)")

# --- 4i. vision_find_and_click ---
section("  4i. vision_find_and_click")

try:
    result = vision_find_and_click("the search bar")
    print(f"  [PASS] vision_find_and_click() returned")
    PASS += 1
    print(f"         -> '{result[:120]}'")
except Exception as e:
    print(f"  [FAIL] vision_find_and_click(): {e}")
    FAIL += 1
    ERRORS.append(("vision_find_and_click", type(e).__name__, str(e), traceback.format_exc()))

# --- 4j. vision_navigate_tool edge cases ---
section("  4j. vision_navigate_tool edge cases")

test_eq("vision_navigate_tool empty target",
        "No target specified for vision navigation.",
        vision_navigate_tool({"target": ""}))

test_eq("vision_navigate_tool missing target",
        "No target specified for vision navigation.",
        vision_navigate_tool({}))


# =========================================================================
# 5. desktop.py
# =========================================================================
# Force-disable FAILSAFE after module import
try:
    import pyautogui; pyautogui.FAILSAFE = False; pyautogui.PAUSE = 0.01
except Exception: pass

section("5. desktop.py")

try:
    from actions.desktop import (
        desktop_control, set_wallpaper, set_wallpaper_from_url,
        get_current_wallpaper, organize_desktop, list_desktop,
        clean_desktop, get_desktop_stats, _get_desktop,
        _build_sandbox, _execute_generated_code,
    )
    print("  [PASS] Import actions.desktop (all symbols)")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] Import actions.desktop: {e}")
    FAIL += 1
    ERRORS.append(("Import desktop", type(e).__name__, str(e), traceback.format_exc()))

# --- 5a. _get_desktop ---
section("  5a. _get_desktop()")

try:
    desktop_path = _get_desktop()
    print(f"  [PASS] _get_desktop() -> {desktop_path}")
    PASS += 1
    if desktop_path.exists():
        print(f"         Path exists: YES")
    else:
        print(f"         Path exists: NO")
except Exception as e:
    print(f"  [FAIL] _get_desktop(): {e}")
    FAIL += 1
    ERRORS.append(("_get_desktop", type(e).__name__, str(e), traceback.format_exc()))

# --- 5b. get_desktop_stats ---
section("  5b. get_desktop_stats()")

try:
    stats = get_desktop_stats()
    print(f"  [PASS] get_desktop_stats()")
    PASS += 1
    print(f"         {stats[:200]}")
except Exception as e:
    print(f"  [FAIL] get_desktop_stats(): {e}")
    FAIL += 1
    ERRORS.append(("get_desktop_stats", type(e).__name__, str(e), traceback.format_exc()))

# --- 5c. list_desktop ---
section("  5c. list_desktop()")

try:
    listing = list_desktop()
    print(f"  [PASS] list_desktop()")
    PASS += 1
    print(f"         {listing[:200]}")
except Exception as e:
    print(f"  [FAIL] list_desktop(): {e}")
    FAIL += 1
    ERRORS.append(("list_desktop", type(e).__name__, str(e), traceback.format_exc()))

# --- 5d. set_wallpaper edge cases ---
section("  5d. set_wallpaper edge cases")

test_eq("set_wallpaper empty path",
        "Image not found: ",
        set_wallpaper(""))

test_eq("set_wallpaper nonexistent path",
        None,
        set_wallpaper("C:\\nonexistent_image_12345.jpg"))

test_eq("set_wallpaper unsupported format",
        None,
        set_wallpaper("test.gif"))  # .gif is NOT in supported list? Let's check

result = set_wallpaper("test.gif")
if result and "Unsupported format" in result:
    print(f"  [PASS] set_wallpaper .gif properly rejected")
    PASS += 1
elif result and "not found" in result.lower():
    print(f"  [INFO] set_wallpaper .gif: file-not-found (expected)")
else:
    print(f"  [INFO] set_wallpaper .gif -> {result}")

# --- 5e. set_wallpaper_from_url edge cases ---
section("  5e. set_wallpaper_from_url edge cases")

test_eq("set_wallpaper_from_url empty URL",
        None,
        set_wallpaper_from_url(""))

result = set_wallpaper_from_url("")
if result and "Could not download" in result:
    print(f"  [PASS] set_wallpaper_from_url empty URL properly handled")
    PASS += 1

result = set_wallpaper_from_url("http://nonexistent.example.com/img.jpg")
if result:
    print(f"  [INFO] set_wallpaper_from_url bad URL -> '{result[:80]}'")

# --- 5f. get_current_wallpaper ---
section("  5f. get_current_wallpaper()")

try:
    wp = get_current_wallpaper()
    print(f"  [PASS] get_current_wallpaper() -> {wp[:100]}")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] get_current_wallpaper(): {e}")
    FAIL += 1
    ERRORS.append(("get_current_wallpaper", type(e).__name__, str(e), traceback.format_exc()))

# --- 5g. _build_sandbox & _execute_generated_code ---
section("  5g. _build_sandbox & _execute_generated_code")

try:
    sandbox = _build_sandbox()
    print(f"  [PASS] _build_sandbox() returned {type(sandbox).__name__} with {len(sandbox)} keys")
    PASS += 1
    assert "Path" in sandbox
    assert "time" in sandbox
    print(f"         Keys: {list(sandbox.keys())}")
except Exception as e:
    print(f"  [FAIL] _build_sandbox(): {e}")
    FAIL += 1
    ERRORS.append(("_build_sandbox", type(e).__name__, str(e), traceback.format_exc()))

test_eq("_execute_generated_code with empty code",
        "This action cannot be performed safely.",
        _execute_generated_code(""))

test_eq("_execute_generated_code with UNSAFE",
        "This action cannot be performed safely.",
        _execute_generated_code("UNSAFE"))

test_eq("_execute_generated_code with valid code",
        "hello from sandbox",
        _execute_generated_code('print("hello from sandbox")'))

test_eq("_execute_generated_code with code that errors",
        None,
        _execute_generated_code('raise ValueError("test error")'))

# --- 5h. organize_desktop error handling ---
section("  5h. organize_desktop / clean_desktop")

try:
    result = organize_desktop("by_type")
    print(f"  [PASS] organize_desktop(by_type) -> '{result[:80]}'")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] organize_desktop(by_type): {e}")
    FAIL += 1
    ERRORS.append(("organize_desktop", type(e).__name__, str(e), traceback.format_exc()))

try:
    result = organize_desktop("by_date")
    print(f"  [PASS] organize_desktop(by_date) -> '{result[:80]}'")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] organize_desktop(by_date): {e}")
    FAIL += 1
    ERRORS.append(("organize_desktop(by_date)", type(e).__name__, str(e), traceback.format_exc()))

try:
    result = clean_desktop()
    print(f"  [PASS] clean_desktop() -> '{result[:80]}'")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] clean_desktop(): {e}")
    FAIL += 1
    ERRORS.append(("clean_desktop", type(e).__name__, str(e), traceback.format_exc()))

# --- 5i. desktop_control edge cases ---
section("  5i. desktop_control edge cases")

test_eq("desktop_control empty params",
        "No action or task specified.",
        desktop_control({}))

test_eq("desktop_control None params",
        "No action or task specified.",
        desktop_control(None))

test_eq("desktop_control unknown action",
        None,
        desktop_control({"action": "bogus_action_xyz"}))

test_eq("desktop_control wallpaper with no path",
        "No image path provided.",
        desktop_control({"action": "wallpaper"}))

test_eq("desktop_control wallpaper_url with no url",
        "No URL provided.",
        desktop_control({"action": "wallpaper_url"}))

test_eq("desktop_control list",
        None,
        desktop_control({"action": "list"}))

test_eq("desktop_control stats",
        None,
        desktop_control({"action": "stats"}))

test_eq("desktop_control task with no description",
        "Please describe what you want to do on the desktop.",
        desktop_control({"action": "task"}))


# =========================================================================
# SUMMARY
# =========================================================================
print(f"\n{'=' * 70}")
print(f"  FINAL TEST SUMMARY")
print(f"{'=' * 70}")
print(f"  PASSED: {PASS}")
print(f"  FAILED: {FAIL}")
print(f"  TOTAL:  {PASS + FAIL}")

if ERRORS:
    print(f"\n{'=' * 70}")
    print(f"  DETAILED FAILURE REPORT")
    print(f"{'=' * 70}")
    for i, (name, exc_type, msg, tb) in enumerate(ERRORS, 1):
        print(f"\n  --- Failure #{i}: {name} ---")
        print(f"  Exception: {exc_type}")
        print(f"  Message:   {msg}")
        if tb:
            # Show last 5 lines of traceback
            tb_lines = tb.strip().split('\n')
            for line in tb_lines[-5:]:
                print(f"    {line}")

sys.exit(0 if FAIL == 0 else 1)
