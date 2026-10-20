"""The heavy collaborators, built once when the worker starts."""

from dataclasses import dataclass

from exam_core.embeddings import Embedder
from exam_core.storage import Storage, get_storage

from worker.embedder import get_embedder
from worker.fetching import Fetcher, fetch_html
from worker.llm import Llm, get_llm


@dataclass(frozen=True)
class Services:
    storage: Storage
    embedder: Embedder
    fetcher: Fetcher
    llm: Llm | None


def build_services() -> Services:
    return Services(storage=get_storage(), embedder=get_embedder(), fetcher=fetch_html, llm=get_llm())
