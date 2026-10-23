import io
from datetime import UTC, datetime, timedelta

import pytest
from pdfminer.high_level import extract_text

from app.clock import get_clock
from app.main import app
from app.sample_exam import SAMPLE_EXAM
from tests.helpers_api import P, client, new_teacher

KEYS = [q.key for q in SAMPLE_EXAM.questions]
RIGHT = {q.key: q.correct_option for q in SAMPLE_EXAM.questions}


class FakeClock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    fake = FakeClock()
    app.dependency_overrides[get_clock] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_clock, None)


@pytest.fixture
def teacher():
    return new_teacher()


def start(teacher, minutes=30):
    r = client.post(f"{P}/exam-sessions", headers=teacher, json={"exam_id": "sample", "duration_minutes": minutes})
    assert r.status_code == 201, r.text
    return r.json()


def token_of(session):
    return session["join_url"].rsplit("/", 1)[1]


def join(session, name="Ana"):
    r = client.post(f"{P}/join/{token_of(session)}/participants", json={"name": name})
    assert r.status_code == 201, r.text
    return {"X-Participant-Token": r.json()["participant_token"]}


def answer(session, who, key, option):
    return client.put(f"{P}/join/{token_of(session)}/answers/{key}", headers=who, json={"selected_option": option})


def submit(session, who):
    return client.post(f"{P}/join/{token_of(session)}/submit", headers=who)


def dashboard(teacher, session):
    r = client.get(f"{P}/exam-sessions/{session['id']}", headers=teacher)
    assert r.status_code == 200, r.text
    return r.json()


# ---- download


def test_download_student_and_teacher_pdfs(teacher):
    student = client.get(f"{P}/sample-exam/pdf", headers=teacher)
    assert student.status_code == 200 and student.headers["content-type"] == "application/pdf"
    assert "sample-exam-student.pdf" in student.headers["content-disposition"]
    text = extract_text(io.BytesIO(student.content))
    assert "Sample exam" in text and "Name:" in text and "1. Which gas do plants absorb" in text
    assert "Carbon dioxide" in text and "Answer:" not in text

    key = client.get(f"{P}/sample-exam/pdf", headers=teacher, params={"version": "teacher"})
    assert "sample-exam-teacher.pdf" in key.headers["content-disposition"]
    text = extract_text(io.BytesIO(key.content))
    assert "Answer key" in text and "Answer: B." in text and "Plants take in carbon dioxide" in text
    assert client.get(f"{P}/sample-exam/pdf", headers=teacher, params={"version": "x"}).status_code == 422


def test_sample_exam_is_shown_to_teachers_with_answers(teacher):
    exam = client.get(f"{P}/sample-exam", headers=teacher).json()
    assert exam["question_count"] == len(KEYS) and exam["questions"][0]["correct_option"] == "B"


# ---- starting a session


def test_start_returns_a_join_url_and_a_fixed_window(teacher, clock):
    s = start(teacher, 45)
    assert s["status"] == "open" and s["duration_minutes"] == 45 and s["question_count"] == len(KEYS)
    assert datetime.fromisoformat(s["ends_at"]) == clock.now + timedelta(minutes=45)
    assert s["join_url"].startswith("http") and "/join/" in s["join_url"]
    assert s["participant_count"] == 0


def test_start_validation(teacher):
    post = lambda **b: client.post(f"{P}/exam-sessions", headers=teacher, json=b)  # noqa: E731
    assert post(duration_minutes=0).status_code == 422
    assert post(duration_minutes=99999).status_code == 422
    assert post(duration_minutes=481).status_code == 422  # over the configured maximum
    assert post(exam_id="nope", duration_minutes=10).status_code == 404


def test_sessions_are_private_to_their_teacher(teacher):
    s = start(teacher)
    other = new_teacher()
    assert client.get(f"{P}/exam-sessions/{s['id']}", headers=other).status_code == 404
    assert client.post(f"{P}/exam-sessions/{s['id']}/close", headers=other).status_code == 404
    assert client.get(f"{P}/exam-sessions", headers=other).json() == []
    assert [x["id"] for x in client.get(f"{P}/exam-sessions", headers=teacher).json()] == [s["id"]]


# ---- a student takes the exam


def test_student_flow_gets_results_immediately_and_dashboard_updates(teacher):
    s = start(teacher)
    info = client.get(f"{P}/join/{token_of(s)}").json()
    assert info["status"] == "open" and info["question_count"] == len(KEYS) and "questions" not in info

    ana = join(s, "Ana")
    me = client.get(f"{P}/join/{token_of(s)}/me", headers=ana).json()
    assert me["status"] == "in_progress" and len(me["questions"]) == len(KEYS) and me["result"] is None
    assert "correct_option" not in str(me) and "explanation" not in str(me)  # no answers before submitting

    assert dashboard(teacher, s)["participants"][0]["status"] == "in_progress"

    for key in KEYS[:-1]:
        assert answer(s, ana, key, RIGHT[key]).status_code == 204
    wrong = "B" if RIGHT[KEYS[-1]] == "A" else "A"
    assert answer(s, ana, KEYS[-1], wrong).status_code == 204
    assert answer(s, ana, KEYS[0], "A").status_code == 204  # changing an answer overwrites it
    assert answer(s, ana, KEYS[0], RIGHT[KEYS[0]]).status_code == 204

    mid = dashboard(teacher, s)["participants"][0]
    assert mid["answered_count"] == len(KEYS) and mid["score"] is None

    result = submit(s, ana)
    assert result.status_code == 200
    body = result.json()
    assert body["score"] == len(KEYS) - 1 and body["total"] == len(KEYS)
    missed = [r for r in body["review"] if not r["is_correct"]]
    assert len(missed) == 1 and missed[0]["correct_option"] == RIGHT[KEYS[-1]] and missed[0]["explanation"]

    board = dashboard(teacher, s)
    assert board["participants"][0]["status"] == "submitted" and board["participants"][0]["score"] == len(KEYS) - 1
    assert board["average_score"] == len(KEYS) - 1
    assert board["session"]["participant_count"] == 1 and board["session"]["submitted_count"] == 1
    last = board["questions"][-1]
    assert last["answered_count"] == 1 and last["correct_count"] == 0
    assert board["questions"][0]["correct_count"] == 1

    # After submitting the student can reload and still sees the result, but cannot change anything.
    again = client.get(f"{P}/join/{token_of(s)}/me", headers=ana).json()
    assert again["status"] == "submitted" and again["result"]["score"] == len(KEYS) - 1 and again["questions"] == []
    assert answer(s, ana, KEYS[0], "A").json()["code"] == "ALREADY_SUBMITTED"
    assert submit(s, ana).status_code == 409


