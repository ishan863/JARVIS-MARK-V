"""Clipboard manager — save, recall, and manage clipboard history."""
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_FILE = DATA_DIR / "clipboard_history.json"
MAX_HISTORY = 50


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_history() -> list:
    _ensure_dir()
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_history(history: list):
    _ensure_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-MAX_HISTORY:], f, indent=2)


def _get_clipboard_text() -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        text = r.stdout.strip()
        if text:
            return text
    except Exception:
        pass
    # Fallback: try pyperclip
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except ImportError:
        pass
    return ""


def _set_clipboard_text(text: str):
    try:
        import pyperclip
        pyperclip.copy(text)
        return
    except ImportError:
        pass
    try:
        escaped = text.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Set-Clipboard -Value '{escaped}'"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass


def clipboard_manager(parameters=None, player=None, **kwargs) -> str:
    params = parameters or {}
    action = params.get("action", "save").strip().lower()

    if action == "save":
        text = _get_clipboard_text()
        if not text:
            return "Clipboard is empty — nothing to save."
        history = _load_history()
        entry = {
            "text": text[:500],
            "timestamp": datetime.now().isoformat(),
        }
        if history and history[-1]["text"] == entry["text"]:
            return "Clipboard unchanged — skipped duplicate."
        history.append(entry)
        _save_history(history)
        return f"Saved clipboard ({len(text)} chars). History: {len(history)} entries."

    if action == "recall":
        history = _load_history()
        if not history:
            return "No clipboard history available."
        idx_str = params.get("index", "").strip()
        if idx_str:
            try:
                idx = int(idx_str) - 1
                if idx < 0 or idx >= len(history):
                    return f"Invalid index. History has {len(history)} entries (1-{len(history)})."
                entry = history[idx]
            except ValueError:
                return f"Invalid index: {idx_str}"
        else:
            entry = history[-1]

        _set_clipboard_text(entry["text"])
        ts = entry.get("timestamp", "?")[:19]
        preview = entry["text"][:80]
        return f"Restored entry {history.index(entry) + 1} from {ts}: {preview}"

    if action == "list":
        history = _load_history()
        if not history:
            return "Clipboard history is empty."
        lines = [f"Clipboard History ({len(history)} entries):"]
        for i, entry in enumerate(reversed(history[-10:]), 1):
            ts = entry.get("timestamp", "?")[:19]
            preview = entry["text"][:60].replace("\n", " ")
            lines.append(f"  #{len(history) - i + 1} [{ts}] {preview}")
        return "\n".join(lines)

    if action == "clear":
        _save_history([])
        return "Clipboard history cleared."

    if action == "read":
        text = _get_clipboard_text()
        if text:
            return f"Clipboard: {text[:200]}"
        return "Clipboard is empty."

    return f"Unknown action: {action}. Use: save, recall, list, clear, read."
