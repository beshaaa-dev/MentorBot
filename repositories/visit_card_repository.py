"""
Visit Card Service - Business logic for visit card video processing
"""
from datetime import datetime
import logging

from crm.crm_service import upload_video, update_lead_status_by_lead, get_crm_lead
from crm.crm_chat_service import send_video_to_chat
from config import CRM_VISIT_CARD_IS_SENT_STATUS
from database.user_service import find_by_tg_id
from repositories.task_repository import get_visit_card

logger = logging.getLogger(__name__)


class VisitCardProcessingError(Exception):
    """Ошибка обработки визитки"""
    pass


async def process_visit_card_video(
    telegram_user_id: int,
    file_bytes: bytes
) -> None:
    """
    Обработка видео визитки: загрузка в AMoCRM Drive и отправка в чат.
    
    Args:
        telegram_user_id: Telegram ID пользователя
        file_bytes: Байты видеофайла
        
    Raises:
        VisitCardProcessingError: При ошибке обработки визитки
    """
    # Получаем пользователя из БД
    user = find_by_tg_id(telegram_user_id)
    if not user or not user.crm_id:
        logger.warning(f"User not found or no crm_id for tg_id={telegram_user_id}")
        raise VisitCardProcessingError("Пользователь не найден в системе")

    # Получаем визитку и lead_id
    visit_card = get_visit_card(user.crm_id)
    lead_id = visit_card.lead_id if visit_card else None
    
    if not lead_id:
        logger.warning(f"No lead_id found for user {user.crm_id}")
        raise VisitCardProcessingError("Не найдена сделка для визитки")

    # Генерируем имя файла с текущей датой
    current_date = datetime.now().strftime("%Y-%m-%d")
    filename = f"visit_{current_date}.mp4"

    # Загружаем видео в AMoCRM Drive
    video_url, file_size = await upload_video(file_bytes, filename)
    
    if not video_url:
        logger.error(f"Failed to upload visit card video to Drive for lead {lead_id}")
        raise VisitCardProcessingError("Ошибка загрузки видео в AMoCRM")

    logger.info(f"Video uploaded to Drive: {video_url}, size: {file_size} bytes")

    # Обновляем статус сделки
    lead = get_crm_lead(int(lead_id))
    if lead:
        update_lead_status_by_lead(lead, CRM_VISIT_CARD_IS_SENT_STATUS)
        logger.info(f"Updated lead {lead_id} status to CRM_VISIT_CARD_IS_SENT_STATUS")

    # Отправляем видео в чат AMoCRM
    contact_name = f"{user.first_name} {user.last_name}".strip() or "Клиент"
    chat_success = await send_video_to_chat(
        video_url=video_url,
        contact_id=int(user.crm_id),
        filename=filename,
        lead_id=int(lead_id),
        contact_name=contact_name,
        file_size=file_size
    )
    
    if not chat_success:
        logger.error(f"Failed to send video to chat for contact {user.crm_id}, lead {lead_id}")
        raise VisitCardProcessingError("Ошибка отправки видео в чат AMoCRM")
    
    logger.info(f"Video sent to chat for contact {user.crm_id}, lead {lead_id}")
