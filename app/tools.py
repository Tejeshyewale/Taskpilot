"""
Tools available to the agent.

Search priority:
  1. Tavily (if TAVILY_API_KEY set) — higher quality, paid
  2. DuckDuckGo via ddgs — free, no key required, works out of the box

No fake/mock content is ever returned. If both fail, the tool reports
failure honestly and the graph's own retry/give-up logic handles it —
this is what makes the agent's behavior trustworthy: what you see in
the final report is real, or clearly marked unresolved, never invented.
"""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "").strip()


def web_search(query: str, max_retries: int = 2) -> dict:
    if TAVILY_KEY:
        result = _tavily_search(query, max_retries)
        if result["success"]:
            return result
        # Tavily failed — fall through to free DuckDuckGo rather than giving up.

    return _duckduckgo_search(query, max_retries)


def _tavily_search(query: str, max_retries: int) -> dict:
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_KEY, "query": query, "max_results": 3},
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                return {"success": False, "content": "", "source": "", "error": "No results"}
            top = results[0]
            return {"success": True, "content": top.get("content", "")[:1000],
                     "source": top.get("url", ""), "error": None}
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            time.sleep(0.5 * (attempt + 1))
    return {"success": False, "content": "", "source": "", "error": last_error}


def _duckduckgo_search(query: str, max_retries: int) -> dict:
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
            if not results:
                return {"success": False, "content": "", "source": "", "error": "No results"}
            # Combine top results into one findings blob for richer context.
            combined = "\n".join(f"- {r.get('body', '')}" for r in results if r.get("body"))
            top_source = results[0].get("href", "")
            return {"success": True, "content": combined[:1500], "source": top_source, "error": None}
        except Exception as e:  # noqa: BLE001
            last_error = str(e)
            time.sleep(0.5 * (attempt + 1))
    return {"success": False, "content": "", "source": "", "error": last_error}


# ------------------------------------------------------------------
# Calculator tool — a second, genuinely different tool (not another
# search wrapper), so the agent is a real multi-tool system: it picks
# between "look something up" and "compute something" per subquestion.
# Uses Python's `ast` module to evaluate ONLY numeric expressions —
# no eval(), no arbitrary code execution, safe by construction.
# ------------------------------------------------------------------
import ast
import operator as _op

_SAFE_OPS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Div: _op.truediv, ast.Pow: _op.pow, ast.USub: _op.neg,
    ast.Mod: _op.mod, ast.FloorDiv: _op.floordiv,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Unsupported expression")


def calculator(expression: str) -> dict:
    """Evaluates a pure arithmetic expression safely. No variables, no function calls, no imports."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return {"success": True, "content": str(result), "source": "calculator", "error": None}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "content": "", "source": "", "error": f"Could not evaluate: {e}"}


def needs_calculator(subquestion: str) -> bool:
    """
    Lightweight heuristic router: does this subquestion look like pure
    arithmetic rather than something requiring real-world information?
    Kept as a fast heuristic (not an extra LLM call) to avoid doubling
    latency/cost on every single subquestion — upgradeable to an
    LLM-based router later if the heuristic proves too coarse.
    """
    import re
    stripped = subquestion.strip().rstrip("?")
    return bool(re.fullmatch(r"[\d\s\.\+\-\*\/\(\)%]+", stripped)) and any(c.isdigit() for c in stripped)
