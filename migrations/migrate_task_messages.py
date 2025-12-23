"""
Migration script to migrate Task.file_id to TaskMessage model.

This script:
1. Creates the task_messages table
2. Migrates all existing Task.file_id values to TaskMessage records with task_number=1
3. Drops the file_id column from tasks table
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, inspect as sqlalchemy_inspect
from database.db_helper import engine, get_db
from database.models import Task, TaskMessage, Base
from logger import setup_logger

logger = setup_logger(__name__)


def migrate():
    """Execute the migration."""
    with get_db() as db:
        try:
            logger.info("Starting migration: Task.file_id -> TaskMessage")

            # Step 1: Create task_messages table
            logger.info("Step 1: Creating task_messages table...")
            Base.metadata.create_all(bind=engine, tables=[TaskMessage.__table__])
            logger.info("task_messages table created successfully")

            # Step 2: Check if file_id column exists in tasks table
            logger.info("Step 2: Checking if file_id column exists...")
            inspector = sqlalchemy_inspect(engine)
            columns = [col["name"] for col in inspector.get_columns("tasks")]

            if "file_id" not in columns:
                logger.warning(
                    "file_id column does not exist in tasks table. Migration may have already been run."
                )
                logger.info("Migration completed (nothing to migrate)")
                return

            # Step 3: Migrate existing file_id values to TaskMessage
            logger.info("Step 3: Migrating existing file_id values to TaskMessage...")

            # Use raw SQL to get tasks with file_id (since file_id is removed from model)
            result = db.execute(
                text(
                    "SELECT id, file_id FROM tasks WHERE file_id IS NOT NULL AND file_id != ''"
                )
            )
            tasks_data = result.fetchall()

            migrated_count = 0
            skipped_count = 0

            for task_id, file_id in tasks_data:
                # Check if TaskMessage already exists for this task
                existing_message = (
                    db.query(TaskMessage)
                    .filter(
                        TaskMessage.task_id == task_id, TaskMessage.task_number == 1
                    )
                    .first()
                )

                if not existing_message:
                    task_message = TaskMessage(
                        task_id=task_id, file_id=file_id, task_number=1
                    )
                    db.add(task_message)
                    migrated_count += 1
                else:
                    skipped_count += 1
                    logger.debug(
                        f"TaskMessage already exists for task {task_id}, skipping"
                    )

            db.commit()
            logger.info(f"Migrated {migrated_count} Task records to TaskMessage")

            # Step 4: Drop file_id column from tasks table
            logger.info("Step 4: Dropping file_id column from tasks table...")

            # SQLite doesn't support DROP COLUMN directly, need to use ALTER TABLE workaround
            if engine.dialect.name == "sqlite":
                logger.info("Using SQLite-compatible migration (recreate table)...")

                # Get all column names except file_id
                columns_to_keep = [col for col in columns if col != "file_id"]
                columns_str = ", ".join(columns_to_keep)

                # Create new table without file_id
                db.execute(
                    text(
                        f"""
                    CREATE TABLE tasks_new (
                        id INTEGER NOT NULL PRIMARY KEY,
                        student_id INTEGER NOT NULL,
                        mentor_id INTEGER NOT NULL,
                        lead_id VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                """
                    )
                )

                # Copy data
                db.execute(
                    text(
                        f"""
                    INSERT INTO tasks_new ({columns_str})
                    SELECT {columns_str}
                    FROM tasks
                """
                    )
                )

                # Drop old table
                db.execute(text("DROP TABLE tasks"))

                # Rename new table
                db.execute(text("ALTER TABLE tasks_new RENAME TO tasks"))

                logger.info("SQLite migration completed (table recreated)")
            else:
                # For other databases (PostgreSQL, MySQL, etc.)
                db.execute(text("ALTER TABLE tasks DROP COLUMN file_id"))
                logger.info("file_id column dropped successfully")

            db.commit()
            logger.info("Migration completed successfully!")

        except Exception as e:
            db.rollback()
            logger.error(f"Migration failed: {e}")
            raise


if __name__ == "__main__":
    migrate()
