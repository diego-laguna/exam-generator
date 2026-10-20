"""The embedding contract. The model itself runs in the worker (worker/embedder.py)."""

from collections.abc import Sequence
from typing import Protocol

# Must match the model in settings (BAAI/bge-small-en-v1.5). Changing it needs a migration.
EMBEDDING_DIM = 384


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
