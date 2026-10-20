import random
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from exam_core.models import (
    Answer,
    Domain,
    Exam,
    ExamMode,
    ExamQuestion,
    ExamStatus,
    Question,
    User,
)


def select_question_ids(db: Session, count: int, domain_ids: list[int] | None) -> list[int]:
    """Pick up to `count` questions, spread across domains in proportion to exam weights.

    Greedy: each pick goes to the domain furthest below its weighted share that still has
    questions left, so a thin domain doesn't block the rest.
    """
    stmt = select(Domain)
    if domain_ids:
        stmt = stmt.where(Domain.id.in_(domain_ids))
    domains = db.scalars(stmt).all()
    total_weight = sum(d.weight for d in domains) or 1

    pools: dict[int, list[int]] = {}
    for d in domains:
        ids = list(db.scalars(select(Question.id).where(Question.domain_id == d.id)))
        random.shuffle(ids)
        pools[d.id] = ids
    weights = {d.id: d.weight / total_weight for d in domains}
    taken: dict[int, list[int]] = {d.id: [] for d in domains}

    for i in range(count):
        candidates = [d for d, pool in pools.items() if pool]
        if not candidates:
            break
        best = max(candidates, key=lambda d: weights[d] * (i + 1) - len(taken[d]))
        taken[best].append(pools[best].pop())

    selected = [q for qs in taken.values() for q in qs]
    random.shuffle(selected)
    return selected


def create_exam(
    db: Session, user: User, mode: ExamMode, requested: int, domain_ids: list[int] | None
) -> Exam:
    settings = get_settings()
    question_ids = select_question_ids(db, requested, domain_ids)
    exam = Exam(
        user_id=user.id,
        mode=mode,
        status=ExamStatus.ready if question_ids else ExamStatus.failed,
        question_count=len(question_ids),
        requested_question_count=requested,
        duration_minutes=(
            len(question_ids) * settings.exam_minutes_per_question
            if mode == ExamMode.exam and question_ids
            else None
        ),
    )
    db.add(exam)
    db.flush()
    db.add_all(
        ExamQuestion(exam_id=exam.id, question_id=qid, position=pos)
        for pos, qid in enumerate(question_ids, start=1)
    )
    db.commit()
    return exam


def finalize_exam(db: Session, exam: Exam, submitted_at: datetime) -> None:
    exam.score = db.scalar(
        select(func.count()).where(Answer.exam_id == exam.id, Answer.is_correct.is_(True))
    )
    exam.status = ExamStatus.finished
    exam.submitted_at = submitted_at


def expire_if_needed(db: Session, exam: Exam, now: datetime) -> None:
    """Auto-finalize an exam whose time window has passed (FR-TIME-3)."""
    if exam.status == ExamStatus.in_progress and exam.ends_at and now >= exam.ends_at:
        finalize_exam(db, exam, submitted_at=exam.ends_at)
        db.commit()
