"""Folder name index — builds a searchable index of folder names across drives + Desktop.

Scans:
  - Desktop (recursive, depth 5)
  - Drive roots (top-level folders on C:, D:, etc.)
  - User folders (Documents, Downloads, Pictures, etc.) 1 level deep

Usage:
  from actions.folder_index import folder_index
  results = folder_index.search("march bill", top_n=5)
  best = folder_index.quick_find("march bill")  # returns path or None
"""

import os
import json
import time
import difflib
from pathlib import Path

_INDEX_PATH = Path.home() / "Desktop" / ".jarvis_folder_index.json"
_DESKTOP_DEPTH = 5
_CACHE_MAX_AGE = 86400  # 24 hours — rebuild if older


class _FolderIndex:
    def __init__(self):
        self._entries: list[dict] = []
        self._loaded = False

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def search(self, query: str, top_n: int = 5) -> list[tuple[str, str, float]]:
        """Fuzzy-search folder names. Returns [(display_name, full_path, score), ...]."""
        self._ensure_loaded()
        query_lower = query.strip().lower()
        scored: list[tuple[str, str, float]] = []

        for entry in self._entries:
            name_lower = entry["name"].lower()
            # Substring match
            if query_lower in name_lower or name_lower in query_lower:
                overlap = min(len(query_lower), len(name_lower)) / max(len(query_lower), len(name_lower), 1)
                ratio = 0.7 + 0.3 * overlap  # 0.7-1.0 for substring hits
            else:
                ratio = difflib.SequenceMatcher(None, query_lower, name_lower).ratio()

            if ratio >= 0.35:
                scored.append((entry["name"], entry["path"], ratio))

        seen = set()
        results: list[tuple[str, str, float]] = []
        for name, path, ratio in sorted(scored, key=lambda x: -x[2]):
            if path not in seen:
                seen.add(path)
                results.append((name, path, ratio))
                if len(results) >= top_n:
                    break
        return results

    def quick_find(self, query: str, threshold: float = 0.8) -> str | None:
        """Return the best-matching folder path if confidence >= threshold."""
        results = self.search(query, top_n=1)
        if results and results[0][2] >= threshold:
            return results[0][1]
        return None

    def all_folders(self) -> list[dict]:
        """Return all raw entries (for debugging)."""
        self._ensure_loaded()
        return list(self._entries)

    def rebuild(self):
        """Force a full rebuild of the index."""
        self._entries = self._scan_all()
        self._save()
        self._loaded = True

    # ------------------------------------------------------------------ #
    #  Internal
    # ------------------------------------------------------------------ #

    def _ensure_loaded(self):
        if self._loaded:
            return
        raw = self._load()
        if raw is not None:
            age = time.time() - raw.get("built_at", 0)
            if age < _CACHE_MAX_AGE:
                self._entries = raw.get("folders", [])
                self._loaded = True
                return
        # Stale or missing — rebuild
        self.rebuild()

    def _load(self) -> dict | None:
        try:
            if _INDEX_PATH.exists():
                with open(_INDEX_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _save(self):
        try:
            data = {
                "built_at": time.time(),
                "folders": self._entries,
            }
            _INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_INDEX_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[FolderIndex] Save error: {e}")

    def _scan_all(self) -> list[dict]:
        entries: dict[str, list[dict]] = {}  # name_lower -> list of entry dicts

        def _add(path_str: str):
            p = Path(path_str)
            name_lower = p.name.lower()
            if name_lower not in entries:
                entries[name_lower] = []
            entries[name_lower].append({
                "name": p.name,
                "path": str(p.resolve()),
                "mtime": p.stat().st_mtime if p.exists() else 0,
            })

        def _scan_dir(root: Path, max_depth: int, depth: int = 0):
            try:
                for item in os.scandir(root):
                    if item.is_dir(follow_symlinks=False):
                        name = item.name
                        if name.startswith(".") or name.startswith("$"):
                            continue
                        _add(item.path)
                        if depth < max_depth:
                            _scan_dir(Path(item.path), max_depth, depth + 1)
            except (PermissionError, OSError):
                pass

        # 1. Desktop (recursive)
        desktop = Path.home() / "Desktop"
        if desktop.exists():
            print(f"[FolderIndex] Scanning Desktop ({desktop})...")
            _scan_dir(desktop, _DESKTOP_DEPTH)

        # 2. Drive roots (top-level folders)
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                print(f"[FolderIndex] Scanning drive root {drive}...")
                try:
                    for item in os.scandir(drive):
                        if item.is_dir(follow_symlinks=False) and not item.name.startswith("$"):
                            _add(item.path)
                except (PermissionError, OSError):
                    pass

        # 3. User special folders (1 level deep)
        user_folders = [
            Path.home() / "Documents",
            Path.home() / "Downloads",
            Path.home() / "Pictures",
            Path.home() / "Music",
            Path.home() / "Videos",
        ]
        for folder in user_folders:
            if folder.exists():
                print(f"[FolderIndex] Scanning {folder.name}...")
                _scan_dir(folder, 1)

        # Flatten to list
        result = []
        for name, paths in entries.items():
            result.extend(paths)

        print(f"[FolderIndex] Indexed {len(result)} folders ({len(entries)} unique names)")
        return result


# Singleton
folder_index = _FolderIndex()
