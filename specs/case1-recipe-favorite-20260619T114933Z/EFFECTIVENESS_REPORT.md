# DevLoop Spec Phase — Effectiveness Report (Case 1: Recipe Favorites)

**Run**: `case1-recipe-favorite-20260619T114933Z`
**Target**: Mealie repo @ `4a099c1` (590 .py / ~50K LOC)
**Pipeline**: Stages 1–8 executed via Copilot CLI sub-agents (no real Anthropic/OpenAI calls)

---

## 1. Pipeline execution summary

| Stage | Sub-agents | Duration | Output |
|---|---|---|---|
| 1 — Repo skeleton | 0 (direct) | ~5s | `context/skeleton.md` |
| 2 — Intent (analyzer + skeptic + verifier) | 1 combined | 87s | `intent/confirmed.json` (confidence 0.96) |
| 3 — Exploration (5 perspectives parallel) | 5 in parallel | ~3 min wall | 5 × `*_perspective.md` |
| 3.5 — Consolidator | 1 | 247s | `exploration/consolidated.{md,json}` |
| 4+5 — Approach + Writer (combined) | 1 | 205s | `spec.md`, `spec.json`, `approach/selected.md` |
| 6 — 4 Reviewers in parallel | 4 in parallel | ~5 min wall | 4 × `review_v1_*.md` |
| **Total** | **12 sub-agent invocations** | **~15 min wall-clock** | **18 artifacts** |

---

## 2. The single most important system win

**The system caught that Mealie ALREADY has favorites implementation** — something the user's spec text did not acknowledge.

- Data explorer found: `mealie/db/models/users/user_to_recipe.py` (`UserToRecipe.is_favorite`)
- API explorer found: `mealie/routes/users/ratings.py` POST `/{id}/favorites/{slug}` already exists
- UI explorer found: `RecipeFavoriteBadge.vue`, `pages/user/[id]/favorites.vue` already exist
- Data explorer found migration: `2024-03-18-02.28.15_d7c6efd2de42_migrate_favorites_and_ratings_to_user_.py` consolidated favorites once already

→ Consolidator surfaced this as **Critical Conflict #1** ("Greenfield request vs existing favorites code")
→ Writer chose Conservative approach: reuse `UserToRecipe.is_favorite`, do not create a new table, add self-service write aliases + recipe response fields

**This is exactly the kind of "look before you leap" behavior a naive LLM running on just the user input would miss.**

---

## 3. Reviewer verdicts

All 4 reviewers verified findings against real Mealie code (read files, checked line ranges).

| Reviewer | Verdict | Critical | High | Medium |
|---|---|---|---|---|
| Architecture | NEEDS_REFINE | 0 | 3 | 3 |
| Completeness | NEEDS_REFINE | 3 | 5 | 5 |
| Executability | NEEDS_REFINE | 1 | 4 | 5 |
| Consistency | NEEDS_REFINE | 1 | 2 | 4 |
| **Total** | **needs_refine** | **5** | **14** | **17** |

### Critical issues caught (top 5)

1. **COMP-C-001** — i18n requirement totally missing from spec despite input §4 mandating it
2. **COMP-C-002** — 3-layer pattern coverage skips `services/user_services/`
3. **COMP-C-003** — Spec deviates from input's "新增 user_favorite_recipe 表" without escalating as blocking decision
4. **EXEC-C-001** — FR-006 defers `/api/users/self/favorites` compatibility decision to reviewer — code agent has no default direction
5. **CONS-C-001** — US-3 AC1 ("paginated recipe-summary") contradicts US-3 AC4 + Assumption ("retain rating-summary alias")

### Architecturally surgical findings (verified against real code)

- **ARCH-H-001**: Anonymous reads target the wrong controller. `/api/recipes` is gated by `UserAPIRouter`+`BaseUserController`. The actual anonymous path is `PublicRecipesController` in `mealie/routes/explore/controller_public_recipes.py:20-125` which FR-007/FR-009 never reference
- **ARCH-H-002**: `column_aliases` is not a projection extension point — only consumed at `repository_generic.py:370` (queryFilter) and `:414` (order by), never in SELECT. Following FR-008 verbatim would yield sortable/filterable fields that never appear in JSON response
- **ARCH-H-003**: Asymmetric cleanup — `_delete_recipe` already cleans `UserToRecipe`; `RepositoryUsers.delete` does not, and FK has no `ondelete`

### Drift / verification failures the reviewer caught

- `pagination.py:32-49` does NOT contain `PaginationBase` (starts at L51)
- `repository_generic.py:104-179` cited for `_filter_builder` — actually at L94-102
- `fixture_recipe.py:16-131` — file only has 103 lines
- `test_multitenant_cases.py:1-94` — file only has 74 lines
- spec.md vs spec.json disagreement on code_references for FR-002, FR-005, FR-006, FR-008, FR-011

---

## 4. What the system did right

