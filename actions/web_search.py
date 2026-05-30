import sys
from pathlib import Path

from core.security import security


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()


def _get_api_key() -> str:
    keys = {}
    try:
        dec = security.decrypt_keys()
        if isinstance(dec, dict):
            keys = dec
    except Exception:
        keys = {}
    return str(keys.get("gemini_api_key", "")).strip()


def _gemini_search(query: str) -> str:
    key = _get_api_key()
    if not key:
        raise ValueError("Gemini API key is missing.")

    import google.genai as genai

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = (response.text or "").strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(
                {
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                }
            )
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):
            lines.append(f"{i}. {r['title']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list[str], aspect: str) -> str:
    query = f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data."
    try:
        return _gemini_search(query)
    except Exception:
        pass

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison - {aspect.upper()}", "-" * 40]
    for item in items:
        lines.append(f"\n- {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  * {r['snippet']}")
    return "\n".join(lines)


def web_search(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    query = params.get("query", "").strip()
    mode = params.get("mode", "search").lower().strip()
    items = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."
    if items and mode != "compare":
        mode = "compare"

    if player:
        try:
            player.write_log(f"[Search] {query or ', '.join(items)}")
        except Exception:
            pass

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)

        try:
            return _gemini_search(query)
        except Exception:
            results = _ddg_search(query)
            return _format_ddg(query, results)
    except Exception as e:
        return f"Search failed: {e}"
