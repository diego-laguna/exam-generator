from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import AdminOnly, AnyUser, CurrentUser, DbSession
from app.embeddings import EmbedderDep
from app.fetching import FetcherDep, validate_source_url
from app.ingestion import ingest_source
from app.models import Chunk, Role, SampleQuestion, Source, SourceStatus, TaskStatement

router = APIRouter(tags=["sources"])


class SourceCreate(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _allowlisted(cls, v: str) -> str:
        return validate_source_url(v)  # UrlNotAllowed is a ValueError -> 422


class SourceOut(BaseModel):
    id: int
    url: str
    title: str | None
    status: SourceStatus
    chunk_count: int
    error: str | None  # visible to admins only
    created_at: datetime


def _out(src: Source, chunk_count: int, viewer: Role) -> SourceOut:
    return SourceOut(
        id=src.id,
        url=src.url,
        title=src.title,
        status=src.status,
        chunk_count=chunk_count,
        error=src.error if viewer == Role.admin else None,
        created_at=src.created_at,
    )


@router.post(
    "/sources",
    response_model=SourceOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[AdminOnly],
)
def create_source(
    body: SourceCreate,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    fetcher: FetcherDep,
    embedder: EmbedderDep,
):
    source = Source(url=body.url, status=SourceStatus.pending)
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This URL was already added")
    db.refresh(source)
    background.add_task(ingest_source, source.id, fetcher, embedder)
    return _out(source, 0, user.role)


@router.get("/sources", response_model=list[SourceOut], dependencies=[AnyUser])
def list_sources(user: CurrentUser, db: DbSession):
    rows = db.execute(
        select(Source, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.source_id == Source.id)
        .group_by(Source.id)
        .order_by(Source.id)
    )
    return [_out(src, count, user.role) for src, count in rows]


@router.delete(
    "/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AdminOnly]
)
def delete_source(source_id: int, db: DbSession):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    db.delete(source)  # chunks go with it (ON DELETE CASCADE)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


Option = Literal["A", "B", "C", "D"]


class SampleIn(BaseModel):
    task_statement: str | None = Field(None, description='Task statement code, e.g. "1.1"')
    domain_id: int | None = None
    stem: str = Field(min_length=20)
    options: dict[str, str]
    correct_option: Option

    @field_validator("options")
    @classmethod
    def _four_options(cls, v: dict[str, str]) -> dict[str, str]:
        if set(v) != {"A", "B", "C", "D"} or not all(t.strip() for t in v.values()):
            raise ValueError("options must have non-empty texts for exactly A, B, C and D")
        return v

    @model_validator(mode="after")
    def _has_target(self) -> "SampleIn":
        if self.task_statement is None and self.domain_id is None:
            raise ValueError("provide task_statement or domain_id")
        return self


class SamplesCreate(BaseModel):
    samples: Annotated[list[SampleIn], Field(min_length=1, max_length=50)]


class SamplesCreated(BaseModel):
    created: int
    ids: list[int]


@router.post(
    "/samples",
    response_model=SamplesCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AdminOnly],
)
def create_samples(body: SamplesCreate, db: DbSession, embedder: EmbedderDep):
    tasks = {t.code: t for t in db.scalars(select(TaskStatement))}
    resolved: list[tuple[int, int | None]] = []
    for i, sample in enumerate(body.samples):
        task = None
        if sample.task_statement is not None:
            task = tasks.get(sample.task_statement)
            if task is None:
                raise HTTPException(422, f"samples[{i}]: unknown task statement '{sample.task_statement}'")
        domain_id = task.domain_id if task else sample.domain_id
        if task and sample.domain_id is not None and sample.domain_id != task.domain_id:
            raise HTTPException(422, f"samples[{i}]: task statement does not belong to that domain")
        if domain_id is None or not 1 <= domain_id <= 4:
            raise HTTPException(422, f"samples[{i}]: unknown domain")
        resolved.append((domain_id, task.id if task else None))

    vectors = embedder.embed([s.stem for s in body.samples])
    rows = [
        SampleQuestion(
            domain_id=domain_id,
            task_statement_id=task_id,
            stem=s.stem,
            options=s.options,
            correct_option=s.correct_option,
            embedding=vec,
        )
        for s, (domain_id, task_id), vec in zip(body.samples, resolved, vectors)
    ]
    db.add_all(rows)
    db.commit()
    return SamplesCreated(created=len(rows), ids=[r.id for r in rows])
