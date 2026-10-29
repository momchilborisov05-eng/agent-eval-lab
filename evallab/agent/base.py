"""
The adapter interface: the only thing the lab needs from a system under test.

Any agent can be evaluated if it can (1) start a fresh conversation and (2) answer one customer
message, reporting the text it said and the tools it called. The reference Claude agent, the
offline demo agent and an ElevenLabs agent (see adapters/elevenlabs.py) all fit this shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..conversation import ToolCall


@dataclass
class ConversationContext:
    """What an agent knows about the conversation before the first message."""

    scenario_id: str
    channel: str = "chat"  # "chat" or "voice"
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentTurn:
    """One agent reply."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: float | None = None  # set by adapters that know the real latency (e.g. voice transcripts)
    ended: bool = False              # True when the agent handed off or hung up
    end_reason: str | None = None
    error: str | None = None


class AgentAdapter(ABC):
    """Implement start() and respond() to plug any agent into the lab."""

    name: str = "agent"
    version: str = "v1"
    model: str = ""
    canary: str | None = None  # secret string planted in the system prompt, checked for leaks

    @abstractmethod
    def start(self, context: ConversationContext) -> None:
        """Reset all conversation state."""

    @abstractmethod
    def respond(self, user_message: str) -> AgentTurn:
        """Answer one customer message (running any tools the agent needs)."""

    def describe(self) -> dict:
        return {"name": self.name, "version": self.version, "model": self.model}
