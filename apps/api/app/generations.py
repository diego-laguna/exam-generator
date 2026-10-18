from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import ClockDep
from app.config import get_settings
from app.dependencies import CurrentUser, DbSession, TeacherOnly
from app.embeddings import EmbedderDep
from app.llm import LlmDep
from app.models import BankQuestion, Document, DocumentStatus, GenerationJob, JobStatus
from app.question_gen import run_generation

router = APIRouter(prefix="/generations", tags=["generations"], dependencies=[TeacherOnly])

_ACTIVE = (JobStatus.queued, JobStatus.running)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message})


class GenerationCreate(BaseModel):
    document_ids: list[int] = Field(min_length=1, max_length=20)
    mcq_count: int = Field(0, ge=0)
    true_false_count: int = Field(0, ge=0)
    focus: str | None = Field(None, max_length=500, description="Optional topic to concentrate on")

    @model_validator(mode="after")
    def _counts(self) -> "GenerationCreate":
        total = self.mcq_count + self.true_false_count
        limit = get_settings().generation_max_questions
        if not 1 <= total <= limit:
            raise ValueError(f"mcq_count + true_false_count must be between 1 and {limit}")
        return self


class GenerationOut(BaseModel):
    id: int
    status: JobStatus
    document_ids: list[int]
    mcq_count: int
    true_false_count: int
    requested_count: int
    produced_count: int
    question_ids: list[int]
    focus: str | None
    error: str | None
    created_at: datetime


def _expire_stale(db: Session, job: GenerationJob, now: datetime) -> None:
    limit = timedelta(minutes=get_settings().job_stale_minutes)
    if job.status in _ACTIVE and now - job.updated_at > limit:
        job.status = JobStatus.failed
        job.error = "The job timed out"
        db.commit()


def _out(db: Session, job: GenerationJob) -> GenerationOut:
    ids = list(
        db.scalars(select(BankQuestion.id).where(BankQuestion.job_id == job.id).order_by(BankQuestion.id))
    )
    return GenerationOut(
        id=job.id,
        status=job.status,
        document_ids=job.document_ids,
        mcq_count=job.mcq_count,
        true_false_count=job.true_false_count,
        requested_count=job.mcq_count + job.true_false_count,
        produced_count=job.produced_count,
        question_ids=ids,
        focus=job.focus,
        error=job.error,
        created_at=job.created_at,
    )


def get_owned_job(job_id: int, user: CurrentUser, db: DbSession, clock: ClockDep) -> GenerationJob:
    job = db.scalar(
        select(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.owner_id == user.id)
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation not found")
    _expire_stale(db, job, clock())
    return job


OwnedJob = Annotated[GenerationJob, Depends(get_owned_job)]


@router.post("", response_model=GenerationOut, status_code=status.HTTP_202_ACCEPTED)
def create_generation(
    body: GenerationCreate,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    clock: ClockDep,
    llm: LlmDep,
    embedder: EmbedderDep,
):
    document_ids = sorted(set(body.document_ids))
    documents = db.scalars(
        select(Document).where(Document.id.in_(document_ids), Document.owner_id == user.id)
    ).all()
    if len(documents) != len(document_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if any(d.status != DocumentStatus.ready for d in documents):
        raise _error(status.HTTP_409_CONFLICT, "DOCUMENT_NOT_READY", "All documents must be ready")

    now = clock()
    for active in db.scalars(
        select(GenerationJob).where(GenerationJob.owner_id == user.id, GenerationJob.status.in_(_ACTIVE))
    ):
        _expire_stale(db, active, now)
        if active.status in _ACTIVE:  # one job at a time per teacher caps LLM spend
            raise _error(status.HTTP_409_CONFLICT, "JOB_IN_PROGRESS", "A generation is already running")

    job = GenerationJob(
        owner_id=user.id,
        document_ids=document_ids,
        mcq_count=body.mcq_count,
        true_false_count=body.true_false_count,
        focus=body.focus.strip() or None if body.focus else None,
        status=JobStatus.queued,
        produced_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background.add_task(run_generation, job.id, llm, embedder)
    return _out(db, job)


@router.get("", response_model=list[GenerationOut])
def list_generations(user: CurrentUser, db: DbSession, clock: ClockDep):
    jobs = db.scalars(
        select(GenerationJob).where(GenerationJob.owner_id == user.id).order_by(GenerationJob.id.desc()).limit(50)
    ).all()
    for job in jobs:
        _expire_stale(db, job, clock())
    return [_out(db, j) for j in jobs]


@router.get("/{job_id}", response_model=GenerationOut)
def get_generation(job: OwnedJob, db: DbSession):
    return _out(db, job)
