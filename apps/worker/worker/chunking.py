"""HTML -> heading-aware text chunks for embedding."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import reduce
from typing import cast

from bs4 import BeautifulSoup, Tag

MIN_CHUNK_CHARS = 40  # drop fragments too small to be useful as retrieval context

_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "td", "dt", "dd", "blockquote"]
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_NOISE = ["script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"]
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Section:
    heading: str
    paragraphs: list[str]


@dataclass(frozen=True)
class Chunk:
    heading: str
    content: str


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def extract_sections(html: str) -> tuple[str | None, list[Section]]:
    """Returns the page title and its content split into sections at each heading."""
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.title) if soup.title else None
    for tag in soup(_NOISE):
        tag.decompose()
    root = soup.find(id="main-content") or soup.find("main") or soup.body or soup
    assert isinstance(root, Tag)

    sections: list[Section] = []
    heading, paragraphs = title or "", []
    for el in root.find_all(_BLOCKS):
        if not isinstance(el, Tag) or el.find(_BLOCKS):
            continue  # only leaf blocks, so nested elements aren't counted twice
        text = _text(el)
        if not text:
            continue
        if el.name in _HEADINGS:
            if paragraphs:
                sections.append(Section(heading, paragraphs))
            heading, paragraphs = text, []
        else:
            paragraphs.append(text)
    if paragraphs:
        sections.append(Section(heading, paragraphs))
    return title or None, sections


def _split_long(text: str, limit: int) -> list[str]:
    """Splits one paragraph that exceeds `limit` on sentence, then word, boundaries."""
    if len(text) <= limit:
        return [text]
    pieces, current = reduce(
        lambda acc, sentence: _add_sentence(acc, sentence, limit),
        _SENTENCE_END.split(text),
        (cast(tuple[str, ...], ()), ""),
    )
    return list((*pieces, current) if current else pieces)


def _add_sentence(
    acc: tuple[tuple[str, ...], str], sentence: str, limit: int
) -> tuple[tuple[str, ...], str]:
    pieces, current = acc
    while len(sentence) > limit:  # a sentence with no break points: cut on spaces
        cut = sentence.rfind(" ", 0, limit)
        cut = cut if cut > 0 else limit
        pieces = (*pieces, *((current,) if current else ()), sentence[:cut].strip())
        current = ""
        sentence = sentence[cut:].strip()
    if current and len(current) + 1 + len(sentence) > limit:
        return (*pieces, current), sentence
    return pieces, f"{current} {sentence}".strip()


def _overlap_tail(text: str, size: int) -> str:
    if size <= 0:
        return ""
    tail = text[-size:]
    return tail[tail.find(" ") + 1 :] if " " in tail and len(text) > size else tail


def _add_piece(
    acc: tuple[tuple[str, ...], str], piece: str, max_chars: int, overlap: int
) -> tuple[tuple[str, ...], str]:
    bodies, current = acc
    if current and len(current) + 1 + len(piece) > max_chars:
        tail = _overlap_tail(current, overlap)
        return (*bodies, current), (f"{tail}\n{piece}" if tail else piece)
    return bodies, (f"{current}\n{piece}" if current else piece)


def pack_bodies(pieces: Iterable[str], max_chars: int, overlap: int) -> list[str]:
    """Packs text pieces into bodies of at most ~`max_chars`, each starting with the overlap tail."""
    bodies, current = reduce(
        lambda acc, piece: _add_piece(acc, piece, max_chars, overlap),
        pieces,
        (cast(tuple[str, ...], ()), ""),
    )
    return list((*bodies, current) if current else bodies)


def chunk_section(section: Section, max_chars: int, overlap: int) -> list[Chunk]:
    pieces = (p for para in section.paragraphs for p in _split_long(para, max_chars - overlap))
    return [
        Chunk(section.heading, f"{section.heading}\n\n{body}" if section.heading else body)
        for body in pack_bodies(pieces, max_chars, overlap)
        if len(body) >= MIN_CHUNK_CHARS
    ]


def chunk_sections(sections: list[Section], max_chars: int, overlap: int) -> list[Chunk]:
    """Packs paragraphs into chunks of at most ~`max_chars` (excluding the heading prefix),
    never crossing a heading. Consecutive chunks of a section share `overlap` characters."""
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")
    return [c for section in sections for c in chunk_section(section, max_chars, overlap)]
