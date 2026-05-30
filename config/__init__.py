import json, os
from pathlib import Path
from core.security import security

_CONFIG_PATH = Path(__file__).parent / "api_keys.json"
_SETTINGS_PATH = Path(__file__).parent / "mark_xl_settings.json"

_decrypted_cache: dict | None = None

def get_config() -> dict:
    global _decrypted_cache
    if _decrypted_cache is not None:
        return _decrypted_cache
    try:
        dec = security.decrypt_keys()
        if isinstance(dec, dict) and dec:
            _decrypted_cache = dec
            return _decrypted_cache
    except Exception:
        pass
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                _decrypted_cache = json.load(f)
                return _decrypted_cache
        except Exception:
            pass
    return {}

def clear_config_cache():
    global _decrypted_cache
    _decrypted_cache = None

def get_settings() -> dict:
    if _SETTINGS_PATH.exists():
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "chat_model": "gemini-2.5-flash",
        "vision_model": "gemini-2.5-flash",
        "theme": "Neon Blue",
        "autonomous": False,
        "notifications": True,
    }

def get_os() -> str:
    return get_config().get("os_system", "windows").lower()

def is_windows() -> bool: return get_os() == "windows"
def is_mac()     -> bool: return get_os() == "mac"
def is_linux()   -> bool: return get_os() == "linux"

def validate_api_keys() -> dict:
    keys = get_config()
    results = {}
    providers = [
        ("gemini_api_key", "Gemini", lambda k: k.startswith("AIzaSy") or k.startswith("AQ.")),
        ("groq_api_key", "Groq", lambda k: k.startswith("gsk_")),
        ("nvidia_api_key", "NVIDIA", lambda k: k.startswith("nvapi-")),
        ("deepseek_api_key", "DeepSeek", lambda k: bool(k.strip())),
        ("openrouter_api_key", "OpenRouter", lambda k: bool(k.strip())),
    ]
    for key_name, label, validator in providers:
        val = keys.get(key_name, "").strip()
        if val and validator(val):
            results[key_name] = {"present": True, "valid": True, "label": label}
        elif val and not validator(val):
            results[key_name] = {"present": True, "valid": False, "label": label}
        else:
            results[key_name] = {"present": False, "valid": False, "label": label}
    return results
