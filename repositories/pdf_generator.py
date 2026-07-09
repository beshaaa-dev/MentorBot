from crm.crm_service import Lead
from logger import setup_logger
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from functools import lru_cache
import os
import platform

logger = setup_logger(__name__)


def _escape_text(value: str, preserve_newlines: bool = False) -> str:
    """Экранирование HTML специальных символов в тексте.
    
    Args:
        value: Текст для экранирования
        preserve_newlines: Если True, преобразовать переносы строк в <br/> теги для рендеринга в PDF
    """
    escaped = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if preserve_newlines:
        # Convert double newlines (paragraphs) and single newlines to <br/> tags
        escaped = escaped.replace("\r\n", "\n").replace("\n", "<br/>")
    return escaped


def _font_candidates() -> list[tuple[str, str]]:
    """Candidate (regular, bold) TTF path pairs, most preferred first."""
    candidates: list[tuple[str, str]] = []

    # Packaged with the app, so it is present on every machine and container.
    try:
        import font_roboto
    except ImportError:
        logger.warning("font-roboto is not installed, falling back to system fonts")
    else:
        candidates.append((font_roboto.Roboto, font_roboto.RobotoBold))

    system = platform.system()
    if system == "Darwin":
        candidates.append(
            (
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            )
        )
        candidates.append(("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"))
    elif system == "Linux":
        candidates.append(
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            )
        )
        candidates.append(
            (
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            )
        )
    elif system == "Windows":
        candidates.append(("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"))

    return candidates


@lru_cache(maxsize=1)
def _register_cyrillic_font() -> tuple[str, str]:
    """Register a Cyrillic-capable TTF pair and return its (regular, bold) names.

    reportlab's built-in Helvetica is WinAnsi-encoded. Rather than raising on a
    Cyrillic character it silently swaps in ZapfDingbats, whose 'n' glyph is a
    filled black square, so every letter comes out as an unreadable box. Helvetica
    is therefore a last resort and its use is logged as an error.
    """
    for regular_path, bold_path in _font_candidates():
        if not os.path.exists(regular_path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("Cyrillic", regular_path))
        except Exception as e:
            logger.warning(f"Failed to register font {regular_path}: {e}")
            continue

        if not os.path.exists(bold_path):
            logger.warning(f"No bold companion for {regular_path}, reusing regular")
            return "Cyrillic", "Cyrillic"

        try:
            pdfmetrics.registerFont(TTFont("CyrillicBold", bold_path))
        except Exception as e:
            logger.warning(f"Failed to register bold font {bold_path}: {e}")
            return "Cyrillic", "Cyrillic"

        return "Cyrillic", "CyrillicBold"

    logger.error(
        "No Cyrillic-capable font found. PDF text will render as black squares. "
        "Reinstall dependencies so that font-roboto is available."
    )
    return "Helvetica", "Helvetica-Bold"


def create_anketa_pdf(lead: Lead | None) -> bytes | None:
    """
    Создать PDF анкету из данных лида.

    Args:
        lead: Lead объект с данными анкеты, или None для пустого PDF

    Returns:
        PDF файл в виде байтов, или None если все поля пустые
    """
    buffer = BytesIO()

    # Create document
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Анкета")

    # If no data provided, return empty PDF
    if not lead:
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

    # Define custom fields with their question labels
    fields = [
        ("fio", "ФИО"),
        ("age", "Возраст"),
        ("city", "Город проживания"),
        ("current_study", "Где ты сейчас учишься?"),
        (
            "why_this_mentor",
            "Почему вы хотите в группу именно к этому наставнику?",
        ),
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

__all__ = ["create_anketa_pdf"]
