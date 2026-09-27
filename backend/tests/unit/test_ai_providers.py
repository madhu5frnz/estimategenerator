"""Provider plumbing without network access: a fake Anthropic client stands in."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.ai import providers
from app.ai.providers import (
    AnthropicProvider,
    ProviderResult,
    cost_usd,
    get_provider,
    system_prompt,
)
from app.ai.schemas import ExtractionResult
from app.config import get_settings
from app.core.errors import AppError


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ("AI_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    providers._provider.cache_clear()
    yield
    get_settings.cache_clear()
    providers._provider.cache_clear()


class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def provider_with(
    outcome: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[AnthropicProvider, FakeMessages]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    provider = AnthropicProvider()
    fake = FakeMessages(outcome)
    provider._client = SimpleNamespace(messages=fake)  # type: ignore[assignment]
    return provider, fake


def response(**overrides: Any) -> SimpleNamespace:
    base = {
        "stop_reason": "end_turn",
        "parsed_output": ExtractionResult(project_type="road"),
        "model": "claude-sonnet-5",
        "usage": SimpleNamespace(input_tokens=500, output_tokens=900, cache_read_input_tokens=2500,
                                 cache_creation_input_tokens=0),
    }  # fmt: skip
    return SimpleNamespace(**{**base, **overrides})


def test_default_provider_is_rules_without_a_key() -> None:
    assert get_provider().name == "rules"


def test_anthropic_selected_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    assert get_provider().name == "anthropic"
    monkeypatch.setenv("AI_PROVIDER", "rules")
    get_settings.cache_clear()
    providers._provider.cache_clear()
    assert get_provider().name == "rules"


def test_request_shape_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, fake = provider_with(response(), monkeypatch)
    result = provider.extract("CC road 500 m long")
    call = fake.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert call["output_format"] is ExtractionResult
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "road_layer" in call["system"][0]["text"]
    assert call["messages"][0]["content"] == "<description>\nCC road 500 m long\n</description>"
    assert (result.input_tokens, result.output_tokens, result.cache_read_tokens) == (500, 900, 2500)


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (response(stop_reason="refusal"), "AI_REFUSED"),
        (response(stop_reason="max_tokens"), "AI_OUTPUT_INVALID"),
        (response(parsed_output=None), "AI_OUTPUT_INVALID"),
        (
            anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.test")),
            "AI_PROVIDER_UNAVAILABLE",
        ),
        (
            anthropic.RateLimitError(
                "slow down",
                response=httpx2.Response(429, request=httpx2.Request("POST", "https://api.test")),
                body=None,
            ),
            "AI_PROVIDER_BUSY",
        ),
        (
            anthropic.InternalServerError(
                "boom",
                response=httpx2.Response(500, request=httpx2.Request("POST", "https://api.test")),
                body=None,
            ),
            "AI_PROVIDER_UNAVAILABLE",
        ),
    ],
)
def test_failures_become_clear_errors(
    outcome: Any, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, _ = provider_with(outcome, monkeypatch)
    with pytest.raises(AppError) as exc:
        provider.extract("CC road")
    assert exc.value.error_code == code


def test_cost_uses_price_table() -> None:
    result = ProviderResult(
        result=ExtractionResult(), model="claude-sonnet-5", input_tokens=1000, output_tokens=1800,
        cache_read_tokens=2500, cache_write_tokens=0,
    )  # fmt: skip
    # 1000×2 + 2500×2×0.1 + 1800×10 = 20,500 per million → $0.0205
    assert cost_usd(result) == Decimal("0.020500")
    assert cost_usd(ProviderResult(result=ExtractionResult(), model="unknown")) == Decimal(0)


def test_system_prompt_forbids_rates_and_invention() -> None:
    prompt = system_prompt()
    assert "Never invent" in prompt
    assert "Do not provide rates" in prompt
    assert "{{template_catalogue_json}}" not in prompt
