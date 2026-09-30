from __future__ import annotations

from typing import Any, Protocol

from fastapi import Request
from pydantic import BaseModel


class LlmResult(BaseModel):
    available: bool = False
    data: dict[str, Any] | None = None


UNAVAILABLE_LLM = LlmResult(available=False)


class LlmPort(Protocol):
    """LLM is gepkapselt: output is never persisted directly — schema-validated,
    then review screen (ARCHITECTURE §16). Vault content never reaches the LLM."""

    async def extract(self, *, prompt: str, schema: dict[str, Any]) -> LlmResult: ...


def get_llm(request: Request) -> LlmPort:
    """FastAPI dependency: the LLM adapter chosen at startup (``app.state.llm``). Lives in the
    kernel so modules depend only on ``kernel/*`` — the concrete adapter (Ollama, or the Null
    adapter when disabled) is selected in the composition root (``main.py``). import-linter forbids
    ``modules``/``kernel`` → ``adapters`` (ADR-0068)."""
    llm: LlmPort = request.app.state.llm
    return llm
