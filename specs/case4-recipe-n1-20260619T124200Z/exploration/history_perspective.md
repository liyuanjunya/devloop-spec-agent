# History Perspective — Case 4 (Recipe list N+1 refactor)

> Scope: `mealie/repos/repository_recipes.py`, `mealie/repos/repository_generic.py`,
> `mealie/services/recipe/`, `mealie/schema/recipe/recipe.py`, plus cross-cutting
> commits that touched eager-loading, the `loader_options()` pattern, pagination
> arithmetic, and the `RecipeSummary` response shape.
>
> Source: `git --no-pager log` in `C:\Users\v-liyuanjun\Downloads\mealie\`
> (current HEAD: `c3f87736 feat: In-app AI Provider Configuration (#7650)`).

---

## TL;DR (read this first)

1. **The "naive lazy-load" baseline the spec posits does not exist on `main`.**
   Mealie already adopted the `loader_options()` pattern in 2024 and *currently*
   eager-loads `recipe_category`, `tags`, `tools`, and `user` on the
   `GET /api/recipes` query (see `RecipeSummary.loader_options()` in
   `mealie/schema/recipe/recipe.py:168-175`, applied from
   `mealie/repos/repository_recipes.py:276-277`). The remaining N+1 risk is more
   subtle (see §3).
2. **The "apply options late" trick — applying `.options(...)` *after*
   `add_pagination_to_query()` — is a load-bearing invariant** (introduced in
   `ba363da2`). Any refactor that re-applies loader options before paging will
   break the COUNT query and silently inflate `total` / `total_pages`.
3. **Three recent commits make the response shape and pagination contract
   *unusually* fragile right now**: `7b325082` (correct pagination count),
   `d02023e1` (`household_id IS NOT NULL` filter on recipes only),
   `216ae857` (last-made ordering with nulls). All three would regress if a
   careless eager-load refactor changes the COUNT subquery shape.
4. **Spec mentions `comments_count` as one of the N+1 victims, but no such
   field currently exists in the response.** Grep for
   `comment_count|comments_count|commentsCount` finds only the query-filter
   keyword in `mealie/schema/static/recipe_keys.py:41` (`comment_count = "commentCount"`).
   The N+1 fix must decide: (a) add the column-as-aggregate (new field — breaks
   "100% field-stable" promise unless the field is already on the wire), or
   (b) document that no `comments_count` is exposed today.

---

## 1. Top 15 commits (most relevant first)

Listed in **relevance order**, not chronological. All hashes verified via
`git log` on `c3f87736`.

| # | Hash | Subject | Why it matters for this task |
|---|------|---------|------------------------------|
| 1 | `ba363da2` | `chore: Optimize Loads on Queries (#4220)` (Sep 2024, M. Genson) | **Direct precedent.** Removed the inline `joinedload(...)` block in `RepositoryRecipes.page_all` and introduced `RecipeSummary.loader_options()` (returning `joinedload` for `recipe_category`, `tags`, `tools`, `user.load_only(household_id)`). Crucially moved the `.options(...)` call to **after** `add_pagination_to_query()` so loader joins don't poison the COUNT subquery. The current N+1 fix lives or dies on the same trick. |
| 2 | `4b426ddf` | `Remove all sqlalchemy lazy-loading from app (#2260)` (Mar 2023, Sören) | **Foundational precedent.** Eradicated implicit lazy loads from serialization across the app (`+354 / −145` lines, 23 files). Commit message explicitly notes "try using `selectinload` a bit more instead of `joinedload`" — this is the precedent for swapping M2M loaders. |
| 3 | `49bd420c` | `fix: all recipes performance regressions (#2062)` (Jan 2023, Sören) | First "all recipes is slow" fix. Split validators between `Recipe` and `RecipeSummary` so the summary path does not pay validation cost. Touched the exact three files this task targets. |
| 4 | `7b325082` | `fix: the add_pagination_to_query now always returns the correct count (#6505)` (Dec 2025, A. Pautet) | **High-risk dependency.** Reworked the count subquery so it returns the correct `total` when joins inflate rows. Any new `joinedload` on a *-to-many relationship before `.add_pagination_to_query` will resurrect the original bug. |
| 5 | `d02023e1` | `fix: Only fetch recipes with a household id (#6773)` (Dec 2025, M. Genson) | **Multitenant correctness.** Added `q.filter(RecipeModel.household_id.is_not(None))` to `page_all`. Spec requires "household_id filter must still apply" — this is exactly the filter being protected. |
| 6 | `216ae857` | `fix: Include unmade recipes when filtering by last made (#7130)` (Feb 2026, M. Genson) | Recently touched `repository_recipes.py` (+9 lines) for null handling on `last_made`. The `_get_last_made_col_alias` correlated subquery (`repository_recipes.py:54-70`) is exactly the kind of "per-recipe extra query" that *looks* like N+1 to a sql trace but is actually a single correlated subquery — be careful in the new perf test about counting it. |
| 7 | `2a541f08` | `feat: User-specific Recipe Ratings (#3345)` (Apr 2024) | Introduced the `_get_rating_col_alias` correlated `EXISTS`+`SELECT MAX` (`repository_recipes.py:72-93`). Pattern precedent: per-recipe aggregates implemented as **correlated scalar subqueries on the main `SELECT`** rather than joins. This is the right template for any new `comments_count`-style aggregate. |
| 8 | `e9892aba` | `feat: Move "on hand" and "last made" to household (#4616)` (Sep 2024) | Reshaped `HouseholdToRecipe` and rewrote the `last_made` lookup as a household-scoped correlated subquery. Sets the architectural precedent that "computed per-row fields are subqueries, never lazy-loaded relationships". |
| 9 | `c029a639` | `fix: preserve stored recipe slugs during hydration (#7294)` (Mar 2026) | Most recent touch to `repository_recipes.py` (+8 lines) and `schema/recipe/recipe.py` (+2 lines). Establishes the "slug" contract — any change to recipe serialization paths must preserve hydration order. |
| 10 | `26924ab0` | `fix: #6802 prevent 500 internal server error when patching recipe tags (#6803)` (Mar 2026) | Recent +10 lines to `repository_recipes.py` for tag-patch durability. Hints that tag write paths share session state with the read paths the new perf test will instrument — be aware when adding query counters. |
| 11 | `987c7209` | `feat: Query relative dates (#6984)` (Feb 2026) | Refactored `QueryFilterBuilder` out of `response/` into `services/query_filter/`. `repository_recipes.py` import on line 30 (`from mealie.services.query_filter.builder import QueryFilterBuilder`) and `repository_generic.py` line 28 reference it. Any test that mocks the filter pipeline must import from the new path. |
| 12 | `642c826f` | `fix: Protect sensitive data in query filter API (GHSA-8m57-7cv5-rjp8) (#7629)` (May 2026) | Added `_filterable_column` allow-list on ORM models. The N+1 fix must not introduce a new column that the filter API exposes without going through this allow-list. |
| 13 | `64d8786d` | `fix: Improve recipe bulk deletion (#6772)` (Dec 2025) | Restructured `RecipeService` and `recipe_bulk_service`. The spec mentions `mealie/services/recipe/` as an alternative refactor site — that surface has just been reshuffled, so prefer the repo-layer fix. |
| 14 | `327da02f` | `feat: Structured Yields (#4489)` (Nov 2024) | Added `recipe_servings`, `recipe_yield_quantity` fields onto `RecipeSummary` (now at `schema/recipe/recipe.py:127-129`). Demonstrates the "response shape add" change pattern (also requires `task dev:generate` to update `frontend/app/lib/api/types/recipe.ts`). |
| 15 | `7a107584` | `feat: Upgrade to Pydantic V2 (#3134)` (Aug 2024) | Why every list-recipes response goes through `orjson.dumps(pagination_response.model_dump(by_alias=True))` (`recipe_crud_routes.py:392`) instead of Pydantic's response serializer — the comment "Response is returned directly, to avoid validation and improve performance" (line 394) is the *reason* the repo currently `model_validate`s but the route bypasses route-level validation. |

### Bonus prior-art commits worth a glance

- `9d35b092` — `fix performance issues on /api/foods (#2163)` — sibling refactor for the foods list; same technique.
- `15c6df88` — `perf: use score_cutoff for fuzzy string matching (#2553)` — search perf, may show up in query counts if a `search=` term is passed.
- `7d4a379f` — `feat: improve database indexing (#2104)` — sets the index baseline; the new perf test should not assume any *additional* index beyond what is here unless an alembic migration is added.
- `9e77a9f3` — `prs-fleshgolem-2070: feat: sqlalchemy 2.0 (#2096)` — confirms the codebase is on SA 2.x, so `selectinload` IN-clause batching is the modern default (one extra query per relationship, regardless of N).

---

## 2. Prior N+1 fixes — adopted precedent

Mealie has already absorbed the eager-loading playbook in three waves. Any new
fix should match these conventions or be ready to justify the deviation in PR.

### 2.1 The `loader_options()` classmethod (the canonical pattern)

Set in `ba363da2`, used by every paginated endpoint in the app. Reference
implementations:

- **`RecipeSummary.loader_options()`** — `mealie/schema/recipe/recipe.py:168-175`

  ```python
  @classmethod
  def loader_options(cls) -> list[LoaderOption]:
      return [
          joinedload(RecipeModel.recipe_category),
          joinedload(RecipeModel.tags),
          joinedload(RecipeModel.tools),
          joinedload(RecipeModel.user).load_only(User.household_id),
      ]
  ```

- **`Recipe.loader_options()`** — `mealie/schema/recipe/recipe.py:299-320`
  (full recipe — uses a *mix* of `selectinload` for collections and
  `joinedload` for one-to-one) — note the inline comment on line 318:
  > "for whatever reason, joinedload can mess up the order here, so use
  > selectinload just this once"
  …which is exactly the kind of empirical caveat the new test must enforce.

### 2.2 The "apply options late" invariant

Applied in `mealie/repos/repository_recipes.py:276-277`
and `mealie/repos/repository_generic.py:339-342`:

```python
q, count, total_pages = self.add_pagination_to_query(q, pagination_result)
# Apply options late, so they do not get used for counting
q = q.options(*RecipeSummary.loader_options())
```

Why: `add_pagination_to_query` (`repository_generic.py:357-405`) builds the
`COUNT(*)` from `query.order_by(None).distinct().subquery()`. If the eager
joins are on the query at that point, the subquery contains the join rows
and the `distinct()` masks but does not always eliminate inflation — see
`7b325082` for the fallout. Any new `selectinload` calls must be applied
**after** line 274 / line 339, not before.

### 2.3 The "computed-field as correlated subquery" pattern

For per-recipe values that aren't simple relationships (rating, last_made),
Mealie uses correlated scalar subqueries hung off `column_aliases` on the
repository:

- `_get_last_made_col_alias` — `repository_recipes.py:54-70`
- `_get_rating_col_alias`   — `repository_recipes.py:72-93`

…wired into `column_aliases` at `repository_recipes.py:39-47`. These produce
**one query total** (the main SELECT pulls them as scalar subqueries per
returned row, evaluated by the DB in a single statement). This is the
correct template for any new aggregate like `comments_count`.

### 2.4 Sibling-entity precedents (look here for "we already did this")

- `mealie/repos/repository_foods.py` — `9d35b092` made foods O(1) with the same trick.
- `mealie/repos/repository_users.py` — `4b426ddf` touched it (+3 lines).
- `mealie/repos/repository_generic.RepositoryGeneric.page_all`
  (`repository_generic.py:309-355`) is the canonical "do it right" version
  the recipe override deviates from only for cookbook + organizer + search +
  household quirks.

---

## 3. Recent response-shape changes — contract-preservation risk register

Spec demands **"API response JSON fields, order, content, and pagination
behavior: zero change."** These are the items that have moved or will move
under the refactor's feet.

| Risk | Where | Why it matters |
|------|-------|----------------|
| **`RecipeSummary` field set is *de facto* the wire contract** | `mealie/schema/recipe/recipe.py:116-175` | Route is `response_model=PaginationBase[RecipeSummary]` (`recipe_crud_routes.py:340`), but the actual body is built via `orjson.dumps(pagination_response.model_dump(by_alias=True))` (line 392), bypassing FastAPI's response filter. **Whatever is on `RecipeSummary` ships, by_alias.** Adding a field there ships it; the spec's "fields unchanged" rule prohibits this. |
| **No `comments_count` field exists today** | grep across `mealie/`, `frontend/app/` | The spec lists "最近评论数" / "comments_count" as a victim. There is no such field on `RecipeSummary` and the frontend never reads it. **Either (a) drop "comments_count" from scope, or (b) add it and update the contract — both choices must be justified explicitly in the PR.** |
| **`recipe_servings`, `recipe_yield_quantity` are recent and frontend-coupled** | Added by `327da02f` (Nov 2024), `schema/recipe/recipe.py:127-128` | Their default is `0` (not `null`) via `clean_numbers` validator (line 151-153). Any path that bypasses `model_validate` (e.g. raw SQL → dict) will silently change `null` → `0` or vice versa. The frontend reads them via `RecipePageInfoCard.vue`. |
| **`rating` is now a computed alias, not the raw column** | `_get_rating_col_alias` (`repository_recipes.py:72-93`), wired into `column_aliases` at line 47 | When `by_user(user_id)` is called (which `recipe_crud_routes.py:370` does), the `rating` ORM attribute on the row is replaced with the computed effective rating (user rating if present, else recipe rating, else `None`). **A raw-SQL refactor that re-reads `RecipeModel.rating` directly will regress per-user rating display.** |
| **`last_made` is a household-scoped subquery, not a column** | `_get_last_made_col_alias` (`repository_recipes.py:54-70`); commit `216ae857` | Returns `coalesce(subquery, 1900-01-01 UTC)` — the *date floor* is part of the contract for ordering. A new aggregate that re-implements this differently will change `ORDER BY last_made` results. |
| **`add_pagination_to_query` returns `count` from a `distinct().subquery()`** | `repository_generic.py:376` | If the new perf test issues `selectinload`, those are separate `SELECT ... WHERE id IN (...)` statements — fine. But if a developer reaches for `joinedload` on a many-side relationship and forgets the "apply late" rule, `count` jumps and `total_pages` regresses. |
| **`recipe_yield: str \| None` has a `clean_strings` validator that stringifies numbers** | `schema/recipe/recipe.py:155-162` | If the new SQL path bypasses Pydantic validation, an integer in the DB will ship as a number instead of a string. |
| **`set_pagination_guides` builds `next` / `previous` URLs from query params** | `recipe_crud_routes.py:386-390` | This response key must remain wire-stable. Any refactor that changes the order of `query_params` will reorder URL params (JSON-equivalent but byte-diff-noisy). |
| **Pydantic V2 aliases (`orgURL`)** | `schema/recipe/recipe.py:141` (`org_url: ... = Field(None, alias="orgURL")`) | `model_dump(by_alias=True)` is required to emit `orgURL`. Any new aggregate field should consciously decide on snake_case vs alias to match the rest of the wire. |
| **Recent `c029a639` (slug preservation) updated `_query_one` semantics** | `repository_recipes.py` ±8 lines | Reads done through `_query_one` rely on the new slug-keep behavior. The N+1 refactor should keep using the same `_query_one`/`_query` plumbing rather than bypass it. |
| **`d02023e1` (Dec 2025) added `RecipeModel.household_id.is_not(None)` to `page_all`** | `repository_recipes.py:238` | The `is_not(None)` is now part of the security filter — required to prevent cross-household leakage. The N+1 rewrite must preserve it. |

---

## 4. Cross-perspective questions (for the UI/spec/coding rounds)

> Tag the answer owner explicitly when you bring this to the joint review.

1. **`comments_count` reality check (UI + Spec)** — The spec lists it as one
   of the N+1 victims, but it's not in the current `RecipeSummary` schema and
   no frontend code reads it. Do we (a) drop it from scope, or (b) actively
   add it as a new field (which violates the "100% field-unchanged" rule
   unless we get an explicit waiver)? Pulling in the UI perspective will
   clarify whether any card variant *should* show a comment count.
2. **`joinedload` → `selectinload` swap is the obvious win, but does it
   change ordering? (Coding)** — Current `loader_options()` uses
   `joinedload(RecipeModel.tags)` etc. With `limit/offset`, joinedload on
   many-to-many forces SA to wrap in a subquery (the current `.unique().all()`
   handles dedup). Swapping to `selectinload` issues 1 extra `WHERE id IN (...)`
   per relationship — better for pagination but ordering of the *child*
   collection (e.g. tags within a recipe) is no longer guaranteed by the
   parent's `ORDER BY`. The schema's `Recipe.loader_options()`
   (`schema/recipe/recipe.py:299-320`) already chose `selectinload` for
   collections except `recipe_category` (kept as `joinedload`) — what was the
   rationale, and does it apply here?
3. **Query-count test: what counts as "a query"? (Coding + Spec)** — The
   spec proposes `event.listens_for(engine, "before_cursor_execute")`. But:
   - `_get_rating_col_alias` is a correlated subquery — does **not** produce
     extra cursor executes.
   - `selectinload` *does* produce 1 extra cursor execute per loaded
     relationship.
   - `add_pagination_to_query` always issues a separate `COUNT(*)` query.
   - The `cookbook` lookup (`recipe_crud_routes.py:362`) is a separate query.

   The "≤ 5 queries" budget in the spec needs to spell out which of these are
   counted (the baseline is probably *not* 1 query even after a perfect fix).
4. **Multitenant filter integrity under `selectinload` (CR)** — When
   `selectinload(RecipeModel.tags)` fires, it issues `SELECT … FROM tag WHERE
   id IN (...)` *without* the recipe's group/household filter. If a tag is
   shared across groups (legal — see `RecipeTag.group_id` nullability at
   `schema/recipe/recipe.py:63`), no leakage occurs because we're loading
   tags *for already-filtered recipes*. But the test in
   `tests/multitenant_tests/` must explicitly assert that recipes from group
   B do not appear when listing group A's recipes — this is independent of
   N+1 but coupled by the refactor risk.
5. **Where does the new test plug in? (Coding)** —
   `tests/multitenant_tests/` exists but uses a `case_*.py` parametrized
   pattern with `test_multitenant_cases.py` as the entry. The spec asks for
   `tests/integration_tests/test_recipe_list_query_count.py` — there's
   already a deep `tests/integration_tests/user_recipe_tests/` subtree;
   confirm whether the new file goes at the top level or under the subtree
   (latter is more consistent with existing layout).
6. **`pagination_response.set_pagination_guides` makes a route URL lookup —
   is that a SQL query? (Coding)** — No, but worth confirming during the
   perf-test run that no other dependency injection (e.g. user resolution)
   wakes up a session and adds queries to the count.
7. **What was the actual prod report? (Spec)** — Spec says "obvious latency
   with >100 recipes" but the codebase already eager-loads tags/categories/
   tools. The realistic remaining N+1 candidates are:
   - **`user` lookup** — currently eager (`.load_only(household_id)`), so
     fine.
   - **`comments_count`** — not in response, so not actually an N+1.
   - **`image` metadata** — `image: Any | None` on `RecipeSummary:126` is
     just an integer/string column on `RecipeModel`, no extra query.
   - **`households_with_tool` on each `RecipeTool`** — `RecipeTool` schema
     (`schema/recipe/recipe.py:83-95`) includes `households_with_tool: list[str]`
     populated by a `field_validator`. **This is the most likely real culprit
     — every tool serialization can trigger a per-tool lookup of
     `households_to_tools`.** Worth confirming before the coding phase
     commits to a fix shape.

---

## 5. One-paragraph history summary (for the joint design doc)

Between `49bd420c` (Jan 2023) and `ba363da2` (Sep 2024) Mealie refactored every
paginated endpoint to use a per-schema `loader_options()` classmethod, apply
eager loads *after* the COUNT subquery, and surface computed per-row values
(rating, last_made) as correlated scalar subqueries rather than relationship
hydration. The `GET /api/recipes` path follows that pattern today
(`repository_recipes.py:220-293` + `schema/recipe/recipe.py:168-175`), so the
remaining N+1 budget is narrow: the most plausible regressions are
many-to-many `joinedload` × `LIMIT` cartesian inflation (mitigated by `.unique()`
but expensive at scale), per-tool `households_with_tool` resolution baked into
the `RecipeTool` schema's `field_validator`, and any new aggregate like the
spec-hypothesized `comments_count` (which does not exist in the current
contract). Three Dec 2025 – Feb 2026 commits (`7b325082`, `d02023e1`,
`216ae857`) make the COUNT subquery, the `household_id IS NOT NULL` filter, and
the `last_made` null-handling behavior load-bearing — the refactor must touch
none of them by accident.
