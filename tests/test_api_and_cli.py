"""Dashboard API endpoints (FastAPI TestClient) and the CLI."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import ROOT, SCENARIOS_DIR

from evallab.cli import main
from evallab.demo import run_demo
from evallab.web.app import create_app

TMP = Path(tempfile.mkdtemp())
DB = TMP / "api.db"
run_demo(DB, SCENARIOS_DIR)
client = TestClient(create_app(DB))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def cli(*args, db=DB):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--db", str(db), "--scenarios", str(SCENARIOS_DIR), *args])
    return code, out.getvalue(), err.getvalue()


class ApiTests(unittest.TestCase):
    def test_runs(self):
        res = client.get("/api/runs")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["id"] for r in res.json()], ["demo-prompt-v1", "demo-prompt-v2"])

    def test_run_summary(self):
        data = client.get("/api/runs/demo-prompt-v2").json()
        for key in ("run", "categories", "failure_reasons", "latency", "judge_criteria", "judge_agreement", "scenarios"):
            self.assertIn(key, data)
        self.assertEqual(client.get("/api/runs/missing").status_code, 404)

    def test_result_detail(self):
        rid = client.get("/api/runs/demo-prompt-v1").json()["scenarios"][0]["result_id"]
        detail = client.get(f"/api/results/{rid}").json()
        self.assertIn("turns", detail)
        self.assertIn("checks", detail)
        self.assertEqual(client.get("/api/results/999999").status_code, 404)
        self.assertEqual(client.get("/api/results/abc").status_code, 422)

    def test_compare(self):
        data = client.get("/api/compare", params={"a": "demo-prompt-v1", "b": "demo-prompt-v2"}).json()
        self.assertGreater(data["pass_rate_delta"], 0)
        self.assertIn("newly_failing", data["groups"])
        self.assertEqual(client.get("/api/compare", params={"a": "demo-prompt-v1", "b": "x"}).status_code, 404)
        self.assertEqual(client.get("/api/compare").status_code, 422)

    def test_gtm_and_sql(self):
        self.assertTrue(client.get("/api/runs/demo-prompt-v2/gtm").json()["intents"])
        self.assertEqual(client.get("/api/runs/missing/gtm").status_code, 404)
        sql = client.get("/api/sql").json()
        self.assertIn("WITH failures AS", sql["top_failure_reasons"])

    def test_frontend_is_served(self):
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Agent Eval Lab", page.text)
        self.assertEqual(client.get("/static/app.js").status_code, 200)


class CliTests(unittest.TestCase):
    def test_validate(self):
        code, out, _ = cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("valid scenarios", out)

    def test_runs_report_compare(self):
        self.assertIn("demo-prompt-v2", cli("runs")[1])
        code, out, _ = cli("report", "demo-prompt-v1")
        self.assertEqual(code, 0)
        self.assertIn("Top failure reasons", out)
        code, out, _ = cli("compare", "demo-prompt-v1", "demo-prompt-v2")
        self.assertIn("Newly failing", out)
        self.assertEqual(cli("compare", "demo-prompt-v1", "nope")[0], 1)

    def test_live_run_without_key_explains_how_to_fix(self):
        import os
        saved = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        try:
            code, _, err = cli("run", "--scenario", "faq-warranty", db=TMP / "nokey.db")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        self.assertEqual(code, 2)
        self.assertIn("ANTHROPIC_API_KEY", err)
        self.assertIn("python -m evallab demo", err)

    def test_offline_run_and_transcript_import(self):
        db = TMP / "cli.db"  # a separate database, so the API tests above see exactly the two demo runs
        code, out, _ = cli("run", "--agent", "demo", "--simulator", "scripted", "--judge", "demo", "--gtm", "rules",
                           "--category", "faq", "--label", "offline faq", db=db)
        self.assertEqual(code, 0)
        self.assertIn("2/2 passed", out)
        code, out, _ = cli("score-transcript", str(ROOT / "examples" / "elevenlabs_post_call_webhook.json"),
                           "--scenario", "voice-disfluent-order-id", db=db)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("PASS"))


if __name__ == "__main__":
    unittest.main()
