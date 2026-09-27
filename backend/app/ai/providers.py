"""Extraction providers: ``rules`` (default, no key needed), ``mock`` (tests) and
``anthropic`` (when ANTHROPIC_API_KEY is set). All return the same ExtractionResult."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Protocol

import structlog

from app.ai import rules
from app.ai.schemas import ExtractionResult
from app.config import get_settings
from app.core.errors import AppError
from app.domain.quantity.templates import template_rows

log = structlog.get_logger(__name__)
PROMPT_ID = "extract_parameters"
PROMPT_VERSION = 1
PROMPT_FILE = Path(__file__).parent / "prompts" / f"{PROMPT_ID}.v{PROMPT_VERSION}.md"


@dataclass
class ProviderResult:
    result: ExtractionResult
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class ExtractionProvider(Protocol):
    name: str
    provenance: str  # provenance stamped on values this provider extracted
    metered: bool  # counts against the plan's AI quota

    def model_id(self) -> str: ...

    def extract(self, text: str) -> ProviderResult: ...


class RulesProvider:
    name = "rules"
    provenance = "rule_extracted"
    metered = False

    def model_id(self) -> str:
        return rules.RULES_VERSION

    def extract(self, text: str) -> ProviderResult:
        started = time.perf_counter()
        result = rules.extract(text)
        return ProviderResult(
            result=result,
            model=self.model_id(),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw=result.model_dump(),
        )


class MockProvider:
    """Returns recorded outputs registered by tests (falls back to the rules parser)."""

    name = "mock"
    provenance = "ai_extracted"
    metered = True
    responses: ClassVar[dict[str, dict[str, Any]]] = {}

    def model_id(self) -> str:
        return "mock"

    @classmethod
    def register(cls, text: str, output: dict[str, Any]) -> None:
        cls.responses[hashlib.sha256(text.strip().encode()).hexdigest()] = output

    def extract(self, text: str) -> ProviderResult:
        raw = self.responses.get(hashlib.sha256(text.strip().encode()).hexdigest())
        if raw is None:
            raw = rules.extract(text).model_dump()
        return ProviderResult(
            result=ExtractionResult.model_validate(raw), model="mock", input_tokens=1200,
            output_tokens=400, raw=raw,
        )  # fmt: skip


def system_prompt() -> str:
    catalogue = [
        {k: row[k] for k in ("id", "name", "category", "expression", "parameters", "output_unit")}
        for row in template_rows()
    ]
    return PROMPT_FILE.read_text(encoding="utf-8").replace(
        "{{template_catalogue_json}}", json.dumps(catalogue, indent=1, ensure_ascii=False)
    )


class AnthropicProvider:
    name = "anthropic"
    provenance = "ai_extracted"
    metered = True

    def __init__(self) -> None:
        import anthropic

        settings = get_settings()
        assert settings.anthropic_api_key is not None
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=float(settings.ai_request_timeout_seconds),
            max_retries=2,
        )

    def model_id(self) -> str:
        return get_settings().ai_model_standard

    def extract(self, text: str) -> ProviderResult:
        a = self._anthropic
        started = time.perf_counter()
        try:
            response = self._client.messages.parse(
                model=self.model_id(),
                max_tokens=8000,
                # Stable system prompt first so it is served from the prompt cache.
                system=[
                    {
                        "type": "text",
                        "text": system_prompt(),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": f"<description>\n{text}\n</description>"}],
                output_format=ExtractionResult,
            )
        except a.RateLimitError as exc:
            raise AppError(
                "AI_PROVIDER_BUSY", "The AI service is busy. Please try again shortly.", 503
            ) from exc
        except a.APIStatusError as exc:
            log.warning("anthropic_error", status=exc.status_code)
            raise AppError(
                "AI_PROVIDER_UNAVAILABLE",
                "The AI service returned an error. Please try again.",
                502,
            ) from exc
        except a.APIConnectionError as exc:
            raise AppError(
                "AI_PROVIDER_UNAVAILABLE", "Could not reach the AI service. Please try again.", 503
            ) from exc

        if response.stop_reason == "refusal":
            raise AppError(
                "AI_REFUSED", "The AI declined this request. Try rephrasing the description.", 422
            )
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise AppError(
                "AI_OUTPUT_INVALID", "The AI response was incomplete. Please try again.", 422
            )
        usage = response.usage
        return ProviderResult(
            result=response.parsed_output,
            model=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw=response.parsed_output.model_dump(),
        )


def cost_usd(result: ProviderResult) -> Decimal:
    """Estimated cost from the configured price table (USD per million tokens)."""
    prices = get_settings().ai_price_table.get(result.model)
    if not prices:
        return Decimal(0)
    per_in, per_out = (Decimal(str(p)) for p in prices[:2])
    uncached = Decimal(result.input_tokens)
    cost = (
        uncached * per_in
        + Decimal(result.cache_write_tokens) * per_in * Decimal("1.25")
        + Decimal(result.cache_read_tokens) * per_in * Decimal("0.1")
        + Decimal(result.output_tokens) * per_out
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


@lru_cache(maxsize=4)
def _provider(name: str) -> ExtractionProvider:
    if name == "anthropic":
        return AnthropicProvider()
    if name == "mock":
        return MockProvider()
    return RulesProvider()


def get_provider() -> ExtractionProvider:
    settings = get_settings()
    name = settings.effective_ai_provider
    if name == "anthropic" and settings.anthropic_api_key is None:
        name = "rules"
    return _provider(name)
