"""
CLI script: find a mentor by Telegram nickname, then generate an anketa PDF
for every student who has a task assigned to that mentor.

Usage:
    python generate_pdfs_for_mentor.py <tg_nickname> [--output-dir <dir>]

The nickname may be supplied with or without a leading '@'.
PDFs are written to <output_dir>/ (default: pdfs_<nickname>/).
"""

import argparse
import os
import sys

from crm.crm_service import init_amo_crm_integration
from thread_safe_token_manager import ThreadSafeTokenManager
from database.task_service import get_tasks_by_status
from database.models import TaskStatus
from database.user_service import find_by_tg_nickname, get_by_id
from repositories.user_repository import get_student_anketa_pdf
from logger import setup_logger

logger = setup_logger(__name__)


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

    logger.info(f"Starting PDF generation for mentor '@{nickname}', output_dir='{output_dir}'")
    print(f"Initializing CRM...")

    try:
        init_amo_crm_integration()
        logger.info("[crm] CRM initialized successfully")
    except Exception as exc:
        logger.error(f"[crm] CRM initialization failed: {exc}", exc_info=True)
        print(f"ERROR: CRM initialization failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Force refreshing CRM token...")
    try:
        token_manager = ThreadSafeTokenManager.get_instance()
        token_manager._force_refresh_token()
        logger.info("[crm] Token force-refreshed successfully")
        print("Token refreshed.")
    except Exception as exc:
        logger.error(f"[crm] Token force-refresh failed: {exc}", exc_info=True)
        print(f"ERROR: Token refresh failed: {exc}", file=sys.stderr)
        sys.exit(1)

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

        try:
            filename, pdf_bytes, full_name = get_student_anketa_pdf(student_id, task.lead_id)
            logger.info(
                f"[pdf] get_student_anketa_pdf returned: filename='{filename}' "
                f"pdf_size={len(pdf_bytes) if pdf_bytes else None} crm_name='{full_name}'"
            )
        except Exception as exc:
            logger.error(
                f"[pdf] Exception for student_id={student_id} lead_id={task.lead_id}: {exc}",
                exc_info=True,
            )
            print(f"    ERROR: {exc}", file=sys.stderr)
            skipped += 1
            continue

        if not pdf_bytes:
            logger.warning(
                f"[pdf] Empty anketa for student_id={student_id} lead_id={task.lead_id} — skipping"
            )
            print(f"    Skipped — anketa is empty for {student_label}.")
            skipped += 1
            continue

        output_path = os.path.join(output_dir, filename)
        # Avoid overwriting if two students share the same name
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
