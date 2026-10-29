"""
Analytics in plain SQL: pass rates, failure analysis, latency percentiles, judge agreement,
run-vs-run regression and GTM summaries.

Every query lives in QUERIES so the dashboard can show the SQL behind each card. Only the few
statistics SQLite can't express nicely (Cohen's kappa, McNemar's exact test) are computed in Python
from SQL results.
"""

from __future__ import annotations

import json
from math import comb

from .agreement import cohen_kappa

QUERIES: dict[str, str] = {
    "runs": """
SELECT r.id, r.label, r.mode, r.agent_name, r.agent_version, r.model, r.simulator, r.judge,
       r.judge_trials, r.started_at, r.usage_json,
       COUNT(s.id)                          AS scenarios,
       COALESCE(SUM(s.passed), 0)           AS passed,
       ROUND(100.0 * AVG(s.passed), 1)      AS pass_rate,
       COALESCE(SUM(s.judge_disagreement), 0) AS judge_disagreements
FROM runs r
LEFT JOIN scenario_results s ON s.run_id = r.id
GROUP BY r.id
ORDER BY r.started_at, r.id""",

    "pass_rate_by_category": """
SELECT category,
       COUNT(*)                         AS scenarios,
       SUM(passed)                      AS passed,
       ROUND(100.0 * AVG(passed), 1)    AS pass_rate,
       ROUND(100.0 * AVG(checks_passed), 1) AS checks_pass_rate,
       ROUND(100.0 * AVG(judge_passed), 1)  AS judge_pass_rate
FROM scenario_results
WHERE run_id = :run_id
GROUP BY category
ORDER BY pass_rate, category""",

    "top_failure_reasons": """
WITH failures AS (
    SELECT s.scenario_id,
           c.check_type || ':' || c.name AS reason,
           CASE c.severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 ELSE 3 END AS severity_rank
    FROM check_results c
    JOIN scenario_results s ON s.id = c.result_id
    WHERE s.run_id = :run_id AND c.passed = 0
    UNION
    SELECT s.scenario_id, 'judge:' || j.criterion, 2
    FROM judge_scores j
    JOIN scenario_results s ON s.id = j.result_id
    WHERE s.run_id = :run_id AND j.passed = 0
)
SELECT reason,
       COUNT(DISTINCT scenario_id) AS scenarios,
       CASE MIN(severity_rank) WHEN 1 THEN 'critical' WHEN 2 THEN 'major' ELSE 'minor' END AS severity,
       GROUP_CONCAT(DISTINCT scenario_id) AS scenario_ids
FROM failures
GROUP BY reason
ORDER BY scenarios DESC, MIN(severity_rank), reason
LIMIT 12""",

    "latency": """
WITH lat AS (
    SELECT s.channel, t.latency_ms,
           ROW_NUMBER() OVER (PARTITION BY s.channel ORDER BY t.latency_ms) AS rn,
           COUNT(*)     OVER (PARTITION BY s.channel)                       AS n
    FROM turns t
    JOIN scenario_results s ON s.id = t.result_id
    WHERE s.run_id = :run_id AND t.role = 'agent' AND t.latency_ms IS NOT NULL
)
SELECT channel,
       MAX(n)                                           AS agent_turns,
       ROUND(AVG(latency_ms))                           AS avg_ms,
       MIN(CASE WHEN rn >= 0.50 * n THEN latency_ms END) AS p50_ms,
       MIN(CASE WHEN rn >= 0.95 * n THEN latency_ms END) AS p95_ms,
       MAX(latency_ms)                                  AS max_ms
FROM lat
GROUP BY channel
ORDER BY channel""",

    "judge_criteria": """
SELECT j.criterion,
       ROUND(AVG(j.score), 2)            AS avg_score,
       ROUND(100.0 * AVG(j.passed), 1)   AS pass_rate,
       SUM(j.grounded_quotes)            AS grounded_quotes,
       SUM(j.total_quotes)               AS total_quotes
FROM judge_scores j
JOIN scenario_results s ON s.id = j.result_id
WHERE s.run_id = :run_id
GROUP BY j.criterion
ORDER BY j.criterion""",

    "judge_agreement": """
SELECT a.criterion,
       COUNT(*)                                  AS pairs,
       ROUND(AVG(a.score = b.score), 3)          AS exact_agreement,
       ROUND(AVG(ABS(a.score - b.score) <= 1), 3) AS within_one,
       ROUND(AVG(ABS(a.score - b.score)), 2)     AS mean_abs_diff
FROM judge_scores a
JOIN judge_scores b
  ON b.result_id = a.result_id AND b.criterion = a.criterion AND a.trial = 1 AND b.trial = 2
JOIN scenario_results s ON s.id = a.result_id
WHERE s.run_id = :run_id
GROUP BY a.criterion
ORDER BY a.criterion""",

    "verdict_pairs": """
SELECT s.scenario_id, a.verdict AS verdict_1, b.verdict AS verdict_2
FROM judge_trials a
JOIN judge_trials b ON b.result_id = a.result_id AND a.trial = 1 AND b.trial = 2
JOIN scenario_results s ON s.id = a.result_id
WHERE s.run_id = :run_id
ORDER BY s.scenario_id""",

    "scenario_results": """
SELECT s.id AS result_id, s.scenario_id, s.title, s.category, s.channel, s.passed, s.checks_passed,
       s.judge_passed, s.judge_disagreement, s.turns, s.max_turns, s.end_reason, s.error,
       (SELECT GROUP_CONCAT(c.check_type || ':' || c.name, ', ')
          FROM check_results c WHERE c.result_id = s.id AND c.passed = 0) AS failed_checks,
       (SELECT GROUP_CONCAT(DISTINCT j.criterion)
          FROM judge_scores j WHERE j.result_id = s.id AND j.passed = 0) AS failed_criteria,
       (SELECT ROUND(MAX(t.latency_ms)) FROM turns t WHERE t.result_id = s.id AND t.role = 'agent') AS max_latency_ms
FROM scenario_results s
WHERE s.run_id = :run_id
ORDER BY s.passed, s.category, s.scenario_id""",

    "regression_scenarios": """
SELECT a.scenario_id, a.title, a.category,
       a.passed AS passed_a, b.passed AS passed_b,
       a.id AS result_a, b.id AS result_b,
       CASE
           WHEN a.passed = 1 AND b.passed = 0 THEN 'newly_failing'
           WHEN a.passed = 0 AND b.passed = 1 THEN 'newly_passing'
           WHEN a.passed = 1 AND b.passed = 1 THEN 'still_passing'
           ELSE 'still_failing'
       END AS change,
       (SELECT GROUP_CONCAT(c.check_type || ':' || c.name, ', ')
          FROM check_results c WHERE c.result_id = b.id AND c.passed = 0) AS failed_checks_b,
       (SELECT GROUP_CONCAT(DISTINCT j.criterion)
          FROM judge_scores j WHERE j.result_id = b.id AND j.passed = 0) AS failed_criteria_b
FROM scenario_results a
JOIN scenario_results b ON b.scenario_id = a.scenario_id
WHERE a.run_id = :run_a AND b.run_id = :run_b
ORDER BY CASE change WHEN 'newly_failing' THEN 1 WHEN 'newly_passing' THEN 2
                     WHEN 'still_failing' THEN 3 ELSE 4 END, a.scenario_id""",

    "regression_criteria": """
WITH per_run AS (
    SELECT s.run_id, j.criterion, AVG(j.score) AS avg_score, AVG(j.passed) AS pass_rate
    FROM judge_scores j
    JOIN scenario_results s ON s.id = j.result_id
    WHERE s.run_id IN (:run_a, :run_b)
    GROUP BY s.run_id, j.criterion
)
SELECT criterion,
       ROUND(MAX(CASE WHEN run_id = :run_a THEN avg_score END), 2) AS avg_a,
       ROUND(MAX(CASE WHEN run_id = :run_b THEN avg_score END), 2) AS avg_b,
       ROUND(MAX(CASE WHEN run_id = :run_b THEN avg_score END)
           - MAX(CASE WHEN run_id = :run_a THEN avg_score END), 2) AS delta,
       ROUND(100.0 * MAX(CASE WHEN run_id = :run_a THEN pass_rate END), 1) AS pass_rate_a,
       ROUND(100.0 * MAX(CASE WHEN run_id = :run_b THEN pass_rate END), 1) AS pass_rate_b
FROM per_run
GROUP BY criterion
ORDER BY criterion""",

    "regression_checks": """
SELECT c.check_type,
       SUM(CASE WHEN s.run_id = :run_a AND c.passed = 0 THEN 1 ELSE 0 END) AS failures_a,
       SUM(CASE WHEN s.run_id = :run_b AND c.passed = 0 THEN 1 ELSE 0 END) AS failures_b
FROM check_results c
JOIN scenario_results s ON s.id = c.result_id
WHERE s.run_id IN (:run_a, :run_b)
GROUP BY c.check_type
HAVING failures_a + failures_b > 0
ORDER BY failures_b - failures_a DESC, c.check_type""",

    "regression_categories": """
SELECT category,
       ROUND(100.0 * AVG(CASE WHEN run_id = :run_a THEN passed END), 1) AS pass_rate_a,
       ROUND(100.0 * AVG(CASE WHEN run_id = :run_b THEN passed END), 1) AS pass_rate_b
FROM scenario_results
WHERE run_id IN (:run_a, :run_b)
GROUP BY category
ORDER BY category""",

    "gtm_intents": """
SELECT l.primary_intent,
       COUNT(*)                                                    AS conversations,
       SUM(l.purchase_intent IN ('medium', 'high'))                AS buying_signals,
       SUM(l.contact_captured)                                     AS contacts_captured,
       SUM(l.upsell_opportunity IS NOT NULL)                       AS upsell_opportunities,
       SUM(l.churn_risk = 'high')                                  AS high_churn_risk,
       ROUND(100.0 * AVG(l.sentiment = 'negative'), 1)             AS negative_pct
FROM leads l
JOIN scenario_results s ON s.id = l.result_id
WHERE s.run_id = :run_id
GROUP BY l.primary_intent
ORDER BY conversations DESC, l.primary_intent""",

    "gtm_leads": """
SELECT s.id AS result_id, s.scenario_id, l.primary_intent, l.product_interest, l.purchase_intent,
       l.upsell_opportunity, l.churn_risk, l.sentiment, l.contact_captured, l.summary
FROM leads l
JOIN scenario_results s ON s.id = l.result_id
WHERE s.run_id = :run_id
  AND (l.purchase_intent IN ('medium', 'high') OR l.upsell_opportunity IS NOT NULL OR l.churn_risk = 'high')
ORDER BY CASE l.purchase_intent WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
         CASE l.churn_risk WHEN 'high' THEN 1 ELSE 2 END, s.scenario_id""",
}


