"""Insert sample users (idempotent). Run: uv run python -m scripts.seed"""

from sqlalchemy import select

from exam_core.db import SessionLocal
from exam_core.models import Role, User
from app.security import password_hash

SAMPLE_USERS = [
    ("alice", "wonderland", Role.admin),
    ("bob", "builder", Role.student),
    ("carol", "christmas", Role.student),
    ("dave", "teacher-pass", Role.teacher),
]


def seed() -> None:
    with SessionLocal() as db:
        existing = {u.username: u for u in db.scalars(select(User))}
        for username, password, role in SAMPLE_USERS:
            if username in existing:
                existing[username].role = role
            else:
                db.add(
                    User(username=username, password_hash=password_hash.hash(password), role=role)
                )
        db.commit()


if __name__ == "__main__":
    seed()
    print(f"Seeded sample users: {', '.join(u for u, _, _ in SAMPLE_USERS)}")
