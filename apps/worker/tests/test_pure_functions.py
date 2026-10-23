from exam_core.models import QuestionType
from worker.chunking import Section, chunk_sections, pack_bodies
from worker.pdf_text import Line, chunk_lines, number_lines, quote_matches
from worker.pure import (
    avoid_window,
    citation_snapshots,
    document_chunk_rows,
    generation_failure,
    question_slots,
)


def test_number_lines_skips_empty() -> None:
    assert number_lines(2, ["a", "", "b"]) == [Line(2, 1, "a"), Line(2, 2, "b")]


def test_chunk_lines_windows_overlap() -> None:
    lines = [Line(1, i, f"l{i}") for i in range(1, 8)]
    chunks = chunk_lines(lines, 4, 1)
    assert [[ln.number for ln in c.lines] for c in chunks] == [[1, 2, 3, 4], [4, 5, 6, 7]]
    assert chunk_lines([], 4, 1) == []


def test_pack_bodies_overlaps() -> None:
    assert pack_bodies(["aaa bbb", "ccc ddd"], 9, 3) == ["aaa bbb", "bbb\nccc ddd"]


def test_chunk_sections_prefixes_heading() -> None:
    body = "x" * 50
    out = chunk_sections([Section("Title", [body])], 200, 20)
    assert [c.content for c in out] == [f"Title\n\n{body}"]


def test_quote_matches() -> None:
    rows = [[1, 1, "Hello wor-"], [1, 2, "ld again"]]
    assert quote_matches(rows, 1, 1, 2, "hello world")
    assert not quote_matches(rows, 1, 1, 3, "hello world")


def test_question_slots_and_failure() -> None:
    assert question_slots(2, 1) == (QuestionType.mcq, QuestionType.mcq, QuestionType.true_false)
    assert generation_failure(1, 3) is None
    assert generation_failure(0, 1) == "The model could not be reached"
    assert generation_failure(0, 0) == "No question passed validation"


def test_citation_snapshots_and_avoid_window() -> None:
    assert citation_snapshots("f.pdf", 7, [{"page": 1}]) == [
        {"document": "f.pdf", "chunk_id": 7, "page": 1}
    ]
    assert avoid_window(["a", "b", "c"], 2) == ["b", "c"]


def test_document_chunk_rows() -> None:
    chunks = chunk_lines([Line(1, 1, "a")], 4, 1)
    rows = document_chunk_rows(chunks, [[0.5]])
    assert rows == [{"position": 0, "lines": [[1, 1, "a"]], "content": "a", "embedding": [0.5]}]