def query(conn, name: str, **params) -> list[dict]:
    return [dict(r) for r in conn.execute(QUERIES[name], params).fetchall()]


def mcnemar_exact_p(b: int, c: int) -> float | None:
    """Two-sided exact McNemar test on discordant pairs (b: pass->fail, c: fail->pass)."""
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    p = 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, p)


def list_runs(conn) -> list[dict]:
    runs = query(conn, "runs")
    for r in runs:
        r["usage"] = json.loads(r.pop("usage_json") or "{}")
    return runs


def run_summary(conn, run_id: str) -> dict | None:
    run = next((r for r in list_runs(conn) if r["id"] == run_id), None)
    if run is None:
        return None
    pairs = query(conn, "verdict_pairs", run_id=run_id)
    criteria = query(conn, "judge_criteria", run_id=run_id)
    grounded = sum(c["grounded_quotes"] or 0 for c in criteria)
    total = sum(c["total_quotes"] or 0 for c in criteria)
    return {
        "run": run,
        "categories": query(conn, "pass_rate_by_category", run_id=run_id),
        "failure_reasons": query(conn, "top_failure_reasons", run_id=run_id),
        "latency": query(conn, "latency", run_id=run_id),
        "judge_criteria": criteria,
        "judge_agreement": {
            "criteria": query(conn, "judge_agreement", run_id=run_id),
            "pairs": len(pairs),
            "verdict_agreement": (sum(p["verdict_1"] == p["verdict_2"] for p in pairs) / len(pairs)) if pairs else None,
            "kappa": cohen_kappa([bool(p["verdict_1"]) for p in pairs], [bool(p["verdict_2"]) for p in pairs]),
            "unstable": [p["scenario_id"] for p in pairs if p["verdict_1"] != p["verdict_2"]],
            "quote_grounding": (grounded / total) if total else None,
            "ungrounded_quotes": total - grounded,
        },
        "scenarios": query(conn, "scenario_results", run_id=run_id),
    }


