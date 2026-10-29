"""
Evaluate ElevenLabs Agents (ElevenAgents / Conversational AI) conversations with the same checks and
judge as simulated ones - without calling any ElevenLabs API.

Two integration paths:

1. Offline / production monitoring (implemented here): ElevenLabs can send a post-call webhook with the
   full transcript, and the same conversation object can be exported from the conversation history.
   parse_elevenlabs_conversation() converts that JSON into a Conversation, which the lab scores against
   a scenario (CLI: `python -m evallab score-transcript`). Store the webhook payloads, score them nightly,
   and the dashboard becomes a quality monitor for real traffic.

2. Live simulation (documented in the README, not implemented): an AgentAdapter whose respond() sends
   the simulated customer's text to a deployed agent in text-only mode and collects its reply and tool
   events. Everything else in the lab stays the same.

Expected payload shape (only these fields are read; everything else is ignored, and field names should
be checked against the current ElevenLabs docs):

    {"type": "post_call_transcription",               # optional webhook envelope
     "data": {
        "agent_id": "...", "conversation_id": "...",
        "transcript": [
          {"role": "user" | "agent", "message": "text or null", "time_in_call_secs": 12,
           "tool_calls":   [{"tool_name": "...", "params_as_json": "{...}", "request_id": "..."}],
           "tool_results": [{"tool_name": "...", "result_value": "...", "is_error": false, "request_id": "..."}]},
          ...],
        "metadata": {...}, "analysis": {...}}}

Notes on fidelity: consecutive agent entries (e.g. a tool call entry followed by the spoken reply) are
merged into one agent turn. Latency is estimated from time_in_call_secs (time between the end of the
customer's entry and the agent's reply), which has one-second resolution, so treat it as approximate.
"""

from __future__ import annotations

import json
from typing import Any

from ..conversation import Conversation, ToolCall, Turn


class TranscriptFormatError(ValueError):
    """The JSON does not look like an ElevenLabs conversation."""


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def parse_elevenlabs_conversation(payload: dict, scenario_id: str = "imported",
                                  tool_name_map: dict[str, str] | None = None) -> Conversation:
    """Convert an ElevenLabs conversation (webhook payload or conversation object) into a Conversation."""
    if not isinstance(payload, dict):
        raise TranscriptFormatError("Expected a JSON object.")
    data = payload["data"] if isinstance(payload.get("data"), dict) else payload
    transcript = data.get("transcript")
    if not isinstance(transcript, list) or not transcript:
        raise TranscriptFormatError("No 'transcript' list found (expected data.transcript[] with role/message).")
    names = tool_name_map or {}

    turns: list[Turn] = []
    index = 0
    last_user_time: float | None = None
    for i, entry in enumerate(transcript):
        if not isinstance(entry, dict) or entry.get("role") not in ("user", "agent"):
            raise TranscriptFormatError(f"transcript[{i}]: each entry needs role 'user' or 'agent'.")
        text = (entry.get("message") or "").strip()
        t = entry.get("time_in_call_secs")
        if entry["role"] == "user":
            if not text:
                continue
            if turns and turns[-1].role == "user":
                turns[-1].text += " " + text  # the customer spoke twice before the agent answered
            else:
                index += 1
                turns.append(Turn(index, "user", text))
            last_user_time = t
            continue

        results = {r.get("request_id") or r.get("tool_name"): r for r in entry.get("tool_results") or []}
        calls = []
        for call in entry.get("tool_calls") or []:
            key = call.get("request_id") or call.get("tool_name")
            result = results.pop(key, None)
            calls.append(ToolCall(
                name=names.get(call.get("tool_name"), call.get("tool_name") or "unknown"),
                arguments=_parse_json(call.get("params_as_json") or call.get("parameters") or {}) or {},
                result=_parse_json(result.get("result_value")) if result else None,
                is_error=bool(result.get("is_error")) if result else False,
            ))
        # A result whose call appeared in an earlier entry: attach it to that call.
        for result in results.values():
            for turn in reversed(turns):
                match = next((c for c in turn.tool_calls if c.result is None), None)
                if match:
                    match.result = _parse_json(result.get("result_value"))
                    match.is_error = bool(result.get("is_error"))
                    break
        latency = None
        if t is not None and last_user_time is not None and text:
            latency = max(0.0, (float(t) - float(last_user_time)) * 1000)
        if turns and turns[-1].role == "agent":
            prev = turns[-1]
            prev.text = (prev.text + " " + text).strip()
            prev.tool_calls += calls
            prev.latency_ms = prev.latency_ms if prev.latency_ms is not None else latency
        else:
            if index == 0:
                index = 1  # the agent greeted first: the greeting belongs to exchange 1
            turns.append(Turn(index, "agent", text, calls, latency))

    meta = {"source": "elevenlabs", "agent_id": data.get("agent_id"), "conversation_id": data.get("conversation_id")}
    return Conversation(scenario_id=scenario_id, turns=turns, end_reason="imported", meta=meta)
