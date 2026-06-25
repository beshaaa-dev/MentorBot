import requests
from dataclasses import dataclass

from config import CRM_SUBDOMAIN
from database.models import TaskStatus
from database.task_service import get_tasks_by_status
from database.user_service import get_by_id
from logger import setup_logger
from repositories.pdf_generator import create_anketa_pdf

logger = setup_logger(__name__)

_FIELD_NAME_TO_ATTR: dict[str, str] = {
    "ФИО": "fio",
    "Возраст": "age",
    "Город проживания": "city",
    "Где ты сейчас учишься?": "current_study",
    "Почему вы хотите в группу именно к этому наставнику?": "why_this_mentor",
    "Что для тебя сейчас важнее всего из этого?": "most_important_now",
    "Если смотреть на ближайшие 2–3 года, в каком направлении ты хочешь двигаться?": "direction_2_3_years",
    "Когда у тебя одновременно несколько задач и дедлайнов, что обычно происходит?": "multiple_tasks_behavior",
    "Чем ты занимаешься помимо учёбы регулярно?": "activities_besides_study",
    "Назови до 3–5 достижений / результатов, которыми ты действительно гордишься": "top_achievements",
    "Опиши ситуацию, где у тебя не получилось, хотя ты старался(лась)": "failure_situation",
    "Какие свои качества ты считаешь сильными — и как они могут быть полезны другим участникам группы?": "strong_qualities",
    "Какие качества или привычки ты хотел(а) бы изменить в себе?": "qualities_to_change",
}


@dataclass
class LeadData:
    fio: str | None = None
    age: str | None = None
    city: str | None = None
    current_study: str | None = None
    why_this_mentor: str | None = None
    most_important_now: str | None = None
    direction_2_3_years: str | None = None
    multiple_tasks_behavior: str | None = None
    activities_besides_study: str | None = None
    top_achievements: str | None = None
    failure_situation: str | None = None
    strong_qualities: str | None = None
    qualities_to_change: str | None = None


def fetch_lead_anketa(lead_id: str, access_token: str) -> LeadData | None:
    url = f"https://{CRM_SUBDOMAIN}.amocrm.ru/api/v4/leads/{lead_id}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error(f"[crm] Network error fetching lead {lead_id}: {exc}")
        return None

    if resp.status_code == 404:
        logger.warning(f"[crm] Lead {lead_id} not found (404)")
        return None
    if not resp.ok:
        logger.error(
            f"[crm] Failed to fetch lead {lead_id}: HTTP {resp.status_code} — {resp.text[:300]}"
        )
        return None

    body = resp.json()
    lead = LeadData()
    populated = 0

    for cf in body.get("custom_fields_values") or []:
        attr = _FIELD_NAME_TO_ATTR.get(cf.get("field_name", ""))
        if attr:
            values = cf.get("values") or []
            value = values[0].get("value") if values else None
            if value:
                setattr(lead, attr, value)
                populated += 1

    logger.info(f"[crm] Lead {lead_id}: populated {populated} anketa field(s)")
    return lead


def _latest_task_per_student(tasks) -> dict[int, object]:
    latest: dict[int, object] = {}
    for task in tasks:
        existing = latest.get(task.student_id)
        if existing is None or task.updated_at > existing.updated_at:
            latest[task.student_id] = task
    return latest


def generate_mentor_pdfs(
    mentor_id: int, access_token: str
) -> tuple[list[tuple[str, bytes]], int]:
    """
    Generate anketa PDFs for all unique students assigned to mentor.

    Returns (results, total_students) where results is a list of
    (student_label, pdf_bytes) pairs and total_students is the number of
    unique students found across all task statuses.
    """
    all_tasks = []
    for status in TaskStatus:
        try:
            tasks = get_tasks_by_status(mentor_id, status)
            all_tasks.extend(tasks)
        except Exception as exc:
            logger.error(
                f"[tasks] Failed to query status={status.value}: {exc}", exc_info=True
            )

    student_tasks = _latest_task_per_student(all_tasks)
    total_students = len(student_tasks)
    results: list[tuple[str, bytes]] = []

    for student_id, task in student_tasks.items():
        student = get_by_id(student_id)
        student_label = (
            " ".join(filter(None, [student.first_name, student.last_name])).strip()
            if student
            else f"student_{student_id}"
        ) or f"student_{student_id}"

        lead = fetch_lead_anketa(task.lead_id, access_token)
        if lead is None:
            logger.warning(
                f"[pdf] Could not fetch lead {task.lead_id} for student_id={student_id} — skipping"
            )
            continue

        try:
            pdf_bytes = create_anketa_pdf(lead)
        except Exception as exc:
            logger.error(
                f"[pdf] Exception generating PDF for student_id={student_id}: {exc}",
                exc_info=True,
            )
            continue

        if not pdf_bytes:
            logger.warning(f"[pdf] Empty anketa for student_id={student_id} — skipping")
            continue

        results.append((student_label, pdf_bytes))

    logger.info(
        f"[pdf] mentor_id={mentor_id}: generated={len(results)} skipped={total_students - len(results)}"
    )
    return results, total_students
