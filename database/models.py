from enum import Enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum as SQLEnum, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from database.db_helper import Base


class UserRole(str, Enum):
    MENTOR = "mentor"
    STUDENT = "student"


class TaskStatus(str, Enum):
    UNCHECKED = "unchecked"
    APPROVED = "approved"
    DISAPPROVED = "disapproved"
    POSTPONED = "postponed"


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
    lead_id = Column(String, nullable=False)
    # Статус задачи
    status = Column(SQLEnum(TaskStatus), nullable=False)
    # Дата создания задачи
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Дата обновления задачи
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    # Связь с сообщениями задачи
    task_messages = relationship(
        "TaskMessage", back_populates="task", cascade="all, delete-orphan"
    )


class TaskMessage(Base):
    __tablename__ = "task_messages"

    # Уникальный id
    id = Column(Integer, primary_key=True, nullable=False)
    # ID задачи
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    # ID файла/сообщения в Telegram
    file_id = Column(String, nullable=False)
    # Номер задания (1, 2 или 3)
    task_number = Column(Integer, nullable=False)
    # Дата создания сообщения
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Связь с задачей
    task = relationship("Task", back_populates="task_messages")


class TestResult(Base):
    __tablename__ = "test_results"

    # Уникальный id
    id = Column(Integer, primary_key=True, nullable=False)
    # ID пользователя
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # ID лида в AmoCRM
    lead_id = Column(String, nullable=False)
    # Баллы по блокам
    block1_score = Column(Integer, nullable=False)
    block2_score = Column(Integer, nullable=False)
    block3_score = Column(Integer, nullable=False)
    block4_score = Column(Integer, nullable=False)
    block5_score = Column(Integer, nullable=False)
    block6_score = Column(Integer, nullable=False)
    # Баллы за кейсы
    case1_score = Column(Integer, nullable=False)
    case2_score = Column(Integer, nullable=False)
    # Общий балл
    total_score = Column(Integer, nullable=False)
    # Тип профиля
    profile_type = Column(String, nullable=False)
    # Дата прохождения теста
    completed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


# ================================
# Survey System Models
# ================================


class BroadcastStatus(str, Enum):
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    CANCELLED = "cancelled"


class BroadcastType(str, Enum):
    MESSAGE = "message"
    SURVEY = "survey"


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, nullable=False)
    chat_id = Column(Integer, unique=True, nullable=False)  # Telegram chat ID
    chat_title = Column(String, nullable=True)
    added_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # False when bot is removed from chat

    # Relationships
    broadcasts = relationship("Broadcast", secondary="broadcast_chats", back_populates="chats")


class ChatMember(Base):
    __tablename__ = "chat_members"

    id = Column(Integer, primary_key=True, nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    user_tg_id = Column(Integer, nullable=False)  # Telegram user ID (no FK, soft link)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # False when user leaves
    is_admin = Column(Boolean, default=False)  # Admin status in this chat
    admin_status_updated_at = Column(DateTime, nullable=True)  # Last admin check

    # Composite unique constraint
    __table_args__ = (UniqueConstraint("chat_id", "user_tg_id"),)


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, nullable=False)
    curator_tg_id = Column(Integer, nullable=False)
    scheduled_time = Column(DateTime, nullable=True)  # None = sent immediately
    sent_at = Column(DateTime, nullable=True)  # When actually sent
    status = Column(SQLEnum(BroadcastStatus), default=BroadcastStatus.SCHEDULED)
    broadcast_type = Column(SQLEnum(BroadcastType), nullable=False)
    message_content = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    chats = relationship("Chat", secondary="broadcast_chats", back_populates="broadcasts")
    responses = relationship("SurveyResponse", back_populates="broadcast", cascade="all, delete-orphan")


class BroadcastChat(Base):
    __tablename__ = "broadcast_chats"

    id = Column(Integer, primary_key=True, nullable=False)
    broadcast_id = Column(Integer, ForeignKey("broadcasts.id"), nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True, nullable=False)
    broadcast_id = Column(Integer, ForeignKey("broadcasts.id"), nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    user_tg_id = Column(Integer, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    is_completed = Column(Boolean, default=False)
    reminder_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    broadcast = relationship("Broadcast", back_populates="responses")
    answers = relationship("SurveyAnswer", back_populates="response", cascade="all, delete-orphan")


class SurveyAnswer(Base):
    __tablename__ = "survey_answers"

    id = Column(Integer, primary_key=True, nullable=False)
    response_id = Column(Integer, ForeignKey("survey_responses.id"), nullable=False)
    question_key = Column(String, nullable=False)  # e.g., "q1", "q2_followup"
    answer_text = Column(String, nullable=True)
    answer_value = Column(Integer, nullable=True)  # For numeric ratings
    answered_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    response = relationship("SurveyResponse", back_populates="answers")
