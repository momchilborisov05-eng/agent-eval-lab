"""The Claude agent's tool loop (fake client), simulators, the tool backend and the ElevenLabs adapter."""

import json
import unittest

from helpers import ROOT, FakeClaude, conversation, scenario, text_response, tool_use_response

from evallab.adapters.elevenlabs import TranscriptFormatError, parse_elevenlabs_conversation
from evallab.agent.base import ConversationContext
from evallab.agent.claude_agent import ClaudeSupportAgent
from evallab.agent.prompts import CANARY, PROMPT_V1, PROMPT_V2
from evallab.agent.tools import TOOL_DEFINITIONS, SupportBackend
from evallab.demo.agent import normalize_speech, parse_date
from evallab.runner import run_conversation
from evallab.simulator import LLMUserSimulator, ScriptedSimulator


class BackendTests(unittest.TestCase):
    def test_tool_schemas_are_strict(self):
        for tool in TOOL_DEFINITIONS:
            self.assertTrue(tool["strict"], tool["name"])
            self.assertFalse(tool["input_schema"]["additionalProperties"], tool["name"])
            self.assertEqual(set(tool["input_schema"]["required"]), set(tool["input_schema"]["properties"]))

    def test_order_status_reports_verification(self):
        backend = SupportBackend()
        record, err = backend.execute("check_order_status", {"order_id": "au10482", "email": "maria.petrova@example.com"})
        self.assertFalse(err)
        self.assertTrue(record["email_verified"])
        record, _ = backend.execute("check_order_status", {"order_id": "AU-10482", "email": "someone@else.com"})
        self.assertFalse(record["email_verified"])
        _, err = backend.execute("check_order_status", {"order_id": "AU-99999", "email": None})
        self.assertTrue(err)

    def test_booking_rules(self):
        backend = SupportBackend()
        full, err = backend.execute("book_appointment", {"order_id": "AU-10388", "email": "p.ivanov@example.com",
                                                          "date": "2026-11-04", "time_window": "morning", "issue": "x"})
        self.assertTrue(err)
        self.assertEqual(full["error"], "slot_unavailable")
        self.assertEqual(full["available_slots"][0]["date"], "2026-11-05")  # nearest free day first
        ok, err = backend.execute("book_appointment", {"order_id": "AU-10388", "email": "p.ivanov@example.com",
                                                        "date": "2026-11-05", "time_window": "afternoon", "issue": "x"})
        self.assertFalse(err)
        self.assertTrue(ok["confirmation"].startswith("APT-"))
        again, err = backend.execute("book_appointment", {"order_id": "AU-10388", "email": "p.ivanov@example.com",
                                                           "date": "2026-11-05", "time_window": "afternoon", "issue": "x"})
        self.assertTrue(err)  # the slot is taken now

    def test_returns_window_and_unknown_tool(self):
        backend = SupportBackend()
        late, err = backend.execute("create_return_request", {"order_id": "AU-10403", "email": "ana.georgieva@example.com", "reason": "x"})
        self.assertEqual(late["error"], "outside_return_window")
        _, err = backend.execute("issue_refund", {})
        self.assertTrue(err)


