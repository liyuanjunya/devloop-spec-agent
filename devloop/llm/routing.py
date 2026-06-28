"""Model routing: pick the right provider/model for each role."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ModelAssignment:
    provider: str
    model: str


class ModelRouter:
    """Routes role names (writer / reviewer / etc.) to (provider, model).

    Enforces cross-company constraint: writer and reviewer must come from
    different companies (e.g. anthropic ↔ openai).
    """

    def __init__(
        self,
        primary_provider: str,
        primary_model: str,
        cross_review_provider: str,
        cross_review_model: str,
        stage_defaults: dict[str, str] | None = None,
    ):
        if primary_provider == cross_review_provider:
            raise ValueError(
                f"Cross-company review violated: primary={primary_provider}, "
                f"review={cross_review_provider}. They must be different companies."
            )
        self.primary_provider = primary_provider
        self.primary_model = primary_model
        self.cross_review_provider = cross_review_provider
        self.cross_review_model = cross_review_model
        self.stage_defaults = stage_defaults or {}

    def assign(self, role: str) -> ModelAssignment:
        """Get the provider/model assignment for a given role."""
        side = self.stage_defaults.get(role)
        if side is None:
            # Unknown role -> default to primary
            return ModelAssignment(self.primary_provider, self.primary_model)
        if side == "primary":
            return ModelAssignment(self.primary_provider, self.primary_model)
        if side == "cross_review":
            return ModelAssignment(self.cross_review_provider, self.cross_review_model)
        raise ValueError(f"Unknown side '{side}' in stage_defaults for role '{role}'")

    def opposite(self, current_provider: str) -> ModelAssignment:
        """Return the provider/model from the opposite side."""
        if current_provider == self.primary_provider:
            return ModelAssignment(self.cross_review_provider, self.cross_review_model)
        return ModelAssignment(self.primary_provider, self.primary_model)


def load_router_from_yaml(
    yaml_path: Path,
    primary_provider: str,
    primary_model: str,
    cross_review_provider: str,
    cross_review_model: str,
) -> ModelRouter:
    data: dict = {}
    if yaml_path.exists():
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    stage_defaults = data.get("stage_defaults", {}) or {}
    return ModelRouter(
        primary_provider=primary_provider,
        primary_model=primary_model,
        cross_review_provider=cross_review_provider,
        cross_review_model=cross_review_model,
        stage_defaults=stage_defaults,
    )
