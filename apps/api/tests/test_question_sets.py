import pytest

from app.pdf_text import extract_lines

from tests.test_documents import P, client, new_teacher, storage, teacher, upload  # noqa: F401
from tests.test_generation import QUOTE, draft, generate, llm_with, ready_document, use_llm  # noqa: F401


@pytest.fixture
def questions(storage, teacher, use_llm):
    use_llm(llm_with(lambda prompt: draft(tf="true_false" in prompt)))
    job = generate(teacher, ready_document(teacher), mcq_count=2, true_false_count=1)
    assert len(job["question_ids"]) == 3
    return job["question_ids"]


def make_set(teacher, ids, title="Unit 1 quiz"):
    r = client.post(f"{P}/question-sets", headers=teacher, json={"title": title, "question_ids": ids})
    assert r.status_code == 201, r.text
    return r.json()


def pdf_text(response):
    lines, _ = extract_lines(response.content, 50)
    return "\n".join(l.text for l in lines)


def test_create_list_get_keeps_question_order(teacher, questions):
    ids = list(reversed(questions))
    created = make_set(teacher, ids)
    assert created["question_count"] == 3 and [q["id"] for q in created["questions"]] == ids
    assert created["questions"][0]["correct_option"]  # the teacher sees answers
    assert client.get(f"{P}/question-sets/{created['id']}", headers=teacher).json()["questions"][0]["id"] == ids[0]
    listed = client.get(f"{P}/question-sets", headers=teacher).json()
    assert [(s["title"], s["question_count"]) for s in listed] == [("Unit 1 quiz", 3)]


def test_replace_reuses_the_set_later(teacher, questions):
    created = make_set(teacher, questions)
    r = client.put(
        f"{P}/question-sets/{created['id']}",
        headers=teacher,
        json={"title": "Unit 1 retake", "question_ids": questions[:2]},
    )
    assert r.status_code == 200 and r.json()["title"] == "Unit 1 retake" and r.json()["question_count"] == 2
    # Saved sets can be reused: the same questions can go into another set.
    assert make_set(teacher, questions, "Final")["question_count"] == 3


def test_validation(teacher, questions):
    post = lambda body: client.post(f"{P}/question-sets", headers=teacher, json=body)  # noqa: E731
    assert post({"title": "x", "question_ids": []}).status_code == 422
    assert post({"title": "  ", "question_ids": questions}).status_code == 422
    assert post({"title": "x", "question_ids": [questions[0], questions[0]]}).status_code == 422
    assert post({"title": "x", "question_ids": [10**9]}).status_code == 404


def test_other_teachers_cannot_see_or_use_a_set_or_its_questions(teacher, questions):
    created = make_set(teacher, questions)
    other = new_teacher()
    sid = created["id"]
    assert client.get(f"{P}/question-sets/{sid}", headers=other).status_code == 404
    assert client.get(f"{P}/question-sets/{sid}/pdf", headers=other).status_code == 404
    assert client.put(f"{P}/question-sets/{sid}", headers=other, json={"title": "x", "question_ids": questions}).status_code == 404
    assert client.delete(f"{P}/question-sets/{sid}", headers=other).status_code == 404
    r = client.post(f"{P}/question-sets", headers=other, json={"title": "x", "question_ids": questions})
    assert r.status_code == 404  # cannot put someone else's questions in a set
    assert client.get(f"{P}/question-sets", headers=other).json() == []


def test_delete_set_keeps_questions(teacher, questions):
    sid = make_set(teacher, questions)["id"]
    assert client.delete(f"{P}/question-sets/{sid}", headers=teacher).status_code == 204
    assert client.get(f"{P}/question-sets/{sid}", headers=teacher).status_code == 404
    assert client.get(f"{P}/questions/{questions[0]}", headers=teacher).status_code == 200


def test_deleting_a_question_removes_it_from_sets(teacher, questions):
    sid = make_set(teacher, questions)["id"]
    client.delete(f"{P}/questions/{questions[0]}", headers=teacher)
    assert client.get(f"{P}/question-sets/{sid}", headers=teacher).json()["question_count"] == 2


def test_student_pdf_has_no_answers_or_sources(teacher, questions):
    sid = make_set(teacher, questions)["id"]
    r = client.get(f"{P}/question-sets/{sid}/pdf", headers=teacher)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and 'filename="Unit-1-quiz-student.pdf"' in r.headers["content-disposition"]
    text = pdf_text(r)
    assert "Unit 1 quiz" in text and "Name:" in text and "1. What does chlorophyll absorb" in text
    assert "Sunlight" in text and "True" in text
    assert "Answer:" not in text and "Source:" not in text and "lesson.pdf" not in text


def test_teacher_pdf_has_answers_explanations_and_page_line_sources(teacher, questions):
    sid = make_set(teacher, questions)["id"]
    r = client.get(f"{P}/question-sets/{sid}/pdf", headers=teacher, params={"version": "teacher"})
    assert r.status_code == 200 and "teacher.pdf" in r.headers["content-disposition"]
    text = pdf_text(r)
    assert "Answer key" in text and "Answer: A." in text
    assert "The excerpt says chlorophyll absorbs sunlight." in text
    assert "Source: lesson.pdf, page 1, line 2" in text


def test_pdf_escapes_markup_in_question_text(teacher, storage, use_llm):
    def evil(prompt):
        d = draft()
        return d.model_copy(update={"stem": "Which tag is <b>bold</b> & what is 5 < 6 in <i>HTML</i>?"})

    use_llm(llm_with(evil))
    ids = generate(teacher, ready_document(teacher))["question_ids"]
    sid = make_set(teacher, ids)["id"]
    r = client.get(f"{P}/question-sets/{sid}/pdf", headers=teacher)
    assert r.status_code == 200
    assert "<b>bold</b> & what is 5 < 6 in <i>HTML</i>?" in pdf_text(r)


def test_pdf_of_unknown_version_is_422(teacher, questions):
    sid = make_set(teacher, questions)["id"]
    assert client.get(f"{P}/question-sets/{sid}/pdf", headers=teacher, params={"version": "x"}).status_code == 422
