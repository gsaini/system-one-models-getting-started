"""An Anthropic provider for TypeSafe's adapter that also sets `effort`.

The adapter's own `AnthropicProvider` sends `model`, `max_tokens`, `system`, `messages`, and
`output_config.format` (schema-constrained output). On claude-opus-5-5 thinking is always on and
effort defaults to `medium`; a yes/no classification doesn't need that much, and the launch post
compares against "default reasoning". This subclass merges `effort` into `output_config` so the
comparison can be run at `low` as well as the default.

It reaches into the adapter's private helpers, so pyproject pins the adapter's minor version.
"""

from __future__ import annotations

from typing import Any

from system_one_adapter.providers.anthropic import AnthropicProvider, _request_kwargs, _result
from system_one_adapter.providers.base import Message, ProviderResult, record_request, translating

EFFORTS = ("low", "medium", "high", "xhigh", "max")


class EffortAnthropicProvider(AnthropicProvider):
    def __init__(self, model_name: str, *, effort: str | None = None, max_tokens: int = 4096) -> None:
        if effort is not None and effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}")
        super().__init__(model_name, max_tokens=max_tokens)
        self.effort = effort

    def build_kwargs(self, messages: list[Message], schema: dict[str, Any], *, structured: bool) -> dict[str, Any]:
        kwargs = _request_kwargs(self.model_name, messages, schema, structured=structured, max_tokens=self.max_tokens)
        if self.effort:
            kwargs["output_config"] = {**kwargs.get("output_config", {}), "effort": self.effort}
        return kwargs

    def request(self, messages: list[Message], *, schema: dict[str, Any], structured: bool) -> ProviderResult:
        with translating(self.translate_error):
            kwargs = self.build_kwargs(messages, schema, structured=structured)
            record_request(kwargs, api="messages")
            response = self._client.messages.create(**kwargs)
        return _result(response)
