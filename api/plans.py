"""StatAxis SX package catalog and stable product identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SXPlan(StrEnum):
    """Public StatAxis package names used by the product and billing layers."""

    FREE = "sx_free"
    IDEA = "sx_idea"
    INTELLIGENCE = "sx_intelligence"
    ANALYST = "sx_analyst"
    PRO = "sx_pro"
    CORPORATE = "sx_corporate"
    ENTERPRISE = "sx_enterprise"


@dataclass(frozen=True)
class SXPlanDefinition:
    """Stable metadata for one customer-facing SX package."""

    code: SXPlan
    name: str
    promise: str
    premium: bool
    max_seats: int | None


SX_PLANS: dict[SXPlan, SXPlanDefinition] = {
    SXPlan.FREE: SXPlanDefinition(
        code=SXPlan.FREE,
        name="SX Free",
        promise="Explore the Data",
        premium=False,
        max_seats=1,
    ),
    SXPlan.IDEA: SXPlanDefinition(
        code=SXPlan.IDEA,
        name="SX Idea",
        promise="Discover the Signal",
        premium=True,
        max_seats=1,
    ),
    SXPlan.INTELLIGENCE: SXPlanDefinition(
        code=SXPlan.INTELLIGENCE,
        name="SX Intelligence",
        promise="Understand the Signal",
        premium=True,
        max_seats=1,
    ),
    SXPlan.ANALYST: SXPlanDefinition(
        code=SXPlan.ANALYST,
        name="SX Analyst",
        promise="Analyse the Signal",
        premium=True,
        max_seats=1,
    ),
    SXPlan.PRO: SXPlanDefinition(
        code=SXPlan.PRO,
        name="SX Pro",
        promise="Act on the Signal",
        premium=True,
        max_seats=1,
    ),
    SXPlan.CORPORATE: SXPlanDefinition(
        code=SXPlan.CORPORATE,
        name="SX Corporate",
        promise="Team Intelligence",
        premium=True,
        max_seats=5,
    ),
    SXPlan.ENTERPRISE: SXPlanDefinition(
        code=SXPlan.ENTERPRISE,
        name="SX Enterprise",
        promise="Institutional Intelligence",
        premium=True,
        max_seats=None,
    ),
}


def get_plan(plan: SXPlan | str) -> SXPlanDefinition:
    """Resolve a package code/name to its stable definition."""
    try:
        resolved = SXPlan(plan)
    except ValueError as exc:
        raise ValueError(f"unknown SX plan: {plan}") from exc
    return SX_PLANS[resolved]


def all_plans() -> tuple[SXPlanDefinition, ...]:
    """Return packages in their public catalogue order."""
    return tuple(SX_PLANS[plan] for plan in SXPlan)
