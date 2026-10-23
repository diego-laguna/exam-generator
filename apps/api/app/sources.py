from datetime import datetime
from typing import Annotated, Literal

from exam_core.errors import Conflict, InvalidInput, NotFound
from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import AdminOnly, AnyUser, CurrentUser, DbSession
from app.queueing import QueueDep, enqueue
from exam_core.models import Chunk, Role, SampleQuestion, Source, SourceStatus, TaskStatement
from exam_core.queue import EmbedSamples, IngestSource
from exam_core.urls import validate_source_url

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
    summary="Add a documentation source",
    description=(
        "Admin only. Queues an AWS documentation page (HTML or PDF) for download, chunking and embedding. Only allowlisted hosts over https are accepted, redirects included. Returns 202; poll `GET /sources` until the status is `ready` or `failed`."
        "\n\n"
        "**Use case:** The admin submits `{\"url\": \"https://docs.aws.amazon.com/pdfs/AmazonECR/latest/userguide/ecr-ug.pdf\"}` to add the ECR guide to the study material."
    ),
)
def create_source(
    body: SourceCreate,
    user: CurrentUser,
    db: DbSession,
    queue: QueueDep,
):
    source = Source(url=body.url, status=SourceStatus.pending)
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("This URL was already added", code="SOURCE_DUPLICATE")
    db.refresh(source)

    def undo() -> None:
        db.delete(source)
        db.commit()

    enqueue(queue, IngestSource(source_id=source.id), undo)
    return _out(source, 0, user.role)


@router.get(
    "/sources",
    response_model=list[SourceOut],
    dependencies=[AnyUser],
    summary="List documentation sources",
    description=(
        "Any signed-in user. Lists every ingested source with its status (`pending`, `ingesting`, `ready`, `failed`) and chunk count. The `error` text is only filled in for admins."
        "\n\n"
        "**Use case:** After adding a source, the admin refreshes the list to see whether it reached `ready` and how many chunks it produced."
    ),
)
def list_sources(user: CurrentUser, db: DbSession):
    rows = db.execute(
        select(Source, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.source_id == Source.id)
        .group_by(Source.id)
        .order_by(Source.id)
    )
    return [_out(src, count, user.role) for src, count in rows]


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[AdminOnly],
    summary="Delete a source",
    description=(
        "Admin only. Removes a source and all of its chunks. Responds 404 for an unknown id."
        "\n\n"
        "**Use case:** A page was ingested by mistake, so the admin deletes source 7 and its chunks disappear with it."
    ),
)
def delete_source(source_id: int, db: DbSession):
    source = db.get(Source, source_id)
    if source is None:
        raise NotFound("Source not found", code="SOURCE_NOT_FOUND")
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
    summary="Add sample questions",
    description=(
        "Admin only. Adds up to 50 hand-written sample questions in one request, all or nothing. Each names a task statement code (such as `1.1`) or a domain id, four options A-D and the correct one."
        "\n\n"
        "**Use case:** The admin pastes a JSON batch `{\"samples\": [{\"task_statement\": \"1.1\", \"stem\": \"...\", \"options\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}, \"correct_option\": \"B\"}]}` to grow the question bank."
    ),
)
def create_samples(body: SamplesCreate, db: DbSession, queue: QueueDep):
    tasks = {t.code: t for t in db.scalars(select(TaskStatement))}
    resolved: list[tuple[int, int | None]] = []
    for i, sample in enumerate(body.samples):
        task = None
        if sample.task_statement is not None:
            task = tasks.get(sample.task_statement)
            if task is None:
                raise InvalidInput(
                    f"samples[{i}]: unknown task statement '{sample.task_statement}'", code="UNKNOWN_TASK_STATEMENT"
                )
        domain_id = task.domain_id if task else sample.domain_id
        if task and sample.domain_id is not None and sample.domain_id != task.domain_id:
            raise InvalidInput(f"samples[{i}]: task statement does not belong to that domain", code="TASK_DOMAIN_MISMATCH")
        if domain_id is None or not 1 <= domain_id <= 4:
            raise InvalidInput(f"samples[{i}]: unknown domain", code="UNKNOWN_DOMAIN")
        resolved.append((domain_id, task.id if task else None))

    rows = [
        SampleQuestion(
            domain_id=domain_id,
            task_statement_id=task_id,
            stem=s.stem,
            options=s.options,
            correct_option=s.correct_option,
        )
        for s, (domain_id, task_id) in zip(body.samples, resolved)
    ]
    db.add_all(rows)
    db.commit()

    def undo() -> None:
        for row in rows:
            db.delete(row)
        db.commit()

    enqueue(queue, EmbedSamples(sample_ids=[r.id for r in rows]), undo)
    return SamplesCreated(created=len(rows), ids=[r.id for r in rows])
