"""Eval Harness — run a set of golden features through the orchestrator
and emit machine-readable + human-readable reports."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from devloop.config import load_settings
from devloop.spec_phase import SpecRunResult, create_orchestrator
from devloop.spec_phase.schemas import Spec


@dataclass
class GoldenCase:
    name: str
    description: str
    repo: Path
    tags: list[str] = field(default_factory=list)
    min_fr_count: int = 1
    min_user_stories: int = 1
    expected_intent_type: str | None = None

    @classmethod
    def from_file(cls, path: Path, project_root: Path) -> GoldenCase:
        data = json.loads(path.read_text(encoding="utf-8"))
        repo = Path(data["repo"])
        if not repo.is_absolute():
            repo = project_root / repo
        return cls(
            name=path.stem,
            description=data["description"],
            repo=repo,
            tags=data.get("tags", []),
            min_fr_count=data.get("min_fr_count", 1),
            min_user_stories=data.get("min_user_stories", 1),
            expected_intent_type=data.get("expected_intent_type"),
        )


@dataclass
class CaseResult:
    name: str
    ok: bool
    spec: Spec | None = None
    workspace: Path | None = None
    duration_s: float = 0.0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def validate_spec(spec: Spec, case: GoldenCase) -> tuple[list[str], list[str], dict[str, Any]]:
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    metrics["fr_count"] = len(spec.functional_requirements)
    metrics["user_story_count"] = len(spec.user_stories)
    metrics["sc_count"] = len(spec.success_criteria)
    metrics["self_concerns_count"] = len(spec.self_concerns)

    if len(spec.functional_requirements) < case.min_fr_count:
        failures.append(
            f"FR count {len(spec.functional_requirements)} below min {case.min_fr_count}"
        )
    if len(spec.user_stories) < case.min_user_stories:
        failures.append(
            f"User story count {len(spec.user_stories)} below min {case.min_user_stories}"
        )
    if not spec.success_criteria:
        warnings.append("No success criteria defined")
    if not spec.self_concerns:
        warnings.append("Writer skipped self-reflection")

    func_fr_without_refs = [
        fr
        for fr in spec.functional_requirements
        if fr.requirement_type == "functional" and not fr.code_references
    ]
    if func_fr_without_refs:
        ids = ", ".join(fr.id for fr in func_fr_without_refs)
        warnings.append(f"Functional FRs without code references: {ids}")

    referenced_paths = set()
    for fr in spec.functional_requirements:
        for ref in fr.code_references:
            referenced_paths.add(ref.path)
    missing_paths = []
    for p in referenced_paths:
        if not (case.repo / p).exists():
            missing_paths.append(p)
    metrics["referenced_path_count"] = len(referenced_paths)
    metrics["missing_path_count"] = len(missing_paths)
    if missing_paths:
        failures.append(f"Spec references non-existent paths: {missing_paths[:5]}")

    metrics["iterations"] = spec.metadata.iterations
    metrics["needs_review"] = spec.metadata.needs_review

    return failures, warnings, metrics


async def run_case(case: GoldenCase, orchestrator) -> CaseResult:
    t0 = time.perf_counter()
    try:
        run_result: SpecRunResult = await orchestrator.run(case.description, case.repo)
    except Exception as e:
        return CaseResult(
            name=case.name,
            ok=False,
            duration_s=time.perf_counter() - t0,
            failures=[f"{type(e).__name__}: {e}"],
        )

    duration = time.perf_counter() - t0
    if not run_result.ok:
        return CaseResult(
            name=case.name,
            ok=False,
            duration_s=duration,
            failures=[f"preflight: {run_result.reason}"],
        )

    spec = run_result.spec
    assert spec is not None
    failures, warnings, metrics = validate_spec(spec, case)
    return CaseResult(
        name=case.name,
        ok=len(failures) == 0,
        spec=spec,
        workspace=run_result.workspace,
        duration_s=duration,
        failures=failures,
        warnings=warnings,
        metrics=metrics,
    )


async def run_eval(
    golden_dir: Path,
    project_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    settings = load_settings()
    orchestrator = create_orchestrator(settings)

    cases = [
        GoldenCase.from_file(p, project_root)
        for p in sorted(golden_dir.glob("*.json"))
    ]
    if not cases:
        raise FileNotFoundError(f"No golden cases found in {golden_dir}")

    results: list[CaseResult] = []
    for case in cases:
        r = await run_case(case, orchestrator)
        results.append(r)

    output_dir.mkdir(parents=True, exist_ok=True)

    aggregate = {
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok),
        "total_duration_s": sum(r.duration_s for r in results),
        "avg_duration_s": sum(r.duration_s for r in results) / max(1, len(results)),
        "avg_iterations": sum(
            r.metrics.get("iterations", 0) for r in results if r.spec
        ) / max(1, sum(1 for r in results if r.spec)),
        "needs_review_count": sum(
            1 for r in results if r.spec and r.metrics.get("needs_review")
        ),
        "missing_path_count_total": sum(
            r.metrics.get("missing_path_count", 0) for r in results
        ),
        "cases": [_case_to_dict(r) for r in results],
    }

    (output_dir / "report.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        _render_report_markdown(aggregate), encoding="utf-8"
    )

    return aggregate


def _case_to_dict(r: CaseResult) -> dict[str, Any]:
    return {
        "name": r.name,
        "ok": r.ok,
        "duration_s": r.duration_s,
        "failures": r.failures,
        "warnings": r.warnings,
        "metrics": r.metrics,
        "workspace": str(r.workspace) if r.workspace else None,
    }


def _render_report_markdown(agg: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Eval report")
    lines.append("")
    lines.append(f"- Total cases: {agg['total']}")
    lines.append(f"- Passed: **{agg['passed']}** ({agg['passed']/max(1,agg['total']):.0%})")
    lines.append(f"- Failed: {agg['failed']}")
    lines.append(f"- Avg duration: {agg['avg_duration_s']:.1f}s")
    lines.append(f"- Avg iterations: {agg['avg_iterations']:.2f}")
    lines.append(f"- Needs review count: {agg['needs_review_count']}")
    lines.append(f"- Missing referenced paths (total): {agg['missing_path_count_total']}")
    lines.append("")
    lines.append("## Per-case results")
    lines.append("| Case | OK | Iter | Duration | FRs | Stories | Issues |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for c in agg["cases"]:
        m = c["metrics"]
        status = "OK" if c["ok"] else "FAIL"
        issues = "; ".join(c["failures"]) or "-"
        lines.append(
            f"| {c['name']} | {status} | {m.get('iterations','?')} | "
            f"{c['duration_s']:.1f}s | {m.get('fr_count','?')} | "
            f"{m.get('user_story_count','?')} | {issues} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=Path("eval/golden_set"))
    parser.add_argument("--output", type=Path, default=Path("eval/reports"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    asyncio.run(run_eval(args.golden, args.project_root, args.output))
