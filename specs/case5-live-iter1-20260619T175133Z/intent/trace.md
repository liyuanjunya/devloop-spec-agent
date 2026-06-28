# Intent Trace — Case 5 (Live, Iter 1)

> **Stage**: 2 — Intent Agent
> **Run**: case5-live-iter1-20260619T175133Z
> **Input**: `specs/case5-live-iter1-20260619T175133Z/input.md`
> **Grounding**: `specs/case5-live-iter1-20260619T175133Z/context/grounding.md`
> **Codebase**: `C:\Users\v-liyuanjun\Downloads\mealie\`
> **Rounds used**: 1
> **Final verdict**: `add_feature` (confidence 0.95)

---

## 0. Scope vocabulary note

The `scope` field is restricted to: `backend / frontend / data_model / api / infra / ui / test / docs / security / auth / external_integration / performance / payment`.

Real conceptual scopes from the spec were flattened as follows:

`implicit_scopes:[scheduler,event_bus,multitenant,i18n]`

Flattening map (recorded so the design agent can re-expand):
- **scheduler** → `infra` + `backend` (scheduled task registration is infra; task body is backend service logic).
- **event_bus** → `backend` (event dispatch lives in `mealie/services/event_bus_service/`; no separate vocabulary slot).
- **multitenant** → implied by `backend` + `data_model` (household/group isolation is enforced via repository factory and per-row household_id filter; no separate slot).
- **i18n** → `docs` + `backend` (YAML message bundle under `mealie/lang/messages/` is the closest match for `docs`; lookup helper is `backend`).

Final `scope` array: `["backend", "data_model", "api", "test", "infra", "docs"]`.

---

## 1. Hypotheses considered

| ID  | Type        | Summary                                                                                            | Verdict   |
| --- | ----------- | -------------------------------------------------------------------------------------------------- | --------- |
| H1  | add_feature | Opt-in per-household auto-sync vertical: prefs fields + scheduled task + manual trigger + event + pantry-staple flag, on top of existing scheduler/shopping/event-bus reuse | **primary** |
| H2  | refactor    | Extract reusable auto-sync / consolidation abstraction from existing shopping_lists service        | rejected  |
| H3  | perf_opt    | Optimize shopping-list consolidation to handle scheduled bulk insertion at scale                   | rejected  |

### Why H1 wins

The spec is an entirely additive vertical with six explicit sub-requirements (config / scheduler / aggregation / event / manual trigger / multitenant tests). Every artifact named in the spec is a `新增` (add-new) deliverable on top of clearly named *existing* abstractions that the spec instructs to *reuse* (`复用`). There is no signal of behavioral preservation (rules-out refactor) and no signal of performance budgets (rules-out perf_opt).

### Why H2 is rejected

`grep` of `input.md` for refactor-family verbs (`重构`, `抽离`, `extract`, `refactor`) returns zero hits. The mention of `consolidate_ingredients` (which itself doesn't exist verbatim — see §3 spec drift) is framed as *consuming* the function, not modifying it.

### Why H3 is rejected

`grep` of `input.md` for perf-family terms (`perf`, `latency`, `p95`, `throughput`, `benchmark`, `优化`) returns zero hits. The only adjacent concern — multi-replica deployment (line 82 of input.md) — is explicitly framed as a correctness requirement ('保证同一 household 同一天只被一个 worker 处理' = "ensure each household is processed by exactly one worker per day"), i.e., an idempotency/concurrency guarantee, not a throughput optimization.

---

## 2. Skeptic round (6 challenges)

1. **SK1**: Could be 4 sub-features → no, they share one user capability; spec's own '三环节考察点' table groups them.
2. **SK2**: Is `IngredientFood.is_pantry_staple` a separate feature? → no, the flag has no isolated user value; required by auto-sync filter step 4.
3. **SK3**: Should i18n + migration drop out of scope? → no, vocabulary maps them to `docs` and `infra`; both are acceptance-required.
4. **SK4**: Spec references `@scheduled` decorator and `consolidate_ingredients` function that don't exist verbatim — is the spec hallucinating? → no, equivalent abstractions exist under different names (see §3); spec-side terminology drift, not intent ambiguity.
5. **SK5**: '每 30 分钟' cadence has no direct bucket (only daily/hourly/minutely exist) — infeasible? → feasible by self-throttled minutely callback OR by adding an `every_30_min` bucket; both are add_feature implementation choices.
6. **SK6**: Does 'no naive `datetime.now()`' imply a repo-wide audit? → no, scoped to the new task body.

All resolved without re-classification.

---

## 3. Spec-vs-codebase drift findings (flag for design agent)

| Spec term                       | Actual codebase reality                                                                                                                                         |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `@scheduled` decorator           | Use `SchedulerRegistry.register_minutely(callback)` in `scheduler_registry.py:38` + `ScheduledFunc` dataclass in `scheduled_func.py:8`.                          |
| `consolidate_ingredients`        | Use inline consolidation: `merge_items` (`shopping_lists.py:73`), `add_recipe_ingredients_to_list` (`shopping_lists.py:413`), and the `consolidated_create_items` loop inside `bulk_create_items` (`shopping_lists.py:162-177`). |
| `period_minutes=30` for scheduler | No 30-min bucket exists; only `_daily / _hourly / _minutely` at `scheduler_registry.py:13-15`. Implementation must either self-throttle on `_minutely` (recommended) or add a new bucket. |
| `Food` model                     | Class name is `IngredientFoodModel`, table `ingredient_foods` (`ingredient.py:153`). `is_pantry_staple` column does not exist — new migration required.          |
| `event_bus.dispatch(MealPlanAutoSyncedToShopping)` | Add new enum member `meal_plan_auto_synced_to_shopping` to `EventTypes(Enum)` in `event_types.py:13`; payload schema mirrors `EventShoppingListData` (`event_types.py:130`). |

None of these change the intent classification — they are facts for the design phase to bind to.

---

## 4. Verifications (evidence chain)

| Hypothesis | Evidence (file:line — what verified)                                                                                                                       |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1         | `mealie/services/scheduler/tasks/__init__.py` — tasks directory exists with siblings; `auto_sync_shopping.py` confirmed absent → new file needed.            |
| H1         | `mealie/db/models/household/preferences.py:16-44` — `HouseholdPreferencesModel` is flat & extensible.                                                        |
| H1         | `mealie/db/models/recipe/ingredient.py:153-260` — `IngredientFoodModel` has no `is_pantry_staple`; safe to add.                                              |
| H1         | `mealie/services/event_bus_service/event_types.py:13,130-141` — `EventTypes` enum + `EventShoppingListData` payload pattern exist; new member needed.        |
| H1         | `mealie/services/household_services/shopping_lists.py:73,162,413` — reusable merge / append entry points exist exactly where the spec says to reuse them.     |
| H1         | `mealie/services/scheduler/scheduler_registry.py:13-39` + `scheduled_func.py:8` — registration mechanism exists (spec's '@scheduled' is terminology drift).  |
| H2         | Counter-evidence: zero hits in `input.md` for refactor verbs (`重构`, `抽离`, `extract`, `refactor`).                                                          |
| H3         | Counter-evidence: zero hits in `input.md` for perf terms (`perf`, `latency`, `p95`, `throughput`, `benchmark`, `优化`); multi-replica framed as correctness.   |

---

## 5. Final output

- **intent_type**: `add_feature`
- **scope**: `["backend", "data_model", "api", "test", "infra", "docs"]`
- **implicit_scopes**: `[scheduler, event_bus, multitenant, i18n]`
- **confidence**: `0.95`
- **rounds_used**: `1`

JSON written to `intent/confirmed.json` (schema-validated).
