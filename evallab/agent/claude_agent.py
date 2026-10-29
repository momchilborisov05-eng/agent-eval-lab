"""
The reference system under test: a Brightway support agent built on Claude tool use.

A manual agentic loop (rather than the SDK tool runner) so every tool call, its arguments and its
result can be recorded for evaluation, and so latency covers the whole turn including tools.
"""

from __future__ import annotations

import json
import time

from ..conversation import ToolCall
from ..llm import MODEL, Usage, fallback_kwargs
from .base import AgentAdapter, AgentTurn, ConversationContext
from .prompts import CANARY, get_prompt
from .tools import TOOL_DEFINITIONS, SupportBackend

MAX_TOOL_ROUNDS = 6  # model calls per customer message, so a confused agent can't loop forever


class ClaudeSupportAgent(AgentAdapter):
    name = "brightway-support"

    def __init__(self, client, prompt_version: str = "v2", usage: Usage | None = None):
        self.client = client
        self.version = prompt_version
        self.model = MODEL
        self.canary = CANARY
        self.usage = usage or Usage()
        # The system prompt and tools are identical for every conversation, so they are prompt-cached.
        self.system = [{"type": "text", "text": get_prompt(prompt_version), "cache_control": {"type": "ephemeral"}}]
        self.backend = SupportBackend()
        self.messages: list[dict] = []
        self.channel = "chat"

    def start(self, context: ConversationContext) -> None:
        self.backend = SupportBackend()
        self.messages = []
        self.channel = context.channel

    def respond(self, user_message: str) -> AgentTurn:
        started = time.perf_counter()
        prefix = "[voice call transcript] " if self.channel == "voice" else ""
        self.messages.append({"role": "user", "content": prefix + user_message})
        calls: list[ToolCall] = []

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=8000,
                system=self.system,
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
                output_config={"effort": "low"},  # support replies are latency-sensitive
                **fallback_kwargs(),
            )
            self.usage.add(response.usage)
            # Append the full content (thinking, fallback and tool_use blocks included), never just the text.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return self._turn("", calls, started, error="The model declined to answer.")
            if response.stop_reason == "max_tokens":
                return self._turn(_text(response), calls, started, error="The reply was cut off (max_tokens).")
            if response.stop_reason != "tool_use":
                return self._turn(_text(response), calls, started)

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result, is_error = self.backend.execute(block.name, dict(block.input))
                calls.append(ToolCall(block.name, dict(block.input), result, is_error))
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(result, ensure_ascii=False), "is_error": is_error})
            # All results of one assistant message go back in a single user message.
            self.messages.append({"role": "user", "content": results})

        return self._turn("", calls, started, error=f"No final answer after {MAX_TOOL_ROUNDS} tool rounds.")

    def _turn(self, text: str, calls: list[ToolCall], started: float, error: str | None = None) -> AgentTurn:
        transferred = any(c.name == "transfer_to_human" and not c.is_error for c in calls)
        return AgentTurn(
            text=text, tool_calls=calls, latency_ms=round((time.perf_counter() - started) * 1000, 1),
            ended=transferred, end_reason="transferred" if transferred else None, error=error,
        )


def _text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()
