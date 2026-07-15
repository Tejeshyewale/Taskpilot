"""
State schema — the single source of truth that flows through every node.
Reducers (operator.add / custom merge fns) control HOW updates merge,
not just overwrite. This is the #1 thing naive agent projects get wrong.
"""

from typing import TypedDict, Annotated, List, Dict, Optional
import operator


def merge_dict(existing: Dict, new: Dict) -> Dict:
    """Custom reducer: merge two dicts instead of overwriting."""
    merged = dict(existing or {})
    merged.update(new or {})
    return merged


class AgentState(TypedDict):
    # --- Task definition (set once) ---
    goal: str
    max_iterations: int
    thread_id: str
    user_id: str
    language: str  # e.g. "English", "Hindi" — drives compose_node's output language
    notify_email: Optional[str]  # if set, an email is sent when the report is ready

    # --- Planning ---
    subquestions: List[str]                       # produced by planner
    answered: Annotated[Dict[str, dict], merge_dict]  # subq -> {answer, sources, tool_used}

    # --- Loop control / safety ---
    step_count: int
    research_attempts: Annotated[Dict[str, int], merge_dict]  # subq -> attempt count

    # --- Reasoning trace (append-only, shown to user + used for debugging) ---
    trace: Annotated[List[str], operator.add]

    # --- Self-critique ---
    needs_more_research: bool
    critique_notes: str

    # --- Human-in-the-loop ---
    draft_outline: Optional[str]
    human_feedback: Optional[str]
    human_approved: bool

    # --- Final output ---
    final_report: Optional[str]
    sources: List[str]
    is_complete: bool
