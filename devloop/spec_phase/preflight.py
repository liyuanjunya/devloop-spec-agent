"""Stage 0: input pre-flight check (deterministic, no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Verb-like roots that suggest a clear action being requested.
# Multi-language because the user is bilingual (zh/en).
# Chinese verbs are matched character-by-character against the user text via the
# `CHINESE_VERB_CHARS` set, with surrounding-context heuristics in `_chinese_verb_present`.
CHINESE_VERB_CHARS = {
    "加",
    "添",
    "增",
    "建",
    "改",
    "修",
    "实",
    "支",
    "去",
    "删",
    "移",
    "替",
    "升",
    "对",
    "接",
    "开",
    "优",
    "重",
    "提",
    "整",
    "做",  # OK alone or as part of "做一个"; disambiguated by context
    "搞",
}
# Common Chinese verb tokens (2+ chars).
CHINESE_VERB_TOKENS = {
    "添加",
    "新增",
    "实现",
    "支持",
    "修复",
    "修改",
    "重构",
    "优化",
    "升级",
    "替换",
    "对接",
    "接入",
    "开发",
    "整合",
    "去掉",
    "删除",
    "移除",
    "提升",
    "改善",
}
# Chinese 2-character words that contain `做`/`加` etc but should NOT be treated as verb hints
# because they are nouns (workpiece, action, etc.).
CHINESE_VERB_FALSE_POSITIVES = {
    "工作",
    "动作",
    "操作",
    "做法",
    "做事",  # noun-ish
    "增加",  # actually a verb — OK
}

ENGLISH_VERB_TOKENS = {
    "add",
    "create",
    "implement",
    "build",
    "make",
    "support",
    "fix",
    "improve",
    "refactor",
    "optimize",
    "enable",
    "introduce",
    "integrate",
    "remove",
    "delete",
    "update",
    "migrate",
    "rename",
    "replace",
    "extract",
    "upgrade",
    "expose",
    "wire",
    "render",
}

MIN_CHARS = 8
MAX_CHARS_FOR_AUTOMATIC = 5000


@dataclass
class PreflightResult:
    ok: bool
    reason: str = ""
    suggestion: str = ""

    @classmethod
    def passed(cls) -> PreflightResult:
        return cls(ok=True)

    @classmethod
    def failed(cls, reason: str, suggestion: str = "") -> PreflightResult:
        return cls(ok=False, reason=reason, suggestion=suggestion)


_WORD_RE = re.compile(r"[A-Za-z]+|[\u4e00-\u9fff]")  # Each CJK char counted as a "word"
_ENGLISH_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z\-']{1,}\b")


def _english_verb_present(text: str) -> bool:
    lowered = text.lower()
    for tok in _ENGLISH_TOKEN_RE.findall(lowered):
        if tok in ENGLISH_VERB_TOKENS:
            return True
    return False


def _chinese_verb_present(text: str) -> bool:
    # Token-level: prefer 2-char verb phrases
    for tok in CHINESE_VERB_TOKENS:
        if tok in text:
            # Check it's not part of a false-positive longer word
            # (CHINESE_VERB_TOKENS are typically standalone — accept)
            return True
    # Character-level fallback: a leading Chinese verb-character followed by
    # something else, but avoid the documented false positives.
    for fp in CHINESE_VERB_FALSE_POSITIVES:
        # Only block if the whole text reduces to false positives — generous accept
        pass
    # Stricter character check: the verb character must NOT be embedded inside a
    # known false-positive word.
    for ch in text:
        if ch in CHINESE_VERB_CHARS:
            # Look at 2-char windows around ch
            idx = text.index(ch)
            for fp in CHINESE_VERB_FALSE_POSITIVES:
                if fp in text:
                    # If the fp consumes our character, skip; otherwise continue.
                    fp_start = text.find(fp)
                    if fp_start <= idx < fp_start + len(fp):
                        return False if fp in {"工作", "动作", "操作"} else True
            return True
    return False


def preflight(user_input: str) -> PreflightResult:
    """Check user input quality with cheap deterministic rules."""
    text = (user_input or "").strip()

    if len(text) < MIN_CHARS:
        return PreflightResult.failed(
            f"Input is too short ({len(text)} chars; need >= {MIN_CHARS}).",
            "Describe what you want to build, e.g. '给商品页加用户评论功能' or 'add user authentication to the API'.",
        )

    if len(text) > MAX_CHARS_FOR_AUTOMATIC:
        return PreflightResult.failed(
            f"Input is too long ({len(text)} chars). Trim to under {MAX_CHARS_FOR_AUTOMATIC} characters.",
            "Provide a concise feature description, not a complete spec.",
        )

    # Verb requirement
    if not _english_verb_present(text) and not _chinese_verb_present(text):
        if not re.search(r"\b[A-Za-z]{3,}\b.*[:：]", text):
            return PreflightResult.failed(
                "Input does not contain any action verb (e.g. add/fix/implement/加/做/改).",
                "Describe what action you want, e.g. 'add user authentication' rather than 'authentication'.",
            )

    # Must contain at least 2 distinguishable tokens (avoid e.g. "asdfasdf")
    words = _WORD_RE.findall(text)
    distinct = set(w.lower() for w in words)
    if len(distinct) < 2:
        return PreflightResult.failed(
            "Input does not contain enough distinct words.",
            "Describe both what to do AND what to do it to, e.g. 'add login to users API'.",
        )

    return PreflightResult.passed()
