"""Common types shared across schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class ImportanceLevel(StrEnum):
    CRITICAL = "critical"
    RELEVANT = "relevant"
    PERIPHERAL = "peripheral"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CodeRef(BaseModel):
    """Reference to a piece of code."""

    path: str
    symbols: list[str] = Field(default_factory=list)
    line_ranges: list[tuple[int, int]] = Field(default_factory=list)
    snippet: str | None = None


class TimestampedModel(BaseModel):
    """Mixin for models that record creation time."""

    created_at: datetime = Field(default_factory=datetime.utcnow)


IntentType = Literal["add_feature", "fix_bug", "refactor", "perf_opt", "remove_feature"]
ScopeType = Literal[
    "backend",
    "frontend",
    "data_model",
    "api",
    "infra",
    "ui",
    "test",
    "docs",
    "security",
    "auth",
    "external_integration",
    "performance",
    "payment",
]
PerspectiveType = Literal["data", "api", "ui", "test", "history", "security", "performance"]
ReviewerType = Literal[
    "architecture",
    "completeness",
    "executability",
    "consistency",
    "adversarial",
]
PlanType = Literal["conservative", "balanced", "aggressive"]
RequirementType = Literal["functional", "non_functional"]
Verdict = Literal["pass", "fail", "needs_refine", "reject"]
