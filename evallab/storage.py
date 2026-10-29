"""
SQLite storage for runs, conversations, check results, judge scores and lead data.

The schema is normalised (one row per turn, tool call, check, judge criterion), so every analysis in
analytics.py is a plain SQL query and new questions don't need code changes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .runner import ScenarioResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK (mode IN ('demo', 'live', 'import')),
    agent_name    TEXT,
    agent_version TEXT,
    model         TEXT,
    simulator     TEXT,
    judge         TEXT,
    judge_trials  INTEGER,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    usage_json    TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    scenario_id        TEXT NOT NULL,
    title              TEXT,
    category           TEXT,
    channel            TEXT,
    passed             INTEGER NOT NULL,
    checks_passed      INTEGER NOT NULL,
    judge_passed       INTEGER NOT NULL,
    judge_disagreement INTEGER NOT NULL DEFAULT 0,
    turns              INTEGER,
    max_turns          INTEGER,
    end_reason         TEXT,
    error              TEXT,
    scenario_json      TEXT,
    UNIQUE (run_id, scenario_id)
);

CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id   INTEGER NOT NULL REFERENCES scenario_results(id) ON DELETE CASCADE,
    turn_index  INTEGER NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('user', 'agent')),
    text        TEXT,
    latency_ms  REAL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id      INTEGER NOT NULL REFERENCES scenario_results(id) ON DELETE CASCADE,
    turn_index     INTEGER NOT NULL,
    name           TEXT NOT NULL,
    arguments_json TEXT,
    result_json    TEXT,
    is_error       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS check_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id   INTEGER NOT NULL REFERENCES scenario_results(id) ON DELETE CASCADE,
    check_type  TEXT NOT NULL,
    name        TEXT NOT NULL,
    passed      INTEGER NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT,
    turn_index  INTEGER
);

CREATE TABLE IF NOT EXISTS judge_trials (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id  INTEGER NOT NULL REFERENCES scenario_results(id) ON DELETE CASCADE,
    trial      INTEGER NOT NULL,
    judge      TEXT,
    verdict    INTEGER NOT NULL,
    summary    TEXT,
    UNIQUE (result_id, trial)
);

CREATE TABLE IF NOT EXISTS judge_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id       INTEGER NOT NULL REFERENCES scenario_results(id) ON DELETE CASCADE,
    trial           INTEGER NOT NULL,
    criterion       TEXT NOT NULL,
    score           INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    passed          INTEGER NOT NULL,
    rationale       TEXT,
    evidence_json   TEXT,
    grounded_quotes INTEGER NOT NULL DEFAULT 0,
    total_quotes    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leads (
    result_id          INTEGER PRIMARY KEY REFERENCES scenario_results(id) ON DELETE CASCADE,
    primary_intent     TEXT,
    product_interest   TEXT,
    purchase_intent    TEXT,
    upsell_opportunity TEXT,
    churn_risk         TEXT,
    sentiment          TEXT,
    contact_captured   INTEGER,
    summary            TEXT,
    extractor          TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_run ON scenario_results(run_id);
CREATE INDEX IF NOT EXISTS idx_turns_result ON turns(result_id);
CREATE INDEX IF NOT EXISTS idx_checks_result ON check_results(result_id);
CREATE INDEX IF NOT EXISTS idx_judge_result ON judge_scores(result_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "run"


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- writing ----------

    def create_run(self, label: str, mode: str, agent: dict, simulator: str, judge: str, judge_trials: int,
                   run_id: str | None = None, notes: str = "") -> str:
        started = _now()
        run_id = run_id or f"{started[:19].replace('-', '').replace(':', '').replace('T', '-')}-{_slug(label)}"
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, label, mode, agent_name, agent_version, model, simulator, judge, judge_trials,"
                " started_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, label, mode, agent.get("name"), agent.get("version"), agent.get("model"), simulator, judge,
                 judge_trials, started, notes),
            )
        return run_id

    def finish_run(self, run_id: str, usage: dict | None = None) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE runs SET finished_at = ?, usage_json = ? WHERE id = ?",
                         (_now(), json.dumps(usage or {}), run_id))

    def save_result(self, run_id: str, result: ScenarioResult) -> int:
        s, conv = result.scenario, result.conversation
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO scenario_results (run_id, scenario_id, title, category, channel, passed, checks_passed,"
                " judge_passed, judge_disagreement, turns, max_turns, end_reason, error, scenario_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, s.id, s.title, s.category, s.channel, int(result.passed), int(result.checks_passed),
                 int(result.judge_passed), int(result.judge_disagreement), conv.exchange_count, s.max_turns,
                 conv.end_reason, result.error, json.dumps(s.to_dict(), ensure_ascii=False)),
            )
            rid = cur.lastrowid
            for turn in conv.turns:
                conn.execute("INSERT INTO turns (result_id, turn_index, role, text, latency_ms) VALUES (?, ?, ?, ?, ?)",
                             (rid, turn.index, turn.role, turn.text, turn.latency_ms))
                for call in turn.tool_calls:
                    conn.execute(
                        "INSERT INTO tool_calls (result_id, turn_index, name, arguments_json, result_json, is_error)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (rid, turn.index, call.name, json.dumps(call.arguments, ensure_ascii=False),
                         json.dumps(call.result, ensure_ascii=False, default=str), int(call.is_error)),
                    )
            for c in result.checks:
                conn.execute(
                    "INSERT INTO check_results (result_id, check_type, name, passed, severity, message, turn_index)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (rid, c.check, c.name, int(c.passed), c.severity, c.message, c.turn),
                )
            for j in result.judge_trials:
                conn.execute("INSERT INTO judge_trials (result_id, trial, judge, verdict, summary) VALUES (?, ?, ?, ?, ?)",
                             (rid, j.trial, j.judge, int(j.verdict), j.summary))
                for criterion, sc in j.scores.items():
                    evidence = [{"turn": e.turn, "quote": e.quote, "grounded": e.grounded} for e in sc.evidence]
                    conn.execute(
                        "INSERT INTO judge_scores (result_id, trial, criterion, score, passed, rationale, evidence_json,"
                        " grounded_quotes, total_quotes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (rid, j.trial, criterion, sc.score, int(j.criterion_passed(criterion)), sc.rationale,
                         json.dumps(evidence, ensure_ascii=False), sum(e["grounded"] for e in evidence), len(evidence)),
                    )
            if result.lead:
                L = result.lead
                conn.execute(
                    "INSERT INTO leads (result_id, primary_intent, product_interest, purchase_intent, upsell_opportunity,"
                    " churn_risk, sentiment, contact_captured, summary, extractor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rid, L.primary_intent, L.product_interest, L.purchase_intent, L.upsell_opportunity, L.churn_risk,
                     L.sentiment, int(L.contact_captured), L.summary, L.extractor),
                )
        return rid

    def delete_run(self, run_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("DELETE FROM runs WHERE id = ?", (run_id,)).rowcount > 0

    # ---------- reading ----------

    def run_exists(self, run_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is not None

    def get_result_detail(self, result_id: int) -> dict | None:
        """Everything the transcript viewer needs for one scenario result."""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scenario_results WHERE id = ?", (result_id,)).fetchone()
            if row is None:
                return None
            detail = dict(row)
            detail["scenario"] = json.loads(detail.pop("scenario_json") or "{}")
            detail["run"] = dict(conn.execute("SELECT id, label, mode, agent_version FROM runs WHERE id = ?",
                                              (row["run_id"],)).fetchone())
            tools = {}
            for t in conn.execute("SELECT * FROM tool_calls WHERE result_id = ? ORDER BY id", (result_id,)):
                tools.setdefault(t["turn_index"], []).append({
                    "name": t["name"], "arguments": json.loads(t["arguments_json"] or "{}"),
                    "result": json.loads(t["result_json"] or "null"), "is_error": bool(t["is_error"]),
                })
            detail["turns"] = []
            for t in conn.execute("SELECT * FROM turns WHERE result_id = ? ORDER BY id", (result_id,)):
                item = {"index": t["turn_index"], "role": t["role"], "text": t["text"], "latency_ms": t["latency_ms"]}
                if t["role"] == "agent":
                    item["tool_calls"] = tools.get(t["turn_index"], [])
                detail["turns"].append(item)
            detail["checks"] = [dict(c) for c in conn.execute(
                "SELECT check_type, name, passed, severity, message, turn_index FROM check_results"
                " WHERE result_id = ? ORDER BY passed, id", (result_id,))]
            trials = {t["trial"]: {**dict(t), "scores": {}} for t in conn.execute(
                "SELECT trial, judge, verdict, summary FROM judge_trials WHERE result_id = ? ORDER BY trial", (result_id,))}
            for s in conn.execute("SELECT * FROM judge_scores WHERE result_id = ? ORDER BY id", (result_id,)):
                trials[s["trial"]]["scores"][s["criterion"]] = {
                    "score": s["score"], "passed": bool(s["passed"]), "rationale": s["rationale"],
                    "evidence": json.loads(s["evidence_json"] or "[]"),
                }
            detail["judge_trials"] = list(trials.values())
            lead = conn.execute("SELECT * FROM leads WHERE result_id = ?", (result_id,)).fetchone()
            detail["lead"] = dict(lead) if lead else None
        return detail
