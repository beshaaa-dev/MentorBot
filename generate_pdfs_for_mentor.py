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
from database.task_service import get_decided_tasks, get_tasks_by_status
from database.models import TaskStatus
from database.user_service import find_by_tg_nickname, get_by_id
from repositories.user_repository import get_student_anketa_pdf


def _get_all_mentor_tasks(mentor_id: int):
    all_tasks = []
    for status in TaskStatus:
        all_tasks.extend(get_tasks_by_status(mentor_id, status))
    return all_tasks


def _latest_task_per_student(tasks) -> dict[int, object]:
    """Return a mapping of student_id → most recently updated task."""
    latest: dict[int, object] = {}
    for task in tasks:
        existing = latest.get(task.student_id)
        if existing is None or task.updated_at > existing.updated_at:
            latest[task.student_id] = task
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

    print(f"Initializing CRM...")
    init_amo_crm_integration()

    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        print(f"Mentor with nickname '@{nickname}' not found in database.", file=sys.stderr)
        sys.exit(1)

    print(f"Found mentor: id={mentor.id}, name={mentor.first_name} {mentor.last_name}")

    tasks = _get_all_mentor_tasks(mentor.id)
    if not tasks:
        print("No tasks found for this mentor.")
        sys.exit(0)

    student_tasks = _latest_task_per_student(tasks)
    print(f"Found {len(student_tasks)} unique student(s).")

    os.makedirs(output_dir, exist_ok=True)

    generated = 0
    skipped = 0

    for student_id, task in student_tasks.items():
        student = get_by_id(student_id)
        student_label = (
            " ".join(filter(None, [student.first_name, student.last_name])).strip()
            if student
            else f"student_{student_id}"
        ) or f"student_{student_id}"

        print(f"  Generating PDF for {student_label} (student_id={student_id}, lead_id={task.lead_id})...")

        try:
            filename, pdf_bytes, _ = get_student_anketa_pdf(student_id, task.lead_id)
        except Exception as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            skipped += 1
            continue

        if not pdf_bytes:
            print(f"    Skipped — anketa is empty for {student_label}.")
            skipped += 1
            continue

        output_path = os.path.join(output_dir, filename)
        # Avoid overwriting if two students share the same name
        if os.path.exists(output_path):
            base, ext = os.path.splitext(filename)
            output_path = os.path.join(output_dir, f"{base}_{student_id}{ext}")

        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

        print(f"    Saved → {output_path}")
        generated += 1

    print(f"\nDone. Generated: {generated}, skipped: {skipped}.")


if __name__ == "__main__":
    main()
