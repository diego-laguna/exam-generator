from worker.chunking import MIN_CHUNK_CHARS, chunk_sections, extract_sections
from tests.helpers import page

LOREM = "Amazon S3 stores objects in buckets and offers eleven nines of durability. "


def test_extract_title_sections_and_drops_noise():
    html = page("S3 Guide", ("Storage classes", LOREM * 2), ("Security", LOREM))
    title, sections = extract_sections(html)
    assert title == "S3 Guide"
    assert [s.heading for s in sections] == ["Storage classes", "Security"]
    text = " ".join(p for s in sections for p in s.paragraphs)
    assert "Menu" not in text and "Copyright" not in text and "var x" not in text


def test_extract_without_main_container_uses_body():
    title, sections = extract_sections("<html><body><h2>A</h2><p>" + LOREM + "</p></body></html>")
    assert title is None
    assert sections[0].heading == "A"


def test_nested_blocks_not_duplicated():
    html = "<body><ul><li><p>" + LOREM + "</p></li></ul></body>"
    _, sections = extract_sections(html)
    assert sum(len(s.paragraphs) for s in sections) == 1


def test_chunks_respect_max_size_and_never_cross_headings():
    html = page("T", ("First", LOREM * 40), ("Second", LOREM * 3))
    _, sections = extract_sections(html)
    chunks = chunk_sections(sections, max_chars=500, overlap=60)
    assert len(chunks) > 3
    for c in chunks:
        body = c.content.split("\n\n", 1)[1]
        assert len(body) <= 500
        assert c.content.startswith(c.heading)
    assert {c.heading for c in chunks} == {"First", "Second"}


def test_consecutive_chunks_overlap():
    _, sections = extract_sections(page("T", ("H", LOREM * 40)))
    chunks = chunk_sections(sections, max_chars=400, overlap=80)
    first = chunks[0].content.split("\n\n", 1)[1]
    second = chunks[1].content.split("\n\n", 1)[1]
    tail_words = first.split()[-3:]
    assert " ".join(tail_words) in second


def test_overlap_must_be_smaller_than_max():
    import pytest

    with pytest.raises(ValueError):
        chunk_sections([], max_chars=100, overlap=100)


def test_long_unbroken_paragraph_is_split():
    html = "<body><h2>H</h2><p>" + ("word " * 600) + "</p></body>"
    _, sections = extract_sections(html)
    chunks = chunk_sections(sections, max_chars=300, overlap=30)
    assert len(chunks) > 5
    assert all(len(c.content.split("\n\n", 1)[1]) <= 300 for c in chunks)


def test_tiny_fragments_are_dropped():
    _, sections = extract_sections("<body><h2>H</h2><p>Too short.</p></body>")
    assert len("Too short.") < MIN_CHUNK_CHARS
    assert chunk_sections(sections, 500, 50) == []
