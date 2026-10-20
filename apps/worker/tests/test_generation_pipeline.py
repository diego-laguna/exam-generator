import pytest
from exam_core.db import SessionLocal
from exam_core.models import BankQuestion, GenerationJob, JobStatus, Role
from exam_core.testing import FakeEmbedder, create_user, seed_ready_document
from sqlalchemy import select

from tests.helpers import FakeLlm, LlmError
from worker.question_gen import BlindAnswer, DraftCitation, DraftQuestion, run_generation

QUOTE = "Chlorophyll in the leaves absorbs sunlight"  # page 1, line 2 of LESSON


def draft(tf=False, quote=QUOTE, line=2, answer="A"):
    return DraftQuestion(
        stem="What does chlorophyll absorb during photosynthesis?",
        options={"A": "True", "B": "False"} if tf else {"A": "Sunlight", "B": "Soil", "C": "Wind", "D": "Salt"},
        correct_option=answer,  # type: ignore[arg-type]
        explanation="The excerpt says chlorophyll absorbs sunlight.",
        citations=[DraftCitation(page=1, line_start=line, line_end=line, quote=quote)],
    )


def llm_with(generate, blind=lambda: BlindAnswer(answer="A", ambiguous=False, reasoning="stated")):
    def handler(schema, prompt):
        return generate(prompt) if schema is DraftQuestion else blind()

    return FakeLlm(handler)


def queued_job(mcq=1, true_false=0, focus=None, status=JobStatus.queued) -> int:
    with SessionLocal() as db:
        owner = create_user(db, Role.teacher)
        doc = seed_ready_document(db, owner.id)
        job = GenerationJob(
            owner_id=owner.id, document_ids=[doc.id], mcq_count=mcq, true_false_count=true_false,
            focus=focus, status=status, produced_count=0,
        )
        db.add(job)
        db.commit()
        return job.id


def run(job_id, llm):
    run_generation(job_id, llm, FakeEmbedder())
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        assert job is not None
        questions = list(db.scalars(select(BankQuestion).where(BankQuestion.job_id == job_id).order_by(BankQuestion.id)))
        return job, questions


def test_generates_validated_questions_with_page_and_line_citations():
    fake = llm_with(lambda prompt: draft(tf="true_false" in prompt))
    job, questions = run(queued_job(mcq=1, true_false=1), fake)
    assert job.status == JobStatus.done and job.produced_count == 2
    assert {q.type for q in questions} == {"mcq", "true_false"}
    tf = next(q for q in questions if q.type == "true_false")
    assert tf.options == {"A": "True", "B": "False"}
    cite = questions[0].citations[0]
    assert (cite["document"], cite["page"], cite["line_start"], cite["line_end"]) == ("lesson.pdf", 1, 2, 2)
    assert cite["quote"] == QUOTE and cite["chunk_id"]
    assert [s for _, s in fake.calls] == ["DraftQuestion", "BlindAnswer"] * 2


def test_citation_that_does_not_match_the_lines_is_rejected():
    job, questions = run(queued_job(), llm_with(lambda prompt: draft(line=3)))  # the quote is on line 2
    assert job.status == JobStatus.failed and job.produced_count == 0 and not questions
    assert job.error == "No question passed validation"


def test_blind_validation_disagreement_or_ambiguity_discards_the_question():
    wrong = llm_with(lambda prompt: draft(), blind=lambda: BlindAnswer(answer="B", ambiguous=False, reasoning="x"))
    assert run(queued_job(), wrong)[0].status == JobStatus.failed
    vague = llm_with(lambda prompt: draft(), blind=lambda: BlindAnswer(answer="A", ambiguous=True, reasoning="x"))
    assert run(queued_job(), vague)[0].status == JobStatus.failed


def test_retries_until_a_draft_passes():
    attempts = iter([draft(line=3), draft(line=3), draft()])
    fake = llm_with(lambda prompt: next(attempts))
    job, _ = run(queued_job(), fake)
    assert job.status == JobStatus.done and job.produced_count == 1
    assert sum(1 for _, s in fake.calls if s == "DraftQuestion") == 3


def test_model_failures_are_reported():
    job, _ = run(queued_job(), llm_with(lambda prompt: LlmError("boom")))
    assert job.status == JobStatus.failed and job.error == "The model could not be reached"


def test_unexpected_error_is_recorded_without_details():
    def explode(prompt):
        raise RuntimeError("secret internal detail")

    job, _ = run(queued_job(), llm_with(explode))
    assert job.status == JobStatus.failed and job.error == "Generation failed unexpectedly"


def test_prompt_marks_document_text_as_data_and_numbers_lines():
    prompts = []
    run(queued_job(focus="chlorophyll"), llm_with(lambda prompt: prompts.append(prompt) or draft()))
    assert "<excerpt>" in prompts[0] and "[p1 l2] Chlorophyll" in prompts[0]
    assert "Teacher's focus" in prompts[0]


def test_without_an_api_key_the_job_fails_with_a_clear_message():
    job, questions = run(queued_job(), None)
    assert job.status == JobStatus.failed and job.error == "Question generation is not configured"
    assert not questions


@pytest.mark.parametrize("status", [JobStatus.running, JobStatus.done, JobStatus.failed])
def test_redelivered_message_does_not_run_a_job_twice(status):
    fake = llm_with(lambda prompt: draft())
    job, questions = run(queued_job(status=status), fake)
    assert job.status == status and not questions and not fake.calls


def test_deleted_job_is_ignored():
    run_generation(10**9, None, FakeEmbedder())
