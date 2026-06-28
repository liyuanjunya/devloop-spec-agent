# Rewrite Summary: v1 → v2

## Issues addressed
- **ARCH-H-001** → FR-007/FR-008 now explicitly include `PublicRecipesController` and `/api/explore/groups/{group_slug}/recipes` anonymous paths.
- **ARCH-H-002** → FR-008 forbids `column_aliases` as projection and requires SELECT/loader-compatible or batched hydration.
- **ARCH-H-003** → FR-009 splits recipe-delete cleanup, user-delete cleanup, and FK cascade migration remedies.
- **COMP-C-001** → FR-006 adds i18n-backed 404 requirement with verified `en-US` key; no hardcoded English 4xx strings.
- **COMP-C-002** → FR-002 requires a service under `mealie/services/user_services/`.
- **COMP-C-003** → NC-001 makes new table vs reuse a blocking reviewer gate.
- **COMP-H-001 / CONS-H-002** → FR-009 mandates FK cascade migration plus `RepositoryUsers.delete` cleanup.
- **COMP-H-002** → FR-011 and SC-008 enforce >=3 unit, >=6 integration, >=2 multitenant tests.
- **COMP-H-003** → FR-003 pins `mealie/schema/user/user_favorites.py`.
- **COMP-H-004 / EXEC-C-001 / CONS-C-001** → NC-002 and FR-004 choose recipe-list at `/api/users/self/favorites` and move old rating-summary contract.
- **COMP-H-005** → FR-012 adds migration naming, OpenAPI docstrings/`response_model`, and codegen requirements.
- **EXEC-H-001..004 / EXEC-H-005** → All v2 references were re-opened and `spec.md`/`spec.json` are generated from the same markdown source.
- **CONS-H-001** → FR-007 states anonymous `favorited=false` while `favorite_count` remains real and only defaults to 0 when no favorites exist.

## Issues NOT addressed
- **ARCH-M-001** favorite write latency/event-listener performance: not critical/high for v2; SC-004 focuses recipe read N+1.
- **ARCH-M-002** concurrent POST UPSERT behavior: v2 limits idempotency to sequential duplicates; concurrent hardening can be follow-up unless required.
- **COMP-M-003** global vs scoped `favorite_count`: v2 chooses real count for the returned recipe, bounded by endpoint visibility.

## New issues introduced
- v2 intentionally recommends repurposing `GET /api/users/self/favorites`, requiring a ratings-namespaced replacement route and test updates.
- Reviewer text requested `t('errors.no-entry-found')`, but verified code contains `exceptions.no-entry-found`; v2 uses the verified key unless reviewers require adding a new key.
