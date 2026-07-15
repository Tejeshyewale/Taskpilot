"""
TaskPilot core graph.

Flow:
    START -> planner -> research (loop) -> critique -> [research | human_review]
          -> human_review (interrupt) -> compose -> deliver -> END

Every node is wrapped with @traced_node for observability (see tracing.py).
Loop safety: research<->critique cannot exceed state["max_iterations"].
"""

import json
import os
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt, Command

from app.state import AgentState
from app.llm import llm, extract_json
from app.tools import web_search, calculator, needs_calculator
from app.tracing import traced_node

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "checkpoints.sqlite")


# ----------------------------------------------------------------------
# NODE 1 — Planner
# ----------------------------------------------------------------------
@traced_node("planner")
def planner_node(state: AgentState) -> dict:
    system = "Break the following research goal into 3-5 focused subquestions. Return ONLY a JSON list of strings."
    prompt = f"Goal: {state['goal']}"
    raw = llm.generate(system, prompt)

    try:
        subs = extract_json(raw)
        assert isinstance(subs, list) and len(subs) > 0
    except Exception:
        # Defensive fallback — never let a malformed LLM response crash the graph.
        subs = [state["goal"]]

    return {
        "subquestions": subs,
        "answered": {},
        "research_attempts": {q: 0 for q in subs},
        "trace": [f"[planner] produced {len(subs)} subquestions"],
        "step_count": state["step_count"] + 1,
    }


# ----------------------------------------------------------------------
# NODE 2 — Research (one subquestion per pass; picks the first unanswered)
# ----------------------------------------------------------------------
@traced_node("research")
def research_node(state: AgentState) -> dict:
    unanswered = [q for q in state["subquestions"] if q not in state["answered"]]
    if not unanswered:
        # Nothing left to research — no-op update, critique will end the loop.
        return {"trace": ["[research] no unanswered subquestions remain"],
                 "step_count": state["step_count"] + 1}

    target = unanswered[0]
    attempts = state["research_attempts"].get(target, 0)

    # Multi-tool routing: a pure-arithmetic subquestion goes to the
    # calculator tool instead of the web — a real tool-selection decision,
    # not just one hardcoded search call for every subquestion.
    if needs_calculator(target):
        result = calculator(target.rstrip("?"))
        tool_used = "calculator"
    else:
        result = web_search(target)
        tool_used = "web_search"

    new_attempts = dict(state["research_attempts"])
    new_attempts[target] = attempts + 1

    if result["success"]:
        new_answered = {target: {"answer": result["content"], "source": result["source"], "tool": tool_used}}
        note = f"[research] answered '{target[:60]}...' via {tool_used} (source: {result['source']})"
    elif attempts + 1 >= 2:
        # Give up on THIS subquestion after 2 failed attempts rather than
        # burning the whole iteration budget retrying one bad query forever.
        new_answered = {target: {"answer": "(unresolved after retries)", "source": None, "tool": tool_used}}
        note = f"[research] giving up on '{target[:60]}...' after {attempts + 1} failed attempts via {tool_used}"
    else:
        # Tool failed — log it, DON'T crash. Loop-guard above will retry
        # once more before giving up (see branch above).
        new_answered = {}
        note = f"[research] {tool_used} FAILED for '{target[:60]}...' error={result['error']} (will retry)"

    return {
        "answered": new_answered,
        "research_attempts": new_attempts,
        "trace": [note],
        "step_count": state["step_count"] + 1,
    }


# ----------------------------------------------------------------------
# NODE 3 — Critique (self-check: enough info? loop back or move on?)
# ----------------------------------------------------------------------
@traced_node("critique")
def critique_node(state: AgentState) -> dict:
    unanswered = [q for q in state["subquestions"] if q not in state["answered"]]
    max_attempt = max(state["research_attempts"].values()) if state["research_attempts"] else 0

    # Hard safety valve — independent of what the LLM "thinks".
    hit_iteration_cap = state["step_count"] >= state["max_iterations"]

    if not unanswered or hit_iteration_cap:
        needs_more = False
        notes = "All subquestions answered." if not unanswered else \
                f"Iteration cap ({state['max_iterations']}) reached — proceeding with partial findings."
    else:
        system = "You are performing a critique of research completeness."
        prompt = json.dumps({
            "unanswered_count": len(unanswered),
            "max_attempt": max_attempt,
        })
        raw = llm.generate(system, prompt)
        try:
            parsed = extract_json(raw)
            needs_more = bool(parsed.get("needs_more_research", len(unanswered) > 0))
            notes = parsed.get("notes", "")
        except Exception:
            needs_more = len(unanswered) > 0
            notes = "Critique parse failed — defaulting to unanswered-count check."

    # NOTE: step_count is intentionally NOT incremented here. It's only
    # incremented by nodes that do actual work (planner/research/compose).
    # critique is a pure decision node — if it also incremented step_count,
    # the router's cap check below would read a DIFFERENT value than the
    # one critique just used internally, causing an off-by-one where the
    # router stops one pass earlier than critique's own log claims. Keeping
    # a single counter in sync across the node and the router that reads
    # it right after is what makes the safety cap trustworthy.
    return {
        "needs_more_research": needs_more,
        "critique_notes": notes,
        "trace": [f"[critique] needs_more_research={needs_more} | {notes}"],
    }


