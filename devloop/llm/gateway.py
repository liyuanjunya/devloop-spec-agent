"""Top-level LLM Gateway — the single entry point for all LLM calls.

Responsibilities:
- Resolve role → (provider, model)
- Dispatch to provider
- Record traces
- Handle errors with retry (delegated to providers)
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from devloop.llm.providers.base import BaseProvider
from devloop.llm.retry import DEFAULT_BACKOFF_S, retry_with_backoff
from devloop.llm.routing import ModelAssignment, ModelRouter
from devloop.llm.trace import NullTraceWriter, TraceWriter
from devloop.llm.types import LLMResponse, Message, ToolResult, ToolSpec

logger = structlog.get_logger(__name__)


class LLMGateway:
    """The single LLM entry point used by every agent.

    Wraps every provider call in :func:`devloop.llm.retry.retry_with_backoff`
    so a transient hiccup escapes the provider's own SDK retries but is still
    caught and retried with the v7 schedule (5 attempts; [2, 5, 15, 30, 60]s
    backoff). On final failure a ``SubAgentFailedError`` is raised — there is
    no silent "skip and return None" path.
    """

    def __init__(
        self,
        providers: dict[str, BaseProvider],
        router: ModelRouter,
        trace: TraceWriter | None = None,
        *,
        retry_max_attempts: int = 5,
        retry_backoff_s: list[float] | None = None,
    ):
        self.providers = providers
        self.router = router
        self.trace = trace or NullTraceWriter()
        self._counters: dict[str, dict[str, int]] = {}
        self._retry_max_attempts = retry_max_attempts
        self._retry_backoff_s = (
            list(retry_backoff_s) if retry_backoff_s is not None else list(DEFAULT_BACKOFF_S)
        )

        # Sanity check
        for required in {router.primary_provider, router.cross_review_provider}:
            if required not in providers:
                raise ValueError(
                    f"Provider '{required}' required by router but not registered"
                )

    def provider_for(self, role: str) -> tuple[BaseProvider, ModelAssignment]:
        assignment = self.router.assign(role)
        prov = self.providers[assignment.provider]
        return prov, assignment

    async def call(
        self,
        *,
        role: str,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        response_format: str | None = None,
        timeout: float = 120.0,
        run_id: str = "",
        stage: str = "",
        agent: str = "",
        trace_id: str | None = None,
        explicit_model: str | None = None,
        explicit_provider: str | None = None,
    ) -> LLMResponse:
        """Generic call — provider chosen by role unless explicitly overridden."""
        trace_id = trace_id or str(uuid.uuid4())

        if explicit_model and explicit_provider:
            prov = self.providers[explicit_provider]
            model_to_use = explicit_model
            provider_name = explicit_provider
        else:
            prov, assignment = self.provider_for(role)
            model_to_use = assignment.model
            provider_name = assignment.provider

        t_start = time.perf_counter()
        resp: LLMResponse | None = None
        error: str | None = None
        try:
            async def _do_call() -> LLMResponse:
                return await prov.call(
                    model=model_to_use,
                    messages=messages,
                    system=system,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format=response_format,
                    timeout=timeout,
                )

            # Strict v7 retry: 5 attempts, [2, 5, 15, 30, 60]s backoff, halt-loud.
            # NEVER silently skip on exhaustion — SubAgentFailedError is raised.
            resp = await retry_with_backoff(
                _do_call,
                max_attempts=self._retry_max_attempts,
                backoff_s=self._retry_backoff_s,
                operation_name=f"LLM call {provider_name}/{model_to_use} role={role}",
            )
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            latency_ms = (time.perf_counter() - t_start) * 1000
            response_summary: dict[str, Any] | None = None
            usage_dict: dict[str, Any] = {}
            if resp is not None:
                response_summary = {
                    "stop_reason": resp.stop_reason,
                    "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
                }
                usage_dict = resp.usage.model_dump()
                # Aggregate counters onto the run context, if registered
                counter = self._counters.get(run_id)
                if counter is not None:
                    counter["llm_calls"] += 1
                    counter["input_tokens"] += resp.usage.input_tokens
                    counter["output_tokens"] += resp.usage.output_tokens
            self.trace.record_llm_call(
                run_id=run_id,
                trace_id=trace_id,
                stage=stage,
                agent=agent or role,
                provider=provider_name,
                model=model_to_use,
                messages=[m.model_dump() for m in messages],
                tools=[t.model_dump() for t in (tools or [])],
                response=response_summary,
                latency_ms=latency_ms,
                usage=usage_dict,
                error=error,
            )

        assert resp is not None  # only reachable when no exception was raised
        return resp

    def register_run(self, run_id: str) -> dict[str, int]:
        """Register a run-id and return a shared counter dict."""
        counter = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
        self._counters[run_id] = counter
        return counter

    def get_run_counter(self, run_id: str) -> dict[str, int] | None:
        return self._counters.get(run_id)

    def unregister_run(self, run_id: str) -> None:
        self._counters.pop(run_id, None)

    def format_tool_result(self, result: ToolResult, role: str) -> Message:
        prov, _ = self.provider_for(role)
        return prov.format_tool_result(result)


def build_gateway(
    settings: Any,
    *,
    trace: TraceWriter | None = None,
) -> LLMGateway:
    """Build a gateway from a Settings instance.

    Imports providers lazily so missing SDKs don't break imports.
    """
    from devloop.llm.providers.anthropic_provider import AnthropicProvider
    from devloop.llm.providers.openai_provider import OpenAIProvider

    providers: dict[str, BaseProvider] = {}
    if settings.llm.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(
            api_key=settings.llm.anthropic_api_key,
            max_retries=settings.llm.max_retries,
        )
    if settings.llm.openai_api_key:
        providers["openai"] = OpenAIProvider(
            api_key=settings.llm.openai_api_key,
            max_retries=settings.llm.max_retries,
        )

    from pathlib import Path

    from devloop.llm.routing import load_router_from_yaml

    # Find models.yaml
    configs_dir = Path(__file__).resolve().parent.parent.parent / "configs"
    if not configs_dir.exists():
        configs_dir = Path.cwd() / "configs"

    router = load_router_from_yaml(
        configs_dir / "models.yaml",
        primary_provider=settings.llm.primary_provider,
        primary_model=settings.llm.primary_model,
        cross_review_provider=settings.llm.cross_review_provider,
        cross_review_model=settings.llm.cross_review_model,
    )

    return LLMGateway(providers=providers, router=router, trace=trace)
