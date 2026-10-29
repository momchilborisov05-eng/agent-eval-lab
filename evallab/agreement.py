"""
How much can the judge be trusted? Agreement metrics between repeated judge trials.

An LLM judge is itself a stochastic model. Running it twice on the same transcript and comparing
the results is the cheapest way to see where it is unreliable:

- exact agreement:   share of (conversation, criterion) pairs with the same 1-5 score
- within-one:        share that differ by at most one point
- verdict agreement: share of conversations with the same pass/fail verdict
- Cohen's kappa:     verdict agreement corrected for chance (1 = perfect, 0 = chance level)
- quote grounding:   share of evidence quotes that really appear in the transcript

Self-agreement is a lower bar than agreement with humans: a judge can be consistently wrong. The
README lists this and the other known failure modes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


def exact_agreement(a: list[int], b: list[int]) -> float | None:
    if len(a) != len(b):
        raise ValueError("Both score lists must have the same length.")
    return sum(x == y for x, y in zip(a, b)) / len(a) if a else None


def within_one_agreement(a: list[int], b: list[int]) -> float | None:
    if len(a) != len(b):
        raise ValueError("Both score lists must have the same length.")
    return sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a) if a else None


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Cohen's kappa for two binary raters. None when undefined (no items)."""
    if len(a) != len(b):
        raise ValueError("Both label lists must have the same length.")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected == 1:  # both raters gave the same single label to everything
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


@dataclass
class AgreementReport:
    pairs: int
    verdict_agreement: float | None
    kappa: float | None
    exact: dict[str, float | None]
    within_one: dict[str, float | None]
    unstable_scenarios: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(trial_pairs: dict[str, tuple], criteria: list[str]) -> AgreementReport:
    """trial_pairs: scenario_id -> (JudgeResult trial 1, JudgeResult trial 2)."""
    ids = sorted(trial_pairs)
    first = [trial_pairs[i][0] for i in ids]
    second = [trial_pairs[i][1] for i in ids]
    verdicts_a = [r.verdict for r in first]
    verdicts_b = [r.verdict for r in second]
    exact, within = {}, {}
    for c in criteria:
        sa = [r.scores[c].score for r in first]
        sb = [r.scores[c].score for r in second]
        exact[c] = exact_agreement(sa, sb)
        within[c] = within_one_agreement(sa, sb)
    return AgreementReport(
        pairs=len(ids),
        verdict_agreement=exact_agreement([int(v) for v in verdicts_a], [int(v) for v in verdicts_b]),
        kappa=cohen_kappa(verdicts_a, verdicts_b),
        exact=exact, within_one=within,
        unstable_scenarios=[i for i, a, b in zip(ids, verdicts_a, verdicts_b) if a != b],
    )
