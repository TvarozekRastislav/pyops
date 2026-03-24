"""Tracked OpenAI client that records token usage and cost per run."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import openai
from litellm import cost_per_token

log = logging.getLogger(__name__)


@dataclass
class RunUsage:
    """Token usage accumulated for a single run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    n_calls: int = 0
    cost_usd: float = 0.0


class TrackedOpenAIClient:
    """Wraps openai.OpenAI to track token usage per run_id."""

    def __init__(
        self, client: openai.OpenAI | None = None, model: str = "gpt-4o"
    ):
        self._client = client or openai.OpenAI()
        self._model = model
        self._lock = threading.Lock()
        self._usage: dict[str, RunUsage] = {}
        self._current_run_id: str | None = None
        self.chat = _ChatProxy(self)

    @contextmanager
    def track(self, run_id: str):
        """Context manager that sets the active run_id for usage tracking."""
        with self._lock:
            if run_id not in self._usage:
                self._usage[run_id] = RunUsage()
            prev = self._current_run_id
            self._current_run_id = run_id
        try:
            yield self
        finally:
            with self._lock:
                self._current_run_id = prev

    def _record_usage(self, usage) -> None:
        """Record token usage from a chat completion response."""
        with self._lock:
            run_id = self._current_run_id
            if run_id is None or usage is None:
                return
            entry = self._usage[run_id]
            entry.prompt_tokens += usage.prompt_tokens or 0
            entry.completion_tokens += usage.completion_tokens or 0
            entry.total_tokens += (usage.prompt_tokens or 0) + (
                usage.completion_tokens or 0
            )
            entry.n_calls += 1
            entry.cost_usd += self._estimate_cost(
                usage.prompt_tokens or 0,
                usage.completion_tokens or 0,
            )

    def _estimate_cost(
        self, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Estimate USD cost using litellm's pricing database."""
        try:
            prompt_cost, completion_cost = cost_per_token(
                model=self._model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return prompt_cost + completion_cost
        except Exception:
            log.warning("litellm has no pricing for model %s, cost=0", self._model)
            return 0.0

    def get_usage(self, run_id: str) -> RunUsage:
        """Get accumulated usage for a run."""
        return self._usage.get(run_id, RunUsage())

    @property
    def underlying(self) -> openai.OpenAI:
        """Access the underlying OpenAI client directly."""
        return self._client


class _ChatProxy:
    """Proxy for client.chat.completions.create that records usage."""

    def __init__(self, tracker: TrackedOpenAIClient):
        self._tracker = tracker
        self.completions = _CompletionsProxy(tracker)


class _CompletionsProxy:
    """Proxy for chat.completions.create."""

    def __init__(self, tracker: TrackedOpenAIClient):
        self._tracker = tracker

    def create(self, **kwargs) -> object:
        """Forward to OpenAI and record usage."""
        response = self._tracker._client.chat.completions.create(**kwargs)
        if hasattr(response, "usage"):
            self._tracker._record_usage(response.usage)
        return response