class ClaudeAgentTests(unittest.TestCase):
    def test_tool_loop_records_calls_and_echoes_full_content(self):
        client = FakeClaude([
            tool_use_response("check_order_status", {"order_id": "AU-10482", "email": "maria.petrova@example.com"}),
            text_response("Your washing machine arrives on Saturday, October 31."),
        ])
        agent = ClaudeSupportAgent(client, prompt_version="v2")
        agent.start(ConversationContext("s1", "voice"))
        turn = agent.respond("Order AU-10482, maria.petrova@example.com")
        self.assertIn("October 31", turn.text)
        self.assertEqual(turn.tool_calls[0].name, "check_order_status")
        self.assertTrue(turn.tool_calls[0].result["email_verified"])
        self.assertIsNotNone(turn.latency_ms)
        first, second = client.requests
        self.assertTrue(first["messages"][0]["content"].startswith("[voice call transcript]"))
        self.assertEqual(first["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(first["tools"], TOOL_DEFINITIONS)
        self.assertEqual(first["output_config"], {"effort": "low"})
        self.assertNotIn("tool_choice", first)  # forced tool choice is not supported on current models
        # The second request carries the assistant's full content and one user message with the tool result.
        self.assertEqual(second["messages"][1]["role"], "assistant")
        result_block = second["messages"][2]["content"][0]
        self.assertEqual(result_block["type"], "tool_result")
        self.assertEqual(result_block["tool_use_id"], "toolu_1")
        self.assertTrue(json.loads(result_block["content"])["email_verified"])

    def test_transfer_ends_conversation(self):
        client = FakeClaude([
            tool_use_response("transfer_to_human", {"reason": "asked", "summary": "s", "priority": "normal"}),
            text_response("Connecting you now."),
        ])
        agent = ClaudeSupportAgent(client)
        agent.start(ConversationContext("s1"))
        turn = agent.respond("A human please")
        self.assertTrue(turn.ended)
        self.assertEqual(turn.end_reason, "transferred")

    def test_refusal_is_reported_not_raised(self):
        agent = ClaudeSupportAgent(FakeClaude([text_response("", stop_reason="refusal")]))
        agent.start(ConversationContext("s1"))
        turn = agent.respond("hi")
        self.assertEqual(turn.error, "The model declined to answer.")

    def test_prompts_contain_canary(self):
        self.assertIn(CANARY, PROMPT_V1)
        self.assertIn(CANARY, PROMPT_V2)


class SimulatorTests(unittest.TestCase):
    def test_scripted_precedence(self):
        s = scenario(script={"turns": ["first"], "fallback": "again?", "done_when": "APT-\\d+",
                             "replies": [{"when": "fully booked", "say": "the 5th then"}]})
        sim = ScriptedSimulator()
        conv = conversation([("Hi", "Which order?", [], 1)])
        self.assertEqual(sim.reply(s, conv).message, "first")
        conv = conversation([("Hi", "a", [], 1), ("first", "Sorry, the 4th is fully booked.", [], 1)])
        self.assertEqual(sim.reply(s, conv).message, "the 5th then")
        conv = conversation([("Hi", "a", [], 1), ("first", "b", [], 1), ("the 5th then", "Confirm?", [], 1)])
        self.assertEqual(sim.reply(s, conv).message, "again?")  # fallback repeats until done_when
        conv = conversation([("Hi", "Booked: APT-4388", [], 1)])
        self.assertTrue(sim.reply(s, conv).end)

    def test_scripted_without_done_when_says_fallback_once(self):
        s = scenario(script={"turns": [], "fallback": "ok bye"})
        sim = ScriptedSimulator()
        self.assertEqual(sim.reply(s, conversation([("Hi", "a", [], 1)])).message, "ok bye")
        self.assertTrue(sim.reply(s, conversation([("Hi", "a", [], 1), ("ok bye", "b", [], 1)])).end)

    def test_llm_simulator(self):
        client = FakeClaude([text_response({"message": "It's AU-10482", "goal_achieved": False, "end_conversation": False}),
                             text_response({"message": "Thanks, bye", "goal_achieved": True, "end_conversation": True})])
        sim = LLMUserSimulator(client)
        s = scenario(channel="voice", known_facts={"order_id": "AU-10482"})
        conv = conversation([("Hi", "Which order?", [], 1)])
        self.assertEqual(sim.reply(s, conv).message, "It's AU-10482")
        system = client.requests[0]["system"]
        self.assertIn("PHONE CALL", system)
        self.assertIn("order_id: AU-10482", system)
        end = sim.reply(s, conv)
        self.assertTrue(end.end)
        self.assertEqual(end.reason, "goal_met")

    def test_run_conversation_stops_at_max_turns(self):
        class Echo:
            name, version, model, canary = "echo", "v0", "", None
            def start(self, ctx): pass
            def respond(self, msg):
                from evallab.agent.base import AgentTurn
                return AgentTurn(text="Could you repeat that?", latency_ms=5)
            def describe(self): return {"name": "echo"}
        s = scenario(max_turns=3, script={"turns": [], "fallback": "again", "done_when": "never-matches"})
        conv = run_conversation(Echo(), ScriptedSimulator(), s)
        self.assertEqual(conv.end_reason, "max_turns")
        self.assertEqual(conv.exchange_count, 3)


class SpeechAndAdapterTests(unittest.TestCase):
    def test_demo_speech_normalization(self):
        text = normalize_speech("um, A U one oh four eight two? and the email is maria dot petrova at example dot com")
        self.assertIn("AU-10482", text)
        self.assertIn("maria.petrova@example.com", text)
        self.assertEqual(normalize_speech("Order AU-10511 and more"), "Order AU-10511 and more")
        self.assertEqual(parse_date("November 3rd in the morning"), "2026-11-03")

    def test_elevenlabs_webhook_parsing(self):
        payload = json.loads((ROOT / "examples" / "elevenlabs_post_call_webhook.json").read_text(encoding="utf-8"))
        conv = parse_elevenlabs_conversation(payload, scenario_id="voice-disfluent-order-id")
        self.assertEqual(conv.meta["conversation_id"], "conv_example_0001")
        calls = conv.tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].arguments["order_id"], "AU-10482")
        self.assertTrue(calls[0][1].result["email_verified"])
        merged = next(t for t in conv.agent_turns() if t.tool_calls)
        self.assertIn("October 31", merged.text)  # tool entry and spoken reply merged into one turn
        self.assertEqual(merged.latency_ms, 2000.0)

    def test_elevenlabs_rejects_other_json(self):
        with self.assertRaises(TranscriptFormatError):
            parse_elevenlabs_conversation({"messages": []})
        with self.assertRaises(TranscriptFormatError):
            parse_elevenlabs_conversation({"transcript": [{"role": "system", "message": "x"}]})


if __name__ == "__main__":
    unittest.main()
