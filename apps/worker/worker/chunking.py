"""HTML -> heading-aware text chunks for embedding."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

MIN_CHUNK_CHARS = 40  # drop fragments too small to be useful as retrieval context

_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "td", "dt", "dd", "blockquote"]
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_NOISE = ["script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"]
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Section:
    heading: str
    paragraphs: list[str]


@dataclass
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
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > limit:  # a sentence with no break points: cut on spaces
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(text: str, size: int) -> str:
    if size <= 0:
        return ""
    tail = text[-size:]
    return tail[tail.find(" ") + 1 :] if " " in tail and len(text) > size else tail


def chunk_sections(sections: list[Section], max_chars: int, overlap: int) -> list[Chunk]:
    """Packs paragraphs into chunks of at most ~`max_chars` (excluding the heading prefix),
    never crossing a heading. Consecutive chunks of a section share `overlap` characters."""
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")
    chunks: list[Chunk] = []
    for section in sections:
        pieces = [p for para in section.paragraphs for p in _split_long(para, max_chars - overlap)]
        bodies: list[str] = []
        current = ""
        for piece in pieces:
            if current and len(current) + 1 + len(piece) > max_chars:
                bodies.append(current)
                tail = _overlap_tail(current, overlap)
                current = f"{tail}\n{piece}" if tail else piece
            else:
                current = f"{current}\n{piece}" if current else piece
        if current:
            bodies.append(current)
        for body in bodies:
            if len(body) >= MIN_CHUNK_CHARS:
                content = f"{section.heading}\n\n{body}" if section.heading else body
                chunks.append(Chunk(section.heading, content))
    return chunks
