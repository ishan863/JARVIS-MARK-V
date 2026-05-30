import json
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys

try:
    import chromadb
except ImportError:
    chromadb = None

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"
CHROMA_DIR = BASE_DIR / "memory" / "chroma_db"
_lock = Lock()
MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200

class SemanticMemory:
    def __init__(self):
        self.collection = None
        if chromadb:
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self.collection = self.client.get_or_create_collection(name="mark_xl_memory")
            
    def add_fact(self, category: str, key: str, value: str):
        if not self.collection: return
        doc_id = f"{category}_{key}"
        text = f"{category.title()} - {key.replace('_', ' ')}: {value}"
        try:
            self.collection.upsert(
                documents=[text],
                metadatas=[{"category": category, "key": key, "value": value}],
                ids=[doc_id]
            )
        except Exception as e:
            print(f"[ChromaDB] Error saving fact: {e}")
        
    def search_facts(self, query: str, n_results: int = 10) -> list:
        if not self.collection: return []
        count = self.collection.count()
        if count == 0: return []
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(n_results, count)
            )
            return results["documents"][0] if results["documents"] else []
        except Exception as e:
            print(f"[ChromaDB] Error searching facts: {e}")
            return []

semantic_db = SemanticMemory()

def _empty_memory() -> dict:
    return {
        "identity": {}, "preferences": {}, "projects": {},
        "relationships": {}, "wishes": {}, "notes": {},
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            return _empty_memory()

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict): return
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")

def update_memory(memory_update: dict) -> dict:
    memory = load_memory()
    for cat, items in memory_update.items():
        if not isinstance(items, dict): continue
        for key, value in items.items():
            val_str = str(value["value"] if isinstance(value, dict) else value)
            if cat not in memory: memory[cat] = {}
            memory[cat][key] = {"value": val_str, "updated": datetime.now().strftime("%Y-%m-%d")}
            semantic_db.add_fact(cat, key, val_str)
    save_memory(memory)
    return memory

def format_memory_for_prompt(memory: dict | None = None, query: str = None) -> str:
    # If a query is provided, we can fetch semantic facts. Otherwise fallback to standard JSON formatting.
    # For now, we still load the standard JSON base logic and append some semantic context if queried.
    mem = memory or load_memory()
    lines = []
    
    # Standard output omitted for brevity, just dumping identity
    identity = mem.get("identity", {})
    if identity:
        lines.append("Identity:")
        for k, v in identity.items():
            lines.append(f"  - {k}: {v.get('value', v)}")
            
    notes = mem.get("notes", {})
    if notes:
        lines.append("Notes:")
        for k, v in list(notes.items())[:10]:
            lines.append(f"  - {k}: {v.get('value', v)}")
            
    # Add semantic context if there's a query
    if query and semantic_db.collection:
        semantic_results = semantic_db.search_facts(query, n_results=5)
        if semantic_results:
            lines.append("\nRelevant Context from Memory:")
            for r in semantic_results:
                lines.append(f"  - {r}")
                
    if not lines: return ""
    return "[WHAT YOU KNOW ABOUT THIS PERSON]\n" + "\n".join(lines) + "\n"

def remember(key: str, value: str, category: str = "notes") -> str:
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"
