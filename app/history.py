"""
Lightweight history store — records every completed task (goal, thread_id,
timestamp, report, user) to a JSON file, scoped per user, plus a simple
thumbs-up/down feedback rating per report.
"""

import json
import os
import time

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")


def _load() -> list:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save(entries: list):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def record_task(thread_id: str, goal: str, final_report: str, sources: list,
                 user_email: str = "anonymous", language: str = "English"):
    entries = _load()
    entries.insert(0, {
        "thread_id": thread_id,
        "goal": goal,
        "user_email": user_email,
        "language": language,
        "timestamp": time.time(),
        "date_display": time.strftime("%d %b %Y, %H:%M"),
        "final_report": final_report,
        "sources": sources,
        "feedback": None,  # "up" | "down" | None
    })
    entries = entries[:200]
    _save(entries)


def list_history(user_email: str = None) -> list:
    """Lightweight entries (no full report text) for the sidebar, scoped to a user."""
    entries = _load()
    if user_email:
        entries = [e for e in entries if e.get("user_email") == user_email]
    return [
        {"thread_id": e["thread_id"], "goal": e["goal"], "date_display": e["date_display"],
         "feedback": e.get("feedback")}
        for e in entries
    ]


def get_entry(thread_id: str, user_email: str = None):
    for e in _load():
        if e["thread_id"] == thread_id:
            if user_email and e.get("user_email") not in (user_email, "anonymous"):
                return None  # don't leak other users' reports
            return e
    return None


def set_feedback(thread_id: str, rating: str) -> bool:
    if rating not in ("up", "down"):
        return False
    entries = _load()
    for e in entries:
        if e["thread_id"] == thread_id:
            e["feedback"] = rating
            _save(entries)
            return True
    return False


def feedback_summary() -> dict:
    entries = _load()
    up = sum(1 for e in entries if e.get("feedback") == "up")
    down = sum(1 for e in entries if e.get("feedback") == "down")
    return {"up": up, "down": down, "total_rated": up + down}
