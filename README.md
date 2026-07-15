
# TaskPilot — Autonomous Research Agent

A production-oriented autonomous research agent with a premium web UI,
real-time streaming, accounts, and a genuine multi-tool agent core.

Give it a goal, it plans it into subquestions, researches each one with
the right tool (web search or calculator), self-critiques its own
progress, pauses for your approval, and writes a polished final report —
exportable as DOCX or PDF, in the language of your choice, with an
optional email notification when it's ready. A "Battle Mode" side panel
gives instant side-by-side comparisons of two topics.

Built with **LangGraph** (agent orchestration), **FastAPI** (with native
WebSocket streaming), and a hand-built HTML/CSS/JS frontend.

---

## Features

- **Real LLM + real web search, no mock mode** — Gemini / Claude / Groq for
  reasoning, free DuckDuckGo (or optional Tavily) for search
- **Multi-tool agent** — a subquestion is routed to a calculator tool or
  a web-search tool depending on what it actually needs, not one
  hardcoded tool for everything
- **Real-time streaming** — the UI's progress stepper reflects the
  agent's *actual* current step, pushed live over a WebSocket, not a
  client-side animation guessing at timing
- **Accounts** — email/password signup & login (salted, hashed
  passwords); a guest can also skip login and use the app anonymously.
  Each user's report history stays private to them
- **DOCX / PDF export** — a clean, professional formatted document, not
  a JSON dump
- **Multi-language reports** — English, Hindi, Spanish, French, German,
  Japanese
- **Email notifications** — optional, sent when a report finishes
  (gracefully skipped if SMTP isn't configured)
- **Battle Mode** — fast side-by-side comparison of two topics, skipping
  the full plan/research/critique loop for a quick snapshot
- **Feedback** — 👍/👎 rating per report, aggregated for a simple
  usefulness signal
- **Light/dark theme toggle**
- **Task history sidebar**, unique logo, distinct visual identity

## Architecture

```
Browser (static/index.html, style.css, app.js)
        |  fetch() + WebSocket
        v
FastAPI (app/main.py)
        |
        +- /ws/tasks                       -> app/graph.py, streamed live over WebSocket
        +- /api/auth/*                      -> app/auth.py (signup/login/session tokens)
        +- /api/tasks/history, /feedback     -> app/history.py (JSON store, user-scoped)
        +- /api/tasks/{id}/export             -> app/export.py (DOCX/PDF)
        +- /api/search                         -> app/tools.py (quick search)
        +- /api/compare                         -> Battle Mode (search both + LLM synthesis)
        +- /api/trace                            -> app/tracing.py (observability)
```

Agent graph (core design unchanged — see `app/graph.py`):
```
planner -> research <-> critique -> human_review (pauses here) -> compose -> deliver
```
- **Multi-tool routing**: `research` picks `calculator` for pure-arithmetic
  subquestions, `web_search` otherwise (heuristic router — see
  `app/tools.py::needs_calculator`, upgradeable to an LLM-based router)
- Hard iteration cap prevents infinite loops, independent of what the LLM "thinks"
- Per-subquestion retry-then-give-up prevents one bad search from stalling everything
- State persists to SQLite — a task survives a full process restart
- Every node execution is logged to `logs/trace.jsonl` and streamed live over WebSocket

## Running it

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
```
Set **one** LLM key (required):
```
GEMINI_API_KEY=...   # or
ANTHROPIC_API_KEY=... # or
GROQ_API_KEY=...     # free tier: https://console.groq.com/keys
```
Web search works with no key (free DuckDuckGo). Optional additions:
```
TAVILY_API_KEY=...          # higher-quality search
SMTP_HOST=... etc.          # enables email notifications
```

### 3. Run
```bash
uvicorn app.main:app --reload --port 8000
```
Open **http://localhost:8000** — sign up, log in, or skip and use as a guest.

### 4. Docker
```bash
docker compose up --build
```

## Project structure
```
taskpilot/
|-- app/
|   |-- state.py         # state schema + reducers (now includes user_id, language, notify_email)
|   |-- llm.py             # LLM client (Gemini/Anthropic/Groq, lazy key check)
|   |-- tools.py             # web_search (DuckDuckGo/Tavily) + calculator + tool router
|   |-- auth.py                # accounts - hashed passwords, session tokens
|   |-- notify.py                # email notifications (graceful no-op if unconfigured)
|   |-- tracing.py                 # observability (JSONL trace log)
|   |-- graph.py                     # the agent graph - nodes, edges, loop control
|   |-- export.py                      # DOCX + PDF report generation
|   |-- history.py                       # user-scoped task history + feedback ratings
|   |-- run.py / start_task.py / resume_task.py   # CLI + persistence demos
|   `-- main.py                             # FastAPI backend: REST + WebSocket + serves static/
|-- static/
|   |-- index.html                            # single-page app shell (auth gate + main app)
|   |-- style.css                               # premium dark/light theme
|   |-- app.js                                    # frontend logic incl. WebSocket client
|   `-- favicon.svg                                 # unique logo mark
|-- tests/                                           # evaluation harness (needs a real key)
|-- requirements.txt
|-- Dockerfile / docker-compose.yml
`-- .env.example
```

## Design notes

**Logo**: a custom SVG mark (not a stock emoji or icon-font glyph) — an
angular "forward motion" arrow inside a rounded badge, using the app's own
indigo→violet→pink gradient, doubling as the browser favicon.

**UI**: dark-first "mission control" theme, Inter for UI text, JetBrains Mono
for the trace/log panel. A light theme is available via the sidebar toggle.
Motion is limited to the stepper and panel transitions; `prefers-reduced-motion`
is respected; keyboard focus is visible on every interactive element.

**Streaming**: `graph.stream(..., stream_mode="updates")` runs in a worker
thread; each node's completion is forwarded over the WebSocket as it
happens, so the UI's stepper is a direct reflection of backend state, not
a guess.

## Extending it further
- Swap the heuristic calculator router for an LLM-based tool-selection call
- Add a third tool (code execution, file I/O)
- Move history/auth from JSON files to Postgres for true concurrent multi-user scale
- Add password reset / email verification for accounts
=======
# Taskpilot
Autonomous Research Agent

