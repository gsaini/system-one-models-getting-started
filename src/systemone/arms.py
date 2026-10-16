"""Arms: the things we compare. Each one answers `system_one(state, questions)`.

- **Jev** via the official `typesafe-sdk`.
- **An LLM** via TypeSafe's `system-one-adapter`, a drop-in `TypeSafeClient` replacement that asks
  the LLM for the same typed answers with structured outputs. Claude by default; or a local
  model served by Ollama (`--ollama`), through the adapter's OpenAI-compatible provider.
- **Keyword baseline**: offline rules behind the real SDK (see baseline.py).

`Arm.ask` times every call, records tokens and list-price cost, and turns failures into recorded
errors instead of exceptions, so an experiment can finish and report them.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from typesafe_sdk import RetryPolicy, SystemOneResponse, TypeSafeClient, TypeSafeError
from typesafe_sdk.constants import API_KEY_ENV

from systemone.baseline import Answerer, KeywordBaseline

# USD per token (input, output). Checked 2026-10-14; re-check before quoting a cost.
#   Jev: https://docs.typesafe.ai/models — $42 per billion input tokens, output free.
#   Claude: https://platform.claude.com/docs/en/about-claude/pricing
PRICES: dict[str, tuple[float, float]] = {
    "jev": (42 / 1_000_000_000, 0.0),
    "claude-opus-5-5": (4 / 1_000_000, 20 / 1_000_000),
    "claude-sonnet-5-5": (2 / 1_000_000, 10 / 1_000_000),
    "claude-haiku-5-5": (0.10 / 1_000_000, 0.50 / 1_000_000),
    "claude-haiku-4-5": (1 / 1_000_000, 5 / 1_000_000),
    "keyword-baseline": (0.0, 0.0),
}
DEFAULT_LLM = "claude-opus-5-5"
DEFAULT_OLLAMA = "tinyllama"
OLLAMA_URL = "http://localhost:11434/v1"


class MissingCredentials(RuntimeError):
    pass


@dataclass(frozen=True)
class Call:
    ok: bool
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    error: str = ""
    malformed_retries: int = 0  # adapter only: LLM output that failed the schema and was retried


@dataclass
class Arm:
    name: str
    client: Any  # TypeSafeClient or SystemOneAdapterClient: both expose .system_one(state, questions)
    price: tuple[float, float]
    calls: list[Call] = field(default_factory=list)

    def ask(self, state: Any, questions: Any) -> SystemOneResponse | None:
        started = time.perf_counter()
        try:
            response = self.client.system_one(state, questions)
        except TypeSafeError as exc:
            self.calls.append(Call(False, (time.perf_counter() - started) * 1000, error=f"{type(exc).__name__}: {exc}"))
            return None
        latency_ms = (time.perf_counter() - started) * 1000
        usage = response.usage
        tokens_in = getattr(usage, "input_tokens_total", None) or usage.input_tokens or 0
        tokens_out = getattr(usage, "output_tokens_total", None) or usage.output_tokens or 0
        self.calls.append(
            Call(
                True,
                latency_ms,
                tokens_in,
                tokens_out,
                tokens_in * self.price[0] + tokens_out * self.price[1],
                response.model,
                malformed_retries=getattr(usage, "n_retries_malformed_structure", 0) or 0,
            )
        )
        return response

    def summary(self) -> dict[str, Any]:
        ok = [c for c in self.calls if c.ok]
        latencies = sorted(c.latency_ms for c in ok)
        return {
            "arm": self.name,
            "model": next((c.model for c in ok if c.model), ""),
            "calls": len(self.calls),
            "errors": len(self.calls) - len(ok),
            "malformed_retries": sum(c.malformed_retries for c in ok),
            "input_tokens": sum(c.input_tokens for c in ok),
            "output_tokens": sum(c.output_tokens for c in ok),
            "cost_usd": sum(c.cost_usd for c in ok),
            "latency_p50_ms": statistics.median(latencies) if latencies else 0.0,
            "latency_p95_ms": latencies[max(0, round(0.95 * len(latencies)) - 1)] if latencies else 0.0,
        }


def baseline_arm(answerer: Answerer, name: str = "keyword baseline") -> Arm:
    baseline = KeywordBaseline(answerer)
    client = TypeSafeClient(
        api_key="offline-keyword-baseline", transport=baseline.transport(), retry=RetryPolicy(max_retries=0)
    )
    return Arm(name, client, PRICES["keyword-baseline"])


def jev_arm(*, timeout: float = 20.0, retries: int = 2) -> Arm:
    if not os.environ.get(API_KEY_ENV, "").strip():
        raise MissingCredentials(
            f"Jev needs ${API_KEY_ENV} (https://console.typesafe.ai/keys). "
            "Without --live, only the offline baseline runs."
        )
    return Arm("Jev", TypeSafeClient(timeout=timeout, retry=RetryPolicy(max_retries=retries)), PRICES["jev"])


def llm_arm(model: str = DEFAULT_LLM, *, effort: str | None = "low", max_tokens: int = 4096) -> Arm:
    """Claude answering the same typed questions, through TypeSafe's adapter with structured outputs."""
    import anthropic
    from system_one_adapter import SystemOneAdapterClient

    from systemone.providers import EffortAnthropicProvider

    try:
        provider = EffortAnthropicProvider(model, effort=effort, max_tokens=max_tokens)
    except anthropic.AnthropicError as exc:  # no key and no `ant auth login` profile
        raise MissingCredentials(
            f"The LLM arm needs Anthropic credentials (ANTHROPIC_API_KEY or `ant auth login`): {exc}"
        ) from exc
    client = SystemOneAdapterClient(
        structured_outputs=True,  # Claude's schema-constrained output: the shape is guaranteed
        llm_answer_mode="probabilities",  # ask for a distribution, like Jev returns
        normalize_probabilities=True,  # rescale a distribution that doesn't sum to 1 instead of failing
        n_retry_malformed_structure=1,  # and count how often that was needed
        provider="anthropic",
        model=provider,
    )
    label = f"{model}" + (f" (effort {effort})" if effort else " (default effort)")
    return Arm(label, client, PRICES.get(model, PRICES[DEFAULT_LLM]))


