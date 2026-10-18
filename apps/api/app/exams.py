from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.clock import ClockDep
from app.config import get_settings
from app.dependencies import CurrentUser, DbSession, StudentOnly
from app.exam_deps import ActiveExam, OwnedExam, UnlockedExam, error
from app.exam_service import create_exam as create_exam_record
from app.exam_service import expire_if_needed, finalize_exam
from app.models import (
    Answer,
    Domain,
    Exam,
    ExamMode,
    ExamQuestion,
    ExamStatus,
    Question,
    TaskStatement,
)

router = APIRouter(tags=["exams"], dependencies=[StudentOnly])


class ExamCreate(BaseModel):
    mode: ExamMode
    question_count: int | None = Field(None, ge=1, le=100)
    domains: list[int] | None = Field(None, min_length=1)  # domain ids 1-4


class ExamQuestionOut(BaseModel):
    """A question as shown while taking the exam. Never carries the answer."""

    id: int
    position: int
    stem: str
    options: dict[str, str]
    selected_option: str | None


class ExamOut(BaseModel):
    id: int
    mode: ExamMode
    status: ExamStatus
    question_count: int
    requested_question_count: int
    duration_minutes: int | None
    started_at: datetime | None
    ends_at: datetime | None
    submitted_at: datetime | None
    score: int | None
    questions: list[ExamQuestionOut] | None = None


def exam_out(db: Session, exam: Exam, with_questions: bool = False) -> ExamOut:
    out = ExamOut(
        id=exam.id,
        mode=exam.mode,
        status=exam.status,
        question_count=exam.question_count,
        requested_question_count=exam.requested_question_count,
        duration_minutes=exam.duration_minutes,
        started_at=exam.started_at,
        ends_at=exam.ends_at,
        submitted_at=exam.submitted_at,
        score=exam.score if exam.status == ExamStatus.finished else None,
    )
    # Questions are only shown once the exam has started.
    if with_questions and exam.status in (ExamStatus.in_progress, ExamStatus.finished):
        rows = db.execute(
            select(ExamQuestion.position, Question, Answer.selected_option)
            .select_from(ExamQuestion)
            .join(Question, Question.id == ExamQuestion.question_id)
            .outerjoin(
                Answer,
                and_(Answer.exam_id == ExamQuestion.exam_id, Answer.question_id == Question.id),
            )
            .where(ExamQuestion.exam_id == exam.id)
            .order_by(ExamQuestion.position)
        )
        out.questions = [
            ExamQuestionOut(
                id=q.id, position=pos, stem=q.stem, options=q.options, selected_option=selected
            )
            for pos, q, selected in rows
        ]
    return out


