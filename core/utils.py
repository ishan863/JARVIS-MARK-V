import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()

def get_api_key() -> str:
    from core.security import security
    try:
        keys = security.decrypt_keys()
        key = keys.get("gemini_api_key", "").strip()
        if not (key.startswith("AIzaSy") or key.startswith("AQ.")):
            return ""
        return key
    except Exception:
        return ""
