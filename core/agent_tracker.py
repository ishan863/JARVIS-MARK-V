"""Centralized agent activity tracker with real-time status, daily brief, and memory persistence."""
import json
import time
from datetime import datetime, date
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ACTIVITY_FILE = DATA_DIR / "agent_activity.json"
_lock = Lock()


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> list:
    _ensure_dir()
    if ACTIVITY_FILE.exists():
        try:
            with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save(activities: list):
    _ensure_dir()
    # Keep last 500 entries max
    with _lock:
        with open(ACTIVITY_FILE, "w", encoding="utf-8") as f:
            json.dump(activities[-500:], f, indent=2, ensure_ascii=False)


def log_activity(agent: str, action: str, status: str, detail: str = ""):
    """Log an agent activity. agent: tool name. action: what was done. status: success/fail/running. detail: extra info."""
    activities = _load()
    activities.append({
        "agent": agent,
        "action": action,
        "status": status,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
    })
    _save(activities)


def get_recent(limit: int = 20) -> list:
    """Get most recent activities."""
    return _load()[-limit:]


def get_today_summary() -> str:
    """Get a human-readable summary of today's agent activity."""
    today = date.today().isoformat()
    activities = _load()
    today_acts = [a for a in activities if a.get("timestamp", "").startswith(today)]

    if not today_acts:
        return "No activity recorded today."

    by_agent = {}
    for a in today_acts:
        agent = a.get("agent", "unknown")
        by_agent.setdefault(agent, {"success": 0, "fail": 0, "total": 0, "actions": []})
        by_agent[agent]["total"] += 1
        if a.get("status") == "success":
            by_agent[agent]["success"] += 1
        elif a.get("status") == "fail":
            by_agent[agent]["fail"] += 1
        by_agent[agent]["actions"].append(a.get("action", "?"))

    lines = [f"Today's Activity Summary ({today}):"]
    for agent, stats in sorted(by_agent.items()):
        lines.append(
            f"  {agent}: {stats['total']} ops "
            f"({stats['success']} ok, {stats['fail']} failed)"
        )
        # Show last 3 unique actions
        unique = list(dict.fromkeys(stats["actions"]))[-3:]
        for a in unique:
            lines.append(f"    - {a}")

    return "\n".join(lines)


def get_agent_status() -> dict:
    """Get status of all agents that have been active recently."""
    activities = _load()
    if not activities:
        return {}

    status = {}
    seen = set()
    for a in reversed(activities):
        agent = a.get("agent", "unknown")
        if agent not in seen:
            seen.add(agent)
            status[agent] = {
                "last_action": a.get("action", ""),
                "last_status": a.get("status", ""),
                "last_time": a.get("timestamp", ""),
                "detail": a.get("detail", ""),
            }
    return status


def daily_brief(parameters=None, player=None, **kwargs) -> str:
    """Tool: return today's agent activity summary."""
    summary = get_today_summary()
    status = get_agent_status()

    if status:
        lines = [summary, "", "Agent Status:"]
        for agent, info in sorted(status.items()):
            lines.append(f"  {agent}: {info['last_status']} @ {info['last_action']}")
        return "\n".join(lines)
    return summary
