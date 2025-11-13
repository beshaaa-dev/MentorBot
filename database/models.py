from enum import Enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum as SQLEnum
from database.db_helper import Base


class UserRole(str, Enum):
    MENTOR = "mentor"
    STUDENT = "student"


class TaskStatus(str, Enum):
    UNCHECKED = "unchecked"
    APPROVED = "approved"
    DISAPPROVED = "disapproved"
    CHECK_LATER = "check_later"


class User(Base):
    __tablename__ = "users"

    # Уникальный id
    id = Column(Integer, primary_key=True, nullable=False)
    # Telegram id
    tg_id = Column(Integer, nullable=True, unique=True)
    # Ник в Telegram. Он не всегда существует
    tg_nickname = Column(String, nullable=True)
    # Роль пользователя в AmoCRM
    role = Column(SQLEnum(UserRole), nullable=False)
    # Имя пользователя
    first_name = Column(String, nullable=True)
    # Фамилия пользователя
    last_name = Column(String, nullable=True)
    # ID контакта в AmoCRM
    crm_id = Column[str](String, nullable=True)
    # Дата создания пользователя
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Дата первого получения данных о пользователе в AmoCRM
    registered_at = Column(DateTime, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    # Уникальный id
    id = Column(Integer, primary_key=True, nullable=False)
    # ID студента
    student_id = Column(Integer, nullable=False)
    # ID ментора
    mentor_id = Column(Integer, nullable=False)
    # ID лида в AmoCRM
    crm_id = Column(String, nullable=False)
    # ID видео в Telegram
    file_id = Column(String, nullable=False)
    # Статус задачи
    status = Column(SQLEnum(TaskStatus), nullable=False)
    # Дата создания задачи
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Дата обновления задачи
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
