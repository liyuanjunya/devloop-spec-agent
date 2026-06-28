# UI Perspective

## In-scope for THIS spec?
**NO** — the spec is backend-only (API + DB + schema + tests); it explicitly does not request UI changes. See `input.md:25-52,70`.

## ⚠ Critical finding: Frontend favorites scaffolding ALREADY exists in Mealie

- `frontend/app/lib/api/user/users.ts:23-64` — user API client already has favorite endpoints
- `frontend/app/components/Domain/Recipe/RecipeFavoriteBadge.vue:1-65` — existing heart/favorite toggle UI
- `frontend/app/components/Domain/Recipe/RecipeCard.vue` / `RecipeCardMobile.vue` — recipe list/card surfaces already rendering favorite badge
- `frontend/app/components/Domain/Recipe/RecipePage/RecipePageParts/RecipePageHeader.vue` — recipe detail header surface
- `frontend/app/pages/user/[id]/favorites.vue:1-33` — user favorites page exists already

→ **Strong implication: the new backend endpoints in this spec must conform to what the existing UI client expects, OR the spec needs to call out that the UI client also needs migrating to new path `/api/users/self/favorites/`.**

→ **MUST cross-check existing UI client endpoint paths against the spec's `/api/users/self/favorites/{recipe_slug}` to detect mismatch.**

## Relevant frontend artifacts (for future / scope-confirmation)
- `frontend/` — Nuxt 4 app (`app/`, `server/`, `public/`, `nuxt.config.ts`)

## Conventions discovered
- TypeScript type generation: auto-generated from Pydantic/OpenAPI via `task dev:generate`; do NOT manually edit `frontend/app/lib/api/types/` (per `.github/copilot-instructions.md:28-32,69-72`)
- API client pattern: clients live in `frontend/app/lib/api/` and extend `BaseAPI` / `BaseCRUDAPI` (per `.github/copilot-instructions.md:47-50`); `UserApi` is the current pattern (`frontend/app/lib/api/user/users.ts:1-98`)

## Future UI touch points (out of scope, but documented)
- Recipe card heart icon: `frontend/app/components/Domain/Recipe/RecipeCard.vue`
- Mobile recipe card heart icon: `frontend/app/components/Domain/Recipe/RecipeCardMobile.vue`
- Recipe detail header/action area: `frontend/app/components/Domain/Recipe/RecipePage/RecipePageParts/RecipePageHeader.vue`
- User favorites page: `frontend/app/pages/user/[id]/favorites.vue` (likely needs to switch to the new self favorites API for "My Favorites")

## Open questions for spec
- Does the existing UI client point at endpoints that match the new spec, or does it expect different paths? **(Needs verification — Writer/Reviewer should call this out as an assumption or constraint.)**
- Should UI remain completely out of this spec, or include a small frontend follow-up?
- Should the frontend type/API client be updated in the same change, or left for a separate frontend task?

## Tool calls used: 14
