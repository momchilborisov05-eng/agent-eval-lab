"""Scenario loading and validation."""

import tempfile
import unittest
from pathlib import Path

from helpers import SCENARIOS_DIR, scenario

from evallab.scenarios import CATEGORIES, ScenarioError, load_scenarios


class LoadSuiteTests(unittest.TestCase):
    def test_bundled_suite_loads_and_is_valid(self):
        scenarios = load_scenarios(SCENARIOS_DIR)
        self.assertGreaterEqual(len(scenarios), 20)
        self.assertEqual(len({s.id for s in scenarios}), len(scenarios))
        self.assertTrue(all(s.category in CATEGORIES for s in scenarios))
        self.assertTrue(any(s.channel == "voice" for s in scenarios))
        self.assertGreaterEqual(sum("adversarial" in s.tags for s in scenarios), 3)

    def test_filters_by_category_and_id(self):
        security = load_scenarios(SCENARIOS_DIR, category="security")
        self.assertTrue(security and all(s.category == "security" for s in security))
        one = load_scenarios(SCENARIOS_DIR, ids=["faq-warranty"])
        self.assertEqual([s.id for s in one], ["faq-warranty"])
        with self.assertRaisesRegex(ScenarioError, "Unknown scenario id"):
            load_scenarios(SCENARIOS_DIR, ids=["does-not-exist"])

    def test_defaults_and_parsing(self):
        s = scenario(channel="voice", expected_tool_calls=["lookup_faq"],
                     script={"turns": ["a"], "fallback": "b", "done_when": "APT-\\d+",
                             "replies": [{"when": "full", "say": "c"}]})
        self.assertEqual(s.max_latency_ms, 2500)  # voice default
        self.assertEqual(s.expected_tool_calls[0].name, "lookup_faq")
        self.assertEqual(s.script.replies[0]["say"], "c")


class ValidationTests(unittest.TestCase):
    def assertInvalid(self, message, **overrides):
        with self.assertRaisesRegex(ScenarioError, message):
            scenario(**overrides)

    def test_unknown_tool(self):
        self.assertInvalid(r"expected_tool_calls\[0\]\.name: unknown tool 'check_order'",
                           expected_tool_calls=[{"name": "check_order"}])

    def test_bad_regex(self):
        self.assertInvalid("invalid regex", must_say=[{"id": "x", "description": "d", "pattern": "("}])

    def test_bad_category_and_channel(self):
        self.assertInvalid("category", category="billing")
        self.assertInvalid("channel", channel="sms")

    def test_bad_matcher(self):
        self.assertInvalid(r"matcher must be one of",
                           expected_tool_calls=[{"name": "lookup_faq", "args": {"query": {"$like": "x"}}}])

    def test_missing_fields(self):
        self.assertInvalid("opening_message", opening_message="")
        self.assertInvalid("success criterion", success_criteria=[])
        self.assertInvalid("max_turns", max_turns=0)
        self.assertInvalid("unknown customer", customer_id="C999")

    def test_duplicate_ids_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = ("- id: same\n  title: t\n  category: faq\n  persona: p\n  goal: g\n  opening_message: hi\n"
                    "  success_criteria: [ok]\n")
            Path(tmp, "a.yaml").write_text(body, encoding="utf-8")
            Path(tmp, "b.yaml").write_text(body, encoding="utf-8")
            with self.assertRaisesRegex(ScenarioError, "duplicate scenario id 'same'"):
                load_scenarios(Path(tmp))

    def test_unparseable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.yaml").write_text("- id: [unclosed", encoding="utf-8")
            with self.assertRaisesRegex(ScenarioError, "bad.yaml: could not parse"):
                load_scenarios(Path(tmp))


if __name__ == "__main__":
    unittest.main()
