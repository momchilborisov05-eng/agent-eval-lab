"""LLM judge schema handling, evidence grounding, verdict thresholds and agreement metrics."""

import unittest

from helpers import FakeClaude, conversation, scenario, text_response

from evallab import agreement
from evallab.judge import JUDGE_SCHEMA, JudgeError, LLMJudge, ground_evidence, parse_judge_payload


def payload(task=5, policy=5, tone=4, grounded=5, quote="It arrives on Saturday, October 31."):
    def crit(score):
        return {"score": score, "rationale": "because", "evidence": [{"turn": 1, "quote": quote}]}
    return {"task_success": crit(task), "policy_compliance": crit(policy), "tone": crit(tone),
            "groundedness": crit(grounded), "summary": "fine"}


CONV = conversation([("Where is my order?", "It arrives on Saturday, October 31. Anything else?", [], 900)])


class JudgeSchemaTests(unittest.TestCase):
    def test_schema_is_strict(self):
        self.assertFalse(JUDGE_SCHEMA["additionalProperties"])
        self.assertEqual(set(JUDGE_SCHEMA["required"]), {"task_success", "policy_compliance", "tone", "groundedness", "summary"})
        self.assertEqual(JUDGE_SCHEMA["properties"]["tone"]["properties"]["score"]["enum"], [1, 2, 3, 4, 5])

    def test_parse_valid_payload(self):
        result = parse_judge_payload(payload(), trial=2)
        self.assertEqual(result.trial, 2)
        self.assertEqual(result.scores["tone"].score, 4)
        self.assertTrue(result.verdict)

    def test_verdict_uses_thresholds_not_model_opinion(self):
        self.assertFalse(parse_judge_payload(payload(policy=3), 1).verdict)  # policy needs >= 4
        self.assertTrue(parse_judge_payload(payload(tone=3), 1).verdict)     # tone needs >= 3
        self.assertEqual(parse_judge_payload(payload(task=2, grounded=1), 1).failed_criteria, ["task_success", "groundedness"])

    def test_rejects_malformed_payloads(self):
        bad = payload()
        del bad["tone"]
        with self.assertRaisesRegex(JudgeError, "missing criteria: tone"):
            parse_judge_payload(bad, 1)
        for score in (0, 6, "5", True, None):
            with self.assertRaisesRegex(JudgeError, "score must be an integer"):
                parse_judge_payload(payload(task=score), 1)
        with self.assertRaises(JudgeError):
            parse_judge_payload(["not", "an", "object"], 1)

    def test_evidence_grounding(self):
        result = ground_evidence(parse_judge_payload(payload(), 1), CONV)
        self.assertEqual(result.evidence_stats(), (4, 4))
        invented = ground_evidence(parse_judge_payload(payload(quote="Your refund is approved."), 1), CONV)
        self.assertEqual(invented.evidence_stats(), (0, 4))
        elided = ground_evidence(parse_judge_payload(payload(quote="It arrives ... October 31"), 1), CONV)
        self.assertEqual(elided.evidence_stats()[0], 4)  # quotes may skip text with an ellipsis

    def test_llm_judge_request_and_result(self):
        client = FakeClaude([text_response(payload(quote="Saturday, October 31"))])
        s = scenario(success_criteria=["Gives the date."],
                     forbidden_behaviours=[{"id": "x", "description": "Promises a refund"}])
        result = LLMJudge(client).evaluate(s, CONV, trial=1)
        self.assertTrue(result.verdict)
        req = client.requests[0]
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["output_config"]["format"]["schema"], JUDGE_SCHEMA)
        self.assertIn("server-side-fallback-2026-07-01", req.get("betas", []))
        prompt = req["messages"][0]["content"]
        self.assertIn("Gives the date.", prompt)
        self.assertIn("Promises a refund", prompt)
        self.assertIn("[turn 1] AGENT:", prompt)

    def test_refusal_raises_clear_error(self):
        from evallab.llm import LLMError
        client = FakeClaude([text_response("{}", stop_reason="refusal")])
        with self.assertRaisesRegex(LLMError, "declined"):
            LLMJudge(client).evaluate(scenario(), CONV)


class AgreementTests(unittest.TestCase):
    def test_exact_and_within_one(self):
        self.assertEqual(agreement.exact_agreement([5, 4, 3, 2], [5, 4, 2, 2]), 0.75)
        self.assertEqual(agreement.within_one_agreement([5, 4, 3, 1], [5, 3, 2, 4]), 0.75)
        self.assertIsNone(agreement.exact_agreement([], []))
        with self.assertRaises(ValueError):
            agreement.exact_agreement([1], [1, 2])

    def test_cohen_kappa_known_values(self):
        self.assertEqual(agreement.cohen_kappa([True, False, True, False], [True, False, True, False]), 1.0)
        # observed 0.5, expected 0.5 -> kappa 0
        self.assertAlmostEqual(agreement.cohen_kappa([True, True, False, False], [True, False, True, False]), 0.0)
        # textbook example: 20/50 yes-yes, 15/50 no-no, 5 + 10 disagreements -> kappa 0.4
        a = [True] * 25 + [False] * 25
        b = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
        self.assertAlmostEqual(agreement.cohen_kappa(a, b), 0.4, places=6)
        self.assertEqual(agreement.cohen_kappa([True, True], [True, True]), 1.0)  # degenerate: one label only
        self.assertIsNone(agreement.cohen_kappa([], []))

    def test_summarize_flags_unstable_scenarios(self):
        pairs = {
            "a": (parse_judge_payload(payload(), 1), parse_judge_payload(payload(), 2)),
            "b": (parse_judge_payload(payload(task=4), 1), parse_judge_payload(payload(task=3), 2)),
        }
        report = agreement.summarize(pairs, ["task_success", "tone"])
        self.assertEqual(report.pairs, 2)
        self.assertEqual(report.verdict_agreement, 0.5)
        self.assertEqual(report.exact["task_success"], 0.5)
        self.assertEqual(report.within_one["task_success"], 1.0)
        self.assertEqual(report.unstable_scenarios, ["b"])


if __name__ == "__main__":
    unittest.main()