def route_after_critique(state: AgentState) -> str:
    """Conditional edge — the actual decision point in the loop."""
    if state["needs_more_research"] and state["step_count"] < state["max_iterations"]:
        return "research"
    return "human_review"


# ----------------------------------------------------------------------
# NODE 4 — Human-in-the-loop checkpoint
# ----------------------------------------------------------------------
@traced_node("human_review")
def human_review_node(state: AgentState) -> dict:
    system = "Produce a short draft outline (bulleted section headers only) for the final research report."
    prompt = json.dumps(state["answered"])
    outline = llm.generate(system, prompt)

    # This PAUSES graph execution and persists state via the checkpointer.
    # Execution resumes exactly here once the human responds — even if
    # that's minutes, hours, or after a full process restart.
    decision = interrupt({
        "message": "Please review the draft outline before final report generation.",
        "draft_outline": outline,
    })

    approved = bool(decision.get("approved", True))
    feedback = decision.get("feedback", "")

    return {
        "draft_outline": outline,
        "human_approved": approved,
        "human_feedback": feedback,
        "trace": [f"[human_review] approved={approved} feedback='{feedback[:60]}'"],
    }


# ----------------------------------------------------------------------
# NODE 5 — Compose final report
# ----------------------------------------------------------------------
@traced_node("compose")
def compose_node(state: AgentState) -> dict:
    language = state.get("language") or "English"
    system = (
        f"You are a professional research analyst. Write a polished, well-structured "
        f"research report in clear {language}, formatted in Markdown with '#' section "
        f"headings. Structure: an Overview, then one section per finding area, then a "
        f"Conclusion. Write in full, well-organized paragraphs — not bullet dumps — "
        f"using a confident, professional analyst tone. Do NOT include a 'Sources' "
        f"section yourself; sources are appended separately. Do not repeat the raw "
        f"input data verbatim; synthesize it into original analytical prose. "
        f"The ENTIRE report must be written in {language}, including all headings."
    )
    prompt = json.dumps({
        "goal": state["goal"],
        "findings": state["answered"],
        "outline": state["draft_outline"],
        "human_feedback": state["human_feedback"],
    })
    report = llm.generate(system, prompt)

    sources = sorted({
        v.get("source") for v in state["answered"].values()
        if v.get("source")
    })

    return {
        "final_report": report,
        "sources": sources,
        "trace": ["[compose] final report generated"],
        "step_count": state["step_count"] + 1,
    }


# ----------------------------------------------------------------------
# NODE 6 — Deliver (persist to disk)
# ----------------------------------------------------------------------
@traced_node("deliver")
def deliver_node(state: AgentState) -> dict:
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "reports")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{state['thread_id']}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(state["final_report"])

    from app.history import record_task
    record_task(
        thread_id=state["thread_id"],
        goal=state["goal"],
        final_report=state["final_report"],
        sources=state.get("sources", []),
        user_email=state.get("user_id") or "anonymous",
        language=state.get("language") or "English",
    )

    notify_note = ""
    notify_email = state.get("notify_email")
    if notify_email:
        from app.notify import send_report_ready_email, is_configured
        if is_configured():
            sent = send_report_ready_email(
                notify_email, state["goal"],
                f"http://localhost:8000/?thread={state['thread_id']}",
            )
            notify_note = f" | email {'sent' if sent else 'FAILED to send'} to {notify_email}"
        else:
            notify_note = " | email skipped (SMTP not configured)"

    return {
        "is_complete": True,
        "trace": [f"[deliver] report saved to {path}{notify_note}"],
    }


# ----------------------------------------------------------------------
# Graph assembly
# ----------------------------------------------------------------------
def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("research", research_node)
    graph.add_node("critique", critique_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("compose", compose_node)
    graph.add_node("deliver", deliver_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "research")
    graph.add_edge("research", "critique")
    graph.add_conditional_edges("critique", route_after_critique,
                                  {"research": "research", "human_review": "human_review"})
    graph.add_edge("human_review", "compose")
    graph.add_edge("compose", "deliver")
    graph.add_edge("deliver", END)

    return graph.compile(checkpointer=checkpointer)


def get_sqlite_checkpointer():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return SqliteSaver.from_conn_string(DB_PATH)
