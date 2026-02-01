"""
Visit Card Service - Business logic for visit card video processing
"""
from datetime import datetime
import logging

from crm.crm_service import upload_video, update_lead_status_by_lead, get_crm_lead
from crm.crm_chat_service import send_video_to_chat
from config import CRM_VISIT_CARD_IS_SENT_STATUS
from database.user_service import find_by_tg_id
from repositories.user_repository import get_visit_card

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
    logger.info(f"[process_visit_card_video] === STARTING VIDEO PROCESSING ===")
    logger.info(f"[process_visit_card_video] Telegram user ID: {telegram_user_id}")
    logger.info(f"[process_visit_card_video] Video file size: {len(file_bytes)} bytes ({len(file_bytes) / 1024 / 1024:.2f} MB)")
    
    # Получаем пользователя из БД
    logger.debug(f"[process_visit_card_video] Step 1: Fetching user from database...")
    user = find_by_tg_id(telegram_user_id)
    if not user or not user.crm_id:
        logger.warning(f"[process_visit_card_video] User not found or no crm_id for tg_id={telegram_user_id}")
        raise VisitCardProcessingError("Пользователь не найден в системе")
    
    logger.info(f"[process_visit_card_video] User found: crm_id={user.crm_id}, name={user.first_name} {user.last_name}")

    # Получаем визитку и lead_id
    logger.debug(f"[process_visit_card_video] Step 2: Fetching visit card for crm_id={user.crm_id}...")
    visit_card = get_visit_card(user.crm_id)
    lead_id = visit_card.lead_id if visit_card else None
    
    if not lead_id:
        logger.warning(f"[process_visit_card_video] No lead_id found for user {user.crm_id}")
        raise VisitCardProcessingError("Не найдена сделка для визитки")
    
    logger.info(f"[process_visit_card_video] Visit card found: lead_id={lead_id}")

    # Генерируем имя файла с текущей датой
    current_date = datetime.now().strftime("%Y-%m-%d")
    filename = f"visit_{current_date}.mp4"
    logger.debug(f"[process_visit_card_video] Generated filename: {filename}")

    # Загружаем видео в AMoCRM Drive
    logger.info(f"[process_visit_card_video] Step 3: Uploading video to AMoCRM Drive...")
    logger.debug(f"[process_visit_card_video] Upload params: filename={filename}, size={len(file_bytes)} bytes")
    
    video_url, file_size = await upload_video(file_bytes, filename)
    
    if not video_url:
        logger.error(f"[process_visit_card_video] Failed to upload visit card video to Drive for lead {lead_id}")
        raise VisitCardProcessingError("Ошибка загрузки видео в AMoCRM")

    logger.info(f"[process_visit_card_video] Video uploaded successfully!")
    logger.info(f"[process_visit_card_video] Video URL: {video_url}")
    logger.info(f"[process_visit_card_video] File size: {file_size} bytes ({file_size / 1024 / 1024:.2f} MB)")

    # Обновляем статус сделки
    logger.info(f"[process_visit_card_video] Step 4: Updating lead status...")
    lead = get_crm_lead(int(lead_id))
    if lead:
        logger.debug(f"[process_visit_card_video] Lead found: {lead_id}, updating status to {CRM_VISIT_CARD_IS_SENT_STATUS}")
        update_lead_status_by_lead(lead, CRM_VISIT_CARD_IS_SENT_STATUS)
        logger.info(f"[process_visit_card_video] Lead {lead_id} status updated to CRM_VISIT_CARD_IS_SENT_STATUS")
    else:
        logger.warning(f"[process_visit_card_video] Lead {lead_id} not found, skipping status update")

    # Отправляем видео в чат AMoCRM
    logger.info(f"[process_visit_card_video] Step 5: Sending video to AMoCRM chat...")
    contact_name = f"{user.first_name} {user.last_name}".strip() or "Клиент"
    logger.debug(f"[process_visit_card_video] Chat send params:")
    logger.debug(f"[process_visit_card_video]   - video_url: {video_url}")
    logger.debug(f"[process_visit_card_video]   - contact_id: {user.crm_id}")
    logger.debug(f"[process_visit_card_video]   - contact_name: {contact_name}")
    logger.debug(f"[process_visit_card_video]   - filename: {filename}")
    logger.debug(f"[process_visit_card_video]   - lead_id: {lead_id}")
    logger.debug(f"[process_visit_card_video]   - file_size: {file_size}")
    
    chat_success = await send_video_to_chat(
        video_url=video_url,
        contact_id=int(user.crm_id),
        filename=filename,
        lead_id=int(lead_id),
        contact_name=contact_name,
        file_size=file_size
    )
    
    if not chat_success:
        logger.error(f"[process_visit_card_video] Failed to send video to chat for contact {user.crm_id}, lead {lead_id}")
        raise VisitCardProcessingError("Ошибка отправки видео в чат AMoCRM")
    
    logger.info(f"[process_visit_card_video] Video sent to chat successfully!")
    logger.info(f"[process_visit_card_video] === VIDEO PROCESSING COMPLETED ===")
    logger.info(f"[process_visit_card_video] Summary: contact={user.crm_id}, lead={lead_id}, video={video_url}")
