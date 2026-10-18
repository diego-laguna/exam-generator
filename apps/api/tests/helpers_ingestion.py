"""Test doubles for ingestion: a deterministic embedder and a dict-backed fetcher."""

import hashlib
import math
import random
from collections.abc import Sequence

from app.embeddings import EMBEDDING_DIM


def _word_vector(word: str) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]


class FakeEmbedder:
    """Bag-of-words embedding: texts sharing words end up close together."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            total = [0.0] * EMBEDDING_DIM
            for word in text.lower().split():
                for i, x in enumerate(_word_vector(word)):
                    total[i] += x
            norm = math.sqrt(sum(x * x for x in total)) or 1.0
            out.append([x / norm for x in total])
        return out


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
