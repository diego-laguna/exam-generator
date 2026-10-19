import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import ClockDep
from app.config import get_settings
from app.dependencies import CurrentUser, DbSession, TeacherOnly
from app.document_ingestion import ingest_document
from app.embeddings import EmbedderDep
from app.models import Document, DocumentChunk, DocumentStatus
from app.pdf_text import is_pdf
from app.storage import StorageDep

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[TeacherOnly])

_ACTIVE = (DocumentStatus.pending, DocumentStatus.processing)


class DocumentOut(BaseModel):
    id: int
    filename: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    chunk_count: int
    error: str | None
    created_at: datetime


def _clean_filename(name: str | None) -> str:
    base = (name or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:255] or "document.pdf"


def _expire_stale(db: Session, document: Document, now: datetime) -> None:
    """A document stuck in pending/processing (process died mid-job) is reported as failed."""
    limit = timedelta(minutes=get_settings().job_stale_minutes)
    if document.status in _ACTIVE and now - document.updated_at > limit:
        document.status = DocumentStatus.failed
        document.error = "Processing timed out; please upload the file again"
        db.commit()


def get_owned_document(
    document_id: int, user: CurrentUser, db: DbSession, clock: ClockDep
) -> Document:
    """Foreign and missing documents are both 404."""
    document = db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == user.id)
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    _expire_stale(db, document, clock())
    return document


OwnedDocument = Annotated[Document, Depends(get_owned_document)]


def _out(db: DbSession, document: Document) -> DocumentOut:
    count = db.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document.id)
    )
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        status=document.status,
        chunk_count=count or 0,
        error=document.error,
        created_at=document.created_at,
    )


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"The file is larger than {limit} bytes"
            )
    return bytes(data)


@router.post(
    "",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF",
    description=(
        "Teacher only. Uploads a PDF (multipart field `file`). The text is extracted with page and line numbers, split into chunks and embedded in the background. Returns 202; poll the document until its status is `ready` or `failed` (for example a scanned PDF with no text, or too many pages)."
        "\n\n"
        "**Use case:** Dave uploads `biology-chapter-3.pdf` and, when the status turns `ready`, uses it to generate questions."
    ),
)
async def upload_document(
    file: UploadFile,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    storage: StorageDep,
    embedder: EmbedderDep,
):
    data = await _read_capped(file, get_settings().upload_max_bytes)
    if not is_pdf(data):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is not a PDF")
    digest = hashlib.sha256(data).hexdigest()
    key = f"{get_settings().s3_prefix}{user.id}/{uuid.uuid4().hex}.pdf"
    document = Document(
        owner_id=user.id,
        filename=_clean_filename(file.filename),
        sha256=digest,
        size_bytes=len(data),
        storage_key=key,
        status=DocumentStatus.pending,
    )
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You already uploaded this file")
    try:
        storage.put(key, data)
    except Exception:
        db.delete(document)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not store the file")
    db.refresh(document)
    background.add_task(ingest_document, document.id, storage, embedder)
    return _out(db, document)


@router.get(
    "",
    response_model=list[DocumentOut],
    summary="List my documents",
    description=(
        "Teacher only. Lists the caller's own documents with status, page count and chunk count. A document stuck in processing for too long is reported as `failed`."
        "\n\n"
        "**Use case:** Dave opens the Documents screen to see which uploads finished."
    ),
)
def list_documents(user: CurrentUser, db: DbSession, clock: ClockDep):
    documents = db.scalars(
        select(Document).where(Document.owner_id == user.id).order_by(Document.id)
    ).all()
    for document in documents:
        _expire_stale(db, document, clock())
    return [_out(db, d) for d in documents]


@router.get(
    "/{document_id}",
    response_model=DocumentOut,
    summary="Get one document",
    description=(
        "Teacher only. Returns one of the caller's documents. Another teacher's document answers 404."
        "\n\n"
        "**Use case:** The app polls `GET /documents/12` every few seconds after an upload until `status` is `ready`."
    ),
)
def get_document(document: OwnedDocument, db: DbSession):
    return _out(db, document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description=(
        "Teacher only. Deletes the document, its chunks and the stored file. Questions already generated keep their citation text, so saved sets and PDFs stay intact."
        "\n\n"
        "**Use case:** Dave removes an outdated edition of the textbook; the questions he already made from it remain usable."
    ),
)
def delete_document(document: OwnedDocument, db: DbSession, storage: StorageDep):
    key = document.storage_key
    db.delete(document)  # chunks cascade; questions keep their citation snapshots
    db.commit()
    try:
        storage.delete(key)
    except Exception:
        pass  # the row is gone; an orphaned object is cleaned up by the bucket lifecycle rule
    return Response(status_code=status.HTTP_204_NO_CONTENT)
