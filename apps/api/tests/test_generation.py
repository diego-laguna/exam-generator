import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.llm import LlmError, get_llm
from app.main import app
from app.models import BankQuestion, GenerationJob, JobStatus
from app.question_gen import BlindAnswer, DraftCitation, DraftQuestion
from tests.helpers_teacher import FakeLlm
from tests.test_documents import P, client, login, new_teacher, storage, teacher, upload  # noqa: F401

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


@pytest.fixture
def use_llm():
    def install(fake):
        app.dependency_overrides[get_llm] = lambda: fake
        return fake

    yield install
    app.dependency_overrides.pop(get_llm, None)


def ready_document(teacher):
    from tests.test_documents import upload as up

    return up(teacher).json()["id"]


def generate(teacher, doc_id, **body):
    body = {"document_ids": [doc_id], "mcq_count": 1, **body}
    r = client.post(f"{P}/generations", headers=teacher, json=body)
    assert r.status_code == 202, r.text
    return client.get(f"{P}/generations/{r.json()['id']}", headers=teacher).json()


def test_generates_validated_questions_with_page_and_line_citations(storage, teacher, use_llm):
    fake = use_llm(llm_with(lambda prompt: draft(tf="true_false" in prompt)))
    doc_id = ready_document(teacher)
    job = generate(teacher, doc_id, mcq_count=1, true_false_count=1)
    assert job["status"] == "done" and job["produced_count"] == 2 and job["requested_count"] == 2
    questions = [client.get(f"{P}/questions/{qid}", headers=teacher).json() for qid in job["question_ids"]]
    assert {q["type"] for q in questions} == {"mcq", "true_false"}
    tf = next(q for q in questions if q["type"] == "true_false")
    assert tf["options"] == {"A": "True", "B": "False"}
    cite = questions[0]["citations"][0]
    assert (cite["document"], cite["page"], cite["line_start"], cite["line_end"]) == ("lesson.pdf", 1, 2, 2)
    assert cite["quote"] == QUOTE and cite["chunk_id"]
    assert [s for _, s in fake.calls] == ["DraftQuestion", "BlindAnswer"] * 2


def test_citation_that_does_not_match_the_lines_is_rejected(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft(line=3)))  # the quote is on line 2, not 3
    job = generate(teacher, ready_document(teacher))
    assert job["status"] == "failed" and job["produced_count"] == 0
    assert job["error"] == "No question passed validation"


def test_blind_validation_disagreement_or_ambiguity_discards_the_question(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft(), blind=lambda: BlindAnswer(answer="B", ambiguous=False, reasoning="x")))
    assert generate(teacher, ready_document(teacher))["status"] == "failed"
    use_llm(llm_with(lambda prompt: draft(), blind=lambda: BlindAnswer(answer="A", ambiguous=True, reasoning="x")))
    assert generate(teacher, ready_document(teacher))["status"] == "failed"


def test_retries_until_a_draft_passes(storage, teacher, use_llm):
    attempts = iter([draft(line=3), draft(line=3), draft()])
    fake = use_llm(llm_with(lambda prompt: next(attempts)))
    job = generate(teacher, ready_document(teacher))
    assert job["status"] == "done" and job["produced_count"] == 1
    assert sum(1 for _, s in fake.calls if s == "DraftQuestion") == 3


def test_model_failures_are_reported(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: LlmError("boom")))
    job = generate(teacher, ready_document(teacher))
    assert job["status"] == "failed" and job["error"] == "The model could not be reached"


def test_unexpected_error_is_recorded_without_details(storage, teacher, use_llm):
    def explode(prompt):
        raise RuntimeError("secret internal detail")

    use_llm(llm_with(explode))
    job = generate(teacher, ready_document(teacher))
    assert job["status"] == "failed" and job["error"] == "Generation failed unexpectedly"


