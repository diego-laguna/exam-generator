"""Seed exam reference data (domains, task statements) and the fixture question bank.
Idempotent. Run: uv run python -m scripts.seed_reference
"""

from sqlalchemy import select

from exam_core.db import SessionLocal
from exam_core.models import Domain, Question, TaskStatement
from scripts.question_fixtures import QUESTIONS

DOMAINS = [
    (1, "Design Secure Architectures", 30),
    (2, "Design Resilient Architectures", 26),
    (3, "Design High-Performing Architectures", 24),
    (4, "Design Cost-Optimized Architectures", 20),
]

# SAA-C03 exam guide task statements: (domain_id, code, description)
TASK_STATEMENTS = [
    (1, "1.1", "Design secure access to AWS resources"),
    (1, "1.2", "Design secure workloads and applications"),
    (1, "1.3", "Determine appropriate data security controls"),
    (2, "2.1", "Design scalable and loosely coupled architectures"),
    (2, "2.2", "Design highly available and/or fault-tolerant architectures"),
    (3, "3.1", "Determine high-performing and/or scalable storage solutions"),
    (3, "3.2", "Design high-performing and elastic compute solutions"),
    (3, "3.3", "Determine high-performing database solutions"),
    (3, "3.4", "Determine high-performing and/or scalable network architectures"),
    (3, "3.5", "Determine high-performing data ingestion and transformation solutions"),
    (4, "4.1", "Design cost-optimized storage solutions"),
    (4, "4.2", "Design cost-optimized compute solutions"),
    (4, "4.3", "Design cost-optimized database solutions"),
    (4, "4.4", "Design cost-optimized network architectures"),
]


def seed_reference() -> None:
    with SessionLocal() as db:
        for id_, name, weight in DOMAINS:
            domain = db.get(Domain, id_)
            if domain is None:
                db.add(Domain(id=id_, name=name, weight=weight))
            else:
                domain.name, domain.weight = name, weight
        db.flush()

        tasks = {t.code: t for t in db.scalars(select(TaskStatement))}
        for domain_id, code, description in TASK_STATEMENTS:
            if code in tasks:
                tasks[code].description = description
            else:
                tasks[code] = TaskStatement(domain_id=domain_id, code=code, description=description)
                db.add(tasks[code])
        db.flush()

        existing = set(db.scalars(select(Question.stem).where(Question.model == "fixture")))
        for code, stem, options, correct, explanation in QUESTIONS:
            if stem in existing:
                continue
            task = tasks[code]
            db.add(
                Question(
                    domain_id=task.domain_id,
                    task_statement_id=task.id,
                    stem=stem,
                    options=options,
                    correct_option=correct,
                    explanation=explanation,
                    model="fixture",
                )
            )
        db.commit()


if __name__ == "__main__":
    seed_reference()
    print(f"Seeded {len(DOMAINS)} domains, {len(TASK_STATEMENTS)} task statements, "
          f"{len(QUESTIONS)} fixture questions")
