"""
TaskPilot API — backend for the premium web UI.
Run: uvicorn app.main:app --reload --port 8000
Then open http://localhost:8000 in your browser (frontend is served here too).
"""

import os
import uuid
import json
import queue
import asyncio
import threading
import tempfile

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.graph import build_graph, DB_PATH
from app.tracing import read_trace
from app.tools import web_search
from app.export import export_docx, export_pdf
from app.history import list_history, get_entry, set_feedback, feedback_summary
from app.llm import llm, MissingAPIKeyError
from app import auth

app = FastAPI(title="TaskPilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_cm = SqliteSaver.from_conn_string(DB_PATH)
checkpointer = _cm.__enter__()
graph = build_graph(checkpointer=checkpointer)


# ======================================================================
# Auth
# ======================================================================

class SignupRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


def _current_user_email(authorization: str = Header(default=None)) -> str:
    """Returns the logged-in user's email, or 'anonymous' if no/invalid token.
    Soft auth: endpoints still work without login, but a logged-in user's
    history stays private to them."""
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"
    token = authorization.removeprefix("Bearer ").strip()
    user = auth.get_user_by_token(token)
    return user["email"] if user else "anonymous"


@app.post("/api/auth/signup")
def signup(req: SignupRequest):
    try:
        token = auth.signup(req.email, req.password, req.name)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    user = auth.get_user_by_token(token)
    return {"token": token, "user": user}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    try:
        token = auth.login(req.email, req.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    user = auth.get_user_by_token(token)
    return {"token": token, "user": user}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        auth.logout(authorization.removeprefix("Bearer ").strip())
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(authorization: str = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    user = auth.get_user_by_token(authorization.removeprefix("Bearer ").strip())
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return user


# ======================================================================
# Task lifecycle — REST (simple, blocking; used as a fallback / for scripts)
# ======================================================================

class StartRequest(BaseModel):
    goal: str
    max_iterations: int = 6
    language: str = "English"
    notify_email: str = ""


class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool
    feedback: str = ""


class QuickSearchRequest(BaseModel):
    query: str


class CompareRequest(BaseModel):
    topic_a: str
    topic_b: str


class FeedbackRequest(BaseModel):
    thread_id: str
    rating: str  # "up" | "down"


def _initial_state(goal, max_iterations, thread_id, user_id, language, notify_email):
    return {
        "goal": goal, "max_iterations": max_iterations, "thread_id": thread_id,
        "user_id": user_id, "language": language, "notify_email": notify_email or None,
        "subquestions": [], "answered": {}, "step_count": 0,
        "research_attempts": {}, "trace": [], "needs_more_research": False,
        "critique_notes": "", "draft_outline": None, "human_feedback": None,
        "human_approved": False, "final_report": None, "sources": [], "is_complete": False,
    }


def _serialize(result: dict) -> dict:
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        return {"status": "waiting_for_human", "draft_outline": payload["draft_outline"]}
    return {
        "status": "complete" if result.get("is_complete") else "in_progress",
        "final_report": result.get("final_report"),
        "sources": result.get("sources", []),
        "step_count": result.get("step_count"),
        "goal": result.get("goal"),
    }


@app.post("/api/tasks")
def start_task(req: StartRequest, authorization: str = Header(default=None)):
    user_id = _current_user_email(authorization)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = _initial_state(req.goal, req.max_iterations, thread_id, user_id,
                                     req.language, req.notify_email)
    try:
        result = graph.invoke(initial_state, config=config)
    except MissingAPIKeyError as e:
        raise HTTPException(status_code=412, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Task failed: {e}")

    out = _serialize(result)
    out["thread_id"] = thread_id
    return out


@app.post("/api/tasks/resume")
def resume_task(req: ResumeRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    try:
        result = graph.invoke(
            Command(resume={"approved": req.approved, "feedback": req.feedback}),
            config=config,
        )
    except MissingAPIKeyError as e:
        raise HTTPException(status_code=412, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Thread not found or error: {e}")
    out = _serialize(result)
    out["thread_id"] = req.thread_id
    return out


# ======================================================================
# Real-time streaming — WebSocket (the primary way the UI runs tasks)
# ======================================================================

def _run_stream_in_thread(input_or_command, config, event_queue: queue.Queue):
    """Runs the blocking graph.stream() call in a worker thread, pushing
    each event onto a thread-safe queue that the async WS handler drains."""
    try:
        for event in graph.stream(input_or_command, config=config, stream_mode="updates"):
            event_queue.put(("event", event))
    except MissingAPIKeyError as e:
        event_queue.put(("error", str(e)))
    except Exception as e:  # noqa: BLE001
        event_queue.put(("error", f"Task failed: {e}"))
    event_queue.put(("done", None))


async def _drain_stream_to_websocket(websocket: WebSocket, input_or_command, config) -> dict:
    """Runs one graph.stream() pass, forwarding node updates over the
    websocket live. Returns a summary dict describing how it ended:
    {"kind": "interrupt", "draft_outline": ...} or
    {"kind": "complete", "final_report": ..., "sources": [...]} or
    {"kind": "error", "detail": ...}
    """
    event_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()
    thread = threading.Thread(
        target=_run_stream_in_thread, args=(input_or_command, config, event_queue), daemon=True,
    )
    thread.start()

    outcome = {"kind": "error", "detail": "Stream ended unexpectedly."}

    while True:
        kind, payload = await loop.run_in_executor(None, event_queue.get)

        if kind == "error":
            outcome = {"kind": "error", "detail": payload}
            await websocket.send_json({"type": "error", "detail": payload})
            break

        if kind == "done":
            break

        # kind == "event"
        event = payload
        if "__interrupt__" in event:
            draft_outline = event["__interrupt__"][0].value["draft_outline"]
            outcome = {"kind": "interrupt", "draft_outline": draft_outline}
            await websocket.send_json({"type": "waiting_for_human", "draft_outline": draft_outline})
            continue

        node = list(event.keys())[0]
        node_data = event[node]
        note = None
        if isinstance(node_data, dict):
            trace_list = node_data.get("trace")
            note = trace_list[-1] if trace_list else None

        await websocket.send_json({"type": "node_update", "node": node, "note": note})

        if node == "deliver" and isinstance(node_data, dict):
            outcome = {"kind": "complete"}  # final_report/sources come from state, filled below

    return outcome


@app.websocket("/ws/tasks")
async def ws_run_task(websocket: WebSocket):
    """
    Client sends ONE JSON message to start:
      {"goal": "...", "max_iterations": 6, "language": "English",
       "notify_email": "", "user_id": "someone@example.com"}
    Server streams {"type": "node_update", ...} events live, then either:
      {"type": "waiting_for_human", "draft_outline": "...", "thread_id": "..."}
      (client then sends {"approved": true/false, "feedback": "..."} to resume)
    or straight to:
      {"type": "complete", "final_report": "...", "sources": [...], "thread_id": "..."}
    """
    await websocket.accept()
    try:
        start_msg = await websocket.receive_json()
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = _initial_state(
            start_msg["goal"], start_msg.get("max_iterations", 6), thread_id,
            start_msg.get("user_id") or "anonymous",
            start_msg.get("language", "English"), start_msg.get("notify_email", ""),
        )

        await websocket.send_json({"type": "started", "thread_id": thread_id})
        outcome = await _drain_stream_to_websocket(websocket, initial_state, config)

        if outcome["kind"] == "interrupt":
            resume_msg = await websocket.receive_json()
            outcome2 = await _drain_stream_to_websocket(
                websocket, Command(resume={"approved": resume_msg.get("approved", True),
                                             "feedback": resume_msg.get("feedback", "")}),
                config,
            )
            if outcome2["kind"] == "complete":
                snapshot = graph.get_state(config).values
                await websocket.send_json({
                    "type": "complete", "thread_id": thread_id,
                    "final_report": snapshot.get("final_report"),
                    "sources": snapshot.get("sources", []),
                    "goal": snapshot.get("goal"),
                })
        elif outcome["kind"] == "complete":
            snapshot = graph.get_state(config).values
            await websocket.send_json({
                "type": "complete", "thread_id": thread_id,
                "final_report": snapshot.get("final_report"),
                "sources": snapshot.get("sources", []),
                "goal": snapshot.get("goal"),
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await websocket.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ======================================================================
# History, export, feedback
# ======================================================================

@app.get("/api/tasks/{thread_id}/state")
def get_state(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    if snapshot is None or not snapshot.values:
        raise HTTPException(status_code=404, detail="Thread not found")
    return snapshot.values


@app.get("/api/tasks/{thread_id}/export")
def export_report(thread_id: str, format: str = "pdf"):
    entry = get_entry(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Report not found. It may not have completed yet.")

    safe_name = "".join(c if c.isalnum() else "_" for c in entry["goal"][:40]).strip("_")
    tmp_dir = tempfile.gettempdir()

    if format == "docx":
        path = os.path.join(tmp_dir, f"taskpilot_{safe_name}.docx")
        export_docx(entry["goal"], entry["final_report"], entry["sources"], path)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif format == "pdf":
        path = os.path.join(tmp_dir, f"taskpilot_{safe_name}.pdf")
        export_pdf(entry["goal"], entry["final_report"], entry["sources"], path)
        media_type = "application/pdf"
    else:
        raise HTTPException(status_code=400, detail="format must be 'docx' or 'pdf'")

    return FileResponse(path, media_type=media_type, filename=os.path.basename(path))


@app.get("/api/tasks/history")
def get_history(authorization: str = Header(default=None)):
    user_id = _current_user_email(authorization)
    return list_history(user_id)


@app.get("/api/tasks/history/{thread_id}")
def get_history_entry(thread_id: str, authorization: str = Header(default=None)):
    user_id = _current_user_email(authorization)
    entry = get_entry(thread_id, user_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not found")
    return entry


@app.post("/api/tasks/feedback")
def submit_feedback(req: FeedbackRequest):
    ok = set_feedback(req.thread_id, req.rating)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid rating or thread not found")
    return {"status": "ok", "summary": feedback_summary()}


@app.get("/api/tasks/feedback/summary")
def get_feedback_summary():
    return feedback_summary()


# ======================================================================
# Quick search + Compare ("battle") mode
# ======================================================================

@app.post("/api/search")
def quick_search(req: QuickSearchRequest):
    """Standalone quick web search — independent of the agent graph."""
    result = web_search(req.query)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error") or "Search failed")
    return result


@app.post("/api/compare")
def compare_topics(req: CompareRequest):
    """
    'Battle mode' — a fast side-by-side comparison of two topics.
    Deliberately lighter-weight than the full agent pipeline (no planning
    loop, no human-review pause) since the point is a quick comparative
    snapshot, not an exhaustive report.
    """
    result_a = web_search(req.topic_a)
    result_b = web_search(req.topic_b)

    try:
        system = (
            "You are a sharp analyst producing a concise, well-organized side-by-side "
            "comparison in Markdown. Use '# Comparison', then '## <topic A>' and "
            "'## <topic B>' sections summarizing each, then a '## Verdict' section "
            "with 2-3 sentences on the key differences. Do not fabricate specifics "
            "beyond what the findings support."
        )
        prompt = json.dumps({
            "topic_a": req.topic_a, "finding_a": result_a.get("content", ""),
            "topic_b": req.topic_b, "finding_b": result_b.get("content", ""),
        })
        comparison = llm.generate(system, prompt)
    except MissingAPIKeyError as e:
        raise HTTPException(status_code=412, detail=str(e))

    return {
        "comparison": comparison,
        "sources": [s for s in (result_a.get("source"), result_b.get("source")) if s],
    }


# ======================================================================
# Trace + health
# ======================================================================

@app.get("/api/trace")
def get_trace():
    return read_trace()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the frontend (static/ folder) — index.html at the root.
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
