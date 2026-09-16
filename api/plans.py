"""StatAxis SX package catalog and stable product identifiers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SXPlan(StrEnum):
    FREE = "sx_free"
    IDEA = "sx_idea"
    INTELLIGENCE = "sx_intelligence"
    ANALYST = "sx_analyst"
    PRO = "sx_pro"
    CORPORATE = "sx_corporate"
    ENTERPRISE = "sx_enterprise"


@dataclass(frozen=True)
class SXPlanDefinition:
    code: SXPlan
    name: str
    promise: str
    premium: bool
    max_seats: int | None


SX_PLANS: dict[SXPlan, SXPlanDefinition] = {
    SXPlan.FREE: SXPlanDefinition(SXPlan.FREE, "SX Free", "Explore the Data", False, 1),
    SXPlan.IDEA: SXPlanDefinition(SXPlan.IDEA, "SX Idea", "Discover the Signal", True, 1),
    SXPlan.INTELLIGENCE: SXPlanDefinition(SXPlan.INTELLIGENCE, "SX Intelligence", "Understand the Signal", True, 1),
    SXPlan.ANALYST: SXPlanDefinition(SXPlan.ANALYST, "SX Analyst", "Analyse the Signal", True, 1),
    SXPlan.PRO: SXPlanDefinition(SXPlan.PRO, "SX Pro", "Act on the Signal", True, 1),
    SXPlan.CORPORATE: SXPlanDefinition(SXPlan.CORPORATE, "SX Corporate", "Team Intelligence", True, 5),
    SXPlan.ENTERPRISE: SXPlanDefinition(SXPlan.ENTERPRISE, "SX Enterprise", "Institutional Intelligence", True, None),
}


def get_plan(plan: SXPlan | str) -> SXPlanDefinition:
    """Resolve either a stable package code or its public package name."""
    if isinstance(plan, SXPlan):
        return SX_PLANS[plan]
    value = str(plan).strip()
    try:
        return SX_PLANS[SXPlan(value.lower())]
    except ValueError:
        for definition in SX_PLANS.values():
            if definition.name.casefold() == value.casefold():
                return definition
        raise ValueError(f"unknown SX plan: {plan}") from None


def all_plans() -> tuple[SXPlanDefinition, ...]:
    return tuple(SX_PLANS[plan] for plan in SXPlan)
