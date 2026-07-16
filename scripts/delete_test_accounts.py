"""
Fully erase test accounts from the database.

Resolves the given accounts (by Telegram id and/or nickname) to their User rows
and deletes every row that references them across all tables — tasks and their
answers/messages, homeworks and their answers, test results, mentor
notifications, chat memberships, and survey responses/answers — then the users
themselves.

A user is referenced two ways, so both are followed:
  • by users.id  → tasks, homeworks, test_results, mentor_*_notifications
  • by tg_id     → chat_members, survey_responses

Dry-run by default. Nothing is deleted until you pass --apply, which first
writes a timestamped backup of the SQLite file.

Usage:
    # preview
    python scripts/delete_test_accounts.py --tg-id 111 222 --nickname test_user
    # execute
    python scripts/delete_test_accounts.py --tg-id 111 222 --nickname test_user --apply
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

# Allow running as `python scripts/delete_test_accounts.py` from the repo root:
# put the project root on sys.path so `config` / `database` resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, or_

import config
from database.db_helper import get_db
from database.models import (
    Broadcast,
    ChatMember,
    Homework,
    HomeworkAnswer,
    MentorHomeworkNotification,
    MentorTaskNotification,
    SurveyAnswer,
    SurveyResponse,
    Task,
    TaskAnswer,
    TaskMessage,
    TestResult,
    User,
)


def _resolve_users(session, tg_ids: list[int], nicknames: list[str]) -> list[User]:
    """Find the User rows matching any of the given tg_ids or nicknames (case-insensitive)."""
    conditions = []
    if tg_ids:
        conditions.append(User.tg_id.in_(tg_ids))
    if nicknames:
        normalized = [n.lstrip("@").strip().lower() for n in nicknames]
        conditions.append(func.lower(User.tg_nickname).in_(normalized))
    if not conditions:
        return []
    return session.query(User).filter(or_(*conditions)).all()


def _build_specs(session, user_ids: list[int], tg_ids: list[int]):
    """
    Return an ordered list of (label, query) to delete — children before parents.

    Id lists are materialized up front so deletions never invalidate a later
    filter (e.g. deleting tasks before we've selected their answers).
    """
    task_ids = [
        t.id
        for t in session.query(Task.id).filter(
            or_(Task.student_id.in_(user_ids), Task.mentor_id.in_(user_ids))
        )
    ]
    homework_ids = [
        h.id
        for h in session.query(Homework.id).filter(
            or_(Homework.student_id.in_(user_ids), Homework.mentor_id.in_(user_ids))
        )
    ]
    response_ids = [
        r.id
        for r in session.query(SurveyResponse.id).filter(
            SurveyResponse.user_tg_id.in_(tg_ids)
        )
    ] if tg_ids else []

    return [
        ("task_answers", session.query(TaskAnswer).filter(TaskAnswer.task_id.in_(task_ids))),
        ("task_messages", session.query(TaskMessage).filter(TaskMessage.task_id.in_(task_ids))),
        ("tasks", session.query(Task).filter(Task.id.in_(task_ids))),
        ("homework_answers", session.query(HomeworkAnswer).filter(HomeworkAnswer.homework_id.in_(homework_ids))),
        ("homeworks", session.query(Homework).filter(Homework.id.in_(homework_ids))),
        ("test_results", session.query(TestResult).filter(TestResult.user_id.in_(user_ids))),
        ("mentor_homework_notifications", session.query(MentorHomeworkNotification).filter(MentorHomeworkNotification.mentor_id.in_(user_ids))),
        ("mentor_task_notifications", session.query(MentorTaskNotification).filter(MentorTaskNotification.mentor_id.in_(user_ids))),
        ("survey_answers", session.query(SurveyAnswer).filter(SurveyAnswer.response_id.in_(response_ids))),
        ("survey_responses", session.query(SurveyResponse).filter(SurveyResponse.id.in_(response_ids))),
        ("chat_members", session.query(ChatMember).filter(ChatMember.user_tg_id.in_(tg_ids)) if tg_ids else session.query(ChatMember).filter(False)),
        ("users", session.query(User).filter(User.id.in_(user_ids))),
    ]


def _backup_sqlite() -> str | None:
    """Copy the SQLite DB file before a destructive run. Returns the backup path, or None."""
    url = config.DATABASE_URL
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        print(f"WARNING: DATABASE_URL is not SQLite ({url!r}); skipping file backup.")
        return None
    db_path = url[len(prefix):]
    backup_path = f"{db_path}.backup_{datetime.now():%Y%m%d_%H%M%S}_delete_test"
    shutil.copy2(db_path, backup_path)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fully erase test accounts from the database.")
    parser.add_argument("--tg-id", type=int, nargs="*", default=[], help="Telegram ids of test accounts")
    parser.add_argument("--nickname", type=str, nargs="*", default=[], help="Telegram nicknames (with or without @)")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default is a dry run)")
    args = parser.parse_args()

    if not args.tg_id and not args.nickname:
        parser.error("give at least one --tg-id or --nickname")

    with get_db() as session:
        users = _resolve_users(session, args.tg_id, args.nickname)
        if not users:
            print("No matching users found. Nothing to do.")
            return

        user_ids = [u.id for u in users]
        tg_ids = [u.tg_id for u in users if u.tg_id is not None]

        print("Matched users:")
        for u in users:
            print(f"  id={u.id}  tg_id={u.tg_id}  @{u.tg_nickname}  role={u.role.value}  {u.first_name or ''} {u.last_name or ''}".rstrip())

        specs = _build_specs(session, user_ids, tg_ids)

        print("\nRows to delete:")
        total = 0
        for label, query in specs:
            n = query.count()
            total += n
            print(f"  {label:<32} {n}")
        print(f"  {'TOTAL':<32} {total}")

        # Broadcasts are shared data (may target real chats / carry real users'
        # responses), so we never auto-delete them — only warn.
        if tg_ids:
            bcast = session.query(Broadcast).filter(Broadcast.curator_tg_id.in_(tg_ids)).count()
            if bcast:
                print(f"\nNOTE: {bcast} broadcast(s) were created by these accounts (curator_tg_id). "
                      "Not deleted — review manually; deleting a broadcast also drops real users' survey responses.")

        if not args.apply:
            print("\nDRY RUN — nothing deleted. Re-run with --apply to execute.")
            return

        backup_path = _backup_sqlite()
        if backup_path:
            print(f"\nBackup written to {backup_path}")

        for label, query in specs:
            deleted = query.delete(synchronize_session=False)
            print(f"  deleted {deleted:>5} from {label}")
        session.commit()
        print("\nDone. Test accounts fully erased.")


if __name__ == "__main__":
    sys.exit(main())
