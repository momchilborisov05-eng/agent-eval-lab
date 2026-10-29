"""
Offline demo mode. Everything in this package is a deterministic, rule-based stand-in for an LLM
component, so the full pipeline runs without an API key. Demo results are labelled as such in the
database (runs.mode = 'demo') and in the dashboard, and say nothing about any real model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .agent import DemoSupportAgent
from .gtm import RuleLeadExtractor
from .judge import HeuristicJudge

__all__ = ["DemoSupportAgent", "HeuristicJudge", "RuleLeadExtractor", "run_demo"]

DEMO_RUNS = [
    ("v1", "demo-prompt-v1", "Prompt v1 (first draft)"),
    ("v2", "demo-prompt-v2", "Prompt v2 (policies added)"),
]


def run_demo(db_path: Path, scenarios_dir: Path, on_progress: Callable | None = None) -> list[str]:
    """Run the full suite twice (agent profile v1 and v2) and store both runs. Returns the run ids."""
    from ..runner import SuiteRunner
    from ..scenarios import load_scenarios
    from ..simulator import ScriptedSimulator
    from ..storage import Store

    scenarios = load_scenarios(scenarios_dir)
    store = Store(db_path)
    run_ids = []
    for version, run_id, label in DEMO_RUNS:
        store.delete_run(run_id)  # re-running the demo replaces the old demo runs
        agent = DemoSupportAgent(version)
        simulator, judge = ScriptedSimulator(), HeuristicJudge()
        runner = SuiteRunner(agent, simulator, judge, RuleLeadExtractor(), judge_trials=2, on_progress=on_progress)
        store.create_run(f"DEMO - {label}", "demo", agent.describe(), simulator.name, judge.name, 2, run_id=run_id,
                         notes="Offline demo: rule-based agent, scripted customer, heuristic judge, simulated latency.")
        for result in runner.run(scenarios):
            store.save_result(run_id, result)
        store.finish_run(run_id, {"requests": 0, "note": "demo mode - no API calls"})
        run_ids.append(run_id)
    return run_ids
