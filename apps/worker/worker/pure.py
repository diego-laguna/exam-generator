"""Pure helpers for the job handlers: values in, new values out (no I/O, DB, clock or mutation)."""

from collections.abc import Iterable, Sequence
from typing import Any

from exam_core.models import QuestionType
from worker.pdf_text import LineChunk, lines_to_json


def question_slots(mcq_count: int, true_false_count: int) -> tuple[QuestionType, ...]:
    return (QuestionType.mcq,) * mcq_count + (QuestionType.true_false,) * true_false_count


def citation_snapshots(
    filename: str, chunk_id: int, citations: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Citations as stored: the document name and chunk id are snapshotted next to each citation."""
    return [{"document": filename, "chunk_id": chunk_id, **c} for c in citations]


def blind_validation(blind_answer: str, reasoning: str) -> dict[str, Any]:
    return {"blind_answer": blind_answer, "ambiguous": False, "reasoning": reasoning}


def generation_failure(produced: int, llm_failures: int) -> str | None:
    """Error message for a finished generation, or None when at least one question was produced."""
    if produced > 0:
        return None
    return "The model could not be reached" if llm_failures else "No question passed validation"


def avoid_window(stems: Sequence[str], limit: int) -> list[str]:
    return list(stems[-limit:])


def document_chunk_rows(
    chunks: Sequence[LineChunk], vectors: Sequence[Sequence[float]]
) -> list[dict[str, Any]]:
    """Column values of each DocumentChunk (without document_id), position = index."""
    return [
        {"position": i, "lines": lines_to_json(c), "content": c.content, "embedding": vec}
        for i, (c, vec) in enumerate(zip(chunks, vectors))
    ]
