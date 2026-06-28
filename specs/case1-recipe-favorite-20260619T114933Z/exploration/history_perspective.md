# History Perspective

## Template commits (this is how new features are added here)

- `c3f8773 feat: In-app AI Provider Configuration (#7650)` — files changed:
  - `mealie/alembic/versions/2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py`
  - `mealie/db/models/group/ai_providers.py`
  - `mealie/repos/repository_ai_provider.py`
  - `mealie/routes/admin/admin_management_ai_providers.py`
  - `mealie/routes/groups/controller_group_ai_providers.py`
  - `mealie/schema/group/ai_providers.py`
  - plus integration/unit tests

  → **closest match to "new table + repository + routes + migration + tests"** template

- `d2b0681 feat: Announcements (#7431)` — recent "large feature" rollout (broad backend/frontend/test changes)

- `48752bc fix: support CSV/TXT upload and add validation for Plan to Eat import (#6360) (#7622)` — recent feature-adjacent service/test change

## Migration conventions

- File name format: `YYYY-MM-DD-HH.MM.SS_<revision_hash>_<snake_case_desc>.py`
  - Example: `2026-05-18-16.27.05_2187537c52b8_add_table_for_ai_providers.py`
- Commit message: `feat: ... (#PR)` or `fix: ... (#PR)`
- Migration creation usually bundled inside the feature commit (not separate)

## Recipe area recent activity

Recent changes to recipe area are mostly bug fixes (not contentious refactors):
- `c3f8773 feat: In-app AI Provider Configuration (#7650)` touched `mealie/routes/recipe/recipe_crud_routes.py`, `mealie/services/recipe/recipe_service.py`, recipe create flow tests
- `f025bbc fix: default ingredient_references on RecipeInstruction init (#7732)`
- `642c826 fix: Protect sensitive data in query filter API (GHSA-8m57-7cv5-rjp8) (#7629)`
- `1cebfd5 fix: use locale for Recipe Created timeline event (#4497) (#7623)`

No recent reverts; incremental fixes only.

## Existing favorite/star/bookmark attempts

- `git log --oneline --all --grep="favorite\|star\|bookmark\|like"` returned only `d2b0681 feat: Announcements (#7431)` (matched "like" in unrelated text)
- **No prior user-recipe favorite implementation found in commit history** ← important: this is greenfield backend feature.

## Conventions discovered

- New "table-backed feature" usually ships as: Alembic migration + DB model + repository + route/controller + schema + integration tests, **all in one PR**
- Household/group isolation enforced in feature's integration tests, not just service code
- Recent commit naming is concise and PR-numbered

## Open questions for spec

- Should favorites be per-user-per-household, or global per user across all households? **(Spec says user-level; user input clarifies this — confirmed)**
- Should `favorite_count` count all household members or only current household visibility?
- Should recipe response fields be nullable defaults (`favorited=false`, `favorite_count=0`) for non-authenticated users? **(Spec says yes — confirmed)**

## Tool calls used: 2
