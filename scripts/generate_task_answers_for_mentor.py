"""
CLI script: find a mentor by Telegram nickname, then download every task answer
submitted by their students.

Usage:
    python generate_task_answers_for_mentor.py <tg_nickname> [--output-dir <dir>] [--staging-chat <id>]

Output layout:
    <output_dir>/
      <Student Name>/
        task_1.txt      ← text answer
        task_2.mp4      ← media answer (extension inferred from Telegram file_path)
        task_3.oga
      ...

Text messages are forwarded to --staging-chat (default 394179398) to retrieve
their content (Bot API has no getMessages endpoint), then the forwarded message
is immediately deleted.

Media files larger than 20 MB cannot be downloaded via Bot API and are skipped
with a warning.
"""

import argparse
import asyncio
import os
import re
import sys

# Allow running from scripts/ or from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

import telegram
import telegram.error

from database.task_service import get_tasks_by_status
from database.models import TaskStatus
from database.user_service import find_by_tg_nickname, get_by_id
from handlers.utils import parse_message_reference
from logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_STAGING_CHAT = 394179398


# ---------------------------------------------------------------------------
# DB helpers (mirrors generate_pdfs_for_mentor.py)
# ---------------------------------------------------------------------------

def _get_all_mentor_tasks(mentor_id: int):
    all_tasks = []
    for status in TaskStatus:
        logger.debug(f"[tasks] Querying status={status.value} for mentor_id={mentor_id}")
        try:
            tasks = get_tasks_by_status(mentor_id, status)
            logger.info(f"[tasks] status={status.value}: found {len(tasks)} task(s)")
            all_tasks.extend(tasks)
        except Exception as exc:
            logger.error(f"[tasks] Failed to query status={status.value}: {exc}", exc_info=True)
    logger.info(f"[tasks] Total tasks fetched for mentor_id={mentor_id}: {len(all_tasks)}")
    return all_tasks


def _latest_task_per_student(tasks) -> dict[int, object]:
    latest: dict[int, object] = {}
    for task in tasks:
        existing = latest.get(task.student_id)
        if existing is None or task.updated_at > existing.updated_at:
            latest[task.student_id] = task
    logger.info(f"[dedup] Deduplicated to {len(latest)} unique student(s)")
    return latest


def _sanitize_folder_name(name: str) -> str:
    sanitized = re.sub(r"\s+", " ", name.strip())
    sanitized = re.sub(r"[^\w\s\-]+", "", sanitized, flags=re.UNICODE).strip()
    return sanitized


def _task_filename(task_number: int, suffix: str, ext: str) -> str:
    base = f"task_{task_number}"
    if suffix:
        base = f"{base}_{suffix}"
    return f"{base}{ext}"


# ---------------------------------------------------------------------------
# Core async processing
# ---------------------------------------------------------------------------

async def _download_media(bot: telegram.Bot, file_id: str, dest_path: str) -> bool:
    """Download a Telegram media file to dest_path. Returns True on success."""
    try:
        tg_file = await bot.get_file(file_id)
    except telegram.error.TelegramError as exc:
        logger.warning(f"[media] get_file failed for file_id={file_id[:20]}...: {exc}")
        return False

    ext = os.path.splitext(tg_file.file_path)[1]
    if not ext:
        ext = ".bin"

    # Insert extension before any suffix in dest_path if caller passed no ext
    if not os.path.splitext(dest_path)[1]:
        dest_path = dest_path + ext
    else:
        # Replace placeholder extension
        root, _ = os.path.splitext(dest_path)
        dest_path = root + ext

    try:
        data = await tg_file.download_as_bytearray()
    except telegram.error.TelegramError as exc:
        logger.warning(f"[media] download failed for file_id={file_id[:20]}...: {exc}")
        return False

    with open(dest_path, "wb") as f:
        f.write(data)
    logger.info(f"[media] Saved {len(data)} bytes → '{dest_path}'")
    return True


async def _fetch_text(bot: telegram.Bot, chat_id: int, message_id: int, staging_chat: int) -> str | None:
    """Forward a message to staging_chat, extract text, delete it. Returns text or None."""
    try:
        fwd = await bot.forward_message(
            chat_id=staging_chat,
            from_chat_id=chat_id,
            message_id=message_id,
        )
    except telegram.error.TelegramError as exc:
        logger.warning(f"[text] Could not forward message chat_id={chat_id} msg_id={message_id}: {exc}")
        return None

    text = fwd.text or fwd.caption or ""

    try:
        await bot.delete_message(chat_id=staging_chat, message_id=fwd.message_id)
    except telegram.error.TelegramError as exc:
        logger.warning(f"[text] Could not delete forwarded message {fwd.message_id}: {exc}")

    return text or None


