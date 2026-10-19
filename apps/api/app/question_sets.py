from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.dependencies import CurrentUser, DbSession, TeacherOnly
from app.models import BankQuestion, QuestionSet, QuestionSetItem
from app.pdf_export import render_question_set_pdf
from app.questions import BankQuestionOut

router = APIRouter(prefix="/question-sets", tags=["question-sets"], dependencies=[TeacherOnly])


class QuestionSetIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    question_ids: list[int] = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("question_ids")
    @classmethod
    def _unique(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("question_ids must not repeat")
        return v


class QuestionSetSummary(BaseModel):
    id: int
    title: str
    question_count: int
    created_at: datetime
    updated_at: datetime


class QuestionSetOut(QuestionSetSummary):
    questions: list[BankQuestionOut]


def get_owned_set(set_id: int, user: CurrentUser, db: DbSession) -> QuestionSet:
    question_set = db.scalar(
        select(QuestionSet).where(QuestionSet.id == set_id, QuestionSet.owner_id == user.id)
    )
    if question_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question set not found")
    return question_set


OwnedSet = Annotated[QuestionSet, Depends(get_owned_set)]


def _questions(db: Session, question_set: QuestionSet) -> list[BankQuestion]:
    return list(
        db.scalars(
            select(BankQuestion)
            .join(QuestionSetItem, QuestionSetItem.question_id == BankQuestion.id)
            .where(QuestionSetItem.set_id == question_set.id)
            .order_by(QuestionSetItem.position)
        )
    )


def _out(db: Session, question_set: QuestionSet) -> QuestionSetOut:
    questions = _questions(db, question_set)
    return QuestionSetOut(
        id=question_set.id,
        title=question_set.title,
        question_count=len(questions),
        created_at=question_set.created_at,
        updated_at=question_set.updated_at,
        questions=[BankQuestionOut.model_validate(q) for q in questions],
    )


def _check_owned(db: Session, owner_id: int, question_ids: list[int]) -> None:
    found = db.scalar(
        select(func.count(BankQuestion.id)).where(
            BankQuestion.id.in_(question_ids), BankQuestion.owner_id == owner_id
        )
    )
    if found != len(question_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")


def _set_items(db: Session, set_id: int, question_ids: list[int]) -> None:
    db.execute(delete(QuestionSetItem).where(QuestionSetItem.set_id == set_id))
    db.add_all(
        QuestionSetItem(set_id=set_id, question_id=qid, position=i) for i, qid in enumerate(question_ids)
    )


@router.post(
    "",
    response_model=QuestionSetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a question set",
    description=(
        "Teacher only. Saves a titled, ordered selection of the caller's own questions for reuse. Ids must be unique and owned by the caller."
        "\n\n"
        "**Use case:** Dave picks 10 reviewed questions and saves `{\"title\": \"Unit 3 quiz\", \"question_ids\": [41, 42, 45]}`."
    ),
)
def create_question_set(body: QuestionSetIn, user: CurrentUser, db: DbSession):
    _check_owned(db, user.id, body.question_ids)
    question_set = QuestionSet(owner_id=user.id, title=body.title)
    db.add(question_set)
    db.flush()
    _set_items(db, question_set.id, body.question_ids)
    db.commit()
    db.refresh(question_set)
    return _out(db, question_set)


@router.get(
    "",
    response_model=list[QuestionSetSummary],
    summary="List my question sets",
    description=(
        "Teacher only. The caller's saved sets with title and question count."
        "\n\n"
        "**Use case:** Next semester Dave opens the list and finds last year's \"Unit 3 quiz\" to reuse."
    ),
)
def list_question_sets(user: CurrentUser, db: DbSession):
    rows = db.execute(
        select(QuestionSet, func.count(QuestionSetItem.question_id))
        .outerjoin(QuestionSetItem, QuestionSetItem.set_id == QuestionSet.id)
        .where(QuestionSet.owner_id == user.id)
        .group_by(QuestionSet.id)
        .order_by(QuestionSet.id)
    )
    return [
        QuestionSetSummary(
            id=s.id, title=s.title, question_count=count, created_at=s.created_at, updated_at=s.updated_at
        )
        for s, count in rows
    ]


@router.get(
    "/{set_id}",
    response_model=QuestionSetOut,
    summary="Get one question set",
    description=(
        "Teacher only. A set with its questions in order, including answers and citations. Another teacher's set answers 404."
        "\n\n"
        "**Use case:** Dave opens the set to check the order before printing."
    ),
)
def get_question_set(question_set: OwnedSet, db: DbSession):
    return _out(db, question_set)


@router.put(
    "/{set_id}",
    response_model=QuestionSetOut,
    summary="Replace a question set",
    description=(
        "Teacher only. Replaces the title and the full ordered list of questions of an existing set."
        "\n\n"
        "**Use case:** Dave swaps two weak questions for better ones and reorders the rest, keeping the same set and title."
    ),
)
def replace_question_set(question_set: OwnedSet, body: QuestionSetIn, user: CurrentUser, db: DbSession):
    _check_owned(db, user.id, body.question_ids)
    question_set.title = body.title
    _set_items(db, question_set.id, body.question_ids)
    db.commit()
    db.refresh(question_set)
    return _out(db, question_set)


@router.delete(
    "/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a question set",
    description=(
        "Teacher only. Deletes the set only; the questions stay in the bank."
        "\n\n"
        "**Use case:** Dave removes an obsolete quiz without losing the questions he may reuse in another set."
    ),
)
def delete_question_set(question_set: OwnedSet, db: DbSession):
    db.delete(question_set)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{set_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "Printable PDF"}},
    summary="Download a printable PDF",
    description=(
        "Teacher only. Renders the set as a PDF. `version=student` (default) has the questions with name and date lines; `version=teacher` adds the correct answers, explanations and the cited source, page and lines. Responds 409 for an empty set."
        "\n\n"
        "**Use case:** Dave downloads `?version=student` to print for the class and keeps `?version=teacher` as his answer key."
    ),
)
def download_pdf(
    question_set: OwnedSet,
    db: DbSession,
    version: Literal["student", "teacher"] = "student",
):
    """`student`: questions only, with name/date lines. `teacher`: answers, explanations, sources."""
    questions = _questions(db, question_set)
    if not questions:
        raise HTTPException(status.HTTP_409_CONFLICT, "The set has no questions")
    data = render_question_set_pdf(question_set.title, questions, version)
    safe = "".join(c if c.isalnum() else "-" for c in question_set.title).strip("-")[:60] or "questions"
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}-{version}.pdf"'},
    )
