"""
Simulated customers that drive multi-turn conversations against the agent.

- LLMUserSimulator: Claude plays the customer from the scenario's persona, goal and known facts, and
  decides when the goal is met. Realistic and varied, but non-deterministic (and it can itself fail:
  e.g. give up too early or reveal facts too eagerly).
- ScriptedSimulator: replays the scenario's script (turns, fallback, done_when regex). Deterministic,
  free and fast: use it in CI and for the offline demo.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .conversation import Conversation, format_transcript
from .llm import Usage, ask_json
from .scenarios import Scenario


@dataclass
class UserReply:
    message: str
    end: bool = False
    reason: str = ""  # goal_met, script_done, gave_up


class UserSimulator(ABC):
    name = "simulator"

    def opening(self, scenario: Scenario) -> str:
        return scenario.opening_message

    @abstractmethod
    def reply(self, scenario: Scenario, conversation: Conversation) -> UserReply:
        """The customer's next message, given the conversation so far (ending with an agent turn)."""


class ScriptedSimulator(UserSimulator):
    """Replays scenario.script deterministically.

    Order of precedence after each agent reply:
    1. done_when matches the reply -> the customer is satisfied and ends the conversation;
    2. a `replies` rule matches the reply (each rule is used once) -> say its text;
    3. the next line of `turns`;
    4. `fallback`: repeated until done_when matches (if done_when is set), otherwise said once;
    5. otherwise the customer ends the conversation.
    """

    name = "scripted"

    def reply(self, scenario: Scenario, conversation: Conversation) -> UserReply:
        script = scenario.script
        agent_turns = conversation.agent_turns()
        last_agent = agent_turns[-1].text if agent_turns else ""
        if script.done_when and re.search(script.done_when, last_agent):
            return UserReply("", end=True, reason="goal_met")
        already_said = {t.text for t in conversation.user_turns()}
        for rule in script.replies:
            if rule["say"] not in already_said and re.search(rule["when"], last_agent):
                return UserReply(rule["say"])
        scripted = [t for t in conversation.user_turns()[1:] if t.text not in {r["say"] for r in script.replies}]
        said = len(scripted)  # script lines and fallbacks said so far (the opening is not counted)
        if said < len(script.turns):
            return UserReply(script.turns[said])
        if script.fallback and (script.done_when or said == len(script.turns)):
            return UserReply(script.fallback)
        return UserReply("", end=True, reason="script_done")


SIMULATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "goal_achieved": {"type": "boolean"},
        "end_conversation": {"type": "boolean"},
    },
    "required": ["message", "goal_achieved", "end_conversation"],
    "additionalProperties": False,
}


class LLMUserSimulator(UserSimulator):
    name = "llm"

    def __init__(self, client, usage: Usage | None = None):
        self.client = client
        self.usage = usage

    def system_prompt(self, scenario: Scenario) -> str:
        facts = "\n".join(f"- {k}: {v}" for k, v in scenario.known_facts.items()) or "- (nothing specific)"
        voice = (
            "This is a PHONE CALL transcribed by speech-to-text: write like natural speech, with occasional "
            "fillers (uh, um), spell out numbers the way people say them, and say emails with 'dot' and 'at'. "
            if scenario.channel == "voice" else "This is a text chat: write short, natural chat messages. "
        )
        return (
            "You are role-playing a CUSTOMER contacting Brightway Appliances support, to test their AI agent. "
            "Stay in character. You are not an assistant and you never help the agent.\n\n"
            f"Persona: {scenario.persona}\nYour goal: {scenario.goal}\n"
            f"Facts you know (share them only when asked or when it is natural):\n{facts}\n\n"
            f"{voice}Never invent order numbers, emails or other facts that are not listed. Keep messages to one "
            "to three sentences. Your first message was already sent.\n\n"
            "Set goal_achieved to true once the agent has fully done what you wanted (or clearly cannot). Set "
            "end_conversation to true when you would hang up or close the chat: goal achieved, you were transferred "
            "to a human, or you are going in circles. When ending, message may be a short goodbye or empty."
        )

    def reply(self, scenario: Scenario, conversation: Conversation) -> UserReply:
        transcript = format_transcript(conversation, with_tools=False).replace("CUSTOMER:", "YOU:")
        data = ask_json(
            self.client, self.system_prompt(scenario),
            f"Conversation so far:\n{transcript}\n\nWrite your next message as the customer.",
            SIMULATOR_SCHEMA, max_tokens=2000, effort="low", usage=self.usage,
        )
        if data["end_conversation"] or not data["message"].strip():
            return UserReply(data["message"], end=True, reason="goal_met" if data["goal_achieved"] else "gave_up")
        return UserReply(data["message"])