async def _process_student(
    bot: telegram.Bot,
    student_id: int,
    task,
    student_dir: str,
    staging_chat: int,
) -> tuple[int, int]:
    """Process one student's task. Returns (saved, skipped)."""
    os.makedirs(student_dir, exist_ok=True)

    messages = sorted(task.task_messages, key=lambda m: m.task_number)
    task_number_counts: dict[int, int] = {}

    saved = skipped = 0

    for tm in messages:
        n = tm.task_number
        count = task_number_counts.get(n, 0)
        task_number_counts[n] = count + 1
        suffix = str(tm.id) if count > 0 else ""

        ref = parse_message_reference(tm.file_id)
        if ref:
            # Text message
            orig_chat_id, orig_msg_id = ref
            logger.info(
                f"[text] task_message_id={tm.id} task_number={n} "
                f"chat_id={orig_chat_id} message_id={orig_msg_id}"
            )
            text = await _fetch_text(bot, orig_chat_id, orig_msg_id, staging_chat)
            if text is None:
                logger.warning(f"[text] No text retrieved for task_message_id={tm.id} — skipping")
                skipped += 1
                continue

            filename = _task_filename(n, suffix, ".txt")
            dest = os.path.join(student_dir, filename)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info(f"[text] Saved {len(text)} chars → '{dest}'")
            print(f"      task {n} (text) → {dest}")
            saved += 1
        else:
            # Media file
            logger.info(f"[media] task_message_id={tm.id} task_number={n} file_id={tm.file_id[:20]}...")
            # Use placeholder path; _download_media will append the real extension
            dest = os.path.join(student_dir, _task_filename(n, suffix, ""))
            ok = await _download_media(bot, tm.file_id, dest)
            if ok:
                print(f"      task {n} (media) → {dest}.*")
                saved += 1
            else:
                print(f"      task {n} (media) SKIPPED — could not download")
                skipped += 1

    return saved, skipped


async def _run(nickname: str, output_dir: str, staging_chat: int) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in environment.", file=sys.stderr)
        sys.exit(1)

    logger.info(f"[db] Looking up mentor by nickname='{nickname}'")
    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        print(f"Mentor '@{nickname}' not found in database.", file=sys.stderr)
        sys.exit(1)

    logger.info(
        f"[db] Mentor found: id={mentor.id} name='{mentor.first_name} {mentor.last_name}'"
    )
    print(f"Found mentor: id={mentor.id}, name={mentor.first_name} {mentor.last_name}")

    tasks = _get_all_mentor_tasks(mentor.id)
    if not tasks:
        print("No tasks found for this mentor.")
        sys.exit(0)

    student_tasks = _latest_task_per_student(tasks)
    print(f"Found {len(student_tasks)} unique student(s).")

    os.makedirs(output_dir, exist_ok=True)

    total_saved = total_skipped = 0

    async with telegram.Bot(token=token) as bot:
        for student_id, task in student_tasks.items():
            student = get_by_id(student_id)
            student_label = (
                " ".join(filter(None, [student.first_name, student.last_name])).strip()
                if student
                else ""
            ) or f"student_{student_id}"

            folder_name = _sanitize_folder_name(student_label) or f"student_{student_id}"
            student_dir = os.path.join(output_dir, folder_name)

            logger.info(
                f"[student] id={student_id} label='{student_label}' "
                f"task_id={task.id} messages={len(task.task_messages)}"
            )
            print(
                f"  {student_label} (student_id={student_id}, task_id={task.id}, "
                f"{len(task.task_messages)} message(s)):"
            )

            if not task.task_messages:
                print("    No task messages — skipped.")
                continue

            saved, skipped = await _process_student(bot, student_id, task, student_dir, staging_chat)
            total_saved += saved
            total_skipped += skipped

    logger.info(f"[done] saved={total_saved} skipped={total_skipped}")
    print(f"\nDone. Saved: {total_saved}, skipped: {total_skipped}.")


def main():
    parser = argparse.ArgumentParser(
        description="Download task answers for all students of a given mentor."
    )
    parser.add_argument("tg_nickname", help="Mentor's Telegram nickname (with or without @)")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Root directory to save answers (default: task_answers_<nickname>)",
    )
    parser.add_argument(
        "--staging-chat",
        type=int,
        default=_DEFAULT_STAGING_CHAT,
        help=(
            "Telegram chat ID used to temporarily forward text messages "
            f"(default: {_DEFAULT_STAGING_CHAT})"
        ),
    )
    args = parser.parse_args()

    nickname = args.tg_nickname.lstrip("@")
    output_dir = args.output_dir or f"task_answers_{nickname}"

    logger.info(
        f"Starting task-answer export for mentor '@{nickname}', "
        f"output_dir='{output_dir}', staging_chat={args.staging_chat}"
    )

    asyncio.run(_run(nickname, output_dir, args.staging_chat))


if __name__ == "__main__":
    main()
