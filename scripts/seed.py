"""Insert sample users (idempotent). Run: uv run python -m scripts.seed"""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.security import password_hash

SAMPLE_USERS = [
    ("alice", "wonderland"),
    ("bob", "builder"),
    ("carol", "christmas"),
]


def seed() -> None:
    with SessionLocal() as db:
        existing = set(db.scalars(select(User.username)))
        for username, password in SAMPLE_USERS:
            if username not in existing:
                db.add(User(username=username, password_hash=password_hash.hash(password)))
        db.commit()


if __name__ == "__main__":
    seed()
    print(f"Seeded sample users: {', '.join(u for u, _ in SAMPLE_USERS)}")
