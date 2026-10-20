import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from exam_core.db import Base
from exam_core.embeddings import EMBEDDING_DIM


class Role(enum.StrEnum):
    admin = "admin"
    student = "student"
    teacher = "teacher"


class ExamMode(enum.StrEnum):
    practice = "practice"
    exam = "exam"


class ExamStatus(enum.StrEnum):
    generating = "generating"
    ready = "ready"
    in_progress = "in_progress"
    finished = "finished"
    failed = "failed"


class SourceStatus(enum.StrEnum):
    pending = "pending"
    ingesting = "ingesting"
    ready = "ready"
    failed = "failed"


class DocumentStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class QuestionType(enum.StrEnum):
    mcq = "mcq"  # options A-D
    true_false = "true_false"  # options A=True, B=False


def _enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        _enum(Role),
        server_default=Role.student.value,
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefreshToken(Base):
    """Opaque refresh token, stored hashed. Deleted on use (rotation), logout, password change."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RevokedToken(Base):
    """Access-token JTIs invalidated by /logout, kept until they would have expired anyway."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Domain(Base):
    """SAA-C03 exam domain. Ids 1-4 follow the exam guide numbering."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    weight: Mapped[int]  # percent of the exam


class TaskStatement(Base):
    __tablename__ = "task_statements"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # e.g. "1.1"
    description: Mapped[str] = mapped_column(String(255))


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    task_statement_id: Mapped[int] = mapped_column(ForeignKey("task_statements.id"), index=True)
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, str]] = mapped_column(JSONB)  # {"A": "...", ..., "D": "..."}
    correct_option: Mapped[str] = mapped_column(String(1))
    explanation: Mapped[str] = mapped_column(Text)
    cited_chunk_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'")
    )
    validation: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(64))  # "fixture" until generation exists
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[ExamMode] = mapped_column(_enum(ExamMode))
    status: Mapped[ExamStatus] = mapped_column(_enum(ExamStatus))
    question_count: Mapped[int]  # actually served
    requested_question_count: Mapped[int]
    duration_minutes: Mapped[int | None]  # exam mode only
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None]  # number of correct answers, set when finished
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    position: Mapped[int]


class Answer(Base):
    __tablename__ = "answers"

    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    selected_option: Mapped[str] = mapped_column(String(1))
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_correct: Mapped[bool]


def _hnsw_index(table: str) -> Index:
    return Index(
        f"ix_{table}_embedding_hnsw",
        "embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


class Source(Base):
    """A documentation page that is chunked and embedded for retrieval."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[SourceStatus] = mapped_column(_enum(SourceStatus))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (_hnsw_index("chunks"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # "metadata" is reserved by SQLAlchemy's declarative base, hence the attribute name.
    meta: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class SampleQuestion(Base):
    """Few-shot style exemplars. Never used as a source of facts."""

    __tablename__ = "sample_questions"
    __table_args__ = (_hnsw_index("sample_questions"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    task_statement_id: Mapped[int | None] = mapped_column(ForeignKey("task_statements.id"))
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, str]] = mapped_column(JSONB)
    correct_option: Mapped[str] = mapped_column(String(1))
    # Filled in by the worker shortly after the sample is created.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Document(Base):
    """A teacher's uploaded PDF. The file lives in object storage under `storage_key`."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("owner_id", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(512))
    page_count: Mapped[int | None]
    status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentChunk(Base):
    """A run of consecutive PDF lines. `lines` is [[page, line_no, text], ...] (1-based)."""

    __tablename__ = "document_chunks"
    __table_args__ = (_hnsw_index("document_chunks"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    lines: Mapped[list[list]] = mapped_column(JSONB)
    content: Mapped[str] = mapped_column(Text)  # the lines joined, what gets embedded
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    mcq_count: Mapped[int]
    true_false_count: Mapped[int]
    focus: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus))
    produced_count: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BankQuestion(Base):
    """A generated, validated question owned by a teacher. Citations are snapshots (file, page,
    lines, quote), so they stay valid if the source document is later deleted."""

    __tablename__ = "bank_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL")
    )
    type: Mapped[QuestionType] = mapped_column(_enum(QuestionType))
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, str]] = mapped_column(JSONB)
    correct_option: Mapped[str] = mapped_column(String(1))
    explanation: Mapped[str] = mapped_column(Text)
    # [{"document": "file.pdf", "chunk_id": 1, "page": 3, "line_start": 4, "line_end": 6, "quote": "..."}]
    citations: Mapped[list[dict]] = mapped_column(JSONB)
    validation: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QuestionSet(Base):
    __tablename__ = "question_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuestionSetItem(Base):
    __tablename__ = "question_set_items"

    set_id: Mapped[int] = mapped_column(
        ForeignKey("question_sets.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("bank_questions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int]
