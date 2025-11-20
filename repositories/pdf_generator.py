from crm_service import Lead
from logger import setup_logger
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import os
import platform

logger = setup_logger(__name__)


def _escape_text(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _register_cyrillic_font():
    """Register a font that supports Cyrillic characters."""
    system = platform.system()
    font_paths = []

    if system == "Darwin":  # macOS
        font_paths = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ]
    elif system == "Linux":
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    elif system == "Windows":
        font_paths = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]

    # Try to register fonts
    regular_font = None
    bold_font = None

    for path in font_paths:
        if os.path.exists(path):
            try:
                if "Bold" in path or "bold" in path.lower() or "bd" in path.lower():
                    if not bold_font:
                        pdfmetrics.registerFont(TTFont("CyrillicBold", path))
                        bold_font = "CyrillicBold"
                else:
                    if not regular_font:
                        pdfmetrics.registerFont(TTFont("Cyrillic", path))
                        regular_font = "Cyrillic"
            except Exception as e:
                logger.warning(f"Failed to register font {path}: {e}")

    return regular_font or "Helvetica", bold_font or "Helvetica-Bold"


def create_anketa_pdf(lead: Lead | None, student_full_name: str | None = None) -> bytes:
    """
    Create PDF anketa from lead data.

    Args:
        lead: Lead object containing anketa data, or None for empty PDF
        student_full_name: Full name of the student to place inside the PDF

    Returns:
        PDF file as bytes
    """
    buffer = BytesIO()

    # Create document
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Анкета")

    # If no data provided, return empty PDF
    if not lead and not student_full_name:
        doc.build([])
        buffer.seek(0)
        return buffer.getvalue()

    # Register Cyrillic fonts
    regular_font, bold_font = _register_cyrillic_font()

    # Get styles
    styles = getSampleStyleSheet()

    # Create custom styles for questions and answers
    question_style = ParagraphStyle(
        "QuestionStyle",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=12,
        spaceAfter=6,
    )

    answer_style = ParagraphStyle(
        "AnswerStyle",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=10,
        spaceAfter=12,
        leftIndent=0,
    )

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        fontName=bold_font,
        fontSize=16,
        spaceAfter=20,
        alignment=0,  # Left align
    )

    # Build content
    story = []

    # Title
    story.append(Paragraph("Анкета", title_style))
    story.append(Spacer(1, 0.2 * inch))

    if student_full_name:
        story.append(Paragraph("Имя студента", question_style))
        story.append(Paragraph(_escape_text(student_full_name), answer_style))
        story.append(Spacer(1, 0.15 * inch))

    # Define custom fields with their question labels
    fields = [
        ("city", "В каком городе вы живете?"),
        ("source", "Откуда вы узнали о Поколении?"),
        ("why_this_mentor", "Почему вы хотите в группу именно к этому наставнику?"),
        (
            "life_goals",
            "Какие жизненные цели вы хотите достичь с помощью наставничества?",
        ),
        (
            "what_ready_to_do_for_team",
            "Что вы готовы сделать для команды, даже если это выходит за пределы вашей зоны комфорта?",
        ),
        ("three_life_principles", "Назовите три своих жизненных принципа"),
        (
            "question_for_mentor",
            "Какой один вопрос вы бы задали своему будущему наставнику?",
        ),
        (
            "top_5_achievements",
            "Назовите топ-5 своих достижений, которыми вы гордитесь на сегодняшний день.",
        ),
        (
            "olympiad_competition_volunteer_experience",
            "Если у вас есть опыт участия в олимпиадах, конкурсах, волонтерстве или других проектах — расскажите, в каких именно",
        ),
        (
            "portfolio_link",
            "Если у вас есть портфолио, кейсы или другие материалы, которые показывают ваши достижения и опыт, — поделитесь ссылкой. (Например: сайт, соцсети, видео, презентации или документы.) Это необязательный вопрос, но, если есть, можете отправить — это повысит ш",
        ),
        ("strong_qualities", "Какие свои качества вы считаете сильными?"),
        ("qualities_to_change", "Какие качества вы хотели бы изменить в себе?"),
        (
            "qualities_to_realize_in_project",
            "Какие свои качества, сильные стороны, таланты или способности вы хотите реализовать в проекте?",
        ),
        (
            "what_you_do_well",
            "Что у вас получается хорошо и чем вы могли бы быть полезны другим?",
        ),
    ]

    # Process each field
    for field_name, question_text in fields:
        # Get field value from lead
        field_value = getattr(lead, field_name, None) if lead else None

        # Skip if field is empty or None
        if not field_value:
            continue

        # Add question
        story.append(Paragraph(question_text, question_style))

        # Add answer (escape HTML special characters)
        answer_text = _escape_text(field_value)
        story.append(Paragraph(answer_text, answer_style))
        story.append(Spacer(1, 0.1 * inch))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
