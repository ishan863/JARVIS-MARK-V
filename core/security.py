import os
import json
import base64
from pathlib import Path
from cryptography.fernet import Fernet

def get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
KEY_FILE = BASE_DIR / "config" / "master.key"
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
ENCRYPTED_API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.enc"

class SecurityManager:
    def __init__(self):
        self.fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        if not KEY_FILE.exists():
            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            KEY_FILE.write_bytes(key)
        else:
            key = KEY_FILE.read_bytes()
        return Fernet(key)

    def encrypt_keys(self):
        if API_CONFIG_PATH.exists():
            data = API_CONFIG_PATH.read_bytes()
            encrypted = self.fernet.encrypt(data)
            ENCRYPTED_API_CONFIG_PATH.write_bytes(encrypted)
            # Remove plain text file after encryption
            API_CONFIG_PATH.unlink()
            print("[Security] API keys encrypted securely.")

    def decrypt_keys(self) -> dict:
        if ENCRYPTED_API_CONFIG_PATH.exists():
            encrypted = ENCRYPTED_API_CONFIG_PATH.read_bytes()
            try:
                decrypted = self.fernet.decrypt(encrypted)
                return json.loads(decrypted.decode("utf-8"))
            except Exception as e:
                print(f"[Security] Decryption failed: {e}")
                return {}
        elif API_CONFIG_PATH.exists():
            # Migrate unencrypted to encrypted
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.encrypt_keys()
            return data
        return {}

security = SecurityManager()
