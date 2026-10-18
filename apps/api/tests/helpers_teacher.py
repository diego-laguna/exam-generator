"""Test doubles for the teacher flow: in-memory storage, PDF builder, scripted LLM."""

import io
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.llm import LlmError


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def make_pdf(pages: list[list[str]]) -> bytes:
    """One text line per entry, top to bottom, so line N of the page is entry N."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            pdf.drawString(60, y, line)
            y -= 18
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# Long enough lines that a chunk clears the minimum size.
LESSON = [
    [
        "Photosynthesis is the process by which green plants make food.",
        "Chlorophyll in the leaves absorbs sunlight during photosynthesis.",
        "The plant uses carbon dioxide and water to produce glucose and oxygen.",
        "Glucose is stored as starch and used for growth and energy.",
        "Oxygen is released into the air through tiny pores called stomata.",
    ],
    [
        "Cellular respiration releases energy from glucose inside the mitochondria.",
        "It needs oxygen and produces carbon dioxide, water and usable energy.",
        "Plants perform both photosynthesis and cellular respiration every day.",
    ],
]


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


__all__ = ["FakeLlm", "LlmError", "MemoryStorage", "LESSON", "make_pdf"]
