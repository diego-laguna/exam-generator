"""LLM access behind a small seam so tests never touch the network."""

from functools import lru_cache
from typing import Protocol

from anthropic.types import ToolParam
from pydantic import BaseModel, ValidationError

from exam_core.config import get_settings


class LlmError(Exception):
    """The model call failed or returned something unusable. Safe to retry a few times."""


class Llm(Protocol):
    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T:
        """Returns the model's answer parsed into `schema`. Raises LlmError."""
        ...


class AnthropicLlm:
    """Forces a single tool call whose input schema is `schema`, which yields validated JSON."""

    def __init__(self, api_key: str, max_tokens: int) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=90)
        self._max_tokens = max_tokens

    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T:
        tool = ToolParam(
            name="submit",
            description="Submit the result.",
            input_schema=schema.model_json_schema(),
        )
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[tool],
                tool_choice={"type": "tool", "name": "submit"},
            )
        except self._anthropic.APIError as exc:
            raise LlmError(f"Model call failed: {type(exc).__name__}") from exc
        for block in response.content:
            if block.type == "tool_use":
                try:
                    return schema.model_validate(block.input)
                except ValidationError as exc:
                    raise LlmError("The model returned an invalid structure") from exc
        raise LlmError("The model did not return a result")


@lru_cache
def _anthropic_llm() -> Llm | None:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        return None
    return AnthropicLlm(settings.anthropic_api_key.get_secret_value(), settings.llm_max_tokens)


def get_llm() -> Llm | None:
    """The configured model client, or None when the worker has no API key."""
    return _anthropic_llm()
