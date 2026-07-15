"""
LLM client — REAL PROVIDERS ONLY. No test/mock mode.

Priority: GEMINI_API_KEY -> ANTHROPIC_API_KEY -> GROQ_API_KEY

Key detection is LAZY (checked on first actual generate() call, not at
import time). This lets the FastAPI server + UI start and be browsable
even before a key is configured — the user sees a clear in-app error
the moment they try to start a task, instead of the whole server
refusing to boot with a raw Python traceback.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()


class MissingAPIKeyError(RuntimeError):
    pass


class LLMClient:
    def __init__(self):
        self._mode = None  # resolved lazily

    @property
    def mode(self) -> str:
        if self._mode is None:
            self._mode = self._detect_mode()
        return self._mode

    def _detect_mode(self) -> str:
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()

        if gemini_key:
            return "gemini"
        if anthropic_key:
            return "anthropic"
        if groq_key:
            return "groq"

        raise MissingAPIKeyError(
            "No LLM API key found. Add ONE of GEMINI_API_KEY, ANTHROPIC_API_KEY, "
            "or GROQ_API_KEY to a .env file at the project root (same folder as "
            "requirements.txt), then restart the server. "
            "Get a free Groq key at https://console.groq.com/keys"
        )

    def generate(self, system: str, prompt: str) -> str:
        mode = self.mode  # raises MissingAPIKeyError here if nothing configured
        if mode == "gemini":
            return self._call_gemini(system, prompt)
        if mode == "anthropic":
            return self._call_anthropic(system, prompt)
        return self._call_groq(system, prompt)

    def _call_gemini(self, system: str, prompt: str) -> str:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "").strip())
        model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=system)
        resp = model.generate_content(prompt)
        return resp.text

    def _call_anthropic(self, system: str, prompt: str) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip())
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2000,
            system=system, messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    def _call_groq(self, system: str, prompt: str) -> str:
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 2000,
            },
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


llm = LLMClient()


def extract_json(raw: str):
    """Real LLMs often wrap JSON in ```json fences or add commentary — extract the JSON substring before parsing."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    start_candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if start_candidates:
        start = min(start_candidates)
        end_candidates = [i for i in (text.rfind("}"), text.rfind("]")) if i != -1]
        end = max(end_candidates) + 1 if end_candidates else len(text)
        text = text[start:end]
    return json.loads(text)
