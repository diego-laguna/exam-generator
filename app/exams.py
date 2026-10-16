from fastapi import APIRouter

from app.dependencies import AnyUser, StudentOnly, not_implemented

router = APIRouter(tags=["exams"])

# TODO(M4): replace the stubs with real logic and add the ownership (404 on foreign exams),
# active-window and results-unlocked dependencies from PRD section 8.


@router.post("/exams", dependencies=[StudentOnly])
def create_exam():
    not_implemented()


@router.get("/exams/{exam_id}", dependencies=[StudentOnly])
def get_exam(exam_id: int):
    not_implemented()


@router.post("/exams/{exam_id}/start", dependencies=[StudentOnly])
def start_exam(exam_id: int):
    not_implemented()


@router.put("/exams/{exam_id}/answers/{question_id}", dependencies=[StudentOnly])
def save_answer(exam_id: int, question_id: int):
    not_implemented()


@router.post("/exams/{exam_id}/submit", dependencies=[StudentOnly])
def submit_exam(exam_id: int):
    not_implemented()


@router.get("/exams/{exam_id}/results", dependencies=[StudentOnly])
def get_results(exam_id: int):
    not_implemented()


@router.get("/me/stats", dependencies=[AnyUser], tags=["stats"])
def my_stats():
    not_implemented()
