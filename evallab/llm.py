"""
Shared Claude API helpers: the client, the model setting, Structured Outputs calls and token usage.

The simulator, the judge and the lead extractor all use ask_json(), so every model answer is
guaranteed to match a JSON schema. The support agent has its own tool-use loop in agent/claude_agent.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class LLMError(RuntimeError):
    """A problem the user should see, such as a missing API key or a refused request."""


def fallback_kwargs() -> dict:
    """Server-side refusal fallback: if the model declines, the API retries on a fallback model."""
    if MODEL in FALLBACK_MODELS:
        return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    return {}


def make_client():
    """Create an Anthropic client, or explain how to run without one."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise LLMError(
            "No Claude API key found. Copy .env.example to .env and set ANTHROPIC_API_KEY, "
            "or run the offline demo instead: python -m evallab demo"
        )
    import anthropic

    return anthropic.Anthropic()


@dataclass
class Usage:
    """Token counter shared by all model calls of a run."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def add(self, usage) -> None:
        if usage is None:
            return
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        created = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.requests += 1
        self.input_tokens += (getattr(usage, "input_tokens", 0) or 0) + cached + created
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cached_tokens += cached

    def to_dict(self) -> dict:
        return asdict(self)


def ask_json(client, system, user_text: str, schema: dict, *, max_tokens: int = 4000,
             effort: str = "low", usage: Usage | None = None) -> dict:
    """One Structured Outputs call. Returns the parsed JSON object."""
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_text}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        **fallback_kwargs(),
    )
    if usage is not None:
        usage.add(response.usage)
    if response.stop_reason == "refusal":
        raise LLMError("The model declined to process this request.")
    if response.stop_reason == "max_tokens":
        raise LLMError("The model's answer was cut off (max_tokens). Raise max_tokens and retry.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
