# Approach Candidates — Case 3 (Meal Plan → Shopping List Consolidation Bug)

> Three candidate strategies for the minimum fix. Common goals: make the `US-1` reproduction test pass, keep the 4 regression tests green, and avoid regressing the existing tests at `test_group_shopping_lists.py:177-247, 581-739`.

---

## Candidate 1 — Conservative: smallest patch inside the broken consolidation function(s)

### Description
Restore the canonical `(food_id, unit_id)` merge key in `ShoppingListService.can_merge` (`mealie/services/household_services/shopping_lists.py:45-71`) and the `to_item.quantity += from_item.quantity` accumulator in `ShoppingListService.merge_items` (line 96). No new helpers, no extracted methods, no wrapper. The fix is whichever of these two lines was broken (per the injection patch variants in input.md附录).

Concretely:
- If `can_merge` was using `display` or `note` as the key for items with a `food_id`, revert to `item1.food_id == item2.food_id` (plus the existing unit check).
- If `merge_items` was using `=` instead of `+=`, restore `+=`.
- Touch at most 2 lines across both functions.

### Evaluation
| Criterion | Score | Notes |
|---|---|---|
| Bug coverage | High | Directly addresses both bug-injection variants; symmetric to the reported symptom (undercount OR unmerged duplicate rows). |
| Blast radius | Very low | 1-2 lines inside well-isolated predicate/merger; no public-API change; no schema change. |
| Test cost | Low | The 4 required regressions + 1 repro all use the existing `POST /recipe` endpoint; no new HTTP route helper needed. |
| Future-proofing | Medium | Restores correctness but does not add structural defenses. A future regression could re-introduce the same bug if a contributor edits `can_merge` / `merge_items` without reading the regression tests. |
| Drift from input intent | None | input.md explicitly says "只修改导致 bug 的最小代码范围 (理想 1-3 个函数, 几十行)" and "不要重构周边代码". |

---

## Candidate 2 — Defensive: add a wrapper around consolidation + a dedicated test seam

### Description
Keep the fix from Candidate 1 AND introduce a thin wrapper / helper that makes consolidation observable and testable in isolation. For example: extract the in-pass-1 in-memory consolidation loop from `bulk_create_items` lines 162-176 into a separate `_consolidate_create_items(items: list[ShoppingListItemCreate]) -> list[ShoppingListItemCreate]` method on `ShoppingListService`, and add a unit test that asserts the consolidated list contains exactly one entry per `(food_id, unit_id)` for a duplicate-ridden input.

This adds an explicit seam for unit-level testing without going through HTTP/DB, complementing the integration tests.

### Evaluation
| Criterion | Score | Notes |
|---|---|---|
| Bug coverage | High | Same as Candidate 1 for the bug; extra unit test catches future regressions earlier in the pipeline. |
| Blast radius | Low-Medium | A new public/protected method on the service. No schema change, but other callers might start using the seam in unintended ways. |
| Test cost | Medium | Adds a new unit test file (`tests/unit_tests/services/test_shopping_list_consolidation.py`?), plus the 4 required integration regressions. |
| Future-proofing | High | The seam plus a unit test create durable documentation of the merge-key + accumulation invariants. |
| Drift from input intent | Medium | input.md says "不要重构周边代码" — extracting a method is a small refactor, even if low-risk. Acceptable but on the edge. |

---

## Candidate 3 — Comprehensive: refactor consolidation key handling + add invariant checks

### Description
Refactor the merge key into an explicit `MergeKey` value object (e.g. `frozenset({food_id, unit_id, note_fallback})`), replace the ad-hoc `can_merge` boolean predicate with a `_merge_key(item)` helper, switch the O(N²) consolidation loops in `bulk_create_items` and `bulk_update_items` to dict-keyed `O(N)` aggregations, and add post-condition `assert` checks (or invariant validators) that every `(food_id, unit_id)` pair appears at most once after consolidation. Add a property-based / hypothesis test that randomizes recipes and asserts the invariant.

### Evaluation
| Criterion | Score | Notes |
|---|---|---|
| Bug coverage | High | Eliminates the entire class of merge-key bugs by construction. |
| Blast radius | High | Touches `can_merge`, `merge_items`, `bulk_create_items`, `bulk_update_items`, and possibly `get_shopping_list_items_from_recipe`. Behavioral change risk on `note`-only and standard-unit fallback paths; needs careful re-testing against all of `test_group_shopping_lists.py` and `test_group_shopping_list_items.py`. |
| Test cost | High | New unit + integration + property-based tests; risk of finding latent issues that expand scope. |
| Future-proofing | Very high | Codifies invariants in code, not just in tests; algorithmically faster on large lists. |
| Drift from input intent | Very high | Direct contradiction of "只修改导致 bug 的最小代码范围", "不要重构周边代码", and "必须遵循 mealie 既有的 RepositoryShoppingItem / ShoppingListItem schema". Also conflicts with grounding §8 which already flags this file as complex — refactoring it is exactly the kind of broad change the case forbids. |

---

## Recommendation matrix

| Criterion | Conservative | Defensive | Comprehensive |
|---|---|---|---|
| Bug coverage | High | High | High |
| Blast radius | **Very low** | Low-Medium | High |
| Test cost | **Low** | Medium | High |
| Future-proofing | Medium | **High** | Very high |
| Matches input intent | **Yes (strict)** | Borderline | **No** |
| Risk of regressing #5054, #7121, #4800 | **Very low** | Low | Medium |

The Conservative approach is the strict match for input intent and lowest-risk. The Defensive approach is attractive if the team wants a durable seam, but the input explicitly forbids surrounding refactors. The Comprehensive approach is excluded — it contradicts at least three explicit constraints in input.md.

→ See `selected.md` for the chosen approach and rationale.