✅ **Correct intent identification** — confirmed primary intent + 4 excluded hypotheses with grounded reasons; confidence 0.96
✅ **Parallel multi-perspective exploration** — 5 explorers in parallel completed in ~3 min wall, each rigorously cited real files
✅ **Conflict surfacing** — Consolidator caught 5 critical conflicts including the "existing favorites" discovery
✅ **Sound architectural choice** — Writer correctly picked Conservative (reuse) over Aggressive (new table) given evidence
✅ **High-quality spec structure** — 6 user stories with P1/P2 priorities, 11 FRs all with code_references, 7 SCs with measurable thresholds, 8 edge cases, 5 assumptions, 6 out-of-scope items, 4 honest self_concerns
✅ **Rigorous reviewers** — all 4 reviewers verified line ranges against real code, caught spec/JSON drift, identified architecturally surgical issues

---

## 5. What the system did wrong

❌ **Sub-agents that DON'T have `create`/`edit` tools** (e.g., `explore` agents) didn't auto-save their reports — had to manually write their text to disk. Fixable by using `general-purpose` agents (which have full tools) for any stage that must produce file outputs

❌ **Writer missed i18n requirement** (input §4 explicit) — completeness reviewer caught this
❌ **Writer missed `services/user_services/` layer** (input §4 explicit) — completeness reviewer caught this
❌ **Writer left a "reviewer decides compatibility" placeholder** in FR-006 — executability reviewer correctly called this a blocker for a code agent
❌ **Spec.md vs spec.json drift** on code_references for 5 different FRs
❌ **Several cited line ranges are wrong** (off by 1-30 lines)
❌ **Anonymous-read controller misidentified** (`/api/recipes` vs `PublicRecipesController`) — architecture reviewer caught with surgical precision

---

## 6. Recommended next step (V2 = a real production version)

The current run stopped at "Stage 6 reviewers report needs_refine". In the v7 design, this would trigger:

- **Stage 7 — Rewriter**: take all 5 critical + 14 high issues and produce spec v2
- **Stage 8 — Reviewers re-run** (same 4 angles): see if v2 converges
- **Stage 9 — Persist** if PASS, or `needs_review=True` if stuck

For this test we stopped at v1 to show the reviewers' raw output. Running v2 would address the 5 critical issues (i18n, services/, deviation escalation, compatibility decision, US-3 contradiction).

---

## 7. Evaluation table (case 1 scorecard)

| 维度 | 记录 |
|---|---|
| Spec 完整度 (1-5) | **4** — Caught existing-code conflict and architectural fit; missed i18n + services/ layer (caught by reviewer) |
| Coding 测试一次通过 | n/a — pipeline stopped at spec phase by design |
| Coding 是否破坏既有测试 | n/a |
| 多 agent CR 提出的有效问题数 | **36** (5 critical + 14 high + 17 medium) across 4 reviewers, all verified against real code |
| 人工 CR 补充发现的问题数 | TBD (need user judgment) |
| 备注 | Mock-mode pipeline using Copilot CLI sub-agents (no real Anthropic/OpenAI API calls). Major win: caught the existing `UserToRecipe.is_favorite` model that the user's spec text didn't acknowledge. 12 sub-agent invocations in ~15 min wall-clock. |

---

## 8. Three考察点 (from case file)

| 环节 | 关注点 | System 表现 |
|---|---|---|
| Spec | 是否识别"既要新建实体也要扩展已有 recipe 响应"双重需求？是否预判到 N+1？是否提到 multitenant？ | ✅ All three caught: US-1/US-2/US-3 (entity work) + US-4 (recipe response) + FR-009 (no N+1, with measurable SC-004) + FR-011 explicitly references multitenant tests |
| Coding | (n/a — out of scope) | n/a |
| CR | 是否指出未登录时 `favorited` 必须恒为 false 漏测？DELETE 幂等性？用户级收藏数上限？删除 user 时是否级联清理？ | ✅ All 4 caught: COMP-H-001 (cascade on user delete), CONS-H-001 (anonymous favorited contradiction), idempotency in FR-003/FR-004, count semantics in CONS-M-001 |

---

## Files to inspect

```
specs/case1-recipe-favorite-20260619T114933Z/
├── input.md                          ← What you fed in
├── intent/
│   ├── confirmed.json                ← intent + 4 excluded hypotheses
│   └── trace.md                      ← analyzer/skeptic/verifier full trace
├── exploration/
│   ├── consolidated.{md,json}        ← merged + 5 conflicts identified
│   ├── data_perspective.md
│   ├── api_perspective.md
│   ├── test_perspective.md
│   ├── history_perspective.md
│   └── ui_perspective.md
├── approach/
│   └── selected.md                   ← Conservative wins (reuse UserToRecipe)
├── spec.md                           ← ★ The produced spec (human-readable)
├── spec.json                         ← The produced spec (machine-readable)
└── spec_iterations/
    ├── review_v1_architecture.md     ← 0 critical + 3 high + 3 medium
    ├── review_v1_completeness.md     ← 3 critical + 5 high + 5 medium
    ├── review_v1_executability.md    ← 1 critical + 4 high + 5 medium
    └── review_v1_consistency.md      ← 1 critical + 2 high + 4 medium
```
