"""Ollama LLM adapter (ADR-0068). Implements ``LlmPort`` against a *local* Ollama server. Any
failure (server down, timeout, malformed JSON) degrades to ``UNAVAILABLE_LLM`` — the caller then
keeps its deterministic result, so the app never breaks when the LLM is absent. The Ollama URL is
server config (no user input → no SSRF). The model output is returned raw for the caller to
schema-validate; nothing is persisted here. Prompt/response content is never logged (PII)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.kernel.ports.llm import UNAVAILABLE_LLM, LlmResult
from app.logging import get_logger
from app.settings import Settings

_log = get_logger("adapters.ollama")


class OllamaLlm:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.ollama_url.rstrip("/")
        self._model = settings.ollama_model
        self._timeout = settings.ollama_timeout_s

    async def extract(self, *, prompt: str, schema: dict[str, Any]) -> LlmResult:
        """Ask Ollama to fill ``schema`` from ``prompt``. Returns the parsed JSON object on success,
        else ``UNAVAILABLE_LLM`` (never raises into the request path)."""
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "format": schema,  # Ollama structured outputs: constrain generation to the JSON schema
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._url}/api/generate", json=payload)
                resp.raise_for_status()
                body = resp.json()
            raw = body.get("response")
            if not isinstance(raw, str):
                return UNAVAILABLE_LLM
            data = json.loads(raw)
            if not isinstance(data, dict):
                return UNAVAILABLE_LLM
            return LlmResult(available=True, data=data)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            # Degrade gracefully — log the failure class only, never the prompt/response (PII).
            _log.warning("ollama_unavailable", error=type(exc).__name__)
            return UNAVAILABLE_LLM
