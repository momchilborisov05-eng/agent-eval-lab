"""Shared test helpers: project import path, a fake Claude client and conversation builders. No network."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCENARIOS_DIR = ROOT / "scenarios"

from evallab.conversation import Conversation, ToolCall, Turn  # noqa: E402
from evallab.scenarios import parse_scenario  # noqa: E402


def usage():
    return NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def text_response(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return NS(stop_reason=stop_reason, content=[NS(type="text", text=text)], usage=usage())


def tool_use_response(name, args, block_id="toolu_1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=block_id, name=name, input=args)], usage=usage())


class FakeClaude:
    """Returns queued responses in order and records every request (client.beta.messages.create)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        # Snapshot the messages: the agent keeps appending to the same list after the call.
        self.requests.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self.responses:
            raise AssertionError("FakeClaude ran out of queued responses")
        return self.responses.pop(0)


def scenario(**overrides):
    data = {
        "id": "test-scenario", "title": "Test", "category": "orders", "persona": "A tester.",
        "goal": "Check things.", "opening_message": "Hi", "success_criteria": ["It works."],
        "customer_id": "C001", "max_turns": 4,
    }
    data.update(overrides)
    return parse_scenario(data, "test.yaml")


def conversation(exchanges, end_reason="user_goal_met", scenario_id="test-scenario"):
    """exchanges: list of (user_text, agent_text, [ToolCall...], latency_ms)."""
    turns = []
    for i, (user, agent, calls, latency) in enumerate(exchanges, start=1):
        turns.append(Turn(i, "user", user))
        turns.append(Turn(i, "agent", agent, list(calls or []), latency))
    return Conversation(scenario_id=scenario_id, turns=turns, end_reason=end_reason)


__all__ = ["ROOT", "SCENARIOS_DIR", "FakeClaude", "text_response", "tool_use_response", "scenario",
           "conversation", "ToolCall", "Turn", "Conversation", "NS"]
