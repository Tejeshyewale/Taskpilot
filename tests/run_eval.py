"""
Phase 7 — Evaluation harness.

Runs the full graph over a fixed set of test goals (including deliberately
adversarial low-iteration-cap cases) and produces quantified metrics —
the same "tested on N cases, X% success" evidence that gave DocuMind its
"88% answer relevance on 50 test queries" resume line.

Run: python3 -m tests.run_eval
"""

import json
import os
import sys
import time
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph import build_graph

EVAL_SET_PATH = os.path.join(os.path.dirname(__file__), "eval_set.json")
EVAL_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval_checkpoints.sqlite")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval_report.md")


def run_single(app, case: dict) -> dict:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "goal": case["goal"], "max_iterations": case["max_iterations"], "thread_id": thread_id,
        "user_id": "eval-harness", "language": "English", "notify_email": None,
        "subquestions": [], "answered": {}, "step_count": 0,
        "research_attempts": {}, "trace": [], "needs_more_research": False,
        "critique_notes": "", "draft_outline": None, "human_feedback": None,
        "human_approved": False, "final_report": None, "sources": [], "is_complete": False,
    }

    start = time.time()
    error = None
    hit_hitl = False
    hit_iter_cap = False
    final_state = None

    try:
        result = app.invoke(initial_state, config=config)
        if "__interrupt__" in result:
            hit_hitl = True
            result = app.invoke(
                Command(resume={"approved": True, "feedback": "auto-approved by eval harness"}),
                config=config,
            )
        final_state = result
        hit_iter_cap = "Iteration cap" in (final_state.get("critique_notes") or "")
    except Exception as e:  # noqa: BLE001
        error = str(e)

    elapsed = round(time.time() - start, 3)

    if error:
        return {"goal": case["goal"], "success": False, "error": error,
                 "elapsed_sec": elapsed, "note": case.get("note", "")}

    unanswered = [q for q in final_state["subquestions"] if q not in final_state["answered"]]

    return {
        "goal": case["goal"],
        "success": bool(final_state.get("is_complete")),
        "steps": final_state.get("step_count"),
        "subquestions_total": len(final_state.get("subquestions", [])),
        "subquestions_answered": len(final_state.get("subquestions", [])) - len(unanswered),
        "hit_hitl_checkpoint": hit_hitl,
        "hit_iteration_cap": hit_iter_cap,
        "elapsed_sec": elapsed,
        "note": case.get("note", ""),
        "error": None,
    }


def main():
    with open(EVAL_SET_PATH) as f:
        cases = json.load(f)

    if os.path.exists(EVAL_DB_PATH):
        os.remove(EVAL_DB_PATH)

    results = []
    with SqliteSaver.from_conn_string(EVAL_DB_PATH) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] Running: {case['goal'][:60]}...")
            results.append(run_single(app, case))

    # ---- Aggregate metrics ----
    total = len(results)
    successes = sum(1 for r in results if r["success"])
    crashes = sum(1 for r in results if r.get("error"))
    hitl_triggered = sum(1 for r in results if r.get("hit_hitl_checkpoint"))
    iter_cap_triggered = sum(1 for r in results if r.get("hit_iteration_cap"))
    avg_steps = round(sum(r.get("steps", 0) for r in results if r["success"]) / max(successes, 1), 2)

    lines = []
    lines.append("# TaskPilot Evaluation Report\n")
    lines.append(f"Run on {time.strftime('%Y-%m-%d %H:%M:%S')} | Test cases: {total}\n")
    lines.append("## Summary Metrics\n")
    lines.append(f"- **Success rate**: {successes}/{total} ({round(100*successes/total,1)}%)")
    lines.append(f"- **Crash rate**: {crashes}/{total} — target is 0, since crashes are unacceptable regardless of task difficulty")
    lines.append(f"- **Human-in-the-loop checkpoint triggered**: {hitl_triggered}/{total} (expected: all — every task should pause for approval)")
    lines.append(f"- **Iteration safety-cap triggered**: {iter_cap_triggered}/{total} (expected: only the 3 adversarial low-cap cases)")
    lines.append(f"- **Average steps to completion (successful runs)**: {avg_steps}\n")
    lines.append("## Per-Case Results\n")
    lines.append("| Goal | Success | Steps | Subquestions Answered | HITL | Iter Cap Hit | Note |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        if r.get("error"):
            lines.append(f"| {r['goal'][:40]} | ❌ CRASH | - | - | - | - | {r['error'][:40]} |")
        else:
            lines.append(f"| {r['goal'][:40]} | {'✅' if r['success'] else '❌'} | {r['steps']} | "
                          f"{r['subquestions_answered']}/{r['subquestions_total']} | "
                          f"{'yes' if r['hit_hitl_checkpoint'] else 'no'} | "
                          f"{'yes' if r['hit_iteration_cap'] else 'no'} | {r['note']} |")

    report = "\n".join(lines)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print("\n" + report)
    print(f"\nSaved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
