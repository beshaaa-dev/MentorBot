"""
CLI script: find a mentor by Telegram nickname, then forward every task answer
to a target Telegram chat, grouped by student with a header message.

Usage:
    python scripts/generate_task_answers_for_mentor.py <tg_nickname> [--target-chat <id>]

Files are re-sent by file_id (no local download, no size limit).
"""

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

import telegram
import telegram.error

from database.task_service import get_tasks_by_status
from database.models import TaskStatus
from database.user_service import find_by_tg_nickname, get_by_id
from handlers.utils import parse_message_reference, try_send_media_types
from logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_TARGET_CHAT = 394179398


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_all_mentor_tasks(mentor_id: int):
    all_tasks = []
    for status in TaskStatus:
        try:
            tasks = get_tasks_by_status(mentor_id, status)
            logger.info(f"[tasks] status={status.value}: {len(tasks)} task(s)")
            all_tasks.extend(tasks)
        except Exception as exc:
            logger.error(f"[tasks] Failed status={status.value}: {exc}", exc_info=True)
    return all_tasks


def _latest_task_per_student(tasks) -> dict[int, object]:
    latest: dict[int, object] = {}
    for task in tasks:
        existing = latest.get(task.student_id)
        if existing is None or task.updated_at > existing.updated_at:
            latest[task.student_id] = task
    return latest


# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------

async def _send_with_retry(coro_fn, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            return await coro_fn()
        except telegram.error.RetryAfter as exc:
            if attempt < retries:
                logger.warning(f"[flood] RetryAfter {exc.retry_after}s — waiting")
                await asyncio.sleep(exc.retry_after + 1)
            else:
                raise
        except telegram.error.TelegramError as exc:
            logger.warning(f"[send] TelegramError: {exc}")
            return None


async def _forward_student(bot: telegram.Bot, task, student_label: str, target_chat: int) -> tuple[int, int]:
    messages = sorted(task.task_messages, key=lambda m: m.task_number)
    sent = failed = 0

    header = (
        f"Student: {student_label}\n"
        f"Task ID: {task.id} | Status: {task.status.value}\n"
        f"Answers: {len(messages)}"
    )
    await _send_with_retry(lambda: bot.send_message(target_chat, header))

    for tm in messages:
        label = f"Task {tm.task_number}:"
        await _send_with_retry(lambda l=label: bot.send_message(target_chat, l))

        ref = parse_message_reference(tm.file_id)
        if ref:
            from_chat_id, message_id = ref
            result = await _send_with_retry(
                lambda c=from_chat_id, m=message_id: bot.copy_message(
                    chat_id=target_chat, from_chat_id=c, message_id=m
                )
            )
        else:
            result = await _send_with_retry(
                lambda fid=tm.file_id: try_send_media_types(bot, target_chat, fid)
            )

        if result:
            sent += 1
        else:
            failed += 1
            await _send_with_retry(lambda: bot.send_message(target_chat, "⚠️ Failed to forward this answer."))

    return sent, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _run(nickname: str, target_chat: int) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)

    mentor = find_by_tg_nickname(nickname)
    if not mentor:
        print(f"Mentor '@{nickname}' not found in database.", file=sys.stderr)
        sys.exit(1)

    print(f"Found mentor: id={mentor.id}, name={mentor.first_name} {mentor.last_name}")

    tasks = _get_all_mentor_tasks(mentor.id)
    if not tasks:
        print("No tasks found for this mentor.")
        sys.exit(0)

    student_tasks = _latest_task_per_student(tasks)
    print(f"Found {len(student_tasks)} unique student(s). Sending to chat {target_chat}...")

    total_sent = total_failed = 0

    async with telegram.Bot(token=token) as bot:
        await _send_with_retry(
            lambda: bot.send_message(
                target_chat,
                f"=== Task answers for @{nickname} ({len(student_tasks)} students) ==="
            )
        )

        for student_id, task in student_tasks.items():
            student = get_by_id(student_id)
            student_label = (
                " ".join(filter(None, [student.first_name, student.last_name])).strip()
                if student else ""
            ) or f"student_{student_id}"

            print(f"  {student_label} ({len(task.task_messages)} message(s))...")
            sent, failed = await _forward_student(bot, task, student_label, target_chat)
            total_sent += sent
            total_failed += failed

        await _send_with_retry(
            lambda: bot.send_message(
                target_chat,
                f"=== Done. Sent: {total_sent}, failed: {total_failed} ==="
            )
        )

    print(f"\nDone. Sent: {total_sent}, failed: {total_failed}.")


def main():
    parser = argparse.ArgumentParser(
        description="Forward task answers for all students of a mentor to a Telegram chat."
    )
    parser.add_argument("tg_nickname", help="Mentor's Telegram nickname (with or without @)")
    parser.add_argument(
        "--target-chat",
        type=int,
        default=_DEFAULT_TARGET_CHAT,
        help=f"Telegram chat ID to send answers to (default: {_DEFAULT_TARGET_CHAT})",
    )
    args = parser.parse_args()

    nickname = args.tg_nickname.lstrip("@")
    asyncio.run(_run(nickname, args.target_chat))


if __name__ == "__main__":
    main()
