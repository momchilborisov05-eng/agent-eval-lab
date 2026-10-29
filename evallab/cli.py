"""
Command-line interface.

    python -m evallab demo                         offline demo: two runs (prompt v1 vs v2), no API key
    python -m evallab validate                     check all scenario files
    python -m evallab run --prompt v2              live run against the Claude agent (needs an API key)
    python -m evallab runs                         list stored runs
    python -m evallab report <run>                 summary of one run
    python -m evallab compare <run_a> <run_b>      regression report (b compared with a)
    python -m evallab score-transcript FILE --scenario ID   score an ElevenLabs transcript
    python -m evallab serve                        start the dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("EVAL_LAB_DB", ROOT / "eval_lab.db"))
DEFAULT_SCENARIOS = ROOT / "scenarios"


def _pct(value) -> str:
    return "-" if value is None else f"{value:.1f}%"


def _progress(result) -> None:
    mark = "PASS" if result.passed else "FAIL"
    reasons = ", ".join(result.failure_reasons()[:3])
    print(f"  {mark}  {result.scenario.id:<38} {reasons}", flush=True)


def cmd_validate(args) -> int:
    from .scenarios import load_scenarios

    scenarios = load_scenarios(args.scenarios)
    counts = Counter(s.category for s in scenarios)
    channels = Counter(s.channel for s in scenarios)
    print(f"{len(scenarios)} valid scenarios in {args.scenarios}")
    print("  by category: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print("  by channel:  " + ", ".join(f"{k} {v}" for k, v in sorted(channels.items())))
    adversarial = sum("adversarial" in s.tags for s in scenarios)
    print(f"  adversarial: {adversarial}")
    return 0


def cmd_demo(args) -> int:
    from . import analytics
    from .demo import run_demo
    from .storage import Store

    print("Running the OFFLINE DEMO (rule-based agent, scripted customer, heuristic judge, simulated latency).")
    print("No API calls are made. Demo numbers show how the lab works, not how any real model performs.\n")
    ids = run_demo(args.db, args.scenarios, on_progress=_progress)
    with Store(args.db).connect() as conn:
        report = analytics.compare_runs(conn, ids[0], ids[1])
    _print_compare(report)
    print(f"\nSaved to {args.db}. Open the dashboard with: python -m evallab serve")
    return 0


def cmd_run(args) -> int:
    from .llm import MODEL, Usage, make_client
    from .runner import SuiteRunner
    from .scenarios import load_scenarios
    from .simulator import LLMUserSimulator, ScriptedSimulator
    from .storage import Store

    scenarios = load_scenarios(args.scenarios, category=args.category, ids=args.scenario or None)
    needs_llm = args.agent == "claude" or args.simulator == "llm" or args.judge == "llm" or args.gtm == "llm"
    client = make_client() if needs_llm else None
    usage = Usage()

    if args.agent == "claude":
        from .agent.claude_agent import ClaudeSupportAgent
        agent = ClaudeSupportAgent(client, prompt_version=args.prompt, usage=usage)
    else:
        from .demo import DemoSupportAgent
        agent = DemoSupportAgent(args.prompt)
    simulator = LLMUserSimulator(client, usage) if args.simulator == "llm" else ScriptedSimulator()
    if args.judge == "llm":
        from .judge import LLMJudge
        judge = LLMJudge(client, usage)
    else:
        from .demo import HeuristicJudge
        judge = HeuristicJudge()
    if args.gtm == "llm":
        from .gtm import LLMLeadExtractor
        extractor = LLMLeadExtractor(client, usage)
    elif args.gtm == "rules":
        from .demo import RuleLeadExtractor
        extractor = RuleLeadExtractor()
    else:
        extractor = None

    mode = "live" if needs_llm else "demo"
    label = args.label or f"{agent.name} prompt {args.prompt} ({args.simulator} customer, {args.judge} judge)"
    store = Store(args.db)
    run_id = store.create_run(label, mode, agent.describe(), simulator.name, judge.name, args.trials)
    print(f"Run {run_id}: {len(scenarios)} scenarios, agent={args.agent}/{args.prompt}, simulator={args.simulator}, "
          f"judge={args.judge} x{args.trials}" + (f", model={MODEL}" if needs_llm else ""))
    runner = SuiteRunner(agent, simulator, judge, extractor, judge_trials=args.trials, on_progress=_progress)
    passed = 0
    for scenario in scenarios:
        result = runner.run_scenario(scenario)
        store.save_result(run_id, result)
        passed += result.passed
    store.finish_run(run_id, usage.to_dict())
    print(f"\n{passed}/{len(scenarios)} passed ({100 * passed / len(scenarios):.1f}%).")
    if usage.requests:
        print(f"Model calls: {usage.requests}, input tokens: {usage.input_tokens:,} "
              f"({usage.cached_tokens:,} cached), output tokens: {usage.output_tokens:,}")
    print(f"Saved as run {run_id}.")
    return 0


def cmd_runs(args) -> int:
    from . import analytics
    from .storage import Store

    with Store(args.db).connect() as conn:
        runs = analytics.list_runs(conn)
    if not runs:
        print("No runs yet. Try: python -m evallab demo")
        return 0
    w = max(len("run id"), *(len(r["id"]) for r in runs))
    print(f"{'run id':<{w}}  {'mode':<6} {'pass rate':>9}  {'passed':>7}  label")
    for r in runs:
        print(f"{r['id']:<{w}}  {r['mode']:<6} {_pct(r['pass_rate']):>9}  {r['passed']:>3}/{r['scenarios']:<3}  {r['label']}")
    return 0


def cmd_report(args) -> int:
    from . import analytics
    from .storage import Store

    with Store(args.db).connect() as conn:
        summary = analytics.run_summary(conn, args.run_id)
    if summary is None:
        print(f"Unknown run id: {args.run_id}", file=sys.stderr)
        return 1
    run, agreement = summary["run"], summary["judge_agreement"]
    print(f"{run['label']}  [{run['mode']}]")
    print(f"Pass rate {_pct(run['pass_rate'])} ({run['passed']}/{run['scenarios']})\n")
    print("By category:")
    for c in summary["categories"]:
        print(f"  {c['category']:<14} {_pct(c['pass_rate']):>7}  ({c['passed']}/{c['scenarios']})")
    print("\nTop failure reasons:")
    for f in summary["failure_reasons"]:
        print(f"  {f['scenarios']:>2} scenarios  {f['reason']:<40} {f['severity']}")
    print("\nJudge consistency (trial 1 vs trial 2):")
    if agreement["pairs"]:
        kappa = agreement["kappa"]
        print(f"  verdict agreement {agreement['verdict_agreement']:.0%}, Cohen's kappa "
              f"{'-' if kappa is None else f'{kappa:.2f}'}, quote grounding "
              f"{'-' if agreement['quote_grounding'] is None else f'{agreement['quote_grounding']:.0%}'}")
        for c in agreement["criteria"]:
            print(f"  {c['criterion']:<18} exact {c['exact_agreement']:.0%}  within-1 {c['within_one']:.0%}")
    else:
        print("  only one judge trial per conversation")
    return 0


def _print_compare(report: dict) -> None:
    a, b = report["run_a"], report["run_b"]
    print(f"\nRegression report: {b['label']}  vs  {a['label']}")
    print(f"  pass rate {_pct(report['pass_rate_a'])} -> {_pct(report['pass_rate_b'])} "
          f"({report['pass_rate_delta']:+.1f} pp on {report['common_scenarios']} scenarios)")
    p = report["mcnemar_p"]
    if p is not None:
        print(f"  McNemar exact test on changed scenarios: p = {p:.3f}")
    for key, title in (("newly_failing", "Newly failing"), ("newly_passing", "Newly passing"),
                       ("still_failing", "Still failing")):
        ids = report["groups"][key]
        print(f"  {title} ({len(ids)}): {', '.join(ids) or '-'}")
    print("  Judge criteria (avg score a -> b):")
    for c in report["criteria"]:
        print(f"    {c['criterion']:<18} {c['avg_a']:.2f} -> {c['avg_b']:.2f} ({c['delta']:+.2f})")


def cmd_compare(args) -> int:
    from . import analytics
    from .storage import Store

    with Store(args.db).connect() as conn:
        try:
            report = analytics.compare_runs(conn, args.run_a, args.run_b)
        except KeyError as e:
            print(e.args[0], file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_compare(report)
    return 0


def cmd_score_transcript(args) -> int:
    from .adapters.elevenlabs import parse_elevenlabs_conversation
    from .runner import SuiteRunner
    from .scenarios import load_scenarios
    from .storage import Store

    scenario = load_scenarios(args.scenarios, ids=[args.scenario])[0]
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    conversation = parse_elevenlabs_conversation(payload, scenario_id=scenario.id)
    if args.judge == "llm":
        from .judge import LLMJudge
        from .llm import make_client
        judge = LLMJudge(make_client())
    else:
        from .demo import HeuristicJudge
        judge = HeuristicJudge()
    runner = SuiteRunner(agent=None, simulator=None, judge=judge, judge_trials=args.trials)
    result = runner.evaluate(scenario, conversation)
    agent_info = {"name": "elevenlabs-agent", "version": conversation.meta.get("agent_id") or "imported", "model": ""}
    store = Store(args.db)
    run_id = store.create_run(args.label or f"Imported transcript {Path(args.file).name}", "import", agent_info,
                              "recorded", judge.name, args.trials)
    store.save_result(run_id, result)
    store.finish_run(run_id)
    print(f"{'PASS' if result.passed else 'FAIL'}  {scenario.id}  ({conversation.exchange_count} exchanges, saved as run {run_id})")
    for c in result.checks:
        print(f"  {'ok ' if c.passed else 'FAIL'} {c.check}:{c.name} - {c.message}")
    for j in result.judge_trials:
        print(f"  judge trial {j.trial}: " + ", ".join(f"{k} {v.score}" for k, v in j.scores.items()))
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .web.app import create_app

    print(f"Dashboard: http://{args.host}:{args.port}  (database: {args.db})")
    uvicorn.run(create_app(args.db), host=args.host, port=args.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evallab", description="Agent Eval Lab: test conversational AI agents.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite database (default: {DEFAULT_DB.name})")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS, help="scenario folder")
    # The same options are accepted after the command too (python -m evallab demo --db other.db).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=argparse.SUPPRESS, help="SQLite database")
    common.add_argument("--scenarios", type=Path, default=argparse.SUPPRESS, help="scenario folder")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", parents=[common], help="validate scenario files").set_defaults(func=cmd_validate)
    sub.add_parser("demo", parents=[common], help="offline demo: run prompt v1 and v2 without an API key").set_defaults(func=cmd_demo)

    run = sub.add_parser("run", parents=[common], help="run the suite")
    run.add_argument("--agent", choices=["claude", "demo"], default="claude")
    run.add_argument("--prompt", choices=["v1", "v2"], default="v2", help="system prompt version")
    run.add_argument("--simulator", choices=["llm", "scripted"], default="llm")
    run.add_argument("--judge", choices=["llm", "demo"], default="llm")
    run.add_argument("--gtm", choices=["llm", "rules", "off"], default="llm", help="lead extraction")
    run.add_argument("--trials", type=int, default=2, help="judge trials per conversation (agreement needs 2)")
    run.add_argument("--category", help="only scenarios in this category")
    run.add_argument("--scenario", action="append", help="only this scenario id (repeatable)")
    run.add_argument("--label", help="run label shown in the dashboard")
    run.set_defaults(func=cmd_run)

    sub.add_parser("runs", parents=[common], help="list runs").set_defaults(func=cmd_runs)
    report = sub.add_parser("report", parents=[common], help="summary of one run")
    report.add_argument("run_id")
    report.set_defaults(func=cmd_report)
    compare = sub.add_parser("compare", parents=[common], help="regression report: run_b compared with run_a")
    compare.add_argument("run_a")
    compare.add_argument("run_b")
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(func=cmd_compare)

    score = sub.add_parser("score-transcript", parents=[common], help="score an ElevenLabs conversation JSON against a scenario")
    score.add_argument("file")
    score.add_argument("--scenario", required=True)
    score.add_argument("--judge", choices=["llm", "demo"], default="demo")
    score.add_argument("--trials", type=int, default=1)
    score.add_argument("--label")
    score.set_defaults(func=cmd_score_transcript)

    serve = sub.add_parser("serve", parents=[common], help="start the dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    from .llm import LLMError
    from .scenarios import ScenarioError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LLMError, ScenarioError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
