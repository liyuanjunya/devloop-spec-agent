# UI Perspective — Case 4 (Recipe list N+1 refactor)

> Scope: the Nuxt 4 frontend at `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\`
> as it relates to the `GET /api/recipes` response. Verified against the
> current checkout (HEAD `c3f87736`).
>
> All file paths below are absolute on the local checkout; line numbers were
> read with the `view` tool at the time this document was written.

---

## TL;DR (read this first)

1. **The recipe list page is `RecipeExplorerPage.vue` →
   `RecipeCardSection.vue` → `RecipeCard.vue` / `RecipeCardMobile.vue`.**
   The cards bind exactly seven props off each list item: `name`,
   `description`, `slug`, `rating`, `image`, `tags`, `recipeId` — verified at
   `RecipeCardSection.vue:119-127, 144-152` against `RecipeCard.vue:106-124`
   and `RecipeCardMobile.vue:135-156`.
2. **The API client types the list response as
   `PaginationData<Recipe>`, not `PaginationData<RecipeSummary>`** — see
   `frontend/app/lib/api/user/recipes/recipe.ts:107-109`. The backend
   actually ships `RecipeSummary` (`recipe_crud_routes.py:340`,
   `response_model=PaginationBase[RecipeSummary]`). Because TS `Recipe`
   extends `RecipeSummary` structurally (all summary fields are present and
   non-summary fields are `?` optional — `frontend/app/lib/api/types/recipe.ts:228-264` vs `310-336`), it works today. **Any new field on `RecipeSummary` will land in `Recipe` in the generated types and vice versa — keep them aligned.**
3. **Generated TypeScript types are sacred — the org guide
   forbids manual edits.** `frontend/app/lib/api/types/recipe.ts:1-7` says
   verbatim "This file was automatically generated from pydantic models by
   running pydantic2ts. Do not modify it by hand." Any backend schema change
   requires `task dev:generate`.
4. **The list page is infinite-scroll, not paginated UI** — see
   `RecipeCardSection.vue:340-359`. It uses `perPage = 32` and re-issues the
   same `getAll` call for each scroll page. The N+1 fix matters multiplicatively
   here: a 100-recipe library hits 3+ scroll pages, so a per-row query
   regression is 3× the apparent baseline.
5. **The "comments_count" the spec posits is not consumed by the UI anywhere.**
   `grep -rn 'comments_count|commentsCount'` across `frontend/app/` is empty.
   If the backend perf fix adds it, no card surfaces it; if the fix drops it,
   no card breaks.

---

## 2. File-by-file map

### 2.1 Page entrypoint

| Field | Value |
|-------|-------|
| Path | `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\pages\g\[groupSlug]\index.vue` |
| Lines | 1-9 (entire file) |
| Symbols | `RecipeExplorerPage` (imported, mounted as the whole page body) |
| Importance | **Critical** — this is `/g/<slug>` (the "All Recipes" route the spec means). The bare `pages/index.vue` (`frontend/app/pages/index.vue:1-55`) only redirects to it. |
| Reason | This is the only page surface the user sees; it owns `<RecipeExplorerPage />` and nothing else. |

```vue
<template>
  <div>
    <RecipeExplorerPage />
  </div>
</template>
```

(Verified `frontend/app/pages/g/[groupSlug]/index.vue:1-9`.)

### 2.2 The Explorer page component

| Field | Value |
|-------|-------|
| Path | `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\components\Domain\Recipe\RecipeExplorerPage\RecipeExplorerPage.vue` |
| Lines | 1-56 |
| Symbols | `RecipeExplorerPage`, `useLazyRecipes`, `searchQuery`, `recipes`, `appendRecipes`, `replaceRecipes` |
| Importance | **Critical** — coordinates the search form and the card section; owns the `recipes` ref. |
| Reason | This is where the list fetched from `/api/recipes` actually lives in memory before being rendered. The search filter form (`RecipeExplorerPageSearch`) provides the `query` (categories/tags/tools/foods/cookbook/search) that drives the API call. |

Key wiring (`RecipeExplorerPage.vue:40, 12-23`):
```ts
const { recipes, appendRecipes, replaceRecipes } =
  useLazyRecipes(isOwnGroup.value ? null : groupSlug.value);