@router.post(
    "/exams",
    response_model=ExamOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_exam(body: ExamCreate, user: CurrentUser, db: DbSession):
    if body.domains:
        known = set(db.scalars(select(Domain.id).where(Domain.id.in_(body.domains))))
        unknown = sorted(set(body.domains) - known)
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown domain ids: {unknown}")
    settings = get_settings()
    requested = body.question_count or (
        settings.exam_default_questions
        if body.mode == ExamMode.exam
        else settings.practice_default_questions
    )
    exam = create_exam_record(db, user, body.mode, requested, body.domains)
    return exam_out(db, exam)


class ExamSummary(BaseModel):
    id: int
    mode: ExamMode
    status: ExamStatus
    question_count: int
    requested_question_count: int
    duration_minutes: int | None
    started_at: datetime | None
    ends_at: datetime | None
    score: int | None
    created_at: datetime


@router.get("/exams", response_model=list[ExamSummary])
def list_exams(user: CurrentUser, db: DbSession, clock: ClockDep):
    """The caller's 100 most recent exams, newest first."""
    exams = db.scalars(
        select(Exam).where(Exam.user_id == user.id).order_by(Exam.id.desc()).limit(100)
    ).all()
    now = clock()
    for exam in exams:
        expire_if_needed(db, exam, now)  # an exam past its deadline is shown as finished
    return [
        ExamSummary(
            id=e.id,
            mode=e.mode,
            status=e.status,
            question_count=e.question_count,
            requested_question_count=e.requested_question_count,
            duration_minutes=e.duration_minutes,
            started_at=e.started_at,
            ends_at=e.ends_at,
            score=e.score if e.status == ExamStatus.finished else None,
            created_at=e.created_at,
        )
        for e in exams
    ]


@router.get("/exams/{exam_id}", response_model=ExamOut)
def get_exam(exam: OwnedExam, db: DbSession):
    return exam_out(db, exam, with_questions=True)


@router.post("/exams/{exam_id}/start", response_model=ExamOut)
def start_exam(exam: OwnedExam, db: DbSession, clock: ClockDep):
    if exam.status in (ExamStatus.in_progress, ExamStatus.finished):
        raise error(status.HTTP_409_CONFLICT, "EXAM_ALREADY_STARTED", "The exam was already started")
    if exam.status != ExamStatus.ready:
        raise error(status.HTTP_409_CONFLICT, "EXAM_NOT_AVAILABLE", "The exam is not available")
    now = clock()
    exam.started_at = now
    if exam.duration_minutes is not None:
        exam.ends_at = now + timedelta(minutes=exam.duration_minutes)
    exam.status = ExamStatus.in_progress
    db.commit()
    return exam_out(db, exam, with_questions=True)


class AnswerIn(BaseModel):
    selected_option: Literal["A", "B", "C", "D"]


class AnswerOut(BaseModel):
    question_id: int
    selected_option: str
    answered_at: datetime
    # Practice mode only: immediate feedback.
    is_correct: bool | None = None
    correct_option: str | None = None
    explanation: str | None = None


@router.put(
    "/exams/{exam_id}/answers/{question_id}",
    response_model=AnswerOut,
    response_model_exclude_none=True,
)
def save_answer(question_id: int, body: AnswerIn, exam: ActiveExam, db: DbSession, clock: ClockDep):
    question = db.get(Question, question_id)
    if question is None or db.get(ExamQuestion, (exam.id, question_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not in this exam")
    now = clock()
    is_correct = body.selected_option == question.correct_option
    db.execute(
        insert(Answer)
        .values(
            exam_id=exam.id,
            question_id=question_id,
            selected_option=body.selected_option,
            answered_at=now,
            is_correct=is_correct,
        )
        .on_conflict_do_update(
            index_elements=[Answer.exam_id, Answer.question_id],
            set_={
                "selected_option": body.selected_option,
                "answered_at": now,
                "is_correct": is_correct,
            },
        )
    )
    db.commit()
    out = AnswerOut(question_id=question_id, selected_option=body.selected_option, answered_at=now)
    if exam.mode == ExamMode.practice:
        out.is_correct = is_correct
        out.correct_option = question.correct_option
        out.explanation = question.explanation
    return out


@router.post("/exams/{exam_id}/submit", response_model=ExamOut)
def submit_exam(exam: ActiveExam, db: DbSession, clock: ClockDep):
    finalize_exam(db, exam, submitted_at=clock())
    db.commit()
    return exam_out(db, exam)


class ResultQuestion(BaseModel):
    id: int
    position: int
    domain: str
    task_statement: str
    stem: str
    options: dict[str, str]
    selected_option: str | None
    correct_option: str
    is_correct: bool
    explanation: str


class ResultsOut(BaseModel):
    exam_id: int
    mode: ExamMode
    status: ExamStatus
    correct: int
    answered: int
    total: int
    percent: float
    questions: list[ResultQuestion]


@router.get("/exams/{exam_id}/results", response_model=ResultsOut)
def get_results(exam: UnlockedExam, db: DbSession):
    rows = db.execute(
        select(ExamQuestion.position, Question, Domain.name, TaskStatement.code, Answer)
        .select_from(ExamQuestion)
        .join(Question, Question.id == ExamQuestion.question_id)
        .join(Domain, Domain.id == Question.domain_id)
        .join(TaskStatement, TaskStatement.id == Question.task_statement_id)
        .outerjoin(
            Answer,
            and_(Answer.exam_id == ExamQuestion.exam_id, Answer.question_id == Question.id),
        )
        .where(ExamQuestion.exam_id == exam.id)
        .order_by(ExamQuestion.position)
    ).all()
    finished = exam.status == ExamStatus.finished
    questions = [
        ResultQuestion(
            id=q.id,
            position=pos,
            domain=domain,
            task_statement=code,
            stem=q.stem,
            options=q.options,
            selected_option=ans.selected_option if ans else None,
            correct_option=q.correct_option,
            is_correct=bool(ans and ans.is_correct),
            explanation=q.explanation,
        )
        for pos, q, domain, code, ans in rows
        # An unfinished practice exam only reveals the questions already answered.
        if finished or ans is not None
    ]
    correct = sum(1 for _, _, _, _, ans in rows if ans and ans.is_correct)
    answered = sum(1 for *_, ans in rows if ans)
    return ResultsOut(
        exam_id=exam.id,
        mode=exam.mode,
        status=exam.status,
        correct=correct,
        answered=answered,
        total=exam.question_count,
        percent=round(100 * correct / exam.question_count, 1) if exam.question_count else 0.0,
        questions=questions,
    )
