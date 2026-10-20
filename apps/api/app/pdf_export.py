"""Printable PDFs for a question set: a student sheet (no answers) or a teacher key."""

import io
from collections.abc import Sequence
from typing import Literal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from exam_core.models import BankQuestion, QuestionType

Version = Literal["student", "teacher"]


def _citation_text(c: dict) -> str:
    lines = (
        f"line {c['line_start']}"
        if c["line_start"] == c["line_end"]
        else f"lines {c['line_start']}-{c['line_end']}"
    )
    return f"{c.get('document') or 'source'}, page {c['page']}, {lines}"


def _footer(title: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, title[:80])
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def render_question_set_pdf(title: str, questions: Sequence[BankQuestion], version: Version) -> bytes:
    styles = getSampleStyleSheet()
    h1 = styles["Title"]
    body = styles["BodyText"]
    stem = ParagraphStyle("stem", parent=body, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)
    option = ParagraphStyle("option", parent=body, leftIndent=18, spaceAfter=2)
    note = ParagraphStyle("note", parent=body, fontSize=8.5, leading=11, leftIndent=18, textColor=colors.HexColor("#444444"))

    suffix = " - Answer key" if version == "teacher" else ""
    story: list = [Paragraph(escape(title) + escape(suffix), h1)]
    if version == "student":
        story += [Paragraph("Name: ______________________________ &nbsp;&nbsp; Date: ______________", body), Spacer(1, 10)]

    for number, q in enumerate(questions, start=1):
        block: list = [Paragraph(f"{number}. {escape(q.stem)}", stem)]
        if q.type == QuestionType.true_false:
            labels = [("A", "True"), ("B", "False")]
        else:
            labels = sorted(q.options.items())
        for letter, text in labels:
            mark = ("*" if version == "teacher" and letter == q.correct_option else "&nbsp;")
            block.append(Paragraph(f"[{mark}] {letter}. {escape(text)}", option))
        if version == "teacher":
            block.append(Paragraph(f"<b>Answer: {q.correct_option}.</b> {escape(q.explanation)}", note))
            for c in q.citations:
                block.append(Paragraph(f"Source: {escape(_citation_text(c))}", note))
        story.append(KeepTogether(block))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=title, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    )
    footer = _footer(title + suffix)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