```
```vue
<RecipeCardSection
  :recipes="recipes"
  :query="searchQuery"
  @replace-recipes="replaceRecipes"
  @append-recipes="appendRecipes"
/>
```

### 2.3 The card section (infinite scroll + sort)

| Field | Value |
|-------|-------|
| Path | `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\components\Domain\Recipe\RecipeCardSection.vue` |
| Lines | 1-465 |
| Symbols | `RecipeCardSection`, `fetchRecipes`, `initRecipes`, `infiniteScroll`, `sortRecipes`, `navigateRandom` |
| Importance | **Critical** — owns the scroll, the per-page count (32), and the order direction. Translates UI sort choices into `orderBy` / `orderDirection` / `orderByNullPosition` for the backend. |
| Reason | This is the *consumer* of the list payload. Lines 110-153 render the cards from `recipes` and bind exactly seven fields per item. Lines 340-359 are the scroll loop that re-calls `fetchRecipes`. |

Field bindings on the desktop card (lines 119-127):
```vue
<RecipeCard
  :name="recipe.name!"
  :description="recipe.description!"
  :slug="recipe.slug!"
  :rating="recipe.rating!"
  :image="recipe.image!"
  :tags="recipe.tags!"
  :recipe-id="recipe.id!"
/>
```

Mobile card (lines 144-152) is identical.

Pagination knobs the UI controls (lines 230-237 + 260-278):
- `perPage = 32` (hard-coded; `lines 234`)
- `orderBy` from `preferences.orderBy` or `props.query?.orderBy`
- `orderDirection` from `preferences.orderDirection`
- `orderByNullPosition` derived from order direction (`'first'` if asc, `'last'` if desc)
- `_searchSeed` (line 266-267) for random-order stability across pages

These get round-tripped through `useLazyRecipes.fetchMore` (next file).

### 2.4 The API composable

| Field | Value |
|-------|-------|
| Path | `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\composables\recipes\use-recipes.ts` |
| Lines | 1-161 |
| Symbols | `useLazyRecipes`, `fetchMore`, `getRandom`, `getParams`, `useRecipes` (separate composable for the dashboard "recent" list) |
| Importance | **High** — single funnel for *all* `/api/recipes` GETs in the explorer. |
| Reason | `fetchMore` (lines 47-67) is the only call site that passes the query params to `api.recipes.getAll`. It returns `data.items` (`Recipe[]`) directly — the `total`, `total_pages` from the paginated response are **discarded**. Implication: the spec's "total / total_pages must be preserved" is only enforced by backend tests, not by any UI consumer of those fields. |

```ts
async function fetchMore(page, perPage, orderBy, orderDirection,
                        orderByNullPosition, query, queryFilter) {
  const { data, error } = await api.recipes.getAll(
    page, perPage, getParams(orderBy, orderDirection, orderByNullPosition, query, queryFilter),
  );
  if (error?.response?.status === 404) { router.push("/login"); }
  return data ? data.items : [];
}
```

(Verified `use-recipes.ts:47-67`.)

The dashboard "recent recipes" page (`useRecipes` at lines 112-161) goes
through the same API and shares the cache (`recentRecipes` ref at line 9).

### 2.5 The API client (TypeScript)

| Field | Value |
|-------|-------|
| Path | `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\lib\api\user\recipes\recipe.ts` |
| Lines | 1-283 (search call at 107-109; `RecipeSearchQuery` type at 63-91) |
| Symbols | `RecipeAPI extends BaseCRUDAPI<CreateRecipe, Recipe, Recipe>`, `routes.recipesBase = '/api/recipes'`, `search(rsq)`, `RecipeSearchQuery` |
| Importance | **Critical** — owns the URL and the typed response shape. |
| Reason | `baseRoute = routes.recipesBase` (line 94) + inherited `getAll` from `BaseCRUDAPI` (`frontend/app/lib/api/base/base-clients.ts:48`) is what every `useLazyRecipes` call ultimately hits. The explicit `search()` method at lines 107-109 types the response as `PaginationData<Recipe>` — see the next entry for the type contract. |

Note: the third generic on `BaseCRUDAPI<CreateRecipe, Recipe, Recipe>` (line 93)
means the `getAll` return is typed as `Recipe[]`, *not* `RecipeSummary[]`,
even though the backend ships summaries.

### 2.6 The generated types (DO NOT EDIT)

| Field | Value |
|-------|-------|
| Path | `C:\Users\v-liyuanjun\Downloads\mealie\frontend\app\lib\api\types\recipe.ts` |
| Lines | header banner 1-7; `Recipe` interface 228-264; `RecipeSummary` interface 310-336 |
| Symbols | `Recipe`, `RecipeSummary`, `RecipeCategory` (lines 19-24 `CategoryBase`), `RecipeTag` (lines 41-46 `TagBase`), `RecipeTool` (lines 265-271) |
| Importance | **Critical / locked.** File header (lines 1-7) explicitly says auto-generated from Pydantic via `pydantic2ts`, do not modify by hand. The org guide reinforces this. |
| Reason | This is the only contract between backend and frontend in code. Adding a field to backend `RecipeSummary` causes this file to grow on next `task dev:generate`; the field becomes typed-accessible everywhere `recipe.someField` is read. The TS optionality (`field?: T | null`) gives some forward-compat slack, but only if the backend keeps emitting the keys that *are* present today. |

**Exact `RecipeSummary` field set on the wire today** (from
`frontend/app/lib/api/types/recipe.ts:310-336`):

```ts
export interface RecipeSummary {
  id?: string | null;
  userId?: string;
  householdId?: string;
  groupId?: string;
  name?: string | null;
  slug?: string;
  image?: unknown;
  recipeServings?: number;
  recipeYieldQuantity?: number;
  recipeYield?: string | null;
  totalTime?: string | null;
  prepTime?: string | null;
  cookTime?: string | null;
  performTime?: string | null;
  description?: string | null;
  recipeCategory?: RecipeCategory[] | null;
  tags?: RecipeTag[] | null;
  tools?: RecipeTool[];
  rating?: number | null;
  orgURL?: string | null;
  dateAdded?: string | null;
  dateUpdated?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastMade?: string | null;
}
```

(26 fields. Note `tools?: RecipeTool[]` is **not** nullable — the array
always exists; the other two organizer collections are nullable. The spec's
"keep response exactly the same" must include this asymmetry.)

The full `Recipe` interface (lines 228-264) is `RecipeSummary` plus
`recipeIngredient`, `recipeInstructions`, `nutrition`, `settings`, `assets`,
`notes`, `extras`, `comments`. **None of those nine extra fields show up in
the list-page render path; if any of them leaks into the list response,
payload size will balloon.**

### 2.7 Card consumers (specific fields the UI reads off `recipe`)

These are the components that bind *specific* fields off the list item and
will break (or silently render the wrong thing) if the field changes type or
disappears.

| Path | Lines | Fields read off `recipe` | Why it matters |
|------|-------|--------------------------|----------------|
| `frontend/app/components/Domain/Recipe/RecipeCardSection.vue` | 119-127, 144-152 | `name`, `description`, `slug`, `rating`, `image`, `tags`, `id` | The *primary* list consumer (desktop + mobile). |
| `frontend/app/components/Domain/Recipe/RecipeCard.vue` | 39-69, 106-124 (props) | (receives via props above; reads `description`, `name`, `rating`, `image`, `tags`, `slug`, `recipeId`) | Renders favorite/rating/chips. Chips are bound to `tags` (line 60-67, `<RecipeChips :items="tags" :limit="2" url-prefix="tags">`). |
| `frontend/app/components/Domain/Recipe/RecipeCardMobile.vue` | 135-156 (props) | same as desktop card | Used in mobile + dense list view. |
| `frontend/app/components/Domain/Recipe/RecipeCardImage.vue` | (referenced from cards) | `slug`, `recipeId`, `image` (as `imageVersion`) | The `image` field is opaque (`unknown`) on `RecipeSummary`, but is passed as a cache-buster to the image URL. Any change in its serialized type (int → str or vice versa) silently busts CDN caching. |
| `frontend/app/components/Domain/Recipe/RecipeDialogSearch.vue` | 59-63, 76, 85, 171 | `name`, `description`, `slug`, `rating`, `image` (type `RecipeSummary`) | The "command-K search" dialog also consumes summaries. Typed as `RecipeSummary[]` explicitly. |
| `frontend/app/components/Domain/Recipe/RecipeList.vue` | 11, 30, 33; 58, 61 | `slug`, `name`, `description`; props typed `recipes: RecipeSummary[]` | Alternative list view (single column, used in some dialogs/picker contexts). Explicitly typed against `RecipeSummary`. |
| `frontend/app/components/Domain/Recipe/RecipeSuggestion.vue` | 6-10, 44, 53 | `name`, `description`, `slug`, `rating`, `image`; props `recipe: RecipeSummary` | The cocktail-builder / "what can I make" results card. |
| `frontend/app/components/Domain/Recipe/RecipeTimelineItem.vue` | 56-60 | `name`, `slug`, `description`, `rating`, `image` | The timeline shows a mini-card for each event's linked recipe. Reads summary fields directly. |

All of the above will compile against the *current* `RecipeSummary`. Field
*removal* breaks them at runtime (silently null-coercing `:rating="recipe.rating!"`
to `0` for example); field *addition* is silent but inflates payload.

### 2.8 Pages that consume the same fields (full list)

Grep `recipe\.(image|slug|tags|name|description|rating|recipeCategory|tools|totalTime|prepTime|performTime|lastMade)` across `frontend/app/components/Domain/Recipe`:

- Already covered above plus these incidental readers (none in the list path,
  but worth knowing if backend changes ripple):
  - `RecipeActionMenu.vue:29-30, 57-58` — reads `slug`, `name`
  - `RecipePrintView.vue` — reads `prepTime`, `totalTime`, `performTime`,
    `description`, `name`, `image`, `id`, `slug` (full recipe, not summary)
  - `RecipePage/RecipePageParts/RecipePageInfoCard.vue` — reads `prepTime`,
    `totalTime`, `performTime`, `name`, `slug`, `rating`, `description`
  - `RecipeLastMade.vue:179, 183` — reads `lastMade`
  - `RecipePage/RecipePageParts/RecipePageOrganizers.vue` — reads
    `recipeCategory`, `tags`, `tools`
  - `RecipePage/RecipePageParts/RecipePageIngredientToolsView.vue` — reads
    `tools` (note: also `households_with_tool` *through* `tools[i]` — relevant
    to the history-side concern about per-tool query expansion)

None of those four "page" consumers are on the list-page path, but they
share the same generated types, so a `RecipeSummary` field tweak will affect
them transitively.

---

## 3. Frontend-visible field contract

The UI *absolutely depends* on these fields existing on each list item with
their current types/optionality. Source: every binding above + the
`PaginationData<Recipe>` envelope.

### 3.1 Per-item fields (must not change)

| Field | TS type | Read by | Failure mode if removed/changed |
|-------|---------|---------|---------------------------------|
| `id` | `string \| null` | `:key="recipe.id!"`, `:recipe-id="recipe.id!"` (`RecipeCardSection.vue:113, 126`); Vue's `v-for` key | Vue rendering bugs (key collisions, stale DOM), favorite-badge / context-menu break |
| `slug` | `string` | Routing (`/g/<slug>/r/<recipe.slug>`), image URL builder, every card | 404 on click; image broken |
| `name` | `string \| null` | Card title, search dialog | Blank card title |
| `description` | `string \| null` | Card hover reveal (`RecipeCard.vue:25-37`) | Hover overlay shows nothing |
| `rating` | `number \| null` | `RecipeCardRating` star count | Stars render `0` (but as per backend's user-rating subquery, this is computed) |
| `image` | `unknown` (int/str cache-buster) | `RecipeCardImage`'s URL — appended as a query param to bust caches when image changes | Wrong cached image displayed |
| `tags` | `RecipeTag[] \| null` | `RecipeChips :items="tags"` (`RecipeCard.vue:60-67`) shows up to 2 chips | No chips → loss of visual category info |
| `tools` | `RecipeTool[]` | Not on the list cards directly, but **required for `total payload shape stability` since `RecipeSummary` is what ships** | Schema-level break if dropped |
| `recipeCategory` | `RecipeCategory[] \| null` | Not on the list cards directly (see `tools` note) | Schema-level break |
| `totalTime` / `prepTime` / `performTime` / `cookTime` | `string \| null` | Detail page, not list cards | Schema-level break |
| `recipeServings`, `recipeYieldQuantity`, `recipeYield` | `number`, `number`, `string \| null` | Detail page; **defaults are `0` (not null) by Pydantic validator** | Type narrowing breaks if backend ships `null` instead of `0` |
| `createdAt`, `updatedAt`, `lastMade`, `dateAdded`, `dateUpdated` | `string \| null` | Sort UI sends `orderBy='created_at'`/`'updated_at'`/`'last_made'` (`RecipeCardSection.vue:398-417`); list cards do not display | Sort breaks if backend can no longer order by these |
| `userId`, `householdId`, `groupId` | `string` | Not card-rendered, but used by `useLoggedInState` / favorite system | Permission UI bugs if `householdId` disappears |
| `orgURL` | `string \| null` | Detail page only | Schema break |

### 3.2 Envelope fields (must not change)

`PaginationData<Recipe>` from `frontend/app/lib/api/types/non-generated.ts`
(implicitly inherited; the `pagination_response.set_pagination_guides` call
on the backend adds `next`, `previous` URLs):

| Field | Use |
|-------|-----|
| `items` | The only field `useLazyRecipes.fetchMore` actually reads (`use-recipes.ts:66`). `total`, `total_pages`, `next`, `previous` are not consumed by the explorer page. |
| `total` | Not UI-consumed in the explorer, but required to satisfy backend tests and OpenAPI contract. |
| `total_pages` | Same as above. |
| `page` / `per_page` | Echoed back; not consumed. |
| `next` / `previous` | Built by `set_pagination_guides` in `recipe_crud_routes.py:387-390`. Not consumed by the infinite-scroll UI, but part of the OpenAPI contract. |

### 3.3 Hard ordering / sort contract

Sort options the UI sends to the backend (`RecipeCardSection.vue:384-426`):
- `name` (default direction `asc`)
- `rating` (`desc`, `filterNull=true`)
- `created_at` (`desc`)
- `updated_at` (`desc`)
- `last_made` (`desc`, `filterNull=true`)
- `random` (also passes `_searchSeed` for page-stable randomness)

The N+1 refactor must keep all six order-by paths working **and** preserve
the `nulls_first` / `nulls_last` semantics — current behavior is "asc → nulls
first, desc → nulls last" (`RecipeCardSection.vue:262`). The
`add_order_attr_to_query` helper in `repository_generic.py:407-430`
implements this (`nulls_first` on line 426, `nulls_last` on line 428), and
the `random` order path is at `repository_generic.py:436-449`.

---

## 4. Codegen impact — what happens if `RecipeSummary` adds an attribute

The chain of consequences when the N+1 fix touches the schema:

1. **Pydantic model change** — e.g. adding `comments_count: int = 0` to
   `RecipeSummary` in `mealie/schema/recipe/recipe.py`.
2. **Backend ship change immediately** — the route uses
   `orjson.dumps(pagination_response.model_dump(by_alias=True))`
   (`recipe_crud_routes.py:392`), so the field is on the wire the next
   request, with `commentsCount` casing.
3. **Codegen required** — `task dev:generate` re-runs `pydantic2ts` and
   regenerates `frontend/app/lib/api/types/recipe.ts`. The new `commentsCount?: number;` is added to **both** `RecipeSummary` (line ~336) *and* `Recipe` (line ~264) since `Recipe extends RecipeSummary` in Pydantic. If `task dev:generate` is **not** run, TS compilation passes (the field is optional in source) but the field is invisible to type-checking and may be flagged by `eslint`'s `no-explicit-any` if read via cast.
4. **No automatic UI consumption** — Vue templates use `recipe.x` without
   type assertion in many places (e.g. via `v-for`); a new field is silently
   ignored until somebody writes a `<RecipeCard :comments-count="…">`.
5. **Payload size grows** — every list item ships the new field even if no
   card renders it. With infinite-scroll and 32 items/page on a 100+ recipe
   library, even small fields add up over a session.
6. **OpenAPI / contract tests** — `mealie/lang/messages/en-US.json` aside,
   the route's `response_model=PaginationBase[RecipeSummary]`
   (`recipe_crud_routes.py:340`) generates the OpenAPI schema. The
   `docs/docs/overrides/api.html` build, contract snapshot tests (if any in
   `tests/`), and any cached OpenAPI clients will diff.
7. **Sort/filter UI changes** — if the new field is added to
   `_filterable_column` allow-list (`mealie/db/models/_filterable_column.py`,
   introduced by `642c826f`), it becomes filterable via the
   `QueryFilterBuilder` and *could* be added to
   `frontend/app/composables/use-query-filter-builder.ts`. The spec forbids
   "indirectly changing pagination behavior" — adding a new orderable column
   would arguably be a contract change.

### 4.1 The safer alternative — keep `RecipeSummary` byte-stable

The history perspective (§3 of that doc) notes that **no existing UI consumer
reads `comments_count`**. So the recommended posture is:

- **Do not add `comments_count` to `RecipeSummary`** unless the spec is
  explicitly amended to drop the "100% field-stable" constraint.
- If the comment count *is* an N+1 source (i.e. some serializer is touching
  `recipe.comments`), the fix is to remove the eager-load / lazy-load that
  triggers it, **not** to start exposing the aggregate.
- Verify by grepping the backend for any `recipe.comments` access in the
  list-summary code path (the summary loader_options
  at `schema/recipe/recipe.py:168-175` does **not** include `comments`, so
  the lazy-load risk is low — but a JSON serializer that touches `.comments`
  would still trigger it).

### 4.2 If a field truly must be added

Steps in order (the repo's `copilot-instructions.md` enumerates these as
mandatory):

1. Modify the Pydantic model in `mealie/schema/recipe/recipe.py`.
2. Run `task dev:generate` (regenerates `frontend/app/lib/api/types/`,
   `mealie/schema/*/__init__.py`).
3. Update consumers that *should* use the new field — none for `comments_count`
   today; add a `RecipeCard` slot if surfacing it.
4. Add `task py:check` and `task ui:check` runs.
5. PR description must call out the response shape change explicitly.

---

## 5. Cross-perspective questions (for the joint review)

1. **Confirm with History/Spec: should `comments_count` be added?** Frontend
   has zero consumers; the spec lists it but a 100%-field-stable refactor
   forbids adding it. Need an explicit yes/no before coding.
2. **Sort-by `random` with `_searchSeed` — does the new perf test cover it?**
   `RecipeCardSection.vue:418-426` uses `random` ordering with a session-stable
   seed. The backend implements this as a hashed expression — confirm the
   query-count budget includes a `searchSeed`-driven request, since pseudo-random
   often serializes through a window function (1 query, no N+1) but
   regressions are possible.
3. **`filterNull=true` for `rating` and `last_made`** — `RecipeCardSection.vue:395, 415`
   sets the preference, then the (commented-out) block at lines 246-257 shows
   the intent to add `… IS NOT NULL` to the queryFilter string. Today it's
   not appended, but the backend's `_get_last_made_col_alias` returns
   `coalesce(subquery, 1900-01-01)` so `IS NOT NULL` would *never* drop rows.
   The N+1 refactor must not flip either of these behaviors.
4. **`perPage = 32` is hard-coded; the test uses `perPage=50` and `perPage=200`** —
   the spec's test uses larger pages than the UI ever sends. That's fine for
   regression coverage but documents the worst-case payload size: 200 items ×
   ~26 fields each + tags/categories/tools collections. Confirm that any
   `selectinload` strategy stays sub-linear in this regime.
5. **`PaginationData<Recipe>` typing is wrong but tolerated** — `RecipeAPI`
   (`frontend/app/lib/api/user/recipes/recipe.ts:93-109`) types the list as
   `PaginationData<Recipe>`, but the backend ships `RecipeSummary`. Should
   we fix the type to `PaginationData<RecipeSummary>` as part of this PR?
   It is technically a separate bug, but if the N+1 fix changes the
   summary's shape, getting the types right protects future readers.
6. **`useLazyRecipes` discards `total` / `total_pages`** — the UI does not
   consume them. The backend perf test must still assert they're correct
   (history perspective covers this), but the UI side gives us no
   end-to-end signal if they regress.
7. **`RecipeTool.households_with_tool: list[str]` is populated by a
   `field_validator`** — confirmed in `schema/recipe/recipe.py:83-95`.
   The list pages don't render this field, but the **JSON payload always
   includes it** (it's part of `RecipeTool` which is part of `RecipeSummary`).
   If the validator triggers a per-tool DB lookup, that is a real N+1 the
   spec doesn't name. Worth coordinating with History about whether to
   `.options(joinedload(RecipeTool.households))` (or equivalent) in the
   `RecipeSummary.loader_options()`.
8. **`task dev:generate` is required after schema changes** — if the coding
   phase modifies `RecipeSummary`, the PR must include the regenerated
   `frontend/app/lib/api/types/recipe.ts` and any schema `__init__.py` diff.
   CI will likely fail otherwise. Worth pre-warning the coding agent.

---

## 6. One-paragraph UI summary (for the joint design doc)

The "All Recipes" list (`/g/<slug>` page) is rendered by
`RecipeExplorerPage` → `RecipeCardSection` → `RecipeCard`/`RecipeCardMobile`,
hits `GET /api/recipes` through `useLazyRecipes.fetchMore`, and only
materially reads seven fields per item: `id`, `slug`, `name`, `description`,
`rating`, `image`, `tags`. The list payload, however, ships the full
26-field `RecipeSummary` (plus `tools[].households_with_tool` populated by a
Pydantic validator that could itself be an N+1 source). The TS types are
auto-generated from Pydantic — any addition to `RecipeSummary` lands in
`frontend/app/lib/api/types/recipe.ts` on the next `task dev:generate` and
flows into both `Recipe` and `RecipeSummary` interfaces, growing payload
without changing UI behavior unless a card surfaces the field. The
recommended posture for the perf fix is therefore: **do not add new
response fields** (especially `comments_count`, which no consumer reads),
**keep the seven rendered fields byte-stable**, and **preserve the six
sort modes**, the `nulls_first/last` semantics, and the `_searchSeed`-based
random pagination. The most under-discussed N+1 candidate visible from the
frontend types is `RecipeTool.households_with_tool` resolution per tool per
recipe — worth raising before the coding phase commits to a fix shape.
