"""Worker test doubles: a dict-backed fetcher, a scripted LLM, and a sample HTML page."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from worker.llm import LlmError


class FakeFetcher:
    def __init__(self, pages: dict[str, str | Exception] | None = None):
        self.pages: dict[str, str | Exception] = pages or {}
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def page(title: str, *sections: tuple[str, str]) -> str:
    body = "".join(f"<h2>{h}</h2><p>{text}</p>" for h, text in sections)
    return (
        f"<html><head><title>{title}</title><script>var x=1;</script></head><body>"
        f"<nav>Menu Home Docs</nav><div id='main-content'><h1>{title}</h1>{body}</div>"
        f"<footer>Copyright</footer></body></html>"
    )


class FakeLlm:
    """Answers each call from a handler(schema, prompt) -> BaseModel | Exception."""

    def __init__(self, handler: Callable[[type[BaseModel], str], Any]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str]] = []  # (model, schema name)

    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T:
        self.calls.append((model, schema.__name__))
        result = self.handler(schema, prompt)
        if isinstance(result, Exception):
            raise result
        return result


__all__ = ["FakeFetcher", "FakeLlm", "LlmError", "page"]
