"""The built-in exam. Sessions and PDFs use it until teachers can pick their own question sets.

Questions are plain data here, not database rows; a session stores answers by question `key`.
"""

from dataclasses import dataclass

from exam_core.models import QuestionType


@dataclass(frozen=True)
class ExamQuestion:
    key: str
    type: QuestionType
    stem: str
    options: dict[str, str]
    correct_option: str
    explanation: str
    citations: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Exam:
    id: str
    title: str
    questions: tuple[ExamQuestion, ...]

    def question(self, key: str) -> ExamQuestion | None:
        return next((q for q in self.questions if q.key == key), None)


_TRUE_FALSE = {"A": "True", "B": "False"}

SAMPLE_EXAM = Exam(
    id="sample",
    title="Sample exam: basic science",
    questions=(
        ExamQuestion(
            "q1",
            QuestionType.mcq,
            "Which gas do plants absorb from the air for photosynthesis?",
            {"A": "Oxygen", "B": "Carbon dioxide", "C": "Nitrogen", "D": "Hydrogen"},
            "B",
            "Plants take in carbon dioxide and, using light, turn it into sugar and oxygen.",
        ),
        ExamQuestion(
            "q2",
            QuestionType.mcq,
            "What is the chemical symbol for water?",
            {"A": "H2O", "B": "CO2", "C": "O2", "D": "NaCl"},
            "A",
            "A water molecule has two hydrogen atoms and one oxygen atom: H2O.",
        ),
        ExamQuestion(
            "q3",
            QuestionType.mcq,
            "Which planet is closest to the Sun?",
            {"A": "Venus", "B": "Earth", "C": "Mercury", "D": "Mars"},
            "C",
            "Mercury orbits closest to the Sun, at about 58 million kilometres.",
        ),
        ExamQuestion(
            "q4",
            QuestionType.mcq,
            "What force pulls objects toward the centre of the Earth?",
            {"A": "Magnetism", "B": "Friction", "C": "Gravity", "D": "Buoyancy"},
            "C",
            "Gravity is the attraction between masses; Earth's gravity pulls objects toward its centre.",
        ),
        ExamQuestion(
            "q5",
            QuestionType.true_false,
            "Sound travels faster than light.",
            _TRUE_FALSE,
            "B",
            "Light travels at about 300,000 km/s; sound in air at about 343 m/s.",
        ),
        ExamQuestion(
            "q6",
            QuestionType.true_false,
            "Water boils at 100 degrees Celsius at sea level.",
            _TRUE_FALSE,
            "A",
            "At standard sea-level pressure, pure water boils at 100 degrees Celsius.",
        ),
    ),
)

EXAMS: dict[str, Exam] = {SAMPLE_EXAM.id: SAMPLE_EXAM}
