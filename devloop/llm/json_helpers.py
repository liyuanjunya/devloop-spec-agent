"""Helpers for strict-JSON LLM calls.

Two-phase pattern (from agent_v4): tools and response_format are mutually
exclusive in many providers. When a stage needs both tool calls *and* a
strict-JSON final output, run Phase 1 with tools (markdown allowed), then
Phase 2 without tools but with response_format=json forcing structured output.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from devloop.llm.gateway import LLMGateway
from devloop.llm.types import Message, ToolSpec

T = TypeVar("T", bound=BaseModel)


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Extract a JSON object from a possibly-markdown text."""
    # Try the whole text first
    candidates = [text.strip()]
    # Then any ```json ... ``` block
    for m in JSON_BLOCK_RE.finditer(text):
        candidates.append(m.group(1))
    # Then a heuristic: from first { or [ to last } or ]
    first = min(
        (i for i in (text.find("{"), text.find("[")) if i >= 0),
        default=-1,
    )
    last = max(text.rfind("}"), text.rfind("]"))
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])

    last_error: Exception | None = None
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError as e:
            last_error = e
            continue
    raise ValueError(f"No valid JSON found. Last error: {last_error}. Text: {text[:500]}")


async def call_strict_json(
    gateway: LLMGateway,
    *,
    role: str,
    schema: type[T],
    messages: list[Message],
    system: str = "",
    max_tokens: int = 8192,
    temperature: float = 0.0,
    run_id: str = "",
    stage: str = "",
    agent: str = "",
    max_repair_attempts: int = 2,
) -> T:
    """Call the LLM and parse the response into `schema`.

    If parsing fails, re-prompt with the error message up to ``max_repair_attempts``
    times. Each repair sends only the *original* prompt + the most recent bad
    response + the error — message history does not accumulate, so the context
    window stays bounded even after many retries.
    """
    schema_hint = (
        f"\n\n## Output requirements\n"
        f"Respond with ONLY a JSON object matching this schema:\n\n"
        f"```json\n{json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)}\n```\n"
        f"Return ONLY the JSON. No prose, no markdown, no explanation."
    )

    original_messages = list(messages)
    system_with_hint = (system or "") + schema_hint

    last_error: str = ""
    last_response_content: str = ""
    for attempt in range(max_repair_attempts + 1):
        if attempt == 0:
            attempt_messages = original_messages
        else:
            # Only keep original + previous bad + error — don't accumulate
            attempt_messages = [*original_messages, Message(role="assistant", content=last_response_content), Message(role="user", content=f"The previous response was invalid: {last_error}\n\n" f"Please respond again with ONLY a JSON object matching the schema. " f"No prose, no markdown fences, no explanation.")]

        resp = await gateway.call(
            role=role,
            messages=attempt_messages,
            system=system_with_hint,
            tools=None,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format="json",
            run_id=run_id,
            stage=stage,
            agent=agent or f"{role}_strict_json",
        )
        last_response_content = resp.content
        try:
            data = extract_json(resp.content)
            return schema.model_validate(data)
        except (ValueError, ValidationError) as e:
            last_error = f"{type(e).__name__}: {e}"

    raise ValueError(
        f"call_strict_json failed after {max_repair_attempts + 1} attempts. Last error: {last_error}"
    )


async def call_react_with_tools(
    gateway: LLMGateway,
    *,
    role: str,
    messages: list[Message],
    system: str,
    tools: list[ToolSpec],
    tool_executor,  # Callable[[ToolCall], Awaitable[ToolResult]]
    max_iterations: int = 30,
    max_tokens: int = 8192,
    temperature: float = 0.0,
    run_id: str = "",
    stage: str = "",
    agent: str = "",
    on_iteration=None,  # Optional callback(iteration, response) -> None
) -> tuple[str, int]:
    """Run a ReAct loop: LLM thinks → tools → LLM observes → repeat.

    Returns (final_assistant_content, tool_calls_made).

    Terminates when:
      - LLM produces no tool calls (it's done reasoning), OR
      - max_iterations reached.
    """
    conv = list(messages)
    tool_calls_made = 0

    for iteration in range(max_iterations):
        resp = await gateway.call(
            role=role,
            messages=conv,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            run_id=run_id,
            stage=stage,
            agent=agent or f"{role}_react",
        )

        if on_iteration is not None:
            try:
                await _maybe_await(on_iteration(iteration, resp))
            except Exception:
                pass

        if not resp.tool_calls:
            return resp.content, tool_calls_made

        # Append assistant message with tool_calls
        conv.append(
            Message(
                role="assistant",
                content=resp.content,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in resp.tool_calls
                ],
            )
        )

        # Execute each tool call (in parallel via gather is possible for stateless tools,
        # but mark_as_relevant / take_note write state — keep sequential for determinism).
        for tc in resp.tool_calls:
            tool_calls_made += 1
            result = await tool_executor(tc)
            conv.append(gateway.format_tool_result(result, role=role))

    # Hit max iterations — return whatever text we have
    return resp.content if "resp" in locals() else "", tool_calls_made


async def _maybe_await(value):
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value
