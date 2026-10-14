"""The effort-aware Anthropic provider must add `effort` without disturbing the adapter's request."""

import pytest
from system_one_adapter.providers.base import Message

from systemone.providers import EffortAnthropicProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    return EffortAnthropicProvider("claude-opus-5-5", effort="low")


def test_effort_is_merged_into_output_config_next_to_the_schema(provider):
    schema = {"type": "object", "properties": {"answers": {"type": "object"}}, "required": ["answers"]}
    kwargs = provider.build_kwargs(
        [Message(role="system", content="sys"), Message(role="user", content="hi")], schema, structured=True
    )
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["max_tokens"] == 4096
    assert kwargs["system"] == "sys" and kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["output_config"] == {"format": {"type": "json_schema", "schema": schema}, "effort": "low"}


def test_prompted_mode_has_no_format_but_keeps_effort(provider):
    kwargs = provider.build_kwargs([Message(role="user", content="hi")], {}, structured=False)
    assert kwargs["output_config"] == {"effort": "low"}


def test_no_effort_means_the_adapters_request_is_untouched(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    plain = EffortAnthropicProvider("claude-opus-5-5", effort=None)
    kwargs = plain.build_kwargs([Message(role="user", content="hi")], {"type": "object"}, structured=True)
    assert "effort" not in kwargs["output_config"]


def test_invalid_effort_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    with pytest.raises(ValueError):
        EffortAnthropicProvider("claude-opus-5-5", effort="turbo")
