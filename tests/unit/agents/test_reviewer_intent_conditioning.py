"""Tests for P0-3: reviewer prompts conditioned on intent_type."""

from devloop.spec_phase.agents.reviewers.stage import _intent_specific_guidance


def test_add_feature_guidance_says_code_doesnt_exist_is_fine():
    g = _intent_specific_guidance("add_feature")
    assert "NEW capability" in g
    assert "DO NOT flag" in g
    # The exact false-positive pattern from case-5 must be explicitly addressed:
    assert "does not exist in the checkout" in g
    assert "DO NOT require evidence that the new feature is already implemented" in g


def test_remove_feature_uses_new_capability_template():
    g = _intent_specific_guidance("remove_feature")
    assert "REMOVE" in g
    assert "DO NOT flag" in g


def test_fix_bug_requires_reproduction_test():
    g = _intent_specific_guidance("fix_bug")
    assert "BUG FIX" in g
    assert "MUST" in g.upper() or "must" in g
    assert "FAIL" in g and "PASS" in g
    assert "minimal" in g.lower()


def test_refactor_requires_behavior_preservation():
    g = _intent_specific_guidance("refactor")
    assert "REFACTOR" in g
    assert "preserve" in g.lower()
    assert "regression" in g.lower()


def test_perf_opt_requires_quantified_target_and_byte_for_byte():
    """case-4 lesson: N+1 fix must guarantee response-shape preservation,
    including subtleties like nested array order under selectinload."""
    g = _intent_specific_guidance("perf_opt")
    assert "PERFORMANCE OPTIMIZATION" in g
    assert "quantif" in g.lower()
    assert "behavior-preservation" in g.lower() or "preserve" in g.lower()
    assert "selectinload" in g  # explicit guard against case-4-style subtle break


def test_unknown_intent_type_falls_back_to_general():
    g = _intent_specific_guidance("something_unknown")
    assert "general spec" in g
    assert "do not assume" in g.lower()


def test_empty_intent_type_falls_back_to_general():
    g = _intent_specific_guidance("")
    assert "general spec" in g


def test_intent_type_is_case_insensitive():
    g_upper = _intent_specific_guidance("FIX_BUG")
    g_lower = _intent_specific_guidance("fix_bug")
    assert g_upper == g_lower


def test_render_reviewer_prompt_includes_intent_specific_guidance(monkeypatch):
    """Smoke test that the full reviewer prompt actually contains the
    intent-specific guidance after rendering. This is what the LLM sees."""
    import re

    from devloop.spec_phase.agents.context import SpecContext
    from devloop.spec_phase.agents.reviewers.stage import _render_reviewer_prompt
    from devloop.spec_phase.schemas import (
        ConfirmedIntent,
        ConsolidatedExploration,
        Spec,
        SpecMetadata,
    )

    VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

    class FakePromptLoader:
        def load(self, key, **vars):
            templates = {
                "reviewer/_base": (
                    "BASE_PROMPT\nINTENT={{intent_type}}\n"
                    "GUIDANCE_BLOCK=[{{intent_specific_guidance}}]\n"
                ),
                "reviewer/architecture": "ANGLE_PROMPT\n{{base_prompt}}",
            }
            text = templates[key]
            if not vars:
                return text

            def _sub(m):
                k = m.group(1)
                if k not in vars:
                    return m.group(0)
                return str(vars[k])

            return VAR_RE.sub(_sub, text)

    fake_ctx = SpecContext.__new__(SpecContext)
    fake_ctx.prompts = FakePromptLoader()
    fake_ctx.intent = ConfirmedIntent(
        primary="Add comments to products",
        intent_type="add_feature",
        scope=["backend"],
    )
    fake_ctx.exploration = ConsolidatedExploration()

    spec = Spec(
        metadata=SpecMetadata(feature_id="x", title="Y"),
        summary="..",
    )

    rendered = _render_reviewer_prompt(fake_ctx, "architecture", spec)

    assert "BASE_PROMPT" in rendered
    assert "INTENT=add_feature" in rendered
    assert "NEW capability" in rendered  # the guidance was injected
    assert "DO NOT flag" in rendered
    assert "ANGLE_PROMPT" in rendered  # angle prompt wrapping is preserved
