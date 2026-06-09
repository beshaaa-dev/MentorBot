"""
CLI script: find a mentor by Telegram nickname, then generate an anketa PDF
for every student who has a task assigned to that mentor.

Usage:
    python generate_pdfs_for_mentor.py <tg_nickname> [--output-dir <dir>]

The nickname may be supplied with or without a leading '@'.
PDFs are written to <output_dir>/ (default: pdfs_<nickname>/).

Uses the same tokens/access_token.txt + tokens/refresh_token.txt files as the
main bot (auto-refreshes via OAuth when expired).
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime

# Allow running from scripts/ or from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Must run before any import that reads config.py (which calls os.getenv at import time)
load_dotenv(override=True)

import jwt
import requests

from database.task_service import get_tasks_by_status
from database.models import TaskStatus
from database.user_service import find_by_tg_nickname, get_by_id
from repositories.pdf_generator import create_anketa_pdf
from config import (
    DEFAULT_STUDENT_ANKETA_FILENAME,
    CRM_SUBDOMAIN,
    CRM_CLIENT_ID,
    CRM_CLIENT_SECRET,
    CRM_REDIRECT_URL,
)
from logger import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Token management — mirrors the framework's FileTokensStorage + TokenManager
# ---------------------------------------------------------------------------

_TOKENS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tokens")
_ACCESS_TOKEN_PATH = os.path.join(_TOKENS_DIR, "access_token.txt")
_REFRESH_TOKEN_PATH = os.path.join(_TOKENS_DIR, "refresh_token.txt")


def _read_token_file(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _save_tokens(access_token: str, refresh_token: str) -> None:
    os.makedirs(_TOKENS_DIR, exist_ok=True)
    with open(_ACCESS_TOKEN_PATH, "w") as f:
        f.write(access_token)
    with open(_REFRESH_TOKEN_PATH, "w") as f:
        f.write(refresh_token)
    logger.info("[token] Tokens saved to disk")


def _is_expired(token: str) -> bool:
    data = jwt.decode(token, options={"verify_signature": False})
    exp = datetime.utcfromtimestamp(data["exp"])
    return datetime.utcnow() >= exp


def _refresh_tokens() -> str:
    refresh_token = _read_token_file(_REFRESH_TOKEN_PATH)
    if not refresh_token:
        raise RuntimeError("No refresh token found in tokens/refresh_token.txt")

    logger.info("[token] Access token expired — refreshing via OAuth...")
    resp = requests.post(
        f"https://{CRM_SUBDOMAIN}.amocrm.ru/oauth2/access_token",
        json={
            "client_id": CRM_CLIENT_ID,
            "client_secret": CRM_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": CRM_REDIRECT_URL,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed: HTTP {resp.status_code} — {resp.text[:300]}")

    data = resp.json()
    access_token = data["access_token"]
    new_refresh = data["refresh_token"]
    _save_tokens(access_token, new_refresh)

    masked = f"{access_token[:8]}...{access_token[-4:]}"
    logger.info(f"[token] Refreshed: {masked} (len={len(access_token)})")
    return access_token


def get_access_token() -> str:
    token = _read_token_file(_ACCESS_TOKEN_PATH)
    if not token:
        raise RuntimeError("No access token found in tokens/access_token.txt")
    if _is_expired(token):
        token = _refresh_tokens()
    masked = f"{token[:8]}...{token[-4:]}"
    logger.debug(f"[token] Using: {masked} (len={len(token)})")
    return token


# ---------------------------------------------------------------------------
# AmoCRM direct API
# ---------------------------------------------------------------------------

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
    """Minimal lead representation consumed by create_anketa_pdf."""
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


def fetch_lead(lead_id: str) -> LeadData | None:
    """Fetch a lead from AmoCRM and return its anketa fields."""
    url = f"https://{CRM_SUBDOMAIN}.amocrm.ru/api/v4/leads/{lead_id}"
    logger.debug(f"[crm] GET {url}")
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {get_access_token()}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error(f"[crm] Network error fetching lead {lead_id}: {exc}")
        return None

    logger.debug(f"[crm] Response status={resp.status_code} for lead_id={lead_id}")

    if resp.status_code == 404:
        logger.warning(f"[crm] Lead {lead_id} not found (404)")
        return None
    if not resp.ok:
        logger.error(f"[crm] Failed to fetch lead {lead_id}: HTTP {resp.status_code} — {resp.text[:300]}")
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
                logger.debug(f"[crm]   field '{cf['field_name']}' → {attr} = {str(value)[:80]}")

    logger.info(f"[crm] Lead {lead_id}: populated {populated} anketa field(s)")
    return lead


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_all_mentor_tasks(mentor_id: int):
    all_tasks = []
    for status in TaskStatus:
        logger.debug(f"[tasks] Querying status={status.value} for mentor_id={mentor_id}")
        try:
            tasks = get_tasks_by_status(mentor_id, status)
            logger.info(f"[tasks] status={status.value}: found {len(tasks)} task(s)")
            for t in tasks:
                logger.debug(
                    f"[tasks]   task_id={t.id} student_id={t.student_id} "
                    f"lead_id={t.lead_id} updated_at={t.updated_at}"
                )
            all_tasks.extend(tasks)
        except Exception as exc:
            logger.error(f"[tasks] Failed to query status={status.value}: {exc}", exc_info=True)
    logger.info(f"[tasks] Total tasks fetched for mentor_id={mentor_id}: {len(all_tasks)}")
    return all_tasks


def _latest_task_per_student(tasks) -> dict[int, object]:
    """Return a mapping of student_id → most recently updated task."""
    latest: dict[int, object] = {}
    for task in tasks:
        existing = latest.get(task.student_id)
        if existing is None or task.updated_at > existing.updated_at:
            if existing is not None:
                logger.debug(
                    f"[dedup] student_id={task.student_id}: replacing task_id={existing.id} "
                    f"(updated {existing.updated_at}) with task_id={task.id} (updated {task.updated_at})"
                )
            latest[task.student_id] = task
    logger.info(f"[dedup] Deduplicated to {len(latest)} unique student(s)")
    return latest


def _build_pdf_filename(student_full_name: str) -> str:
    sanitized = re.sub(r"\s+", " ", student_full_name.strip())
    sanitized = re.sub(r"[^\w\s\-]+", "", sanitized, flags=re.UNICODE).strip()
    return f"Анкета {sanitized}.pdf" if sanitized else DEFAULT_STUDENT_ANKETA_FILENAME


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate anketa PDFs for all students of a given mentor."
    )
    parser.add_argument("tg_nickname", help="Mentor's Telegram nickname (with or without @)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save PDFs (default: pdfs_<nickname>)",
    )
    args = parser.parse_args()

    nickname = args.tg_nickname.lstrip("@")
    output_dir = args.output_dir or f"pdfs_{nickname}"

    if not CRM_SUBDOMAIN:
        print("ERROR: CRM_SUBDOMAIN is not set in environment.", file=sys.stderr)
        sys.exit(1)

    try:
        get_access_token()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    logger.info(
        f"Starting PDF generation for mentor '@{nickname}', output_dir='{output_dir}', "
        f"subdomain='{CRM_SUBDOMAIN}'"
    )

    logger.info(f"[db] Looking up mentor by nickname='{nickname}'")
    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        logger.error(f"[db] Mentor '@{nickname}' not found in database")
        print(f"Mentor with nickname '@{nickname}' not found in database.", file=sys.stderr)
        sys.exit(1)

    logger.info(
        f"[db] Mentor found: id={mentor.id} role={mentor.role} "
        f"name='{mentor.first_name} {mentor.last_name}' tg_id={mentor.tg_id}"
    )
    print(f"Found mentor: id={mentor.id}, name={mentor.first_name} {mentor.last_name}")

    tasks = _get_all_mentor_tasks(mentor.id)
    if not tasks:
        logger.warning(f"[tasks] No tasks found for mentor_id={mentor.id}")
        print("No tasks found for this mentor.")
        sys.exit(0)

    student_tasks = _latest_task_per_student(tasks)
    print(f"Found {len(student_tasks)} unique student(s).")

    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"[output] Directory ready: '{output_dir}'")

    generated = 0
    skipped = 0

    for student_id, task in student_tasks.items():
        student = get_by_id(student_id)
        if not student:
            logger.warning(f"[db] Student with id={student_id} not found in database")
        else:
            logger.debug(
                f"[db] Student id={student_id} name='{student.first_name} {student.last_name}' "
                f"tg_nickname={student.tg_nickname} tg_id={student.tg_id}"
            )

        student_label = (
            " ".join(filter(None, [student.first_name, student.last_name])).strip()
            if student
            else f"student_{student_id}"
        ) or f"student_{student_id}"

        logger.info(
            f"[pdf] Processing: student_id={student_id} label='{student_label}' "
            f"task_id={task.id} lead_id={task.lead_id} task_status={task.status}"
        )
        print(f"  Generating PDF for {student_label} (student_id={student_id}, lead_id={task.lead_id})...")

        lead = fetch_lead(task.lead_id)
        if lead is None:
            logger.warning(f"[pdf] Could not fetch lead {task.lead_id} — skipping")
            print(f"    Skipped — CRM lead not found for {student_label}.")
            skipped += 1
            continue

        try:
            pdf_bytes = create_anketa_pdf(lead)
        except Exception as exc:
            logger.error(
                f"[pdf] Exception generating PDF for student_id={student_id}: {exc}",
                exc_info=True,
            )
            print(f"    ERROR: {exc}", file=sys.stderr)
            skipped += 1
            continue

        if not pdf_bytes:
            logger.warning(f"[pdf] Empty anketa for student_id={student_id} lead_id={task.lead_id} — skipping")
            print(f"    Skipped — anketa is empty for {student_label}.")
            skipped += 1
            continue

        filename = _build_pdf_filename(student_label)
        output_path = os.path.join(output_dir, filename)
        if os.path.exists(output_path):
            base, ext = os.path.splitext(filename)
            output_path = os.path.join(output_dir, f"{base}_{student_id}{ext}")
            logger.debug(f"[pdf] Name collision — writing to '{output_path}' instead")

        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

        logger.info(f"[pdf] Saved {len(pdf_bytes)} bytes → '{output_path}'")
        print(f"    Saved → {output_path}")
        generated += 1

    logger.info(f"[done] Generated={generated} skipped={skipped}")
    print(f"\nDone. Generated: {generated}, skipped: {skipped}.")


if __name__ == "__main__":
    main()
