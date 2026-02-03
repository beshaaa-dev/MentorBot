from datetime import datetime
from database.db_helper import get_db
from database.models import Broadcast, BroadcastChat, BroadcastStatus, SurveyResponse, SurveyAnswer, BroadcastType
from logger import setup_logger

logger = setup_logger(__name__)


def create_broadcast(
    curator_tg_id: int,
    scheduled_time: datetime | None = None,
    status: BroadcastStatus = BroadcastStatus.SCHEDULED,
    broadcast_type: BroadcastType = BroadcastType.SURVEY,
    message_content: str | None = None,
) -> Broadcast:
    """Create a new broadcast."""
    with get_db() as db:
        try:
            broadcast = Broadcast(
                curator_tg_id=curator_tg_id,
                scheduled_time=scheduled_time,
                status=status,
                broadcast_type=broadcast_type,
                message_content=message_content,
            )
            db.add(broadcast)
            db.commit()
            db.refresh(broadcast)
            return broadcast
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating broadcast: {e}")
            raise


def add_chat_to_broadcast(broadcast_id: int, chat_id: int) -> BroadcastChat:
    """Add a chat to broadcast's target list."""
    with get_db() as db:
        try:
            broadcast_chat = BroadcastChat(broadcast_id=broadcast_id, chat_id=chat_id)
            db.add(broadcast_chat)
            db.commit()
            db.refresh(broadcast_chat)
            return broadcast_chat
        except Exception as e:
            db.rollback()
            logger.error(f"Error adding chat {chat_id} to broadcast {broadcast_id}: {e}")
            raise


def get_broadcast_by_id(broadcast_id: int) -> Broadcast | None:
    """Get broadcast by ID."""
    with get_db() as db:
        return db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()


def get_broadcast_chats(broadcast_id: int) -> list[BroadcastChat]:
    """Get all chats for a broadcast."""
    with get_db() as db:
        return db.query(BroadcastChat).filter(BroadcastChat.broadcast_id == broadcast_id).all()


def update_broadcast_status(broadcast_id: int, status: BroadcastStatus) -> Broadcast | None:
    """Update broadcast status."""
    with get_db() as db:
        try:
            broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
            if not broadcast:
                return None
            broadcast.status = status
            if status == BroadcastStatus.SENT:
                broadcast.sent_at = datetime.utcnow()
            db.commit()
            db.refresh(broadcast)
            return broadcast
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating broadcast {broadcast_id} status: {e}")
            raise


def get_scheduled_broadcasts(curator_tg_id: int | None = None) -> list[Broadcast]:
    """Get all scheduled broadcasts, optionally filtered by curator."""
    with get_db() as db:
        query = db.query(Broadcast).filter(Broadcast.status == BroadcastStatus.SCHEDULED)
        if curator_tg_id:
            query = query.filter(Broadcast.curator_tg_id == curator_tg_id)
        return query.all()


def create_survey_response(
    broadcast_id: int, chat_id: int, user_tg_id: int
) -> SurveyResponse:
    """Create a survey response record."""
    with get_db() as db:
        try:
            response = SurveyResponse(
                broadcast_id=broadcast_id,
                chat_id=chat_id,
                user_tg_id=user_tg_id,
            )
            db.add(response)
            db.commit()
            db.refresh(response)
            return response
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating survey response for user {user_tg_id}: {e}"
            )
            raise


def get_incomplete_responses(broadcast_id: int) -> list[SurveyResponse]:
    """Get all incomplete survey responses for a broadcast."""
    with get_db() as db:
        return (
            db.query(SurveyResponse)
            .filter(
                SurveyResponse.broadcast_id == broadcast_id,
                SurveyResponse.is_completed == False,
            )
            .all()
        )


def get_incomplete_responses_without_reminder(broadcast_id: int) -> list[SurveyResponse]:
    """Get incomplete responses that haven't received a reminder yet."""
    with get_db() as db:
        return (
            db.query(SurveyResponse)
            .filter(
                SurveyResponse.broadcast_id == broadcast_id,
                SurveyResponse.is_completed == False,
                SurveyResponse.reminder_sent_at == None,
            )
            .all()
        )


def mark_reminder_sent(response_id: int) -> bool:
    """Mark that reminder was sent for this response."""
    with get_db() as db:
        try:
            response = db.query(SurveyResponse).filter(SurveyResponse.id == response_id).first()
            if response:
                response.reminder_sent_at = datetime.utcnow()
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(f"Error marking reminder sent for response {response_id}: {e}")
            return False


def get_all_broadcasts_with_responses() -> list[Broadcast]:
    """Get all broadcasts that have at least one response."""
    with get_db() as db:
        return (
            db.query(Broadcast)
            .join(SurveyResponse, Broadcast.id == SurveyResponse.broadcast_id)
            .distinct()
            .all()
        )


def get_broadcast_responses(broadcast_id: int) -> list[SurveyResponse]:
    """Get all responses for a specific broadcast."""
    with get_db() as db:
        return (
            db.query(SurveyResponse)
            .filter(SurveyResponse.broadcast_id == broadcast_id)
            .all()
        )


def get_response_answers(response_id: int) -> list[SurveyAnswer]:
    """Get all answers for a specific response."""
    with get_db() as db:
        return (
            db.query(SurveyAnswer)
            .filter(SurveyAnswer.response_id == response_id)
            .all()
        )


def update_broadcast_scheduled_time(broadcast_id: int, new_scheduled_time: datetime) -> bool:
    """Update broadcast scheduled time."""
    with get_db() as db:
        try:
            broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
            if broadcast:
                broadcast.scheduled_time = new_scheduled_time
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating broadcast {broadcast_id} scheduled time: {e}")
            return False


def get_response_by_id(response_id: int) -> SurveyResponse | None:
    """Get survey response by ID."""
    with get_db() as db:
        return db.query(SurveyResponse).filter(SurveyResponse.id == response_id).first()


def save_answer(
    response_id: int, question_key: str, answer_text: str | None = None, answer_value: int | None = None
) -> None:
    """Save answer to database."""
    with get_db() as db:
        try:
            answer = SurveyAnswer(
                response_id=response_id,
                question_key=question_key,
                answer_text=answer_text,
                answer_value=answer_value,
            )
            db.add(answer)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving answer for question {question_key}: {e}")
            raise


def mark_response_started(response_id: int) -> bool:
    """Mark survey response as started."""
    with get_db() as db:
        try:
            response = db.query(SurveyResponse).filter(SurveyResponse.id == response_id).first()
            if response:
                response.started_at = datetime.utcnow()
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(f"Error marking response {response_id} as started: {e}")
            return False


def mark_response_completed(response_id: int) -> bool:
    """Mark survey response as completed."""
    with get_db() as db:
        try:
            response = db.query(SurveyResponse).filter(SurveyResponse.id == response_id).first()
            if response:
                response.is_completed = True
                response.completed_at = datetime.utcnow()
                db.commit()
                return True
            return False
        except Exception as e:
            db.rollback()
            logger.error(f"Error marking response {response_id} as completed: {e}")
            return False
