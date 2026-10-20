"""Test doubles and database setup shared by the API and worker test suites."""

import hashlib
import io
import math
import random
import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from exam_core.embeddings import EMBEDDING_DIM
from exam_core.models import Document, DocumentChunk, DocumentStatus, Role, User
from exam_core.queue import Message

ADMIN_URL = "postgresql://learn:learn@localhost:5432/learn_assistant"


def bootstrap_database(name: str) -> None:
    """Drops and recreates database `name` with the full schema. DATABASE_URL must already point at it."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    from exam_core.db import Base, engine

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)


class MemoryQueue:
    """Records what the API sends. Set `fail` to simulate the queue being down."""

    def __init__(self) -> None:
        self.sent: list[Message] = []
        self.fail = False

    def send(self, message: Message) -> None:
        if self.fail:
            raise ConnectionError("queue is down")
        self.sent.append(message)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def _word_vector(word: str) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]


class FakeEmbedder:
    """Bag-of-words embedding: texts sharing words end up close together."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for value in texts:
            total = [0.0] * EMBEDDING_DIM
            for word in value.lower().split():
                for i, x in enumerate(_word_vector(word)):
                    total[i] += x
            norm = math.sqrt(sum(x * x for x in total)) or 1.0
            out.append([x / norm for x in total])
        return out


def make_pdf(pages: list[list[str]]) -> bytes:
    """One text line per entry, top to bottom, so line N of the page is entry N."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            pdf.drawString(60, y, line)
            y -= 18
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


# Long enough lines that a chunk clears the minimum size.
LESSON = [
    [
        "Photosynthesis is the process by which green plants make food.",
        "Chlorophyll in the leaves absorbs sunlight during photosynthesis.",
        "The plant uses carbon dioxide and water to produce glucose and oxygen.",
        "Glucose is stored as starch and used for growth and energy.",
        "Oxygen is released into the air through tiny pores called stomata.",
    ],
    [
        "Cellular respiration releases energy from glucose inside the mitochondria.",
        "It needs oxygen and produces carbon dioxide, water and usable energy.",
        "Plants perform both photosynthesis and cellular respiration every day.",
    ],
]


def create_user(db: Session, role: Role, username: str | None = None) -> User:
    user = User(username=username or f"{role.value}_{uuid.uuid4().hex[:8]}", password_hash="!", role=role)
    db.add(user)
    db.commit()
    return user


def seed_ready_document(
    db: Session, owner_id: int, filename: str = "lesson.pdf", pages: list[list[str]] = LESSON
) -> Document:
    """A processed document (one chunk holding every line), without running the worker."""
    lines = [[p, n, line] for p, page in enumerate(pages, start=1) for n, line in enumerate(page, start=1)]
    content = "\n".join(row[2] for row in lines)
    digest = uuid.uuid4().hex
    document = Document(
        owner_id=owner_id,
        filename=filename,
        sha256=digest,
        size_bytes=1000,
        storage_key=f"documents/{owner_id}/{digest}.pdf",
        status=DocumentStatus.ready,
        page_count=len(pages),
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentChunk(
            document_id=document.id,
            position=0,
            lines=lines,
            content=content,
            embedding=FakeEmbedder().embed([content])[0],
        )
    )
    db.commit()
    return document
