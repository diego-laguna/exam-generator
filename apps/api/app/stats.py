from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select

from app.dependencies import AnyUser, CurrentUser, DbSession
from app.models import Answer, Domain, Exam, ExamMode, ExamStatus, Question, TaskStatement

router = APIRouter(tags=["stats"])


class Accuracy(BaseModel):
    attempted: int
    correct: int
    accuracy: float | None  # null until there is at least one attempt


class TaskStatementStats(Accuracy):
    code: str
    description: str


class DomainStats(Accuracy):
    domain_id: int
    name: str
    task_statements: list[TaskStatementStats]


class StatsOut(BaseModel):
    domains: list[DomainStats]


def _accuracy(attempted: int, correct: int) -> float | None:
    return round(correct / attempted, 3) if attempted else None


@router.get("/me/stats", response_model=StatsOut, dependencies=[AnyUser])
def my_stats(user: CurrentUser, db: DbSession):
    """Accuracy per domain and task statement.

    Counts practice answers and answers from finished exams only, so in-progress exam
    answers can't be used to learn which questions were right before results unlock.
    """
    rows = db.execute(
        select(
            Question.task_statement_id,
            func.count(),
            func.sum(case((Answer.is_correct, 1), else_=0)),
        )
        .select_from(Answer)
        .join(Exam, Exam.id == Answer.exam_id)
        .join(Question, Question.id == Answer.question_id)
        .where(
            Exam.user_id == user.id,
            or_(Exam.mode == ExamMode.practice, Exam.status == ExamStatus.finished),
        )
        .group_by(Question.task_statement_id)
    )
    by_task = {tid: (int(n), int(c)) for tid, n, c in rows}

    tasks = db.scalars(select(TaskStatement).order_by(TaskStatement.code)).all()
    domains = db.scalars(select(Domain).order_by(Domain.id)).all()
    out = []
    for d in domains:
        task_stats = []
        for t in (t for t in tasks if t.domain_id == d.id):
            n, c = by_task.get(t.id, (0, 0))
            task_stats.append(
                TaskStatementStats(
                    code=t.code,
                    description=t.description,
                    attempted=n,
                    correct=c,
                    accuracy=_accuracy(n, c),
                )
            )
        n = sum(t.attempted for t in task_stats)
        c = sum(t.correct for t in task_stats)
        out.append(
            DomainStats(
                domain_id=d.id,
                name=d.name,
                attempted=n,
                correct=c,
                accuracy=_accuracy(n, c),
                task_statements=task_stats,
            )
        )
    return StatsOut(domains=out)
