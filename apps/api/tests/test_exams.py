import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.clock import get_clock
from app.main import app

P = "/api/v1"
client = TestClient(app)
PASSWORD = "s3cret-pass"


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


def _login(username, password):
    r = client.post(f"{P}/auth/login", data={"username": username, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def student():
    """A fresh student, so each test starts with no exams or answers."""
    name = f"s-{uuid.uuid4().hex[:8]}"
    admin = _login("alice", "wonderland")
    assert client.post(f"{P}/users", headers=admin, json={"username": name, "password": PASSWORD}).status_code == 201
    return _login(name, PASSWORD)


def make_exam(h, mode="exam", **kw):
    r = client.post(f"{P}/exams", headers=h, json={"mode": mode, **kw})
    assert r.status_code == 202, r.text
    return r.json()


def start(h, exam_id):
    r = client.post(f"{P}/exams/{exam_id}/start", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def answer(h, exam_id, qid, option="A"):
    return client.put(f"{P}/exams/{exam_id}/answers/{qid}", headers=h, json={"selected_option": option})


def results(h, exam_id):
    return client.get(f"{P}/exams/{exam_id}/results", headers=h)


def code(r):
    return r.json()["detail"]["code"]


# --- creation ---------------------------------------------------------------------------

def test_create_exam_returns_202_and_ready(student):
    exam = make_exam(student, question_count=5)
    assert exam["status"] == "ready"
    assert exam["question_count"] == 5
    assert exam["questions"] is None  # hidden until started


def test_exam_duration_scales_with_question_count(student):
    assert make_exam(student, question_count=5)["duration_minutes"] == 10


def test_practice_has_no_duration(student):
    assert make_exam(student, "practice", question_count=3)["duration_minutes"] is None


def test_request_larger_than_bank_is_capped(student):
    exam = make_exam(student, question_count=65)
    assert exam["requested_question_count"] == 65
    assert 0 < exam["question_count"] < 65


def test_domain_filter(student):
    exam = make_exam(student, "practice", question_count=4, domains=[4])
    for q in start(student, exam["id"])["questions"]:
        assert answer(student, exam["id"], q["id"]).status_code == 200
    domains = {q["domain"] for q in results(student, exam["id"]).json()["questions"]}
    assert domains == {"Design Cost-Optimized Architectures"}


def test_unknown_domain_rejected(student):
    r = client.post(f"{P}/exams", headers=student, json={"mode": "exam", "domains": [99]})
    assert r.status_code == 422


def test_invalid_mode_rejected(student):
    assert client.post(f"{P}/exams", headers=student, json={"mode": "x"}).status_code == 422


# --- FR-OWN-1 / RBAC ----------------------------------------------------------------------

def test_other_students_exam_is_404(student):
    exam = make_exam(student)
    other = _login("bob", "builder")
    for method, path in [
        ("GET", f"/exams/{exam['id']}"),
        ("POST", f"/exams/{exam['id']}/start"),
        ("POST", f"/exams/{exam['id']}/submit"),
        ("GET", f"/exams/{exam['id']}/results"),
    ]:
        assert client.request(method, P + path, headers=other).status_code == 404


def test_admin_cannot_use_exams():
    admin = _login("alice", "wonderland")
    assert client.post(f"{P}/exams", headers=admin, json={"mode": "exam"}).status_code == 403


# --- lifecycle and time rules -------------------------------------------------------------

def test_start_sets_server_side_window(student, clock):
    exam = make_exam(student, question_count=5)
    started = start(student, exam["id"])
    assert started["status"] == "in_progress"
    assert datetime.fromisoformat(started["started_at"]) == clock.now
    assert datetime.fromisoformat(started["ends_at"]) == clock.now + timedelta(minutes=10)
    assert len(started["questions"]) == 5


def test_start_twice_conflicts(student):
    exam = make_exam(student)
    start(student, exam["id"])
    r = client.post(f"{P}/exams/{exam['id']}/start", headers=student)
    assert r.status_code == 409 and code(r) == "EXAM_ALREADY_STARTED"


def test_answer_before_start_conflicts(student):
    exam = make_exam(student)
    r = answer(student, exam["id"], 1)
    assert r.status_code == 409 and code(r) == "EXAM_NOT_STARTED"


def test_get_exam_never_leaks_answers(student):
    """FR-GEN-4"""
    for mode in ("exam", "practice"):
        exam = make_exam(student, mode, question_count=3)
        started = start(student, exam["id"])
        answer(student, exam["id"], started["questions"][0]["id"])
        bodies = [client.get(f"{P}/exams/{exam['id']}", headers=student).text]
        bodies.append(client.post(f"{P}/exams/{exam['id']}/submit", headers=student).text)
        for body in bodies:
            assert "correct_option" not in body and "explanation" not in body


def test_answer_saves_and_overwrites(student):
    exam = make_exam(student, question_count=3)
    q = start(student, exam["id"])["questions"][0]["id"]
    assert answer(student, exam["id"], q, "A").status_code == 200
    assert answer(student, exam["id"], q, "B").status_code == 200
    detail = client.get(f"{P}/exams/{exam['id']}", headers=student).json()
    selected = {x["id"]: x["selected_option"] for x in detail["questions"]}
    assert selected[q] == "B"


def test_exam_mode_answer_gives_no_feedback(student):
    exam = make_exam(student, question_count=3)
    q = start(student, exam["id"])["questions"][0]["id"]
    body = answer(student, exam["id"], q).json()
    assert set(body) == {"question_id", "selected_option", "answered_at"}


def test_invalid_option_and_foreign_question(student):
    exam = make_exam(student, question_count=3)
    q = start(student, exam["id"])["questions"][0]["id"]
    assert answer(student, exam["id"], q, "E").status_code == 422
    assert answer(student, exam["id"], 999999, "A").status_code == 404


def test_answer_after_ends_at_rejected(student, clock):
    """FR-TIME-1"""
    exam = make_exam(student, question_count=3)
    q = start(student, exam["id"])["questions"][0]["id"]
    clock.advance(minutes=6, seconds=1)  # 3 questions -> 6 minutes
    r = answer(student, exam["id"], q)
    assert r.status_code == 409 and code(r) == "EXAM_WINDOW_CLOSED"


def test_answer_at_last_second_still_accepted(student, clock):
    exam = make_exam(student, question_count=3)
    q = start(student, exam["id"])["questions"][0]["id"]
    clock.advance(minutes=5, seconds=59)
    assert answer(student, exam["id"], q).status_code == 200


def test_exam_results_locked_until_finished(student):
    """FR-TIME-2"""
    exam = make_exam(student, question_count=3)
    start(student, exam["id"])
    r = results(student, exam["id"])
    assert r.status_code == 403 and code(r) == "RESULTS_LOCKED"


def test_submit_scores_and_unlocks_results(student):
    exam = make_exam(student, question_count=4)
    questions = start(student, exam["id"])["questions"]
    for q in questions:
        answer(student, exam["id"], q["id"], "A")
    done = client.post(f"{P}/exams/{exam['id']}/submit", headers=student).json()
    assert done["status"] == "finished"
    res = results(student, exam["id"]).json()
    assert res["total"] == 4 and res["answered"] == 4
    assert done["score"] == res["correct"]
    assert len(res["questions"]) == 4
    assert all("explanation" in q and "correct_option" in q for q in res["questions"])
    assert res["correct"] == sum(q["selected_option"] == q["correct_option"] for q in res["questions"])


def test_submit_twice_conflicts(student):
    exam = make_exam(student, question_count=3)
    start(student, exam["id"])
    client.post(f"{P}/exams/{exam['id']}/submit", headers=student)
    r = client.post(f"{P}/exams/{exam['id']}/submit", headers=student)
    assert r.status_code == 409 and code(r) == "EXAM_WINDOW_CLOSED"


def test_expired_exam_is_finalized_on_next_access(student, clock):
    """FR-TIME-3"""
    exam = make_exam(student, question_count=3)
    questions = start(student, exam["id"])["questions"]
    answer(student, exam["id"], questions[0]["id"], "A")
    clock.advance(minutes=7)
    got = client.get(f"{P}/exams/{exam['id']}", headers=student).json()
    assert got["status"] == "finished"
    assert got["score"] is not None
    assert datetime.fromisoformat(got["submitted_at"]) == datetime.fromisoformat(got["ends_at"])
    assert results(student, exam["id"]).status_code == 200  # unlocked by expiry


def test_submit_after_expiry_rejected_but_scored(student, clock):
    exam = make_exam(student, question_count=3)
    start(student, exam["id"])
    clock.advance(minutes=10)
    r = client.post(f"{P}/exams/{exam['id']}/submit", headers=student)
    assert r.status_code == 409 and code(r) == "EXAM_WINDOW_CLOSED"
    assert client.get(f"{P}/exams/{exam['id']}", headers=student).json()["status"] == "finished"


# --- practice mode ------------------------------------------------------------------------

def test_practice_answer_gives_immediate_feedback(student):
    exam = make_exam(student, "practice", question_count=3)
    q = start(student, exam["id"])["questions"][0]["id"]
    body = answer(student, exam["id"], q, "A").json()
    assert {"is_correct", "correct_option", "explanation"} <= set(body)
    assert body["is_correct"] == (body["correct_option"] == "A")


def test_practice_has_no_deadline_and_results_always_available(student, clock):
    exam = make_exam(student, "practice", question_count=3)
    # Results are available even before starting (nothing answered yet).
    assert results(student, exam["id"]).status_code == 200
    started = start(student, exam["id"])
    assert started["ends_at"] is None
    q = started["questions"][0]["id"]
    clock.advance(days=3)
    assert answer(student, exam["id"], q).status_code == 200
    res = results(student, exam["id"]).json()
    assert res["answered"] == 1 and len(res["questions"]) == 1  # only what was answered
    assert res["status"] == "in_progress"


# --- stats --------------------------------------------------------------------------------

def stats(h):
    return client.get(f"{P}/me/stats", headers=h).json()


def test_stats_start_empty(student):
    s = stats(student)
    assert len(s["domains"]) == 4
    assert all(d["attempted"] == 0 and d["accuracy"] is None for d in s["domains"])


def test_stats_count_practice_answers(student):
    exam = make_exam(student, "practice", question_count=6)
    for q in start(student, exam["id"])["questions"]:
        answer(student, exam["id"], q["id"], "A")
    s = stats(student)
    assert sum(d["attempted"] for d in s["domains"]) == 6
    for d in s["domains"]:
        assert d["attempted"] == sum(t["attempted"] for t in d["task_statements"])
        if d["attempted"]:
            assert d["accuracy"] == pytest.approx(d["correct"] / d["attempted"], abs=1e-3)


def test_stats_ignore_unfinished_exam_answers(student):
    exam = make_exam(student, "exam", question_count=4)
    for q in start(student, exam["id"])["questions"]:
        answer(student, exam["id"], q["id"], "A")
    assert sum(d["attempted"] for d in stats(student)["domains"]) == 0
    client.post(f"{P}/exams/{exam['id']}/submit", headers=student)
    assert sum(d["attempted"] for d in stats(student)["domains"]) == 4


def test_stats_are_per_user(student):
    exam = make_exam(student, "practice", question_count=3)
    for q in start(student, exam["id"])["questions"]:
        answer(student, exam["id"], q["id"], "A")
    other = _login("carol", "christmas")
    before = sum(d["attempted"] for d in stats(other)["domains"])
    assert sum(d["attempted"] for d in stats(student)["domains"]) == 3
    assert sum(d["attempted"] for d in stats(other)["domains"]) == before
