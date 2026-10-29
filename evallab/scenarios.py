"""
Test scenarios: loading YAML/JSON files into typed objects and validating them.

A scenario describes a simulated customer (persona, goal, what they know), how to judge the
conversation (success criteria, expected and forbidden tool calls, forbidden behaviours, patterns the
agent must say) and limits (max turns, latency budget). See scenarios/*.yaml and the README.

Validation errors name the file and the field, e.g.
    scenarios/orders.yaml > orders-status-verified > expected_tool_calls[0].name: unknown tool 'check_order'
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .agent.tools import CUSTOMERS, TOOL_NAMES

CATEGORIES = ["orders", "appointments", "returns", "faq", "escalation", "security", "guardrails", "voice", "sales"]
CHANNELS = ["chat", "voice"]
SEVERITIES = ["critical", "major", "minor"]
MATCH_OPERATORS = {"$any", "$regex", "$in", "$absent"}
DEFAULT_LATENCY_MS = {"chat": 8000, "voice": 2500}


class ScenarioError(ValueError):
    """A scenario file is invalid. The message says where and why."""


@dataclass
class ToolExpectation:
    name: str
    args: dict[str, Any] = field(default_factory=dict)  # values: literal or {"$regex"|"$in"|"$any"|"$absent": ...}


@dataclass
class PatternRule:
    id: str
    description: str
    pattern: str | None = None  # regex checked deterministically; None = judged by the LLM judge only
    severity: str = "major"


@dataclass
class UserScript:
    """Deterministic customer for scripted runs (CI, the offline demo)."""

    turns: list[str] = field(default_factory=list)   # said in order, one per agent reply
    fallback: str = ""                               # said when the turns run out (see ScriptedSimulator)
    done_when: str | None = None                     # regex on the agent's reply: the customer's goal is met
    replies: list[dict] = field(default_factory=list)  # [{when: regex on agent reply, say: text}], used once each


@dataclass
class Scenario:
    id: str
    title: str
    category: str
    persona: str
    goal: str
    opening_message: str
    channel: str = "chat"
    tags: list[str] = field(default_factory=list)
    customer_id: str | None = None
    known_facts: dict[str, Any] = field(default_factory=dict)
    success_criteria: list[str] = field(default_factory=list)
    expected_tool_calls: list[ToolExpectation] = field(default_factory=list)
    forbidden_tool_calls: list[ToolExpectation] = field(default_factory=list)
    forbidden_behaviours: list[PatternRule] = field(default_factory=list)
    must_say: list[PatternRule] = field(default_factory=list)
    max_turns: int = 6
    max_latency_ms: int = 0
    script: UserScript = field(default_factory=UserScript)
    source_file: str = ""

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def _fail(where: str, message: str) -> None:
    raise ScenarioError(f"{where}: {message}")


def _check_regex(pattern: Any, where: str) -> None:
    if not isinstance(pattern, str) or not pattern:
        _fail(where, "must be a non-empty regex string")
    try:
        re.compile(pattern)
    except re.error as e:
        _fail(where, f"invalid regex {pattern!r} ({e})")


def _parse_tool_expectations(raw: Any, where: str) -> list[ToolExpectation]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail(where, "must be a list")
    result = []
    for i, item in enumerate(raw):
        loc = f"{where}[{i}]"
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or "name" not in item:
            _fail(loc, "needs a 'name'")
        if item["name"] not in TOOL_NAMES:
            _fail(f"{loc}.name", f"unknown tool {item['name']!r} (known: {', '.join(sorted(TOOL_NAMES))})")
        args = item.get("args") or {}
        if not isinstance(args, dict):
            _fail(f"{loc}.args", "must be a mapping")
        for key, value in args.items():
            if isinstance(value, dict):
                if len(value) != 1 or next(iter(value)) not in MATCH_OPERATORS:
                    _fail(f"{loc}.args.{key}", f"matcher must be one of {sorted(MATCH_OPERATORS)}")
                op, operand = next(iter(value.items()))
                if op == "$regex":
                    _check_regex(operand, f"{loc}.args.{key}.$regex")
                if op == "$in" and not isinstance(operand, list):
                    _fail(f"{loc}.args.{key}.$in", "must be a list")
        result.append(ToolExpectation(name=item["name"], args=args))
    return result


def _parse_rules(raw: Any, where: str, need_pattern: bool) -> list[PatternRule]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _fail(where, "must be a list")
    rules = []
    for i, item in enumerate(raw):
        loc = f"{where}[{i}]"
        if not isinstance(item, dict) or not item.get("id") or not item.get("description"):
            _fail(loc, "needs 'id' and 'description'")
        pattern = item.get("pattern")
        if need_pattern or pattern is not None:
            _check_regex(pattern, f"{loc}.pattern")
        severity = item.get("severity", "major")
        if severity not in SEVERITIES:
            _fail(f"{loc}.severity", f"must be one of {SEVERITIES}")
        rules.append(PatternRule(id=item["id"], description=item["description"], pattern=pattern, severity=severity))
    return rules


def parse_scenario(data: Any, source: str = "<memory>") -> Scenario:
    """Validate one scenario mapping and return a Scenario."""
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: each scenario must be a mapping")
    where = f"{source} > {data.get('id', '<no id>')}"
    for key in ("id", "title", "category", "persona", "goal", "opening_message"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            _fail(where, f"missing required text field '{key}'")
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*", data["id"]):
        _fail(f"{where}.id", "use lowercase letters, digits and dashes")
    if data["category"] not in CATEGORIES:
        _fail(f"{where}.category", f"{data['category']!r} is not one of {CATEGORIES}")
    channel = data.get("channel", "chat")
    if channel not in CHANNELS:
        _fail(f"{where}.channel", f"must be one of {CHANNELS}")
    customer_id = data.get("customer_id")
    if customer_id is not None and customer_id not in CUSTOMERS:
        _fail(f"{where}.customer_id", f"unknown customer {customer_id!r}")
    max_turns = data.get("max_turns", 6)
    if not isinstance(max_turns, int) or not 1 <= max_turns <= 30:
        _fail(f"{where}.max_turns", "must be an integer from 1 to 30")
    latency = data.get("max_latency_ms", DEFAULT_LATENCY_MS[channel])
    if not isinstance(latency, int) or latency <= 0:
        _fail(f"{where}.max_latency_ms", "must be a positive integer")

    script_raw = data.get("script") or {}
    if not isinstance(script_raw, dict):
        _fail(f"{where}.script", "must be a mapping with turns / fallback / done_when")
    turns = script_raw.get("turns") or []
    if not isinstance(turns, list) or not all(isinstance(t, str) for t in turns):
        _fail(f"{where}.script.turns", "must be a list of strings")
    if script_raw.get("done_when") is not None:
        _check_regex(script_raw["done_when"], f"{where}.script.done_when")
    replies = script_raw.get("replies") or []
    if not isinstance(replies, list):
        _fail(f"{where}.script.replies", "must be a list of {when, say}")
    for i, rule in enumerate(replies):
        if not isinstance(rule, dict) or not isinstance(rule.get("say"), str):
            _fail(f"{where}.script.replies[{i}]", "needs 'when' (regex) and 'say' (text)")
        _check_regex(rule.get("when"), f"{where}.script.replies[{i}].when")

    criteria = data.get("success_criteria") or []
    if not isinstance(criteria, list) or not criteria:
        _fail(f"{where}.success_criteria", "list at least one success criterion for the judge")

    return Scenario(
        id=data["id"], title=data["title"], category=data["category"], persona=data["persona"].strip(),
        goal=data["goal"].strip(), opening_message=data["opening_message"].strip(), channel=channel,
        tags=list(data.get("tags") or []), customer_id=customer_id, known_facts=dict(data.get("known_facts") or {}),
        success_criteria=[str(c) for c in criteria],
        expected_tool_calls=_parse_tool_expectations(data.get("expected_tool_calls"), f"{where}.expected_tool_calls"),
        forbidden_tool_calls=_parse_tool_expectations(data.get("forbidden_tool_calls"), f"{where}.forbidden_tool_calls"),
        forbidden_behaviours=_parse_rules(data.get("forbidden_behaviours"), f"{where}.forbidden_behaviours", False),
        must_say=_parse_rules(data.get("must_say"), f"{where}.must_say", True),
        max_turns=max_turns, max_latency_ms=latency,
        script=UserScript(turns=turns, fallback=script_raw.get("fallback") or "", done_when=script_raw.get("done_when"),
                          replies=replies),
        source_file=source,
    )


def load_file(path: Path) -> list[Scenario]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise ScenarioError(f"{path.name}: could not parse file ({e})") from e
    items = data if isinstance(data, list) else (data.get("scenarios") if isinstance(data, dict) and "scenarios" in data else [data])
    return [parse_scenario(item, path.name) for item in items]


def load_scenarios(directory: Path, category: str | None = None, ids: list[str] | None = None) -> list[Scenario]:
    """Load every *.yaml / *.yml / *.json file in a folder. Scenario ids must be unique."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ScenarioError(f"Scenario folder not found: {directory}")
    scenarios: list[Scenario] = []
    seen: dict[str, str] = {}
    for path in sorted(p for p in directory.iterdir() if p.suffix in {".yaml", ".yml", ".json"}):
        for scenario in load_file(path):
            if scenario.id in seen:
                raise ScenarioError(f"{path.name}: duplicate scenario id {scenario.id!r} (also in {seen[scenario.id]})")
            seen[scenario.id] = path.name
            scenarios.append(scenario)
    if not scenarios:
        raise ScenarioError(f"No scenario files in {directory}")
    if category:
        scenarios = [s for s in scenarios if s.category == category]
    if ids:
        missing = set(ids) - {s.id for s in scenarios}
        if missing:
            raise ScenarioError(f"Unknown scenario id(s): {', '.join(sorted(missing))}")
        scenarios = [s for s in scenarios if s.id in ids]
    return scenarios