def ollama_arm(model: str = DEFAULT_OLLAMA, *, base_url: str = OLLAMA_URL) -> Arm:
    """A local model served by Ollama, through the adapter's OpenAI-compatible Chat Completions provider. Free."""
    from system_one_adapter import SystemOneAdapterClient
    from system_one_adapter.providers.openai import OpenAIProvider

    # Fail once up front rather than recording a connection error for every call.
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=3) as resp:
            served = {m["id"] for m in json.load(resp)["data"]}
    except (OSError, ValueError, KeyError) as exc:
        raise MissingCredentials(f"No Ollama server at {base_url} (start it with `ollama serve`): {exc}") from exc
    if model not in served and f"{model}:latest" not in served:
        raise MissingCredentials(f"Ollama doesn't have {model!r}; run `ollama pull {model}`.")

    provider = OpenAIProvider(model, base_url=base_url, api_key="ollama", api="chat_completions")
    client = SystemOneAdapterClient(
        structured_outputs=True,  # Ollama constrains decoding to the JSON schema
        llm_answer_mode="probabilities",
        normalize_probabilities=True,
        n_retry_malformed_structure=1,
        provider="openai",
        model=provider,
    )
    return Arm(f"{model} (Ollama)", client, (0.0, 0.0))


def summary_table(arms: list[Arm]) -> str:
    rows = [a.summary() for a in arms]
    lines = [
        "| arm | model | calls | errors | malformed retries | input / output tokens | cost | latency p50 / p95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['arm']} | `{r['model']}` | {r['calls']} | {r['errors']} | {r['malformed_retries']} | "
            f"{r['input_tokens']:,} / {r['output_tokens']:,} | ${r['cost_usd']:.5f} | "
            f"{r['latency_p50_ms']:.0f} / {r['latency_p95_ms']:.0f} ms |"
        )
    return "\n".join(lines)
