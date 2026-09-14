"""Explainable contribution reporting for StatAxis intelligence."""

from __future__ import annotations

from dataclasses import dataclass

from metrics.stx_index import STXIndexResult


@dataclass(frozen=True)
class SignalContribution:
    """A signal's normalized contribution to the final STX score."""

    name: str
    value: float
    weighted_contribution: float
    share_of_score: float


def explain_index(result: STXIndexResult) -> tuple[SignalContribution, ...]:
    """Return deterministic, score-traceable contributions sorted by impact."""
    if result.score is None:
        return ()

    contributions = []
    for name, contribution in result.component_scores.items():
        value = contribution * result.confidence / 100
        share = contribution / result.score * 100 if result.score else 0.0
        contributions.append(
            SignalContribution(
                name=name,
                value=value,
                weighted_contribution=contribution,
                share_of_score=share,
            )
        )
    return tuple(sorted(contributions, key=lambda item: (-item.weighted_contribution, item.name)))
