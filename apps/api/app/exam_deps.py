"""Authorization dependencies for exams (PRD section 8, layers 3-5)."""

from typing import Annotated

from exam_core.errors import Conflict, NotFound
from fastapi import Depends
from sqlalchemy import select

from app.clock import ClockDep
from app.dependencies import DbSession, require_role
from app.exam_service import expire_if_needed
from exam_core.models import Exam, ExamMode, ExamStatus, Role, User


def get_owned_exam(
    exam_id: int,
    user: Annotated[User, Depends(require_role(Role.student))],
    db: DbSession,
    clock: ClockDep,
) -> Exam:
    """Loads the caller's exam. Foreign and missing exams are both 404 to avoid leaking existence."""
    exam = db.scalar(select(Exam).where(Exam.id == exam_id, Exam.user_id == user.id))
    if exam is None:
        raise NotFound("Exam not found", code="EXAM_NOT_FOUND")
    expire_if_needed(db, exam, clock())
    return exam


OwnedExam = Annotated[Exam, Depends(get_owned_exam)]


def require_active_window(exam: OwnedExam, clock: ClockDep) -> Exam:
    """started_at <= now < ends_at, on the server clock. Practice exams have no end."""
    if exam.status == ExamStatus.ready:
        raise Conflict("The exam has not been started", code="EXAM_NOT_STARTED")
    if exam.status == ExamStatus.finished:
        raise Conflict("The exam is already finished", code="EXAM_WINDOW_CLOSED")
    if exam.status != ExamStatus.in_progress:
        raise Conflict("The exam is not available", code="EXAM_NOT_AVAILABLE")
    now = clock()
    if exam.ends_at is not None and not (exam.started_at and exam.started_at <= now < exam.ends_at):
        raise Conflict("The exam time has expired", code="EXAM_WINDOW_CLOSED")
    return exam


ActiveExam = Annotated[Exam, Depends(require_active_window)]


def require_results_unlocked(exam: OwnedExam) -> Exam:
    """Practice: always. Exam mode: only once finished or expired."""
    if exam.status in (ExamStatus.generating, ExamStatus.failed):
        raise Conflict("The exam is not available", code="EXAM_NOT_AVAILABLE")
    if exam.mode == ExamMode.exam and exam.status != ExamStatus.finished:
        raise Conflict("Results unlock after the exam is submitted or time runs out", code="RESULTS_LOCKED")
    return exam


UnlockedExam = Annotated[Exam, Depends(require_results_unlocked)]