def compare_runs(conn, run_a: str, run_b: str) -> dict:
    """Regression report: B (candidate) compared with A (baseline)."""
    runs = {r["id"]: r for r in list_runs(conn)}
    missing = [r for r in (run_a, run_b) if r not in runs]
    if missing:
        raise KeyError(f"Unknown run id(s): {', '.join(missing)}")
    scenarios = query(conn, "regression_scenarios", run_a=run_a, run_b=run_b)
    groups: dict[str, list[dict]] = {"newly_failing": [], "newly_passing": [], "still_failing": [], "still_passing": []}
    for s in scenarios:
        groups[s["change"]].append(s)
    n = len(scenarios)
    rate_a = 100.0 * sum(s["passed_a"] for s in scenarios) / n if n else None
    rate_b = 100.0 * sum(s["passed_b"] for s in scenarios) / n if n else None
    b, c = len(groups["newly_failing"]), len(groups["newly_passing"])
    return {
        "run_a": runs[run_a], "run_b": runs[run_b],
        "common_scenarios": n,
        "pass_rate_a": round(rate_a, 1) if rate_a is not None else None,
        "pass_rate_b": round(rate_b, 1) if rate_b is not None else None,
        "pass_rate_delta": round(rate_b - rate_a, 1) if n else None,
        "mcnemar_p": mcnemar_exact_p(b, c),
        "scenarios": scenarios,
        "groups": {k: [s["scenario_id"] for s in v] for k, v in groups.items()},
        "criteria": query(conn, "regression_criteria", run_a=run_a, run_b=run_b),
        "checks": query(conn, "regression_checks", run_a=run_a, run_b=run_b),
        "categories": query(conn, "regression_categories", run_a=run_a, run_b=run_b),
    }


def gtm_summary(conn, run_id: str) -> dict:
    return {"intents": query(conn, "gtm_intents", run_id=run_id), "leads": query(conn, "gtm_leads", run_id=run_id)}