def test_unanswered_questions_count_as_wrong(teacher):
    s = start(teacher)
    ana = join(s)
    assert submit(s, ana).json()["score"] == 0


def test_answer_validation(teacher):
    s = start(teacher)
    ana = join(s)
    assert answer(s, ana, "q99", "A").status_code == 404
    assert answer(s, ana, "q5", "C").status_code == 422  # true/false has only A and B
    assert answer(s, ana, "q1", "Z").status_code == 422


def test_names_must_be_unique_and_clean(teacher):
    s = start(teacher)
    join(s, "  Ana   Lopez ")
    r = client.post(f"{P}/join/{token_of(s)}/participants", json={"name": "Ana Lopez"})
    assert r.status_code == 409 and r.json()["code"] == "NAME_TAKEN"
    assert client.post(f"{P}/join/{token_of(s)}/participants", json={"name": "   "}).status_code == 422
    join(start(teacher), "Ana Lopez")  # the same name is fine in another session


def test_session_capacity(teacher, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "session_max_participants", 1)
    s = start(teacher)
    join(s, "A")
    r = client.post(f"{P}/join/{token_of(s)}/participants", json={"name": "B"})
    assert r.status_code == 409 and r.json()["code"] == "SESSION_FULL"


# ---- credentials


def test_tokens_are_checked():
    assert client.get(f"{P}/join/not-a-real-token").status_code == 404
    assert client.post(f"{P}/join/not-a-real-token/participants", json={"name": "x"}).status_code == 404


def test_a_participant_token_works_only_in_its_own_session(teacher):
    s1, s2 = start(teacher), start(teacher)
    ana = join(s1)
    assert client.get(f"{P}/join/{token_of(s2)}/me", headers=ana).status_code == 404
    assert client.get(f"{P}/join/{token_of(s1)}/me", headers={"X-Participant-Token": "x" * 40}).status_code == 404
    assert client.get(f"{P}/join/{token_of(s1)}/me").status_code == 422  # header missing


def test_students_cannot_see_each_others_answers(teacher):
    s = start(teacher)
    ana, ben = join(s, "Ana"), join(s, "Ben")
    answer(s, ana, "q1", "B")
    assert client.get(f"{P}/join/{token_of(s)}/me", headers=ben).json()["answers"] == {}
    assert client.get(f"{P}/join/{token_of(s)}/me", headers=ana).json()["answers"] == {"q1": "B"}


# ---- time


def test_time_limit_is_enforced_on_the_server_clock(teacher, clock):
    s = start(teacher, 10)
    ana = join(s)
    answer(s, ana, "q1", "B")
    clock.advance(minutes=9, seconds=59)
    assert answer(s, ana, "q2", "A").status_code == 204
    clock.advance(seconds=1)  # the window is closed from ends_at on
    late = answer(s, ana, "q3", "C")
    assert late.status_code == 409 and late.json()["code"] == "ALREADY_SUBMITTED"  # finalized on contact
    state = client.get(f"{P}/join/{token_of(s)}/me", headers=ana).json()
    assert state["status"] == "submitted" and state["result"]["score"] == 2  # scored on what was saved
    assert client.get(f"{P}/join/{token_of(s)}").json()["status"] == "ended"
    r = client.post(f"{P}/join/{token_of(s)}/participants", json={"name": "Late"})
    assert r.status_code == 409 and r.json()["code"] == "SESSION_ENDED"


def test_dashboard_scores_students_who_never_submitted_after_time_is_up(teacher, clock):
    s = start(teacher, 5)
    ana = join(s)
    answer(s, ana, "q1", "B")
    assert dashboard(teacher, s)["participants"][0]["score"] is None
    clock.advance(minutes=6)
    board = dashboard(teacher, s)
    assert board["session"]["status"] == "ended" and board["participants"][0]["score"] == 1
    assert board["participants"][0]["status"] == "submitted"


def test_teacher_can_end_a_session_early(teacher, clock):
    s = start(teacher, 60)
    ana = join(s)
    answer(s, ana, "q1", "B")
    clock.advance(minutes=3)
    closed = client.post(f"{P}/exam-sessions/{s['id']}/close", headers=teacher).json()
    assert closed["status"] == "ended" and closed["closed_early"] and closed["submitted_count"] == 1
    assert answer(s, ana, "q2", "A").status_code == 409
    assert client.post(f"{P}/exam-sessions/{s['id']}/close", headers=teacher).status_code == 200  # idempotent
    assert client.get(f"{P}/join/{token_of(s)}").json()["status"] == "ended"
