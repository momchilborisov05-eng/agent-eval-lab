"""
Runs scenarios end to end: simulated customer <-> agent, then checks, judge trials and lead extraction.

A scenario passes only if every deterministic check passes AND every judge trial passes. Using all
trials (not the average) is deliberately conservative: when the judge disagrees with itself, the
result is treated as a failure and flagged for review instead of being counted as a pass by luck.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from .agent.base import AgentAdapter, ConversationContext
from .checks import CheckResult, run_checks
from .conversation import Conversation, Turn
from .gtm import LeadInfo
from .judge import JudgeResult
from .scenarios import Scenario
from .simulator import UserSimulator


@dataclass
class ScenarioResult:
    scenario: Scenario
    conversation: Conversation
    checks: list[CheckResult] = field(default_factory=list)
    judge_trials: list[JudgeResult] = field(default_factory=list)
    lead: LeadInfo | None = None
    error: str | None = None

    @property
    def checks_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def judge_passed(self) -> bool:
        return bool(self.judge_trials) and all(j.verdict for j in self.judge_trials)

    @property
    def judge_disagreement(self) -> bool:
        return len({j.verdict for j in self.judge_trials}) > 1

    @property
    def passed(self) -> bool:
        return self.error is None and self.checks_passed and self.judge_passed

    def failure_reasons(self) -> list[str]:
        reasons = [f"{c.check}:{c.name}" for c in self.checks if not c.passed]
        failed = {c for j in self.judge_trials for c in j.failed_criteria}
        reasons += [f"judge:{c}" for c in sorted(failed)]
        if self.error:
            reasons.append("error")
        return reasons


def run_conversation(agent: AgentAdapter, simulator: UserSimulator, scenario: Scenario) -> Conversation:
    agent.start(ConversationContext(scenario_id=scenario.id, channel=scenario.channel))
    conv = Conversation(scenario_id=scenario.id, meta={"agent": agent.describe(), "simulator": simulator.name})
    message = simulator.opening(scenario)
    for index in range(1, scenario.max_turns + 1):
        conv.turns.append(Turn(index, "user", message))
        started = time.perf_counter()
        turn = agent.respond(message)
        wall_ms = (time.perf_counter() - started) * 1000
        latency = turn.latency_ms if turn.latency_ms is not None else round(wall_ms, 1)
        conv.turns.append(Turn(index, "agent", turn.text, list(turn.tool_calls), latency))
        if turn.error:
            conv.end_reason = "agent_error"
            conv.meta["agent_error"] = turn.error
            return conv
        if turn.ended:
            conv.end_reason = turn.end_reason or "transferred"
            return conv
        reply = simulator.reply(scenario, conv)
        if reply.end:
            conv.end_reason = f"user_{reply.reason or 'done'}"
            return conv
        message = reply.message
    conv.end_reason = "max_turns"
    return conv


class SuiteRunner:
    def __init__(self, agent: AgentAdapter, simulator: UserSimulator, judge, extractor=None,
                 judge_trials: int = 2, on_progress: Callable[[ScenarioResult], None] | None = None):
        if judge_trials < 1:
            raise ValueError("judge_trials must be at least 1")
        self.agent = agent
        self.simulator = simulator
        self.judge = judge
        self.extractor = extractor
        self.judge_trials = judge_trials
        self.on_progress = on_progress

    def evaluate(self, scenario: Scenario, conversation: Conversation) -> ScenarioResult:
        """Score an existing conversation (also used for imported production transcripts)."""
        result = ScenarioResult(scenario=scenario, conversation=conversation)
        result.checks = run_checks(scenario, conversation, canary=getattr(self.agent, "canary", None))
        result.judge_trials = [self.judge.evaluate(scenario, conversation, trial=t)
                               for t in range(1, self.judge_trials + 1)]
        if self.extractor is not None:
            result.lead = self.extractor.extract(conversation)
        return result

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        try:
            conversation = run_conversation(self.agent, self.simulator, scenario)
            result = self.evaluate(scenario, conversation)
        except Exception as e:  # one broken scenario must not stop the suite
            conversation = Conversation(scenario_id=scenario.id, end_reason="agent_error",
                                        meta={"agent_error": str(e), "traceback": traceback.format_exc(limit=3)})
            result = ScenarioResult(scenario=scenario, conversation=conversation,
                                    error=f"{type(e).__name__}: {e}")
        if self.on_progress:
            self.on_progress(result)
        return result

    def run(self, scenarios: list[Scenario]) -> list[ScenarioResult]:
        return [self.run_scenario(s) for s in scenarios]