def test_prompt_marks_document_text_as_data_and_numbers_lines(storage, teacher, use_llm):
    prompts = []
    use_llm(llm_with(lambda prompt: prompts.append(prompt) or draft()))
    generate(teacher, ready_document(teacher), focus="chlorophyll")
    assert "<excerpt>" in prompts[0] and "[p1 l2] Chlorophyll" in prompts[0]
    assert "Teacher's focus" in prompts[0]


def test_generation_is_503_when_the_llm_is_not_configured(storage, teacher):
    r = client.post(f"{P}/generations", headers=teacher, json={"document_ids": [1], "mcq_count": 1})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "LLM_NOT_CONFIGURED"


def test_request_validation(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft()))
    doc_id = ready_document(teacher)
    post = lambda **b: client.post(f"{P}/generations", headers=teacher, json={"document_ids": [doc_id], **b})  # noqa: E731
    assert post().status_code == 422  # no questions requested
    assert post(mcq_count=get_settings().generation_max_questions + 1).status_code == 422
    assert post(mcq_count=-1).status_code == 422


def test_only_own_ready_documents_can_be_used(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft()))
    doc_id = ready_document(teacher)
    other = new_teacher()
    r = client.post(f"{P}/generations", headers=other, json={"document_ids": [doc_id], "mcq_count": 1})
    assert r.status_code == 404
    r = client.post(f"{P}/generations", headers=teacher, json={"document_ids": [10**9], "mcq_count": 1})
    assert r.status_code == 404


def test_jobs_are_private_and_one_runs_at_a_time(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft()))
    doc_id = ready_document(teacher)
    job = generate(teacher, doc_id)
    other = new_teacher()
    assert client.get(f"{P}/generations/{job['id']}", headers=other).status_code == 404

    with SessionLocal() as db:  # simulate a job that is still running
        row = db.get(GenerationJob, job["id"])
        assert row is not None
        row.status = JobStatus.running
        db.commit()
    r = client.post(f"{P}/generations", headers=teacher, json={"document_ids": [doc_id], "mcq_count": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_IN_PROGRESS"


def test_stale_running_job_is_reported_failed_and_unblocks(storage, teacher, use_llm, monkeypatch):
    use_llm(llm_with(lambda prompt: draft()))
    doc_id = ready_document(teacher)
    job = generate(teacher, doc_id)
    with SessionLocal() as db:
        row = db.get(GenerationJob, job["id"])
        assert row is not None
        row.status = JobStatus.running
        db.commit()
    monkeypatch.setattr(get_settings(), "job_stale_minutes", 0)
    assert client.get(f"{P}/generations/{job['id']}", headers=teacher).json()["status"] == "failed"
    assert client.post(f"{P}/generations", headers=teacher, json={"document_ids": [doc_id], "mcq_count": 1}).status_code == 202


def test_questions_survive_document_deletion_with_their_citations(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft()))
    doc_id = ready_document(teacher)
    job = generate(teacher, doc_id)
    client.delete(f"{P}/documents/{doc_id}", headers=teacher)
    q = client.get(f"{P}/questions/{job['question_ids'][0]}", headers=teacher).json()
    assert q["document_id"] is None
    assert q["citations"][0]["document"] == "lesson.pdf" and q["citations"][0]["page"] == 1


def test_questions_are_private_and_filterable(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft(tf="true_false" in prompt)))
    doc_id = ready_document(teacher)
    job = generate(teacher, doc_id, mcq_count=1, true_false_count=1)
    qid = job["question_ids"][0]
    other = new_teacher()
    assert client.get(f"{P}/questions/{qid}", headers=other).status_code == 404
    assert client.delete(f"{P}/questions/{qid}", headers=other).status_code == 404
    assert client.get(f"{P}/questions", headers=other).json() == []
    only_tf = client.get(f"{P}/questions", headers=teacher, params={"type": "true_false", "document_id": doc_id}).json()
    assert [q["type"] for q in only_tf] == ["true_false"]
    assert client.delete(f"{P}/questions/{qid}", headers=teacher).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(BankQuestion).where(BankQuestion.id == qid)) is None
