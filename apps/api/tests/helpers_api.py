"""Shared helpers for tests that call the API as a teacher."""

import uuid

from fastapi.testclient import TestClient

from app.main import app
from exam_core.db import SessionLocal
from exam_core.models import BankQuestion, QuestionType
from exam_core.testing import seed_ready_document

P = "/api/v1"
client = TestClient(app)

QUOTE = "Chlorophyll in the leaves absorbs sunlight"  # page 1, line 2 of LESSON


def login(username, password):
    r = client.post(f"{P}/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def new_teacher():
    admin = login("alice", "wonderland")
    name = f"teacher_{uuid.uuid4().hex[:8]}"
    r = client.post(f"{P}/users", headers=admin, json={"username": name, "password": "teacher-pass", "role": "teacher"})
    assert r.status_code == 201
    return login(name, "teacher-pass")


def owner_id_of(teacher: dict) -> int:
    """The user id behind a bearer header (decoded from its JWT subject)."""
    import jwt

    token = teacher["Authorization"].split(" ", 1)[1]
    return int(jwt.decode(token, options={"verify_signature": False})["sub"])


def ready_document(teacher: dict, filename: str = "lesson.pdf") -> int:
    """A processed document owned by `teacher`, created directly (the worker has its own tests)."""
    with SessionLocal() as db:
        return seed_ready_document(db, owner_id_of(teacher), filename).id


def bank_questions(teacher: dict, document_id: int, mcq: int = 1, true_false: int = 0) -> list[int]:
    """Stored questions as the worker would leave them, with a citation snapshot."""
    ids = []
    with SessionLocal() as db:
        for kind, count in ((QuestionType.mcq, mcq), (QuestionType.true_false, true_false)):
            for _ in range(count):
                tf = kind == QuestionType.true_false
                row = BankQuestion(
                    owner_id=owner_id_of(teacher),
                    document_id=document_id,
                    type=kind,
                    stem="What does chlorophyll absorb during photosynthesis?",
                    options={"A": "True", "B": "False"} if tf else {"A": "Sunlight", "B": "Soil", "C": "Wind", "D": "Salt"},
                    correct_option="A",
                    explanation="The excerpt says chlorophyll absorbs sunlight.",
                    citations=[
                        {"document": "lesson.pdf", "chunk_id": 1, "page": 1, "line_start": 2, "line_end": 2, "quote": QUOTE}
                    ],
                    validation={"blind_answer": "A", "ambiguous": False, "reasoning": "stated"},
                    model="test",
                )
                db.add(row)
                db.flush()
                ids.append(row.id)
        db.commit()
    return ids
