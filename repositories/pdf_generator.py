from crm.crm_service import Lead
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


def _escape_text(value: str, preserve_newlines: bool = False) -> str:
    """Escape HTML special characters in text.
    
    Args:
        value: Text to escape
        preserve_newlines: If True, convert newlines to <br/> tags for PDF rendering
    """
    escaped = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if preserve_newlines:
        # Convert double newlines (paragraphs) and single newlines to <br/> tags
        escaped = escaped.replace("\r\n", "\n").replace("\n", "<br/>")
    return escaped


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


def create_anketa_pdf(lead: Lead | None, student_full_name: str | None = None) -> bytes | None:
    """
    Create PDF anketa from lead data.

    Args:
        lead: Lead object containing anketa data, or None for empty PDF
        student_full_name: Full name of the student to place inside the PDF

    Returns:
        PDF file as bytes, or None if all fields are empty
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
        ("city", "Город проживания"),
        ("current_study", "Где ты сейчас учишься?"),
        ("most_important_now", "Что для тебя сейчас важнее всего из этого?"),
        (
            "direction_2_3_years",
            "Если смотреть на ближайшие 2–3 года, в каком направлении ты хочешь двигаться?",
        ),
        (
            "multiple_tasks_behavior",
            "Когда у тебя одновременно несколько задач и дедлайнов, что обычно происходит?",
        ),
        ("activities_besides_study", "Чем ты занимаешься помимо учёбы регулярно?"),
        (
            "top_achievements",
            "Назови до 3–5 достижений / результатов, которыми ты действительно гордишься",
        ),
        (
            "failure_situation",
            "Опиши ситуацию, где у тебя не получилось, хотя ты старался(лась)",
        ),
        (
            "strong_qualities",
            "Какие свои качества ты считаешь сильными — и как они могут быть полезны другим участникам группы?",
        ),
        (
            "qualities_to_change",
            "Какие качества или привычки ты хотел(а) бы изменить в себе?",
        ),
    ]

    # Check if all fields are empty
    has_any_field = any(
        getattr(lead, field_name, None) for field_name, _ in fields
    ) if lead else False

    # If all fields are empty, don't generate document
    if not has_any_field:
        return None

    # Process each field
    for field_name, question_text in fields:
        # Get field value from lead
        field_value = getattr(lead, field_name, None) if lead else None

        # Skip if field is empty or None
        if not field_value:
            continue

        # Add question
        story.append(Paragraph(question_text, question_style))

        # Add answer (escape HTML special characters and preserve newlines)
        answer_text = _escape_text(field_value, preserve_newlines=True)
        story.append(Paragraph(answer_text, answer_style))
        story.append(Spacer(1, 0.1 * inch))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
