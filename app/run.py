"""
End-to-end runner — demonstrates:
  1. Starting a new task
  2. Graph pausing at the human_review interrupt
  3. Persistence surviving that pause (state is in SQLite, not memory)
  4. Resuming with human feedback
  5. Reading back the full trace

Run: python3 -m app.run "Research the EV battery market in India"
"""

import sys
import os
import uuid
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph import build_graph, DB_PATH
from app.tracing import reset_trace, read_trace


def run_task(goal: str, max_iterations: int = 6):
    reset_trace()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app = build_graph(checkpointer=checkpointer)

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "goal": goal,
            "max_iterations": max_iterations,
            "thread_id": thread_id,
            "user_id": "cli-user",
            "language": "English",
            "notify_email": None,
            "subquestions": [],
            "answered": {},
            "step_count": 0,
            "research_attempts": {},
            "trace": [],
            "needs_more_research": False,
            "critique_notes": "",
            "draft_outline": None,
            "human_feedback": None,
            "human_approved": False,
            "final_report": None,
            "sources": [],
            "is_complete": False,
        }

        print(f"\n=== Starting task (thread_id={thread_id}) ===")
        print(f"Goal: {goal}\n")

        # First invoke — runs until it hits the human_review interrupt()
        result = app.invoke(initial_state, config=config)

        if "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            print("--- PAUSED FOR HUMAN REVIEW ---")
            print(payload["message"])
            print("\nDraft outline:\n" + payload["draft_outline"])

            print("\n[Simulating human approval — in the real UI this is a button click]")
            resume_result = app.invoke(
                Command(resume={"approved": True, "feedback": "Looks good, proceed."}),
                config=config,
            )
            final_state = resume_result
        else:
            final_state = result

        print("\n=== FINAL REPORT ===\n")
        print(final_state.get("final_report", "(no report generated)"))

        print("\n=== TRACE SUMMARY ===")
        for entry in read_trace():
            print(f"  step={entry['step_count_before']:<3} node={entry['node']:<14} "
                  f"({entry['elapsed_sec']}s)  {entry['trace_note'] or ''}")

        print(f"\nTotal steps: {final_state['step_count']}")
        print(f"Report saved at: data/final_report.md")
        return final_state


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else "Research the EV battery market in India"
    run_task(goal)
