"""
One-off migration for the webhook-driven task flow.

Rebuilds `tasks`: adds first_task/second_task/third_task/deadline/edit_reason and
makes mentor_id nullable (SQLite cannot drop NOT NULL via ALTER). `task_answers`
is created separately by init_db()/create_all.

Usage:
    python scripts/migrate_task_flow.py [path/to/mentor_bot.db]
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mentor_bot.db"
)

NEW_TASKS_DDL = """
CREATE TABLE tasks_new (
    id INTEGER NOT NULL PRIMARY KEY,
    student_id INTEGER NOT NULL,
    mentor_id INTEGER,
    lead_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    first_task VARCHAR,
    second_task VARCHAR,
    third_task VARCHAR,
    deadline DATETIME,
    edit_reason VARCHAR,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def migrate(db_path: str) -> None:
    if not os.path.exists(db_path):
        raise SystemExit(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "first_task" in columns:
            print("tasks already migrated — nothing to do")
            return

        # Бэкап только когда действительно есть что мигрировать, иначе повторные
        # запуски засоряли бы каталог копиями базы.
        backup_path = f"{db_path}.backup_{datetime.now():%Y%m%d_%H%M%S}_task_flow"
        shutil.copy2(db_path, backup_path)
        print(f"Backup written to {backup_path}")

        before = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        conn.execute("BEGIN")
        conn.execute(NEW_TASKS_DDL)
        conn.execute(
            """
            INSERT INTO tasks_new (
                id, student_id, mentor_id, lead_id, status,
                first_task, second_task, third_task, deadline, edit_reason,
                created_at, updated_at
            )
            SELECT id, student_id, mentor_id, lead_id, status,
                   NULL, NULL, NULL, NULL, NULL,
                   created_at, updated_at
            FROM tasks
            """
        )

        after = conn.execute("SELECT COUNT(*) FROM tasks_new").fetchone()[0]
        if before != after:
            conn.execute("ROLLBACK")
            raise SystemExit(f"Row count mismatch: {before} -> {after}. Rolled back.")

        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
        conn.commit()
        print(f"Rebuilt `tasks` with {after} rows; mentor_id is now nullable")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB)
