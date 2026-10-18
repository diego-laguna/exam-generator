import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends

from app.config import get_settings

# Must match the model in settings (BAAI/bge-small-en-v1.5). Changing it needs a migration.
EMBEDDING_DIM = 384


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local ONNX embedding model. Loaded lazily; the first call downloads the model."""

    def __init__(self, model_name: str, cache_dir: str) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self._model_name, cache_dir=self._cache_dir)
            return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._load().embed(list(texts))]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    return FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)


EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
