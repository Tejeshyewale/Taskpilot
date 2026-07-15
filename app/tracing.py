"""
Minimal observability layer — no paid tool needed.

Every node execution gets logged as one JSON line: node name, timestamp,
a snapshot of relevant state before/after, and elapsed time. This is what
lets you open a trace file after a run and answer "why did the agent do X"
with evidence instead of a guess — the exact thing interviewers probe for.
"""

import json
import time
import functools
import os

TRACE_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "trace.jsonl")


def _write(entry: dict):
    os.makedirs(os.path.dirname(TRACE_PATH), exist_ok=True)
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def traced_node(node_name: str):
    """Decorator that wraps a LangGraph node function with trace logging."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state):
            start = time.time()
            result = fn(state)
            elapsed = round(time.time() - start, 4)
            _write({
                "node": node_name,
                "timestamp": time.time(),
                "elapsed_sec": elapsed,
                "step_count_before": state.get("step_count"),
                "state_update_keys": list(result.keys()),
                "trace_note": (result.get("trace") or [""])[-1] if "trace" in result else None,
            })
            return result
        return wrapper
    return decorator


def reset_trace():
    if os.path.exists(TRACE_PATH):
        os.remove(TRACE_PATH)


def read_trace() -> list:
    if not os.path.exists(TRACE_PATH):
        return []
    with open(TRACE_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
