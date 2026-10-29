"""End-to-end demo run into SQLite, then every analytics query and the regression diff."""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import SCENARIOS_DIR

from evallab import analytics
from evallab.demo import run_demo
from evallab.storage import Store

TMP = Path(tempfile.mkdtemp())
DB = TMP / "lab.db"
RUN_IDS = run_demo(DB, SCENARIOS_DIR)
STORE = Store(DB)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class EndToEndDemoTests(unittest.TestCase):
    def test_two_runs_are_stored(self):
        with STORE.connect() as conn:
            runs = analytics.list_runs(conn)
        self.assertEqual([r["id"] for r in runs], ["demo-prompt-v1", "demo-prompt-v2"])
        self.assertTrue(all(r["mode"] == "demo" and r["scenarios"] >= 20 for r in runs))
        self.assertLess(runs[0]["pass_rate"], runs[1]["pass_rate"])

    def test_known_behaviours_are_caught(self):
        """v1 leaks data and the prompt; v2 does not, but over-escalates an ambiguous request."""
        with STORE.connect() as conn:
            rows = conn.execute(
                "SELECT s.run_id, s.scenario_id, c.check_type FROM check_results c "
                "JOIN scenario_results s ON s.id = c.result_id WHERE c.passed = 0").fetchall()
        failed = {(r["run_id"], r["scenario_id"], r["check_type"]) for r in rows}
        self.assertIn(("demo-prompt-v1", "security-other-customer-order", "pii_leak"), failed)
        self.assertIn(("demo-prompt-v1", "security-prompt-injection", "prompt_leak"), failed)
        self.assertIn(("demo-prompt-v1", "returns-eligible", "forbidden_pattern"), failed)
        self.assertNotIn(("demo-prompt-v2", "security-other-customer-order", "pii_leak"), failed)
        self.assertIn(("demo-prompt-v2", "appointments-ambiguous-request", "forbidden_tool"), failed)
        self.assertIn(("demo-prompt-v2", "voice-book-installation", "latency"), failed)

    def test_rerunning_demo_replaces_old_runs(self):
        tmp_db = TMP / "rerun.db"
        run_demo(tmp_db, SCENARIOS_DIR)
        run_demo(tmp_db, SCENARIOS_DIR)
        with Store(tmp_db).connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scenario_results").fetchone()[0],
                             2 * len(list(analytics.query(conn, "scenario_results", run_id="demo-prompt-v1"))))


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.conn_cm = STORE.connect()
        self.conn = self.conn_cm.__enter__()

    def tearDown(self):
        self.conn_cm.__exit__(None, None, None)

    def test_pass_rate_by_category_matches_raw_rows(self):
        cats = analytics.query(self.conn, "pass_rate_by_category", run_id="demo-prompt-v2")
        total = sum(c["scenarios"] for c in cats)
        passed = sum(c["passed"] for c in cats)
        raw = self.conn.execute("SELECT COUNT(*), SUM(passed) FROM scenario_results WHERE run_id = 'demo-prompt-v2'").fetchone()
        self.assertEqual((total, passed), (raw[0], raw[1]))

    def test_failure_reasons_and_latency(self):
        summary = analytics.run_summary(self.conn, "demo-prompt-v1")
        reasons = {f["reason"]: f for f in summary["failure_reasons"]}
        self.assertEqual(reasons["pii_leak:other_customer_data"]["severity"], "critical")
        self.assertGreaterEqual(reasons["pii_leak:other_customer_data"]["scenarios"], 3)
        for row in summary["latency"]:
            self.assertLessEqual(row["p50_ms"], row["p95_ms"])
            self.assertLessEqual(row["p95_ms"], row["max_ms"])
        self.assertEqual({r["channel"] for r in summary["latency"]}, {"chat", "voice"})

    def test_percentile_sql_on_known_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "p.db")
            with store.connect() as conn:
                conn.execute("INSERT INTO runs (id, label, mode, started_at) VALUES ('r', 'r', 'live', 'now')")
                conn.execute("INSERT INTO scenario_results (run_id, scenario_id, channel, passed, checks_passed, judge_passed)"
                             " VALUES ('r', 's', 'chat', 1, 1, 1)")
                for i in range(1, 21):  # latencies 100..2000
                    conn.execute("INSERT INTO turns (result_id, turn_index, role, text, latency_ms) VALUES (1, ?, 'agent', '', ?)",
                                 (i, i * 100.0))
                [row] = analytics.query(conn, "latency", run_id="r")
        self.assertEqual((row["p50_ms"], row["p95_ms"], row["max_ms"]), (1000.0, 1900.0, 2000.0))

    def test_judge_agreement_sql_matches_python(self):
        summary = analytics.run_summary(self.conn, "demo-prompt-v2")
        ag = summary["judge_agreement"]
        self.assertEqual(ag["pairs"], summary["run"]["scenarios"])
        rows = self.conn.execute(
            "SELECT a.score AS s1, b.score AS s2 FROM judge_scores a JOIN judge_scores b ON a.result_id = b.result_id "
            "AND a.criterion = b.criterion AND a.trial = 1 AND b.trial = 2 JOIN scenario_results s ON s.id = a.result_id "
            "WHERE s.run_id = 'demo-prompt-v2' AND a.criterion = 'tone'").fetchall()
        expected = sum(r["s1"] == r["s2"] for r in rows) / len(rows)
        tone = next(c for c in ag["criteria"] if c["criterion"] == "tone")
        self.assertAlmostEqual(tone["exact_agreement"], round(expected, 3))
        self.assertTrue(0 <= ag["quote_grounding"] <= 1)
        self.assertEqual(len(ag["unstable"]), summary["run"]["judge_disagreements"])

    def test_regression_diff(self):
        report = analytics.compare_runs(self.conn, "demo-prompt-v1", "demo-prompt-v2")
        groups = report["groups"]
        self.assertIn("appointments-ambiguous-request", groups["newly_failing"])
        self.assertIn("security-other-customer-order", groups["newly_passing"])
        self.assertIn("voice-spelled-email", groups["still_failing"])
        n = report["common_scenarios"]
        self.assertEqual(sum(len(v) for v in groups.values()), n)
        expected_delta = 100.0 * (len(groups["newly_passing"]) - len(groups["newly_failing"])) / n
        self.assertAlmostEqual(report["pass_rate_delta"], round(expected_delta, 1), places=1)
        policy = next(c for c in report["criteria"] if c["criterion"] == "policy_compliance")
        self.assertGreater(policy["delta"], 0)
        self.assertIsNotNone(report["mcnemar_p"])
        with self.assertRaises(KeyError):
            analytics.compare_runs(self.conn, "demo-prompt-v1", "nope")

    def test_mcnemar(self):
        self.assertIsNone(analytics.mcnemar_exact_p(0, 0))
        self.assertEqual(analytics.mcnemar_exact_p(3, 3), 1.0)
        self.assertAlmostEqual(analytics.mcnemar_exact_p(0, 6), 2 / 64)

    def test_gtm_summary(self):
        gtm = analytics.gtm_summary(self.conn, "demo-prompt-v2")
        intents = {i["primary_intent"]: i for i in gtm["intents"]}
        self.assertEqual(sum(i["conversations"] for i in gtm["intents"]), 22)
        self.assertEqual(intents["purchase_inquiry"]["buying_signals"], 1)
        hot = gtm["leads"][0]
        self.assertEqual((hot["scenario_id"], hot["purchase_intent"]), ("sales-purchase-inquiry", "high"))

    def test_result_detail_and_cascade_delete(self):
        rid = self.conn.execute("SELECT id FROM scenario_results WHERE run_id = 'demo-prompt-v1' "
                                "AND scenario_id = 'security-other-customer-order'").fetchone()[0]
        detail = STORE.get_result_detail(rid)
        self.assertEqual(detail["scenario"]["id"], "security-other-customer-order")
        self.assertEqual(len(detail["judge_trials"]), 2)
        self.assertTrue(any(c["check_type"] == "pii_leak" and not c["passed"] for c in detail["checks"]))
        self.assertTrue(detail["turns"][1]["tool_calls"])
        self.assertIsNone(STORE.get_result_detail(999999))

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "c.db"
            run_demo(db, SCENARIOS_DIR)
            store = Store(db)
            self.assertTrue(store.delete_run("demo-prompt-v1"))
            with store.connect() as conn:
                orphans = conn.execute("SELECT COUNT(*) FROM turns t LEFT JOIN scenario_results s ON s.id = t.result_id "
                                       "WHERE s.id IS NULL").fetchone()[0]
            self.assertEqual(orphans, 0)


if __name__ == "__main__":
    unittest.main()
