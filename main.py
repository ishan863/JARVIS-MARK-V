import asyncio
import re
import threading
import json
import sys
import traceback
import time
from pathlib import Path

import sounddevice as sd
try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    print("Error: google-genai package not found. Install with: pip install google-genai")
    raise
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, format_memory_for_prompt,
)

from core.orchestrator import orchestrator, register_actions, ToolContext
from core.security import security

# GPU acceleration — init at import time
_gpu_status = "GPU: initializing..."
def _ensure_gpu():
    global _gpu_status
    try:
        from core.gpu import init as gpu_init, format_status, is_available
        gpu_init()
        if is_available():
            _gpu_status = format_status()
            print(f"[GPU] Status: {_gpu_status}")
        else:
            _gpu_status = "GPU: CPU (CUDA not available)"
    except Exception as e:
        _gpu_status = f"GPU: CPU ({e})"
        print(f"[GPU] Init skipped: {e}")

_ensure_gpu()


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 512  # Increased from 256 to reduce input overflow

def _get_api_key() -> str:
    keys = _load_runtime_config()
    key = keys.get("gemini_api_key", "").strip()
    if not (key.startswith("AIzaSy") or key.startswith("AQ.")):
        raise ValueError("Invalid Gemini API key format. The key must start with 'AIzaSy' or 'AQ.'.")
    return key


