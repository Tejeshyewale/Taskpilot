"""
Starts a task and exits the PROCESS entirely once it hits the human_review
interrupt. Nothing is kept in memory after this script ends — proving that
resume_task.py (a completely separate process) can pick it up purely from
the SQLite checkpoint file on disk.

Run: python3 -m app.start_task "some goal" > thread_id.txt
"""

import sys
import uuid
import os
from langgraph.checkpoint.sqlite import SqliteSaver

from app.graph import build_graph, DB_PATH
from app.tracing import reset_trace


def start(goal: str, max_iterations: int = 6) -> str:
    reset_trace()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "goal": goal, "max_iterations": max_iterations, "thread_id": thread_id,
            "user_id": "cli-user", "language": "English", "notify_email": None,
            "subquestions": [], "answered": {}, "step_count": 0,
            "research_attempts": {}, "trace": [], "needs_more_research": False,
            "critique_notes": "", "draft_outline": None, "human_feedback": None,
            "human_approved": False, "final_report": None, "sources": [], "is_complete": False,
        }

        result = app.invoke(initial_state, config=config)
        assert "__interrupt__" in result, "Expected to pause at human_review"

        print(f"THREAD_ID={thread_id}", file=sys.stderr)
        print(thread_id)  # stdout — this is what gets captured by caller
        print(f"[start_task] Paused for human review. Process exiting now.", file=sys.stderr)
        print(f"[start_task] Draft outline was:\n{result['__interrupt__'][0].value['draft_outline']}",
              file=sys.stderr)


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else "Research the EV battery market in India"
    start(goal)
