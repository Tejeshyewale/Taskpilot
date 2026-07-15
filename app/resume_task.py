"""
Resumes a task in a BRAND NEW process, using only the thread_id + the
SQLite checkpoint file on disk. No shared memory with start_task.py at all.

Run: python3 -m app.resume_task <thread_id>
"""

import sys
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph import build_graph, DB_PATH


def resume(thread_id: str, approved: bool = True, feedback: str = "Approved after restart."):
    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        # No initial_state passed — LangGraph loads it from the checkpoint.
        final_state = app.invoke(
            Command(resume={"approved": approved, "feedback": feedback}),
            config=config,
        )

        print("\n=== RESUMED IN A FRESH PROCESS — FINAL STATE ===")
        print(f"is_complete: {final_state['is_complete']}")
        print(f"total steps: {final_state['step_count']}")
        print(f"\nfinal_report (first 300 chars):\n{final_state['final_report'][:300]}")
        return final_state


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m app.resume_task <thread_id>")
        sys.exit(1)
    resume(sys.argv[1])
