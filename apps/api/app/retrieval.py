from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from exam_core.models import Chunk


def similar_chunks(
    db: Session,
    query_embedding: Sequence[float],
    k: int = 5,
    source_ids: Sequence[int] | None = None,
) -> list[Chunk]:
    """Top-k chunks by cosine similarity, optionally restricted to some sources (used by M5)."""
    distance = cast(Any, Chunk.embedding).cosine_distance(list(query_embedding))
    stmt = select(Chunk).order_by(distance).limit(k)
    if source_ids:
        stmt = stmt.where(Chunk.source_id.in_(source_ids))
    return list(db.scalars(stmt))
