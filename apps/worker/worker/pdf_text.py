"""PDF -> numbered lines -> chunks. Page and line numbers are what citations refer to.

A "line" is a text line as laid out on the page, numbered 1.. in reading order per page (empty
lines are skipped). Numbers come from the extracted text, so they match the printed page when the
PDF has a real text layer; scanned PDFs have none and are rejected.
"""

import io
import re
import unicodedata
from dataclasses import dataclass

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer, LTTextLine
from pdfminer.pdfparser import PDFSyntaxError

from exam_core.errors import IngestionError


@dataclass(frozen=True)
class Line:
    page: int
    number: int
    text: str


@dataclass(frozen=True)
class LineChunk:
    lines: list[Line]

    @property
    def content(self) -> str:
        return "\n".join(line.text for line in self.lines)


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _squeeze(text: str) -> str:
    """Comparison form: no whitespace, hyphens or soft hyphens, so line-end hyphenation and
    re-spaced quotes still match, but a changed word does not. NFKC makes a precomposed "é" equal
    to "e" + combining accent and expands ligatures such as "ﬁ", which PDFs often contain."""
    return re.sub(r"[\s\u00ad-]+", "", unicodedata.normalize("NFKC", text)).lower()


def extract_lines(data: bytes, max_pages: int) -> tuple[list[Line], int]:
    """Returns (lines, page_count). Raises IngestionError with a user-safe message."""
    if not is_pdf(data):
        raise IngestionError("The file is not a PDF")
    lines: list[Line] = []
    pages = 0
    try:
        for page_no, layout in enumerate(
            extract_pages(io.BytesIO(data), laparams=LAParams()), start=1
        ):
            if page_no > max_pages:
                raise IngestionError(f"The PDF has more than {max_pages} pages")
            pages = page_no
            number = 0
            for element in layout:
                if not isinstance(element, LTTextContainer):
                    continue
                for line in element:
                    if not isinstance(line, LTTextLine):
                        continue
                    text = _normalize(line.get_text())
                    if text:
                        number += 1
                        lines.append(Line(page_no, number, text))
    except IngestionError:
        raise
    except PDFSyntaxError as exc:
        raise IngestionError("The PDF is corrupted or not readable") from exc
    except Exception as exc:  # pdfminer raises many types on malformed or encrypted files
        raise IngestionError("The PDF could not be read (it may be encrypted or malformed)") from exc
    if not lines:
        raise IngestionError("The PDF has no extractable text (scanned documents are not supported)")
    return lines, pages


def chunk_lines(lines: list[Line], max_lines: int, overlap: int) -> list[LineChunk]:
    """Windows of consecutive lines, overlapping so a fact at a boundary lands whole in one chunk."""
    if max_lines <= overlap:
        raise ValueError("max_lines must be larger than overlap")
    step = max_lines - overlap
    chunks = []
    for start in range(0, len(lines), step):
        window = lines[start : start + max_lines]
        chunks.append(LineChunk(window))
        if start + max_lines >= len(lines):
            break
    return chunks


def lines_to_json(chunk: LineChunk) -> list[list]:
    return [[line.page, line.number, line.text] for line in chunk.lines]


def numbered_text(lines: list[list]) -> str:
    """Prompt-facing form: each line prefixed with its page and line number."""
    return "\n".join(f"[p{page} l{number}] {text}" for page, number, text in lines)


def quote_matches(lines: list[list], page: int, line_start: int, line_end: int, quote: str) -> bool:
    """True if `quote` appears (whitespace-normalized, case-insensitive) in the cited lines."""
    cited = [
        text for p, n, text in lines if p == page and line_start <= n <= line_end
    ]
    expected = line_end - line_start + 1
    if len(cited) != expected:
        return False
    needle = _squeeze(quote)
    return bool(needle) and needle in _squeeze(" ".join(cited))
