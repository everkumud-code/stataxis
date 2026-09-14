"""Evidence-backed StatAxis View synthesis from measured signals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    """A named directional signal with an optional magnitude."""

    name: str
    direction: str
    strength: float | None = None


@dataclass(frozen=True)
class StatAxisView:
    """Structured output separating facts, analysis, and viewpoint."""

    data: tuple[str, ...]
    analysis: tuple[str, ...]
    view: str
    confidence: float


def _direction(signal: Signal) -> int:
    if signal.direction == "positive":
        return 1
    if signal.direction == "negative":
        return -1
    return 0


def build_stat_axis_view(
    data: list[str],
    signals: list[Signal],
    confidence: float,
) -> StatAxisView:
    """Build a conservative viewpoint without inventing causality."""
    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be between 0 and 100")

    usable = [signal for signal in signals if signal.direction in {"positive", "negative", "neutral"}]
    positive = sum(_direction(signal) == 1 for signal in usable)
    negative = sum(_direction(signal) == -1 for signal in usable)

    analysis: list[str] = []
    if positive and negative:
        analysis.append(
            f"Signals are mixed: {positive} positive and {negative} negative signals are available."
        )
        view = "The evidence is mixed; no single directional conclusion is supported."
    elif positive:
        analysis.append(f"Available signals are directionally positive ({positive} positive).")
        view = "The available evidence supports a positive directional signal."
    elif negative:
        analysis.append(f"Available signals are directionally negative ({negative} negative).")
        view = "The available evidence supports a negative directional signal."
    else:
        analysis.append("No directional signal is available.")
        view = "There is insufficient directional evidence for a conclusion."

    return StatAxisView(
        data=tuple(data),
        analysis=tuple(analysis),
        view=view,
        confidence=confidence,
    )