def _load_runtime_config() -> dict:
    """
    Load config with encrypted-key support.
    Priority:
      1) encrypted config via core.security
      2) plaintext api_keys.json fallback
    """
    try:
        keys = security.decrypt_keys()
        if isinstance(keys, dict) and keys:
            return keys
    except Exception:
        pass

    if API_CONFIG_PATH.exists():
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets, lists, or cancels timed reminders using the OS scheduler. Use 'set' (default) to schedule one-shot or repeating reminders, 'cancel' to stop them, 'list' to see active ones.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":           {"type": "STRING", "description": "'set' (default) | 'cancel' | 'list'. 'list' shows all active reminders with task names you can cancel."},
                "date":             {"type": "STRING", "description": "Date in YYYY-MM-DD format (for 'set' action)"},
                "time":             {"type": "STRING", "description": "Time in HH:MM format (for 'set' action)"},
                "message":          {"type": "STRING", "description": "Reminder message text"},
                "interval_minutes": {"type": "NUMBER", "description": "Repeat interval in minutes (for recurring reminders). Default: 0 (single-shot)"},
                "repeat_count":     {"type": "NUMBER", "description": "Number of times to repeat (for recurring reminders). Default: 1"},
                "task_name":        {"type": "STRING", "description": "Task name to cancel (for 'cancel' action, get this from 'list')"}
            },
            "required": []
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume (volume_up/volume_down/volume_set/mute/unmute/toggle_mute), "
            "brightness (brightness_up/brightness_down), window management (minimize/maximize/close_window/snap_left/snap_right/switch_window/show_desktop), "
            "keyboard shortcuts (copy/paste/cut/undo/redo/select_all/save/enter/escape), "
            "typing text on screen (type_text), closing apps (close_app), fullscreen (full_screen/fullscreen), "
            "dark mode, WiFi toggle, restart, shutdown, "
            "scrolling (scroll_up/down/top/bottom/page_up/down), tab management (new_tab/close_tab/next_tab/prev_tab), "
            "zoom (zoom_in/out/reset), screenshots, lock screen, refresh/reload page, "
            "hardware monitoring (performance/system_performance/hardware_status), "
            "auto-optimize (auto_optimize/optimize/tune). "
            "Use for ANY single computer control command. Do NOT break into multiple calls."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage. Also supports semantic search (find_by_content), code search (search_code), directory indexing (index_directory), and folder name search (find_folder) using AI. Use 'run' to execute Python files. Files created/written are automatically cached for later lookup.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | run | find_folder | find_by_content | search_code | index_directory | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for, or folder name query for find_folder"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "query":       {"type": "STRING", "description": "Search query for find_by_content / search_code / find_folder"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "browser_agent",
        "description": "Autonomous browser agent that completes high-level goals on the web. Takes a goal like 'Search for flights from Delhi to Mumbai' and handles navigation, clicking, typing, and scrolling automatically. Max 30 steps.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING", "description": "The high-level goal to accomplish in the browser"},
            },
            "required": ["goal"]
        }
    },
    {
        "name": "vision_navigate",
        "description": "Looks at the screen, finds a UI element by description, and clicks it. Use for: clicking buttons/links by their label, finding and interacting with on-screen elements.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target": {"type": "STRING", "description": "Description of the element to find and click (e.g. 'the submit button', 'search bar', 'login link')"},
                "angle":  {"type": "STRING", "description": "'screen' for desktop or 'camera' for webcam (default: screen)"},
            },
            "required": ["target"]
        }
    },
    {
        "name": "vscode_controller",
        "description": "Controls VS Code: open projects, create files, run terminal commands, search code, open files at specific lines.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "open | write_file | run_command | open_at_line | search | terminal_output"},
                "path":    {"type": "STRING", "description": "Project path or file path"},
                "content": {"type": "STRING", "description": "File content for write_file action"},
                "command": {"type": "STRING", "description": "Terminal command for run_command"},
                "query":   {"type": "STRING", "description": "Search query for search action"},
                "line":    {"type": "INTEGER", "description": "Line number for open_at_line (default: 1)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "clipboard_manager",
        "description": "Manage clipboard: save current clipboard to history, recall older clipboard entries, list history, clear history, or read current clipboard content.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "save | recall | list | clear | read"},
                "index":  {"type": "INTEGER", "description": "Entry number for recall action (default: most recent)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "calculator",
        "description": "Evaluate math expressions. Supports: + - * / ^ sqrt sin cos tan log pi e. Use for quick calculations, unit conversions, and math problems.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "expression": {"type": "STRING", "description": "Math expression to evaluate (e.g. '2 + 2', 'sqrt(144)', 'sin(30) * pi')"},
            },
            "required": ["expression"]
        }
    },
    {
        "name": "media_control",
        "description": "Control media playback: Spotify and system media. Supports play, pause, next, previous, stop, status, and launch. Use for voice control of music and audio playback.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | pause | next | previous | stop | status | launch"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "notification",
        "description": "Send Windows toast notifications and manage auto-start. Use for reminders, alerts, completions, and checking/installing/removing auto-start on Windows login.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "notify | startup_status | startup_install | startup_remove"},
                "title":   {"type": "STRING", "description": "Notification title (default: MARK XL)"},
                "message": {"type": "STRING", "description": "Notification body text"},
                "duration":{"type": "INTEGER", "description": "Display duration in seconds"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "memory_search",
        "description": "Search MARK's long-term memory using semantic recall. Use when the user asks 'what do you know about...' or wants to recall past conversations, preferences, or facts.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":    {"type": "STRING", "description": "The thing to search for in memory (e.g. 'project settings', 'my favorite color')"},
                "category": {"type": "STRING", "description": "Optional: identity, preferences, projects, notes"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "save_memory",
        "description": "Save a fact or user preference to long-term memory. Use this to remember user preferences, important details, projects, or any information the user wants stored. Categories: identity, preferences, projects, notes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "Memory category: identity, preferences, projects, notes"},
                "key":      {"type": "STRING", "description": "The memory key (e.g. 'user_name', 'favorite_color')"},
                "value":    {"type": "STRING", "description": "The value to remember"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "daily_brief",
        "description": "Get a summary of all agent activities today. Shows what each tool/agent did, how many operations succeeded/failed, and the current status of all agents. Use this when the user asks 'what have you done today', 'good morning brief', 'agent status', or 'show activity'. Also recommended to call this automatically on first interaction after the assistant starts or when the user says good morning.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "crypto_data",
        "description": (
            "Fetches live cryptocurrency data: prices, 24h change, market cap, volume, and price history charts. "
            "Use for ANY crypto request: 'what is bitcoin price', 'show ethereum chart', 'top coins', 'crypto market'. "
            "This also displays an interactive graph on the dashboard."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "coin":     {"type": "STRING",  "description": "Coin name or symbol: bitcoin, ethereum, solana, doge, etc."},
                "action":   {"type": "STRING",  "description": "price | chart | top | all (default: all)"},
                "days":     {"type": "INTEGER", "description": "Number of days for chart history (default: 7)"},
                "currency": {"type": "STRING",  "description": "Currency: usd | eur | gbp | inr (default: usd)"},
            },
            "required": []
        }
    },
    {
        "name": "browser_playwright",
        "description": (
            "Advanced hands-free browser control using Playwright. "
            "Use for: scrolling web pages hands-free, clicking links by text, YouTube playback, "
            "web scraping/extracting content, filling forms, taking screenshots, navigating tabs. "
            "Different from browser_control — this uses a persistent Playwright session for automation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "goto | search | youtube | scroll | click | type | extract | links | screenshot | back | forward | reload | stop | open_tab | press"},
                "url":       {"type": "STRING",  "description": "URL to navigate to"},
                "query":     {"type": "STRING",  "description": "Search query (for search/youtube actions)"},
                "text":      {"type": "STRING",  "description": "Text of element to click"},
                "selector":  {"type": "STRING",  "description": "CSS selector to click or type into"},
                "direction": {"type": "STRING",  "description": "Scroll direction: up | down | top | bottom"},
                "amount":    {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "value":     {"type": "STRING",  "description": "Text to type into a field"},
                "key":       {"type": "STRING",  "description": "Key to press (e.g. Enter, Escape, Tab)"},
            },
            "required": ["action"]
        }
    },
]

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._last_speak_end_time = 0.0
        self.ui.on_text_command = self._on_text_command
        self._turn_done_event: asyncio.Event | None = None
        self._speaking_start_time = 0.0
        # Remote control manager
        from core.remote_manager import remote_manager
        self._remote = remote_manager

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
            if value:
                self._speaking_start_time = time.time()
            if not value:
                self._last_speak_end_time = time.time()
                self._speaking_start_time = 0.0
        try:
            if value:
                self.ui.set_state("SPEAKING")
            elif not self.ui.muted:
                self.ui.set_state("LISTENING")
        except RuntimeError as e:
            # UI may be deleted while async task is running
            if "deleted" not in str(e).lower():
                raise

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        lang_ctx = (
            "[LANGUAGE CONFIG]\n"
            "The user speaks Hindi and English (Hinglish). "
            "Understand both Hindi (hi) and English (en) speech. "
            "Respond in the same language the user speaks.\n\n"
        )

        brief_ctx = ""
        if now.hour < 12:
            try:
                from core.agent_tracker import get_today_summary
                brief = get_today_summary()
                if "No activity" not in brief:
                    brief_ctx = f"[TODAY'S AGENT ACTIVITY]\n{brief}\n\n"
            except Exception:
                pass

        parts = [time_ctx, lang_ctx]
        if brief_ctx:
            parts.append(brief_ctx)
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=250,
                    prefix_padding_ms=150,
                ),
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ALL_INPUT,
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] [Tool] {name}  {args}")
        self.ui.set_state("WORKING" if name in ("browser_agent", "agent_task", "dev_agent") else "THINKING")

        if name == "file_processor":
            if not args.get("file_path") and self.ui.current_file:
                args["file_path"] = self.ui.current_file

        context = ToolContext(ui=self.ui, speak=self.speak, loop=asyncio.get_event_loop())

        try:
            result = await orchestrator.route(name, args, context)
        except Exception as e:
            print(f"[JARVIS] [Error] Tool execution error: {e}")
            result = None

        # Auto-save meaningful interactions to long-term memory
        try:
            if name in ("computer_settings", "volume", "brightness", "system"):
                from memory.memory_manager import remember
                action_key = args.get("action", "")
                val = args.get("value", "")
                if action_key in ("volume_set", "volume_up", "volume_down") and val:
                    remember("volume_level", str(val), "preferences")
                elif action_key in ("brightness_up", "brightness_down"):
                    remember("brightness_adjusted", action_key, "preferences")
        except Exception:
            pass

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _run_background_agent(self, fc, context):
        """Execute long-running agent in background so voice channel stays free."""
        try:
            result = await orchestrator.route(fc.name, dict(fc.args or {}), context)
            summary = str(result)[:300] if result else "completed"
            self.ui.write_log(f"[Agent] Done: {summary}")
            self.speak(f"Task finished.{summary}")
        except Exception as e:
            print(f"[JARVIS] [Error] Background agent: {e}")
            self.ui.write_log(f"[Agent] Error: {e}")
            self.speak(f"The task ran into an error: {str(e)[:100]}")
        finally:
            self.ui.set_state("IDLE")

    async def _send_realtime(self):
        print("[JARVIS] [Send] Started")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                msg = await self.out_queue.get()
                data = msg["data"]
                
                # Validate PCM data before sending
                if not data or len(data) == 0:
                    continue
                
                # Ensure data length is valid for PCM16 (must be even number of bytes)
                if len(data) % 2 != 0:
                    print(f"[JARVIS] [Warning] Invalid PCM data length: {len(data)}, skipping")
                    continue
                
                await self.session.send_realtime_input(
                    audio=types.Blob(
                        data=data,
                        mime_type=msg.get("mime_type", "audio/pcm;rate=16000")
                    )
                )
                consecutive_errors = 0  # Reset on success
                
            except Exception as e:
                consecutive_errors += 1
                print(f"[JARVIS] [Error] Send realtime: {e} (consecutive: {consecutive_errors})")
                
                if consecutive_errors >= max_consecutive_errors:
                    print(f"[JARVIS] [Error] Too many consecutive send errors, reconnecting...")
                    import traceback
                    traceback.print_exc()
                    raise  # Trigger reconnection
                
                await asyncio.sleep(0.1)

    async def _signal_turn_complete(self):
        """Tell the Live API the user finished speaking, so it responds immediately."""
        try:
            await self.session.send_client_content(turn_complete=True)
        except Exception as e:
            print(f"[JARVIS] [Error] turn_complete: {e}")

    async def _listen_audio(self):
        print("[JARVIS] [Mic] Started")
        import numpy as np
        loop = asyncio.get_event_loop()
        chunk_count = 0

        device_idx = None
        # Base multiplier and dynamic AGC state
        base_boost = 3.0
        agc_gain = base_boost
        # Local VAD state — detect silence to signal turn completion
        _last_voice_time = time.perf_counter()
        _turn_signaled = False
        _startup_delay = 2.0  # Wait 2 seconds before sending audio
        _startup_time = time.perf_counter()
        
        try:
            config_data = _load_runtime_config()
            if "mic_device_index" in config_data:
                device_idx = int(config_data["mic_device_index"])
            if "mic_boost" in config_data:
                boost_multiplier = float(config_data["mic_boost"])
        except Exception:
            pass

        # Determine native sample rate of target device
        try:
            device_info = sd.query_devices(device_idx, kind='input') if device_idx is not None else sd.query_devices(kind='input')
            native_sr = int(device_info['default_samplerate'])
            print(f"[JARVIS] Target Input Device: {device_info['name']}")
            print(f"[JARVIS] Native Samplerate: {native_sr} Hz")
        except Exception as e:
            print(f"[JARVIS] [Warning] Querying audio devices failed: {e}. Falling back to default settings.")
            native_sr = SEND_SAMPLE_RATE

        def callback(indata, frames, time_info, status):
            nonlocal chunk_count, _startup_time
            # Silently ignore input overflow - it's normal when CPU is busy
            if status and status != sd.CallbackFlags.input_overflow:
                print(f"[JARVIS] [Mic] Callback status: {status}")

            # Skip audio during startup delay
            if time.perf_counter() - _startup_time < _startup_delay:
                return

            with self._speaking_lock:
                jarvis_speaking = self._is_speaking

            # Only block audio while JARVIS is actively speaking.
            # Remove the 0.8s grace period - allow input immediately after speaking.
            if not jarvis_speaking and not self.ui.muted:
                try:
                    # Convert int16 input to float32 for processing
                    audio_float = indata.flatten().astype(np.float32)
                    
                    # Perform software downsampling if native samplerate differs from target rate
                    if native_sr != SEND_SAMPLE_RATE:
                        num_samples = int(frames * SEND_SAMPLE_RATE / native_sr)
                        xp = np.arange(frames)
                        x = np.linspace(0, frames - 1, num_samples)
                        audio_float = np.interp(x, xp, audio_float)

                    nonlocal agc_gain, _last_voice_time, _turn_signaled
                    rms = np.sqrt(np.mean(audio_float**2))
                    
                    # Only send audio if there's actual voice activity (above noise floor)
                    if rms > 100:  # Increased threshold to filter ambient noise
                        _last_voice_time = time.perf_counter()
                        _turn_signaled = False
                        target_rms = 6000.0
                        instant_gain = target_rms / rms
                        # Limit maximum boost to prevent screaming background noise
                        instant_gain = np.clip(instant_gain, 1.0, 15.0)
                        # Smooth adaptation
                        agc_gain = 0.8 * agc_gain + 0.2 * instant_gain
                    else:
                        # Decay back to base boost slowly in silence
                        agc_gain = 0.95 * agc_gain + 0.05 * base_boost
                        # Don't send silence/ambient noise to API
                        return
                    
                    audio_float = audio_float * agc_gain

                    # Clip to int16 range and convert to bytes - CRITICAL: ensure valid PCM16
                    audio_int16 = np.clip(audio_float, -32768, 32767).astype(np.int16)
                    
                    # Validate the data is not corrupted
                    if len(audio_int16) == 0:
                        return
                    
                    data = audio_int16.tobytes()

                    # Real-time visual feedback of microphone signal amplitude
                    chunk_count += 1
                    amplitude = int(np.max(np.abs(audio_int16)))
                    if chunk_count % 20 == 0:
                        bar = "=" * int(min(30, amplitude / 1000))
                        print(f"\r[JARVIS Mic Input] Level: {amplitude:<5} {bar:<30}", end="", flush=True)

                    # Local VAD: after 0.6s of silence, signal turn_complete to API
                    # so it responds immediately instead of waiting for server-side VAD
                    silence_duration = time.perf_counter() - _last_voice_time
                    if rms <= 100 and silence_duration > 0.6 and not _turn_signaled:
                        _turn_signaled = True
                        asyncio.run_coroutine_threadsafe(
                            self._signal_turn_complete(), loop
                        )

                    # Use call_soon_threadsafe with try-except to handle queue full
                    try:
                        loop.call_soon_threadsafe(
                            self.out_queue.put_nowait,
                            {"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}", "amplitude": amplitude}
                        )
                    except asyncio.QueueFull:
                        pass  # Drop frame if queue is full (prevents overflow)
                        
                except Exception as e:
                    # Silently handle any processing errors to prevent callback crashes
                    pass
            else:
                chunk_count += 1
                if chunk_count % 100 == 0:
                    reason = []
                    if jarvis_speaking:
                        reason.append("JARVIS_SPEAKING")
                    if self.ui.muted:
                        reason.append("UI_MUTED")
                    print(f"\n[JARVIS] [Mic] Audio blocked: {','.join(reason)}")

        try:
            with sd.InputStream(
                device=device_idx,
                samplerate=native_sr,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE if native_sr == SEND_SAMPLE_RATE else int(CHUNK_SIZE * native_sr / SEND_SAMPLE_RATE),
                callback=callback,
            ):
                print("[JARVIS] [Mic] Stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] [Error] Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] [Recv] Started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)
                                current_output = " ".join(out_buf).strip()
                                self.ui.set_output_text(current_output)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)
                                current_transcript = " ".join(in_buf).strip()
                                self.ui.set_input_text(current_transcript)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []
                            self.ui.set_input_text("")

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                # Forward to connected phone clients
                                self._remote.broadcast_text(full_out)
                            out_buf = []
                            self.ui.set_output_text("")

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] [Call] {fc.name}")
                            # Non-blocking for long-running agents
                            if fc.name in ("browser_agent", "agent_task", "dev_agent"):
                                fn_responses.append(types.FunctionResponse(
                                    id=fc.id, name=fc.name,
                                    response={"result": "Task started. Check UI log for progress."}
                                ))
                                context = ToolContext(ui=self.ui, speak=self.speak, loop=asyncio.get_event_loop())
                                try:
                                    asyncio.ensure_future(self._run_background_agent(fc, context))
                                except Exception as e:
                                    print(f"[JARVIS] [Error] Scheduling background agent: {e}")
                            else:
                                fr = await self._execute_tool(fc)
                                fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS] [Error] Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] [Play] Started")
        import numpy as np

        # Load custom speaker device index and volume boost
        speaker_idx = None
        output_volume = 2.0
        try:
            config_data = _load_runtime_config()
            if "speaker_device_index" in config_data:
                speaker_idx = int(config_data["speaker_device_index"])
            if "output_volume" in config_data:
                output_volume = float(config_data["output_volume"])
        except Exception:
            pass

        try:
            device_info = sd.query_devices(speaker_idx, kind='output') if speaker_idx is not None else sd.query_devices(kind='output')
            print(f"[JARVIS] Target Output Device: {device_info['name']}")
        except Exception as e:
            print(f"[JARVIS] [Warning] Querying output audio devices failed: {e}.")

        stream = sd.RawOutputStream(
            device=speaker_idx,
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        MAX_SPEAKING_DURATION = 20.0
        try:
            empty_time = 0.0
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                    empty_time = 0.0
                except asyncio.TimeoutError:
                    empty_time += 0.1
                    if self.audio_in_queue.empty():
                        if (
                            (self._turn_done_event and self._turn_done_event.is_set())
                            or empty_time > 0.6
                            or (self._speaking_start_time > 0 and time.time() - self._speaking_start_time > MAX_SPEAKING_DURATION)
                        ):
                            self.set_speaking(False)
                            if self._turn_done_event:
                                self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                try:
                    # Boost output volume for louder speaker output
                    audio_np = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                    audio_np *= output_volume
                    chunk = np.clip(audio_np, -32768, 32767).astype(np.int16).tobytes()
                    await asyncio.to_thread(stream.write, chunk)
                except Exception as e:
                    print(f"[JARVIS] [Warning] Audio write failed: {e}")
                    continue
        except Exception as e:
            print(f"[JARVIS] [Error] Play: {e}")
        finally:
            self.set_speaking(False)
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    async def _gpu_monitor(self):
        """Keep GPU active and report stats every 15 seconds."""
        cycle = 0
        while True:
            await asyncio.sleep(15)
            try:
                from core.gpu import format_status, is_available, empty_cache
                if is_available():
                    # Small GPU compute to keep utilization visible
                    if cycle % 2 == 0:
                        import torch
                        a = torch.randn(2000, 2000, device="cuda")
                        b = torch.randn(2000, 2000, device="cuda")
                        c = a @ b
                        torch.cuda.synchronize()
                        _ = c.sum().item()
                    else:
                        empty_cache()
                    cycle += 1
                    status = format_status()
                    self.ui.write_log(status)
            except Exception:
                pass

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        reconnect_delay = 3  # Start with 3 seconds
        max_reconnect_delay = 30  # Cap at 30 seconds
        
        while True:
            try:
                print("[JARVIS] [Conn] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue()
                    self._turn_done_event = asyncio.Event()
                    self.ui.muted = False

                    # Wire remote manager to this session
                    self._remote.set_jarvis(self, self._loop)

                    print("[JARVIS] [Conn] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")
                    try:
                        self.ui.write_log(_gpu_status)
                    except Exception:
                        pass

                    # Reset reconnect delay on successful connection
                    reconnect_delay = 3

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._gpu_monitor())

            except Exception as e:
                error_msg = str(e)
                print(f"[JARVIS] [Error] {error_msg}")
                
                # Check if it's the audio format error
                if "1007" in error_msg or "invalid frame payload" in error_msg:
                    print("[JARVIS] [Error] Audio format issue detected. Check microphone settings.")
                    self.ui.write_log("ERROR: Audio format rejected by API. Try muting/unmuting (F4) or restart.")
                    # Longer delay for format errors
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                else:
                    traceback.print_exc()
                    
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print(f"[JARVIS] [Conn] Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)

def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        try:
            key = _get_api_key()
            if not key:
                ui.write_log("ERR: Gemini API key missing. Voice chat cannot start.")
                ui.set_state("MUTED")
                return
            from config import validate_api_keys
            key_status = validate_api_keys()
            for k, v in key_status.items():
                if v["present"]:
                    ui.write_log(f"API {v['label']}: {'OK' if v['valid'] else 'INVALID'}")
            register_actions()
            ui.write_log("SYS: Orchestrator initialized. All tools registered.")
            # Auto-start remote server
            try:
                from core.remote_manager import remote_manager
                url = remote_manager.start()
                ui.write_log(f"SYS: Remote server → {url}  PIN={remote_manager.pin}")
            except Exception as _re:
                ui.write_log(f"SYS: Remote server skipped: {_re}")
            ui.write_log("SYS: Voice preflight passed. Initializing live session...")
            jarvis = JarvisLive(ui)
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n[Sys] Shutting down...")
        except Exception as e:
            err = str(e)
            print(f"[Sys] Voice runner error: {err}")
            traceback.print_exc()
            try:
                ui.write_log(f"ERR: Voice startup failed: {err[:220]}")
                ui.set_state("MUTED")
            except Exception:
                pass

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
