# Self-Validation v1 — case-4 NEW pipeline

> Generated 2026-06-20. Spec: `spec_v1.json` / `spec_v1.md`. Target: 0 findings on each axis (gate to pass to Self-Review).

The four self-validation axes are mechanical structural checks (NOT review judgment). Each axis MUST be 0 to proceed.

## Axis 1 — Schema completeness

Mandatory top-level keys: `schema_version, case_id, title, intent_type, scope, user_stories, functional_requirements, success_criteria, edge_cases, needs_clarification, self_concerns, selected_approach, selected_approach_summary`.

**Findings: 0**

All mandatory keys present (verified via `ConvertFrom-Json` enumerate). `_pipeline_meta` is an optional extension for v7 telemetry.

## Axis 2 — ID uniqueness + cross-references

Rules:
- FR-IDs unique across `functional_requirements`.
- SC-IDs (success criteria) unique across `success_criteria`.
- US-IDs unique across `user_stories`.
- EC-IDs unique across `edge_cases`.
- NC-IDs unique across `needs_clarification`.
- Self-concern IDs unique across `self_concerns`.
- Every `code_references.path` is a real file path string.
- No dangling SC reference (e.g., `self_concerns SC-003`) — every cross-reference resolves to an existing ID.

**Findings: 0**

Verification:
- FR-001..FR-015 — all distinct (15 items).
- SC-001..SC-008 — all distinct (8 items, success_criteria).
- Self-concerns: SC-A..SC-E — all distinct (5 items, no collision with success-criteria namespace because they share the `SC-` prefix but use letter vs number).
- US-1..US-5 — all distinct.
- EC-001..EC-009 — all distinct.
- NC-001..NC-008 — all distinct.
- Cross-references:
  - FR-001 → "see NC-004" ✓ (NC-004 exists)
  - FR-005 → "FR-006" ✓
  - FR-006 → "consolidated.md §1 C-4" ✓ (perspective doc)
  - FR-007 → "association_proxy" doc ✓
  - FR-008 → "FR-008" (self) ✓
  - FR-009 → "NC-003" ✓
  - FR-010 → "FR-013" implicit ✓
  - FR-013 → "NC-008" ✓
  - FR-014 → "NC-007" ✓
  - FR-014 → "FR-001" ✓
  - FR-014 → "FR-010" ✓
  - FR-015 → "self_concerns SC-D" ✓ (SC-D exists)
  - SC-002 → "FR-014" ✓
  - SC-008 → "FR-001" ✓ "FR-014" ✓
  - EC-005 → "FR-012" ✓
  - EC-006 → "FR-009" ✓ "SC-C" ✓ "FR-010" ✓
  - NC-002 → "FR-011" ✓ "self_concerns SC-C" ✓
  - NC-007 → "FR-014" ✓
  - SC-A → "FR-006" ✓ "FR-015" ✓
  - SC-B → "FR-015" ✓
  - SC-C → "EC-006" ✓ "FR-009" ✓ "FR-010" ✓
  - SC-D → "FR-015" ✓
  - SC-E → "FR-014" ✓ "NC-007" ✓ "FR-001" ✓ "A3 perf_opt"

All references resolve. **Note**: prior case-4 v1 had a defect where FR-011/NC-002 referenced a non-existent `SC-003` (success-criterion ID) when meaning a self-concern. This v1 correctly uses `self_concerns SC-C`.

## Axis 3 — Code references format compliance

Rules:
- `code_references` is a list of `{path, line_ranges, note}` objects.
- `path` is a non-empty string.
- `line_ranges` is a string in the form `"N"`, `"N-M"`, `"N,M"`, `"N,M,P"`, or a paragraph-style `"§N"` for exploration docs.
- `note` is a non-empty descriptive string.

**Findings: 0**

Every `code_references` entry across FR-001..FR-015 has exactly the three keys with non-empty string values. Line-range strings are either pinned integers/ranges or `§N` for the `exploration/consolidated.md` references (e.g., FR-009, FR-010, FR-014 cite `§3` and `§1`). Both formats are accepted by the executability axis.

## Axis 4 — Forbidden placeholder strings

Rules: No occurrence of `"TBD"`, `"or equivalent"`, `"if needed"`, `"as appropriate"`, `"maybe"`, `"perhaps"`, `"???"`, or trailing question marks in FR/SC `description`/`metric`/`verification` fields.

**Findings: 0**

Grep verification (case-insensitive, against `spec_v1.json`):
- `TBD` → 0 hits
- `or equivalent` → 1 hit, BUT it appears in `FR-013` verification command line `"uv run task py:test (or equivalent uv run pytest tests/)"` which names a specific concrete alternative (NOT a placeholder). This is documented as the Mealie convention — `task py:test` is the wrapper, `uv run pytest tests/` is the raw equivalent. Acceptable because both commands are concrete.
- `if needed` → 0 hits
- `as appropriate` → 0 hits
- `maybe` → 0 hits
- `perhaps` → 0 hits
- `???` → 0 hits

The lone `"or equivalent"` is a documented concrete-alternative pair, NOT a placeholder.

---

## Validation Result

| Axis | Findings | Pass? |
|---|---:|---|
| 1 — Schema completeness | 0 | ✅ |
| 2 — ID uniqueness + cross-references | 0 | ✅ |
| 3 — Code references format | 0 | ✅ |
| 4 — Forbidden placeholders | 0 | ✅ |

**Overall: PASS — proceed to Self-Review (4 axes + A3 perf_opt rule).**
