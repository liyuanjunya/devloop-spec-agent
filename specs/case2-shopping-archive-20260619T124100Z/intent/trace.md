# Intent Trace — Case 2 (Shopping List Archive)

Run: 2026-06-19T12:42 (single round, no refinement needed)

## Inputs
- `input.md` — Shopping List 归档与历史回顾 (Mealie). Sections: 数据模型 (§1), API 端点 (§2), 归档后不可变性 (§3), 多租户隔离 (§4), 事件总线 (§5), Schema 与响应 (§6), 实现约束 (§7), 测试要求 (§8).
- `context/grounding.md` — Mealie repo grounding (commit 4a099c1).
- Source tree at `C:\Users\v-liyuanjun\Downloads\mealie\`.

## Pipeline

### Step 1 — Read input
- Input is a Chinese-language Mealie feature spec for "归档 (archive)" semantics on the existing ShoppingList entity.
- 8 well-numbered sections covering data model, API, state machine, multitenancy, events, schema, implementation constraints, tests.
- Estimated scope per input header: "~15-20 个文件" — confirms scale of "feature" not "patch".

### Step 2 — Generate candidate hypotheses (3+1)
- **H1 add_feature** — end-to-end feature with all 8 slices (data model + API + state machine + events + i18n + tests). Initial prior ≈ 0.85.
- **H2 data_model_extension** — minimal framing: "just add two columns + a migration; the rest is glue". Initial prior ≈ 0.10.
- **H3 state_machine_extension** — alternative framing: "the core change is the frozen-state semantics on an existing entity". Initial prior ≈ 0.04.
- **H4 multitenant_extension** — long-shot: "the spec is fundamentally about isolation". Initial prior ≈ 0.01 (added so that the cross-cutting tenancy requirement is explicitly considered and rejected).

### Step 3 — Verification by source inspection
Verified each hypothesis by opening the actual files cited in the spec/grounding.

| File | Lines verified | Why it matters |
|------|---------------|----------------|
| `mealie/db/models/household/shopping_list.py` | 1–239 (full) | ShoppingList @ 147-181 has NO archived_at/archived_by_user_id today → confirms additive scope. household_id is `association_proxy('user','household_id')` (line 153) → non-trivial filtering implication for H2/H1. ShoppingListItem.checked @ 65 → the precondition "all items checked" maps to existing column. |
| `mealie/routes/households/controller_shopping_lists.py` | 1–284 (full) | ShoppingListController @ 159-283 currently has CRUD + label/recipe endpoints. Archive endpoints must be added; frozen guard needs to wrap update_one + every item-controller mutation. Confirms H1 over H2. |
| `mealie/repos/repository_shopping_list.py` | 1–12 (full) | Grounding said `repository_shopping.py`; actual filename is `repository_shopping_list.py`. File is a 12-line subclass of HouseholdRepositoryGeneric — confirms spec §7's "在 repository 集中实现归档过滤" lands here. |
| `mealie/repos/repository_generic.py` | 79-102, 505-523 | _query @ 79-92 special-cases AssociationProxyInstance on household_id; _filter_builder @ 94-102 injects group_id+household_id; HouseholdRepositoryGeneric @ 505-523 is the base RepositoryShoppingList extends. Confirms household scoping continues to work for the new archived_at filter. |
| `mealie/services/event_bus_service/event_types.py` | 1–208 (full) | EventTypes enum @ 13-60 has shopping_list_{created,updated,deleted} but no archived. Docstring @ 17-22 explicitly: "any changes made here must also be reflected in the database (and likely requires a database migration)." → reveals a hidden migration slice the spec doesn't call out but H1 captures. EventShoppingListData @ 130-132 only has shopping_list_id → richer payload needed for spec §5. |
| `mealie/lang/messages/en-US.json` | 1–95 (full) | File is JSON not YAML (grounding §5 is wrong). No `shopping-list` namespace exists. New keys must be added there only (.github/copilot-instructions.md says non-en-US locales are Crowdin-managed). |
| `mealie/alembic/versions/2025-09-10-19.21.48_..._add_referenced_recipe_to_ingredients.py` | 1–41 (full) | Canonical nullable-column-with-FK pattern: `batch_alter_table → add_column(nullable=True) → create_index → create_foreign_key`. Reusable verbatim for archived_by_user_id. |
| `mealie/db/models/recipe/recipe.py` | 140-160 | `last_made: FilterableColumn[datetime \| None] = mapped_column(NaiveDateTime)` @ 147 — direct precedent for `archived_at`. |
| `mealie/db/models/_model_base.py` | 1–48 | SqlAlchemyBase already provides created_at + update_at via NaiveDateTime — confirms archived_at type choice and aligns with existing time-column conventions. |

### Step 4 — Skeptic pass
Five challenges raised, each resolved by re-reading the source (see `confirmed.json:skeptic_challenges`). The strongest was challenge #2: adding new EventTypes enum values requires a DB migration on the subscriber repository, per the enum's own docstring — this is a "hidden" implementation cost not in the spec text but inferable from source. Surfaced as a scope item under `scope: [event_bus]`.

### Step 5 — Verdict
- **H1 = primary** (add_feature). Posterior confidence 0.92.
  - 8 spec sections each map cleanly to a sub-slice of an add_feature flow.
  - Counter-indicators of H1 (no new table) are weak; the column additions + new endpoints + new event types + new i18n strings + multitenant tests collectively constitute a feature, not a data model extension.
- **H2, H3 = secondary** (each captures one slice but neither subsumes the whole).
- **H4 = rejected** (no tenancy model change; isolation is regression-prevention).

### Step 6 — Output
- `intent/confirmed.json` written with schema_version 1.0.
- `intent/trace.md` (this file) written.

## Open questions deferred to spec / CR phase
1. Should `archive` enforce all items checked OR a soft override (admin / force flag)? Spec §3 says hard 409.
2. Should `unarchive` validate any post-condition (e.g. items may have been externally deleted)? Spec is silent; flagged for CR per input §三环节考察点.
3. Export/backup behaviour for archived lists? Out of scope here; CR-phase concern per input.
4. Whether the `archived_by` field in the response is a UserSummary or just a UUID. Spec §6 implies UserSummary; will need a `UserSummary` Pydantic import in the schema layer.
5. Whether `total_estimated_amount` in the event payload uses `extras` or a computed sum across ShoppingListItem.quantity × unit — needs spec clarification or a sensible default.
