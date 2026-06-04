from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "PMS_QA_CORRECTIONS_AND_SUGGESTIONS_2026-05-22.md"
TARGET = ROOT / "PMS_QA_CORRECTIONS_AND_SUGGESTIONS_2026-05-22.pdf"


def render_inline(text):
    escaped = escape(text.strip())
    parts = escaped.split("`")
    if len(parts) == 1:
        return escaped
    rendered = []
    for index, part in enumerate(parts):
        rendered.append(f"<font name='Courier'>{part}</font>" if index % 2 else part)
    return "".join(rendered)


def build_pdf():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SmallGap",
        parent=styles["BodyText"],
        spaceAfter=4,
        leading=13,
    ))
    styles.add(ParagraphStyle(
        name="ListText",
        parent=styles["BodyText"],
        leftIndent=12,
        firstLineIndent=-10,
        spaceAfter=3,
        leading=13,
    ))

    story = []
    for raw_line in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 2 * mm))
            continue
        if line.startswith("# "):
            story.append(Paragraph(render_inline(line[2:]), styles["Title"]))
            story.append(Spacer(1, 3 * mm))
        elif line.startswith("## "):
            story.append(Paragraph(render_inline(line[3:]), styles["Heading2"]))
        elif line[:2].isdigit() and line[1:3] == ". ":
            story.append(Paragraph(render_inline(line), styles["ListText"]))
        elif line.startswith("- "):
            story.append(Paragraph(f"- {render_inline(line[2:])}", styles["ListText"]))
        else:
            story.append(Paragraph(render_inline(line), styles["SmallGap"]))

    document = SimpleDocTemplate(
        str(TARGET),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="PMS QA Corrections and Suggestions",
        author="Codex",
    )
    document.build(story)
    print(TARGET)


if __name__ == "__main__":
    build_pdf()
