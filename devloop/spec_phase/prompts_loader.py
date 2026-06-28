"""Prompt loader.

Loads markdown prompt files from `prompts/` with a 3-layer override chain:
  1. prompts/overrides/<name>.md   (project-local overrides, highest priority)
  2. prompts/<name>.md              (defaults)
  3. prompts/reference/spec-kit/<name>.md   (vendored fallback)

Supports simple `{{var}}` substitution.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class PromptNotFoundError(Exception):
    pass


class PromptLoader:
    def __init__(self, prompts_dir: Path):
        self.prompts_dir = Path(prompts_dir).resolve()
        if not self.prompts_dir.is_dir():
            raise FileNotFoundError(f"prompts_dir does not exist: {self.prompts_dir}")

    def _resolve_path(self, name: str) -> Path:
        """Return the actual file path, honoring the override chain."""
        candidates = [
            self.prompts_dir / "overrides" / f"{name}.md",
            self.prompts_dir / f"{name}.md",
            self.prompts_dir / "reference" / "spec-kit" / f"{name}.md",
        ]
        for c in candidates:
            if c.is_file():
                return c
        raise PromptNotFoundError(
            f"Prompt '{name}' not found in any of: " + ", ".join(str(c) for c in candidates)
        )

    def load(self, prompt_name: str, /, **vars: Any) -> str:
        """Load `prompts/{prompt_name}.md` and substitute {{var}} placeholders.

        Positional-only `prompt_name` avoids conflict with `name=` substitution vars.
        """
        path = self._resolve_path(prompt_name)
        text = path.read_text(encoding="utf-8")
        if not vars:
            return text

        def _sub(m: re.Match[str]) -> str:
            key = m.group(1)
            if key not in vars:
                return m.group(0)
            v = vars[key]
            return str(v)

        return VAR_RE.sub(_sub, text)

    def list_available(self) -> list[str]:
        """List all known prompt names (recursive)."""
        out: set[str] = set()
        for p in self.prompts_dir.rglob("*.md"):
            try:
                rel = p.relative_to(self.prompts_dir).with_suffix("").as_posix()
            except ValueError:
                continue
            # Strip 'overrides/' and 'reference/spec-kit/' prefixes
            for prefix in ("overrides/", "reference/spec-kit/"):
                if rel.startswith(prefix):
                    rel = rel[len(prefix) :]
            out.add(rel)
        return sorted(out)
