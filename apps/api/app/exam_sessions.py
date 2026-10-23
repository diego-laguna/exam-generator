"""Download the built-in exam and run timed sessions on it.

Teacher routes (`/sample-exam`, `/exam-sessions`) need a teacher account. Student routes (`/join/...`)
have no account: the secret join token in the URL opens the session and a per-student secret, sent in
the `X-Participant-Token` header, identifies one student inside it.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Literal

from exam_core.errors import Conflict, InvalidInput, NotFound
from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import ClockDep
from app.config import get_settings
from app.dependencies import CurrentUser, DbSession, TeacherOnly
from app.pdf_export import Version, render_question_set_pdf
from app.sample_exam import EXAMS, Exam, ExamQuestion
from exam_core.models import ExamSession, SessionAnswer, SessionParticipant

teacher_router = APIRouter(tags=["exam-sessions"], dependencies=[TeacherOnly])
join_router = APIRouter(prefix="/join", tags=["join"])  # public: the token in the URL is the credential




def _exam(exam_id: str) -> Exam:
    exam = EXAMS.get(exam_id)
    if exam is None:
        raise NotFound("Exam not found", code="EXAM_NOT_FOUND")
    return exam


# ---------------------------------------------------------------- schemas


class SampleExamQuestionOut(BaseModel):
    key: str
    type: Literal["mcq", "true_false"]
    stem: str
    options: dict[str, str]
    correct_option: str
    explanation: str


class SampleExamOut(BaseModel):
    id: str
    title: str
    question_count: int
    questions: list[SampleExamQuestionOut]


class SessionIn(BaseModel):
    exam_id: str = "sample"
    duration_minutes: int = Field(ge=1, le=1440)


class ExamSessionOut(BaseModel):
    id: int
    exam_id: str
    exam_title: str
    question_count: int
    duration_minutes: int
    started_at: datetime
    ends_at: datetime
    status: Literal["open", "ended"]
    closed_early: bool
    join_url: str
    participant_count: int
    submitted_count: int


class ParticipantRow(BaseModel):
    id: int
    name: str
    status: Literal["in_progress", "submitted"]
    answered_count: int
    score: int | None
    joined_at: datetime
    submitted_at: datetime | None


class QuestionStat(BaseModel):
    key: str
    number: int
    stem: str
    answered_count: int
    correct_count: int


class SessionDashboard(BaseModel):
    session: ExamSessionOut
    participants: list[ParticipantRow]
    average_score: float | None
    questions: list[QuestionStat]
    server_now: datetime


class JoinInfo(BaseModel):
    exam_title: str
    question_count: int
    duration_minutes: int
    ends_at: datetime
    status: Literal["open", "ended"]
    server_now: datetime


class JoinIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = re.sub(r"\s+", " ", v).strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class JoinedOut(BaseModel):
    participant_token: str
    name: str


class StudentQuestion(BaseModel):
    """A question as the student sees it: never the answer."""

    key: str
    type: Literal["mcq", "true_false"]
    stem: str
    options: dict[str, str]


class ReviewItem(BaseModel):
    key: str
    stem: str
    options: dict[str, str]
    selected_option: str | None
    correct_option: str
    explanation: str
    is_correct: bool


class SessionResult(BaseModel):
    score: int
    total: int
    review: list[ReviewItem]


class ParticipantState(BaseModel):
    name: str
    status: Literal["in_progress", "submitted"]
    ends_at: datetime
    server_now: datetime
    questions: list[StudentQuestion]  # empty once submitted
    answers: dict[str, str]
    result: SessionResult | None  # only after submitting (or when time ran out)


class AnswerIn(BaseModel):
    selected_option: str = Field(min_length=1, max_length=1)


# ---------------------------------------------------------------- helpers


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _is_over(session: ExamSession, now: datetime) -> bool:
    return session.closed_at is not None or now >= session.ends_at


def _end_time(session: ExamSession) -> datetime:
    return session.closed_at or session.ends_at


def _score(db: Session, participant_id: int) -> int:
    return db.scalar(
        select(func.count()).where(
            SessionAnswer.participant_id == participant_id, SessionAnswer.is_correct.is_(True)
        )
    ) or 0


def _finalize(db: Session, session: ExamSession, now: datetime) -> None:
    """Once a session is over, students who never pressed Submit are scored on what they saved."""
    if not _is_over(session, now):
        return
    pending = db.scalars(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session.id, SessionParticipant.submitted_at.is_(None)
        )
    ).all()
    for p in pending:
        p.submitted_at = _end_time(session)
        p.score = _score(db, p.id)
    if pending:
        db.commit()


def _session_out(db: Session, session: ExamSession, now: datetime) -> ExamSessionOut:
    exam = _exam(session.exam_id)
    joined = db.scalar(
        select(func.count()).where(SessionParticipant.session_id == session.id)
    ) or 0
    submitted = db.scalar(
        select(func.count()).where(
            SessionParticipant.session_id == session.id, SessionParticipant.submitted_at.is_not(None)
        )
    ) or 0
    return ExamSessionOut(
        id=session.id,
        exam_id=session.exam_id,
        exam_title=exam.title,
        question_count=len(exam.questions),
        duration_minutes=session.duration_minutes,
        started_at=session.started_at,
        ends_at=session.ends_at,
        status="ended" if _is_over(session, now) else "open",
        closed_early=session.closed_at is not None,
        join_url=f"{get_settings().web_base_url.rstrip('/')}/join/{session.join_token}",
        participant_count=joined,
        submitted_count=submitted,
    )


def _owned_session(db: Session, session_id: int, user_id: int) -> ExamSession:
    session = db.scalar(
        select(ExamSession).where(ExamSession.id == session_id, ExamSession.owner_id == user_id)
    )
    if session is None:
        raise NotFound("Exam session not found", code="EXAM_SESSION_NOT_FOUND")
    return session


def _question_out(q: ExamQuestion) -> SampleExamQuestionOut:
    return SampleExamQuestionOut(
        key=q.key,
        type=q.type.value,
        stem=q.stem,
        options=q.options,
        correct_option=q.correct_option,
        explanation=q.explanation,
    )


# ---------------------------------------------------------------- teacher: download


@teacher_router.get(
    "/sample-exam",
    response_model=SampleExamOut,
    summary="Show the built-in exam",
    description=(
        "Teacher only. The built-in exam with its answers and explanations."
        "\n\n"
        "**Use case:** Dave reads the questions on the screen before printing them or opening a session."
    ),
)
def get_sample_exam():
    exam = _exam("sample")
    return SampleExamOut(
        id=exam.id,
        title=exam.title,
        question_count=len(exam.questions),
        questions=[_question_out(q) for q in exam.questions],
    )


@teacher_router.get(
    "/sample-exam/pdf",
    summary="Download the built-in exam as a PDF",
    description=(
        "Teacher only. `version=student` (default) has the questions and a name line; `version=teacher` adds the answer key and explanations."
        "\n\n"
        "**Use case:** Dave prints the student version for the class and keeps the teacher version to grade by hand."
    ),
    responses={200: {"content": {"application/pdf": {}}}},
)
def download_sample_exam(version: Version = "student"):
    exam = _exam("sample")
    pdf = render_question_set_pdf(exam.title, exam.questions, version)
    filename = f"{exam.id}-exam-{version}.pdf"
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ---------------------------------------------------------------- teacher: sessions


@teacher_router.post(
    "/exam-sessions",
    response_model=ExamSessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start an exam session",
    description=(
        "Teacher only. Opens the exam to students for `duration_minutes` (the time limit is fixed now and counts from this call, on the server clock). The response has the `join_url` to share with the class."
        "\n\n"
        "**Use case:** Dave sends `{\"exam_id\": \"sample\", \"duration_minutes\": 30}` and posts the returned link in the class chat."
    ),
)
def start_session(body: SessionIn, user: CurrentUser, db: DbSession, clock: ClockDep):
    _exam(body.exam_id)
    if body.duration_minutes > get_settings().session_max_minutes:
        raise InvalidInput(
            f"A session can last at most {get_settings().session_max_minutes} minutes",
            code="DURATION_TOO_LONG",
        )
    now = clock()
    session = ExamSession(
        owner_id=user.id,
        exam_id=body.exam_id,
        join_token=secrets.token_urlsafe(32),
        duration_minutes=body.duration_minutes,
        started_at=now,
        ends_at=now + timedelta(minutes=body.duration_minutes),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_out(db, session, now)


@teacher_router.get(
    "/exam-sessions",
    response_model=list[ExamSessionOut],
    summary="List my exam sessions",
    description=(
        "Teacher only. The caller's sessions, newest first, with how many students joined and submitted."
        "\n\n"
        "**Use case:** Dave reopens yesterday's session to see the final results."
    ),
)
def list_sessions(user: CurrentUser, db: DbSession, clock: ClockDep):
    now = clock()
    rows = db.scalars(
        select(ExamSession).where(ExamSession.owner_id == user.id).order_by(ExamSession.id.desc()).limit(100)
    ).all()
    for s in rows:
        _finalize(db, s, now)
    return [_session_out(db, s, now) for s in rows]


@teacher_router.get(
    "/exam-sessions/{session_id}",
    response_model=SessionDashboard,
    summary="Session dashboard",
    description=(
        "Teacher only. Who joined, who submitted, scores, the average and, per question, how many answered and how many got it right. Poll this to keep a dashboard current."
        "\n\n"
        "**Use case:** While the class is writing, Dave watches the submitted count climb and sees which question most students miss."
    ),
)
def session_dashboard(session_id: int, user: CurrentUser, db: DbSession, clock: ClockDep):
    now = clock()
    session = _owned_session(db, session_id, user.id)
    _finalize(db, session, now)
    exam = _exam(session.exam_id)

    participants = db.scalars(
        select(SessionParticipant)
        .where(SessionParticipant.session_id == session.id)
        .order_by(SessionParticipant.joined_at, SessionParticipant.id)
    ).all()
    answered = {
        pid: n
        for pid, n in db.execute(
            select(SessionAnswer.participant_id, func.count())
            .join(SessionParticipant, SessionParticipant.id == SessionAnswer.participant_id)
            .where(SessionParticipant.session_id == session.id)
            .group_by(SessionAnswer.participant_id)
        )
    }
    per_question = {
        key: (n, ok or 0)
        for key, n, ok in db.execute(
            select(
                SessionAnswer.question_key,
                func.count(),
                func.sum(func.cast(SessionAnswer.is_correct, Integer)),
            )
            .join(SessionParticipant, SessionParticipant.id == SessionAnswer.participant_id)
            .where(SessionParticipant.session_id == session.id)
            .group_by(SessionAnswer.question_key)
        )
    }
    scores = [p.score for p in participants if p.score is not None]
    return SessionDashboard(
        session=_session_out(db, session, now),
        participants=[
            ParticipantRow(
                id=p.id,
                name=p.name,
                status="submitted" if p.submitted_at else "in_progress",
                answered_count=answered.get(p.id, 0),
                score=p.score,
                joined_at=p.joined_at,
                submitted_at=p.submitted_at,
            )
            for p in participants
        ],
        average_score=round(sum(scores) / len(scores), 2) if scores else None,
        questions=[
            QuestionStat(
                key=q.key,
                number=i,
                stem=q.stem,
                answered_count=per_question.get(q.key, (0, 0))[0],
                correct_count=per_question.get(q.key, (0, 0))[1],
            )
            for i, q in enumerate(exam.questions, start=1)
        ],
        server_now=now,
    )


@teacher_router.post(
    "/exam-sessions/{session_id}/close",
    response_model=ExamSessionOut,
    summary="End a session early",
    description=(
        "Teacher only. Stops accepting answers now. Students who have not submitted are scored on the answers they saved. Closing an ended session changes nothing."
        "\n\n"
        "**Use case:** Everyone is done after 20 of the 30 minutes, so Dave closes the session to freeze the results."
    ),
)
def close_session(session_id: int, user: CurrentUser, db: DbSession, clock: ClockDep):
    now = clock()
    session = _owned_session(db, session_id, user.id)
    if not _is_over(session, now):
        session.closed_at = now
        db.commit()
    _finalize(db, session, now)
    return _session_out(db, session, now)


# ---------------------------------------------------------------- students: join, answer, submit

ParticipantToken = Annotated[str, Header(alias="X-Participant-Token", min_length=10, max_length=128)]


def _session_by_token(db: Session, token: str) -> ExamSession:
    session = db.scalar(select(ExamSession).where(ExamSession.join_token == token))
    if session is None:
        raise NotFound("Exam session not found", code="EXAM_SESSION_NOT_FOUND")
    return session


def _participant(db: Session, session: ExamSession, secret: str) -> SessionParticipant:
    p = db.scalar(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session.id, SessionParticipant.token_hash == _hash(secret)
        )
    )
    if p is None:
        raise NotFound("Participant not found", code="PARTICIPANT_NOT_FOUND")
    return p


def _result(db: Session, exam: Exam, p: SessionParticipant) -> SessionResult:
    chosen = {
        a.question_key: a.selected_option
        for a in db.scalars(select(SessionAnswer).where(SessionAnswer.participant_id == p.id))
    }
    review = [
        ReviewItem(
            key=q.key,
            stem=q.stem,
            options=q.options,
            selected_option=chosen.get(q.key),
            correct_option=q.correct_option,
            explanation=q.explanation,
            is_correct=chosen.get(q.key) == q.correct_option,
        )
        for q in exam.questions
    ]
    return SessionResult(score=p.score or 0, total=len(exam.questions), review=review)


@join_router.get(
    "/{token}",
    response_model=JoinInfo,
    summary="Open a join link",
    description=(
        "Public. What the student sees before entering a name: the exam title, the number of questions and the time limit. No questions are returned."
        "\n\n"
        "**Use case:** Ana opens the link Dave posted; the page shows \"Sample exam, 6 questions, 30 minutes\" and a name box."
    ),
)
def join_info(token: str, db: DbSession, clock: ClockDep):
    now = clock()
    session = _session_by_token(db, token)
    exam = _exam(session.exam_id)
    return JoinInfo(
        exam_title=exam.title,
        question_count=len(exam.questions),
        duration_minutes=session.duration_minutes,
        ends_at=session.ends_at,
        status="ended" if _is_over(session, now) else "open",
        server_now=now,
    )


@join_router.post(
    "/{token}/participants",
    response_model=JoinedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Join a session",
    description=(
        "Public. Registers the student under a name and returns a secret `participant_token`; the browser keeps it and sends it as `X-Participant-Token` on later calls. Fails if the session is over, the name is taken in this session or the session is full."
        "\n\n"
        "**Use case:** Ana types her name and presses Start; the page stores the token so a reload puts her back in her exam."
    ),
)
def join_session(token: str, body: JoinIn, db: DbSession, clock: ClockDep):
    now = clock()
    session = _session_by_token(db, token)
    _finalize(db, session, now)
    if _is_over(session, now):
        raise Conflict("This exam session has ended", code="SESSION_ENDED")
    joined = db.scalar(select(func.count()).where(SessionParticipant.session_id == session.id)) or 0
    if joined >= get_settings().session_max_participants:
        raise Conflict("This exam session is full", code="SESSION_FULL")
    secret = secrets.token_urlsafe(32)
    db.add(
        SessionParticipant(session_id=session.id, name=body.name, token_hash=_hash(secret), joined_at=now)
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("Someone already joined with that name; add your surname or a number", code="NAME_TAKEN")
    return JoinedOut(participant_token=secret, name=body.name)


@join_router.get(
    "/{token}/me",
    response_model=ParticipantState,
    summary="My exam",
    description=(
        "Public, with the participant token. The questions (without answers), the answers saved so far and the deadline. After submitting, or once time is up, `result` has the score and the review with correct answers and explanations."
        "\n\n"
        "**Use case:** Ana reloads the page halfway through; this call restores her questions, her ticked options and the countdown."
    ),
)
def my_exam(token: str, participant_token: ParticipantToken, db: DbSession, clock: ClockDep):
    now = clock()
    session = _session_by_token(db, token)
    _finalize(db, session, now)
    p = _participant(db, session, participant_token)
    exam = _exam(session.exam_id)
    done = p.submitted_at is not None
    answers = {
        a.question_key: a.selected_option
        for a in db.scalars(select(SessionAnswer).where(SessionAnswer.participant_id == p.id))
    }
    return ParticipantState(
        name=p.name,
        status="submitted" if done else "in_progress",
        ends_at=session.ends_at if session.closed_at is None else session.closed_at,
        server_now=now,
        questions=[]
        if done
        else [StudentQuestion(key=q.key, type=q.type.value, stem=q.stem, options=q.options) for q in exam.questions],
        answers=answers,
        result=_result(db, exam, p) if done else None,
    )


def _open_participant(
    db: Session, token: str, participant_token: str, now: datetime
) -> tuple[ExamSession, SessionParticipant]:
    session = _session_by_token(db, token)
    _finalize(db, session, now)
    p = _participant(db, session, participant_token)
    if p.submitted_at is not None:
        raise Conflict("You already submitted this exam", code="ALREADY_SUBMITTED")
    return session, p


@join_router.put(
    "/{token}/answers/{question_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save an answer",
    description=(
        "Public, with the participant token. Saves or replaces the answer to one question. Rejected after the session ended or after submitting. The server clock decides; the browser timer is only a display."
        "\n\n"
        "**Use case:** Ana ticks option B on question 3; the page saves it, so a crash does not lose her work."
    ),
)
def save_answer(
    token: str,
    question_key: str,
    body: AnswerIn,
    participant_token: ParticipantToken,
    db: DbSession,
    clock: ClockDep,
):
    now = clock()
    session, p = _open_participant(db, token, participant_token, now)
    exam = _exam(session.exam_id)
    q = exam.question(question_key)
    if q is None:
        raise NotFound("Question not found", code="QUESTION_NOT_FOUND")
    if body.selected_option not in q.options:
        raise InvalidInput("That option does not exist", code="INVALID_OPTION")
    row = db.get(SessionAnswer, (p.id, q.key))
    if row is None:
        row = SessionAnswer(participant_id=p.id, question_key=q.key)
        db.add(row)
    row.selected_option = body.selected_option
    row.answered_at = now
    row.is_correct = body.selected_option == q.correct_option
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@join_router.post(
    "/{token}/submit",
    response_model=SessionResult,
    summary="Submit the exam",
    description=(
        "Public, with the participant token. Ends the student's exam and returns the score and the review at once. The teacher's dashboard shows the result on its next refresh. Unanswered questions count as wrong. Submitting twice returns 409."
        "\n\n"
        "**Use case:** Ana presses Submit and immediately sees \"5 of 6\" with the right answer and explanation for the one she missed."
    ),
)
def submit(token: str, participant_token: ParticipantToken, db: DbSession, clock: ClockDep):
    now = clock()
    session, p = _open_participant(db, token, participant_token, now)
    p.submitted_at = now
    p.score = _score(db, p.id)
    db.commit()
    return _result(db, _exam(session.exam_id), p)
