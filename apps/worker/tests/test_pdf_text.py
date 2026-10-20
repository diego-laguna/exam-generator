import pytest

from exam_core.errors import IngestionError
from worker.pdf_text import Line, chunk_lines, extract_lines, quote_matches
from exam_core.testing import LESSON, make_pdf


def test_extracts_numbered_lines_per_page_in_reading_order():
    lines, pages = extract_lines(make_pdf(LESSON), max_pages=10)
    assert pages == 2
    assert lines[0] == Line(1, 1, LESSON[0][0])
    assert [(l.page, l.number) for l in lines] == [(1, i) for i in range(1, 6)] + [(2, i) for i in range(1, 4)]
    assert lines[5].text == LESSON[1][0]


def test_rejects_non_pdf_and_empty_pdf_and_page_limit():
    with pytest.raises(IngestionError, match="not a PDF"):
        extract_lines(b"hello", 10)
    with pytest.raises(IngestionError, match="no extractable text"):
        extract_lines(make_pdf([[]]), 10)
    with pytest.raises(IngestionError, match="more than 1 pages"):
        extract_lines(make_pdf(LESSON), 1)
    with pytest.raises(IngestionError):
        extract_lines(b"%PDF-1.4 this is not really a pdf", 10)


def test_chunks_overlap_and_cover_everything():
    lines = [Line(1, i, f"line {i}") for i in range(1, 26)]
    chunks = chunk_lines(lines, max_lines=10, overlap=3)
    assert [len(c.lines) for c in chunks] == [10, 10, 10, 4]
    assert chunks[1].lines[0].number == 8  # starts 3 lines before the previous chunk ended
    assert chunks[-1].lines[-1].number == 25
    assert len(chunk_lines(lines[:5], 10, 3)) == 1


def test_quote_matching():
    lines = [[1, 1, "Chlorophyll in the leaves"], [1, 2, "absorbs sun-"], [1, 3, "light during the day."], [2, 1, "Other page"]]
    assert quote_matches(lines, 1, 1, 1, "chlorophyll IN the  leaves")
    assert quote_matches(lines, 1, 2, 3, "absorbs sunlight during")  # across lines, hyphenation
    assert not quote_matches(lines, 1, 1, 1, "absorbs sunlight")  # quote outside the cited lines
    assert not quote_matches(lines, 1, 1, 1, "Chlorophyll in the roots")  # changed word
    assert not quote_matches(lines, 1, 3, 4, "light during the day.")  # line 4 does not exist
    assert not quote_matches(lines, 2, 1, 1, "Chlorophyll")  # wrong page
    assert not quote_matches(lines, 1, 1, 1, "   ")


SPANISH = [
    [
        "La fotosíntesis es el proceso por el cual las plantas verdes fabrican su alimento.",
        "La clorofila de las hojas absorbe la luz del sol durante la fotosíntesis.",
        "¿Qué órgano libera oxígeno? Los estomas, pequeños poros de la hoja.",
        "El señor Muñoz explicó que la glucosa se almacena como almidón.",
    ]
]


def test_spanish_pdf_keeps_accents_and_matches_quotes():
    lines, pages = extract_lines(make_pdf(SPANISH), 10)
    assert pages == 1
    as_json = [[ln.page, ln.number, ln.text] for ln in lines]
    assert "fotosíntesis" in lines[0].text and "¿Qué órgano" in lines[2].text
    assert quote_matches(as_json, 1, 3, 3, "¿Qué órgano libera oxígeno?")
    assert quote_matches(as_json, 1, 4, 4, "EL SEÑOR MUÑOZ explicó")  # case-insensitive
    assert not quote_matches(as_json, 1, 4, 4, "El senor Munoz explicó")  # missing accents/tilde


def test_quote_matching_ignores_unicode_form_and_ligatures():
    composed = "La ﬁbra del señor está en la página"
    decomposed = "La fibra del sen\u0303or esta\u0301 en la pa\u0301gina"
    assert quote_matches([[1, 1, composed]], 1, 1, 1, decomposed)
    assert quote_matches([[1, 1, decomposed]], 1, 1, 1, composed)
