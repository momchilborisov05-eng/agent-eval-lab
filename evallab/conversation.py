"""
The conversation data model shared by every part of the lab.

A conversation is a list of turns. A "turn index" is the exchange number (1-based): the customer
message and the agent reply that answers it share the same index, so a failed check can point at
one exchange in the transcript viewer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: Any = None
    is_error: bool = False


@dataclass
class Turn:
    index: int
    role: str  # "user" or "agent"
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: float | None = None


@dataclass
class Conversation:
    scenario_id: str
    turns: list[Turn] = field(default_factory=list)
    end_reason: str = "unknown"  # user_done, transferred, max_turns, agent_error, imported
    meta: dict[str, Any] = field(default_factory=dict)

    def agent_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == "agent"]

    def user_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.role == "user"]

    def tool_calls(self) -> list[tuple[int, ToolCall]]:
        """Every tool call with the index of the exchange it happened in."""
        return [(t.index, c) for t in self.agent_turns() for c in t.tool_calls]

    @property
    def exchange_count(self) -> int:
        return max((t.index for t in self.turns), default=0)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        turns = [
            Turn(
                index=t["index"], role=t["role"], text=t.get("text") or "",
                tool_calls=[ToolCall(**c) for c in t.get("tool_calls", [])],
                latency_ms=t.get("latency_ms"),
            )
            for t in data.get("turns", [])
        ]
        return cls(scenario_id=data["scenario_id"], turns=turns,
                   end_reason=data.get("end_reason", "unknown"), meta=data.get("meta", {}))


def format_transcript(conversation: Conversation, with_tools: bool = True) -> str:
    """Plain-text transcript for LLM prompts (simulator, judge, lead extraction)."""
    import json

    lines = []
    for turn in conversation.turns:
        speaker = "CUSTOMER" if turn.role == "user" else "AGENT"
        if with_tools:
            for call in turn.tool_calls:
                status = "ERROR" if call.is_error else "ok"
                lines.append(
                    f"[turn {turn.index}] TOOL CALL {call.name}({json.dumps(call.arguments, ensure_ascii=False)})"
                    f" -> {status}: {json.dumps(call.result, ensure_ascii=False, default=str)}"
                )
        lines.append(f"[turn {turn.index}] {speaker}: {turn.text}")
    return "\n".join(lines)
