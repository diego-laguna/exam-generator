from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.dependencies import CurrentUser, DbSession, TeacherOnly
from app.models import BankQuestion, QuestionType

router = APIRouter(prefix="/questions", tags=["questions"], dependencies=[TeacherOnly])


class CitationOut(BaseModel):
    document: str
    chunk_id: int | None = None
    page: int
    line_start: int
    line_end: int
    quote: str


class BankQuestionOut(BaseModel):
    """The teacher's view of a question: answer, explanation and citations included."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: QuestionType
    document_id: int | None
    stem: str
    options: dict[str, str]
    correct_option: str
    explanation: str
    citations: list[CitationOut]
    created_at: datetime


def get_owned_question(question_id: int, user: CurrentUser, db: DbSession) -> BankQuestion:
    question = db.scalar(
        select(BankQuestion).where(BankQuestion.id == question_id, BankQuestion.owner_id == user.id)
    )
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return question


OwnedQuestion = Annotated[BankQuestion, Depends(get_owned_question)]


@router.get(
    "",
    response_model=list[BankQuestionOut],
    summary="List my questions",
    description=(
        "Teacher only. Lists the caller's generated questions with answer, explanation and citations. Filter by `document_id` or `type` (`mcq`, `true_false`); page with `limit` and `offset`."
        "\n\n"
        "**Use case:** Dave filters to `type=true_false` for document 12 to review those questions before building a quiz."
    ),
)
def list_questions(
    user: CurrentUser,
    db: DbSession,
    document_id: int | None = None,
    type: QuestionType | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = select(BankQuestion).where(BankQuestion.owner_id == user.id)
    if document_id is not None:
        stmt = stmt.where(BankQuestion.document_id == document_id)
    if type is not None:
        stmt = stmt.where(BankQuestion.type == type)
    return db.scalars(stmt.order_by(BankQuestion.id).limit(limit).offset(offset)).all()


@router.get(
    "/{question_id}",
    response_model=BankQuestionOut,
    summary="Get one question",
    description=(
        "Teacher only. One question with its correct option, explanation and verified citations. Another teacher's question answers 404."
        "\n\n"
        "**Use case:** Dave opens question 41 to read the quoted passage and check the page and line numbers."
    ),
)
def get_question(question: OwnedQuestion):
    return question


@router.delete(
    "/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a question",
    description=(
        "Teacher only. Deletes the question; it also leaves any question set that included it."
        "\n\n"
        "**Use case:** Dave spots a poorly worded question and deletes it so it never reaches a printed exam."
    ),
)
def delete_question(question: OwnedQuestion, db: DbSession):
    db.delete(question)  # also leaves any set that included it (ON DELETE CASCADE on the item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
