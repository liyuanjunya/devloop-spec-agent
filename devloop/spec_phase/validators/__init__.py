"""Mechanical validators for spec artifacts.

These run alongside (and before/after) the LLM-driven review stages to
catch deterministic problems that LLMs are bad at: e.g. citations that
point to lines that don't exist, or symbols that aren't actually present
in the cited range.
"""

from devloop.spec_phase.validators.citation_verifier import (
    CitationProblem,
    verify_citation,
    verify_spec_citations,
)
from devloop.spec_phase.validators.coverage_gap_detector import (
    GAP_SINGLETON_CRITICAL,
    GAP_SPARSE_PERSPECTIVE,
    GAP_UNRESOLVED_CONFLICT,
    VALID_GAP_KINDS,
    CoverageGap,
    detect_coverage_gaps,
)
from devloop.spec_phase.validators.escalation import (
    EscalationProblem,
    find_underescalated_concerns,
)
from devloop.spec_phase.validators.test_executability import (
    PROBLEM_COLLECT_ERROR,
    PROBLEM_FIXTURE_NOT_FOUND,
    PROBLEM_IMPORT_ERROR,
    PROBLEM_NO_SUCH_FILE,
    TestExecutabilityProblem,
    extract_test_references,
    generate_stub_test_file,
    verify_spec_test_executability,
)
from devloop.spec_phase.validators.trace_matrix import (
    TraceGap,
    build_trace_matrix,
    find_trace_gaps,
)

__all__ = [
    "GAP_SINGLETON_CRITICAL",
    "GAP_SPARSE_PERSPECTIVE",
    "GAP_UNRESOLVED_CONFLICT",
    "PROBLEM_COLLECT_ERROR",
    "PROBLEM_FIXTURE_NOT_FOUND",
    "PROBLEM_IMPORT_ERROR",
    "PROBLEM_NO_SUCH_FILE",
    "VALID_GAP_KINDS",
    "CitationProblem",
    "CoverageGap",
    "EscalationProblem",
    "TestExecutabilityProblem",
    "TraceGap",
    "build_trace_matrix",
    "detect_coverage_gaps",
    "extract_test_references",
    "find_trace_gaps",
    "find_underescalated_concerns",
    "generate_stub_test_file",
    "verify_citation",
    "verify_spec_citations",
    "verify_spec_test_executability",
]
