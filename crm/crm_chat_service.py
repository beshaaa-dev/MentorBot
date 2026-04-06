import os
import json
import hashlib
import hmac
import aiohttp
import asyncio
import time
from email.utils import formatdate
from typing import Optional

from amocrm.v2 import tokens
import config
from async_rate_limiter import async_amo_crm_rate_limiter
from logger import setup_logger

logger = setup_logger(__name__)

# scope_id текущего аккаунта (перезаписывается при перезапуске бота)
# По сути у аккаунта будет один и тот же scope_id до отключения интеграции
_cached_scope_id = None
_scope_id_lock = asyncio.Lock()


async def send_video_to_chat(
    video_url: str,
    contact_id: int,
    filename: str,
    lead_id: Optional[int] = None,
    contact_name: str = "",
    file_size: int = 0,
    text: Optional[str] = None,
) -> bool:
    """
    Send a video message to AMoCRM chat.
    
    Complete flow: creates chat, attaches to contact, and sends video.
    
    Args:
        video_url: URL to video file (AMoCRM Drive URL)
        contact_id: CRM contact ID
        filename: Video filename
        lead_id: Optional lead ID to link message to
        contact_name: Contact name
        file_size: Video file size in bytes
        
    Returns:
        True if successful, False otherwise
    """
    start_time = time.time()
    scope_id = await _get_or_create_scope_id()

    if not scope_id:
        logger.error("[send_video_to_chat] Failed to get scope_id")
        return False

    channel_secret = config.CRM_CHAT_CHANNEL_SECRET

    if not channel_secret:
        logger.error("[send_video_to_chat] Missing channel_secret in config")
        return False

    try:
        # Step 1: Create chat
        conversation_id = f"tgbot-{contact_id}"
        user_id = f"tgbot-user-{contact_id}"
        
        chat_body = {
            "conversation_id": conversation_id,
            "user": {
                "id": user_id,
                "name": contact_name,
            }
        }
  
        chat_request_body = json.dumps(chat_body, separators=(',', ':'))
        
        method = "POST"
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        path = f"/v2/origin/custom/{scope_id}/chats"
        
        content_md5 = hashlib.md5(chat_request_body.encode()).hexdigest()
        signature_string = "\n".join([method.upper(), content_md5, "application/json", date, path])
        signature = hmac.new(channel_secret.encode(), signature_string.encode(), hashlib.sha1).hexdigest()

        headers = {
            "Date": date,
            "Content-Type": "application/json",
            "Content-MD5": content_md5.lower(),
            "X-Signature": signature.lower(),
        }
        
        url = f"https://amojo.amocrm.ru{path}"

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(url, headers=headers, data=chat_request_body, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    resp_text = await response.text()

                    if response.status not in (200, 201):
                        logger.error(
                            f"[send_video_to_chat] Failed to create chat: {response.status} {resp_text}"
                        )
                        return False
                    
                    result = json.loads(resp_text)
                    chat_id = result.get("id")
        
        if not chat_id:
            logger.error(f"[send_video_to_chat] No chat ID in response: {result}")
            return False

        # Step 2: Attach chat to contact
        from crm.crm_service import get_access_token
        access_token = await get_access_token()

        if not access_token:
            logger.error(f"[send_video_to_chat] Failed to get access token!")
            return False

        attach_url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/contacts/chats"
        attach_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        attach_body = [{"contact_id": contact_id, "chat_id": chat_id}]

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(attach_url, headers=attach_headers, json=attach_body, timeout=aiohttp.ClientTimeout(total=30)) as attach_response:
                    resp_text = await attach_response.text()

                    if attach_response.status not in (200, 201):
                        logger.warning(
                            f"[send_video_to_chat] Failed to attach chat: {attach_response.status} {resp_text}"
                        )

        # Step 3: Send video message
        timestamp = int(time.time())
        msec_timestamp = int(time.time() * 1000)
        msgid = f"tgbot-video-{msec_timestamp}"
        sender_id = f"tgbot-contact-{timestamp}"

        sender = {
            "id": sender_id,
            "name": contact_name,
        }
        
        payload = {
            "timestamp": timestamp,
            "msec_timestamp": msec_timestamp,
            "msgid": msgid,
            "conversation_ref_id": chat_id,  # CRITICAL: Use conversation_ref_id for AMoCRM-generated IDs
            "sender": sender,
            "message": {
                "type": "video",
                "media": video_url,
                "file_name": filename,
                "file_size": file_size,
                **({"text": text} if text else {}),
            },
            "silent": False,
        }
        
        if lead_id:
            payload["source"] = {"external_id": str(lead_id)}

        video_body = {
            "event_type": "new_message",
            "payload": payload
        }
        
        video_request_body = json.dumps(video_body, separators=(',', ':'))
        
        # Create signature for video message
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        path = f"/v2/origin/custom/{scope_id}"
        
        content_md5 = hashlib.md5(video_request_body.encode()).hexdigest()
        signature_string = "\n".join([method.upper(), content_md5, "application/json", date, path])
        signature = hmac.new(channel_secret.encode(), signature_string.encode(), hashlib.sha1).hexdigest()

        headers = {
            "Date": date,
            "Content-Type": "application/json",
            "Content-MD5": content_md5.lower(),
            "X-Signature": signature.lower(),
        }
        
        url = f"https://amojo.amocrm.ru{path}"

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(url, headers=headers, data=video_request_body, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    resp_text = await response.text()

                    if response.status in (200, 201):
                        return True
                    logger.error(
                        f"[send_video_to_chat] Failed to send video: HTTP {response.status} {resp_text}"
                    )
                    return False
            
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"[send_video_to_chat] Exception occurred after {total_time:.2f}s: {e}", exc_info=True)
        return False


async def send_media_to_chat(
    media_url: str,
    contact_id: int,
    filename: str,
    media_type: str = "file",
    lead_id: Optional[int] = None,
    contact_name: str = "",
    file_size: int = 0,
    text: Optional[str] = None,
) -> bool:
    """
    Отправка медиа-сообщения в чат AMoCRM.

    Полный процесс: создание чата, привязка к контакту, отправка сообщения.

    Args:
        media_url: URL файла (AMoCRM Drive URL)
        contact_id: ID контакта в CRM
        filename: Имя файла
        media_type: Тип сообщения в Chats API ("voice", "picture", "file", "audio")
        lead_id: ID сделки (опционально)
        contact_name: Имя контакта
        file_size: Размер файла в байтах
        text: Текст сообщения (отображается вместе с файлом)

    Returns:
        True при успехе, False при ошибке
    """
    start_time = time.time()
    scope_id = await _get_or_create_scope_id()

    if not scope_id:
        logger.error("[send_media_to_chat] Failed to get scope_id")
        return False

    channel_secret = config.CRM_CHAT_CHANNEL_SECRET

    if not channel_secret:
        logger.error("[send_media_to_chat] Missing channel_secret in config")
        return False

    try:
        # Step 1: Создание чата
        conversation_id = f"tgbot-{contact_id}"
        user_id = f"tgbot-user-{contact_id}"

        chat_body = {
            "conversation_id": conversation_id,
            "user": {
                "id": user_id,
                "name": contact_name,
            }
        }

        chat_request_body = json.dumps(chat_body, separators=(',', ':'))

        method = "POST"
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        path = f"/v2/origin/custom/{scope_id}/chats"

        content_md5 = hashlib.md5(chat_request_body.encode()).hexdigest()
        signature_string = "\n".join([method.upper(), content_md5, "application/json", date, path])
        signature = hmac.new(channel_secret.encode(), signature_string.encode(), hashlib.sha1).hexdigest()

        headers = {
            "Date": date,
            "Content-Type": "application/json",
            "Content-MD5": content_md5.lower(),
            "X-Signature": signature.lower(),
        }

        url = f"https://amojo.amocrm.ru{path}"

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(url, headers=headers, data=chat_request_body, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    resp_text = await response.text()

                    if response.status not in (200, 201):
                        logger.error(
                            f"[send_media_to_chat] Failed to create chat: {response.status} {resp_text}"
                        )
                        return False

                    result = json.loads(resp_text)
                    chat_id = result.get("id")

        if not chat_id:
            logger.error(f"[send_media_to_chat] No chat ID in response: {result}")
            return False

        # Step 2: Привязка чата к контакту
        from crm.crm_service import get_access_token
        access_token = await get_access_token()

        if not access_token:
            logger.error("[send_media_to_chat] Failed to get access token!")
            return False

        attach_url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/contacts/chats"
        attach_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        attach_body = [{"contact_id": contact_id, "chat_id": chat_id}]

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(attach_url, headers=attach_headers, json=attach_body, timeout=aiohttp.ClientTimeout(total=30)) as attach_response:
                    resp_text = await attach_response.text()

                    if attach_response.status not in (200, 201):
                        logger.warning(
                            f"[send_media_to_chat] Failed to attach chat: {attach_response.status} {resp_text}"
                        )

        # Step 3: Отправка медиа-сообщения
        timestamp = int(time.time())
        msec_timestamp = int(time.time() * 1000)
        msgid = f"tgbot-{media_type}-{msec_timestamp}"
        sender_id = f"tgbot-contact-{timestamp}"

        sender = {
            "id": sender_id,
            "name": contact_name,
        }

        payload = {
            "timestamp": timestamp,
            "msec_timestamp": msec_timestamp,
            "msgid": msgid,
            "conversation_ref_id": chat_id,
            "sender": sender,
            "message": {
                "type": media_type,
                "media": media_url,
                "file_name": filename,
                "file_size": file_size,
                **({"text": text} if text else {}),
            },
            "silent": False,
        }

        if lead_id:
            payload["source"] = {"external_id": str(lead_id)}

        msg_body = {
            "event_type": "new_message",
            "payload": payload
        }

        msg_request_body = json.dumps(msg_body, separators=(',', ':'))

        date = formatdate(timeval=None, localtime=False, usegmt=True)
        path = f"/v2/origin/custom/{scope_id}"

        content_md5 = hashlib.md5(msg_request_body.encode()).hexdigest()
        signature_string = "\n".join([method.upper(), content_md5, "application/json", date, path])
        signature = hmac.new(channel_secret.encode(), signature_string.encode(), hashlib.sha1).hexdigest()

        headers = {
            "Date": date,
            "Content-Type": "application/json",
            "Content-MD5": content_md5.lower(),
            "X-Signature": signature.lower(),
        }

        url = f"https://amojo.amocrm.ru{path}"

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(url, headers=headers, data=msg_request_body, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    resp_text = await response.text()

                    if response.status in (200, 201):
                        return True
                    logger.error(
                        f"[send_media_to_chat] Failed to send {media_type}: HTTP {response.status} {resp_text}"
                    )
                    return False

    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"[send_media_to_chat] Exception occurred after {total_time:.2f}s: {e}", exc_info=True)
        return False


async def _get_amojo_id() -> str:
    logger.debug(f"[_get_amojo_id] Starting to fetch amojo_id...")
    try:
        from crm.crm_service import get_access_token
        logger.debug(f"[_get_amojo_id] Requesting access token...")
        access_token = await get_access_token()
        
        if not access_token:
            logger.error(f"[_get_amojo_id] Failed to get access token!")
            return None
        
        logger.debug(f"[_get_amojo_id] Access token obtained: {access_token[:20]}...")
        
        url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/account?with=amojo_id"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        logger.info(f"[_get_amojo_id] === GET AMOJO_ID REQUEST ===")
        logger.info(f"[_get_amojo_id] URL: {url}")
        logger.info(f"[_get_amojo_id] Headers: Authorization=Bearer {access_token[:20]}...")
        
        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    text = await response.text()
                    logger.info(f"[_get_amojo_id] === GET AMOJO_ID RESPONSE ===")
                    logger.info(f"[_get_amojo_id] Status: {response.status}")
                    logger.info(f"[_get_amojo_id] Response headers: {dict(response.headers)}")
                    logger.info(f"[_get_amojo_id] Response body: {text}")
                    
                    if response.status == 200:
                        result = json.loads(text)
                        amojo_id = result.get("amojo_id")
                        if amojo_id:
                            logger.info(f"[_get_amojo_id] Got amojo_id: {amojo_id}")
                            return amojo_id
                        else:
                            logger.error(f"[_get_amojo_id] No amojo_id in response")
                            return None
                    else:
                        logger.error(f"[_get_amojo_id] Failed to get amojo_id: {response.status}")
                        return None
    except Exception as e:
        logger.error(f"[_get_amojo_id] Exception occurred: {e}", exc_info=True)
        return None


async def _connect_channel(channel_id: str, channel_secret: str, amojo_id: str, bot_name: str = "TG BOT") -> str:
    """Connect chat channel to AMoCRM account."""
    try:
        connect_body = {
            "account_id": amojo_id,
            "title": bot_name,
            "hook_api_version": "v2",
        }
        
        connect_request_body = json.dumps(connect_body, separators=(',', ':'))
        logger.debug(f"[_connect_channel] Connect request body: {connect_request_body}")
        method = "POST"
        content_type = "application/json"
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        path = f"/v2/origin/custom/{channel_id}/connect"
        
        content_md5 = hashlib.md5(connect_request_body.encode()).hexdigest()
        signature_string = "\n".join([method.upper(), content_md5, content_type, date, path])
        signature = hmac.new(channel_secret.encode(), signature_string.encode(), hashlib.sha1).hexdigest()
        
        logger.debug(f"[_connect_channel] Connect signature: method={method}, path={path}, content_md5={content_md5}")
        
        headers = {
            "Date": date,
            "Content-Type": content_type,
            "Content-MD5": content_md5.lower(),
            "X-Signature": signature.lower(),
        }
        
        url = f"https://amojo.amocrm.ru{path}"
        
        logger.info(f"[_connect_channel] === CONNECT CHANNEL REQUEST ===")
        logger.info(f"[_connect_channel] URL: {url}")
        logger.info(f"[_connect_channel] Headers: {headers}")
        logger.info(f"[_connect_channel] Body: {connect_request_body}")
        
        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(url, headers=headers, data=connect_request_body, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    text = await response.text()
                    logger.info(f"[_connect_channel] === CONNECT CHANNEL RESPONSE ===")
                    logger.info(f"[_connect_channel] Status: {response.status}")
                    logger.info(f"[_connect_channel] Response headers: {dict(response.headers)}")
                    logger.info(f"[_connect_channel] Response body: {text}")
                    
                    if response.status in (200, 201):
                        result = json.loads(text)
                        scope_id = result.get("scope_id")
                        if scope_id:
                            logger.info(f"[_connect_channel] Channel connected successfully, scope_id: {scope_id}")
                            return scope_id
                        else:
                            logger.error(f"[_connect_channel] No scope_id in response")
                            return None
                    else:
                        logger.error(f"[_connect_channel] Failed to connect channel: {response.status}")
                        return None
    except Exception as e:
        logger.error(f"[_connect_channel] Exception occurred: {e}", exc_info=True)
        return None


async def _get_or_create_scope_id() -> str:
    """
    Get cached scope_id or create new one by connecting channel.
    
    Returns:
        scope_id string or None if failed
    """
    global _cached_scope_id
    
    logger.debug(f"[_get_or_create_scope_id] Acquiring lock...")
    async with _scope_id_lock:
        if _cached_scope_id:
            logger.info(f"[_get_or_create_scope_id] Using cached scope_id: {_cached_scope_id}")
            return _cached_scope_id
        
        logger.info(f"[_get_or_create_scope_id] No cached scope_id, fetching new one...")
    
    # Используем блокировку для thread-safe инициализации
    async with _scope_id_lock:
        # Двойная проверка после получения блокировки
        if _cached_scope_id:
            return _cached_scope_id
        
        # Подключаем аккаут к каналу чатов 
        logger.info("Connecting channel to get scope_id...")
        
        channel_id = config.CRM_CHAT_CHANNEL_ID
        channel_secret = config.CRM_CHAT_CHANNEL_SECRET
        
        if not channel_id or not channel_secret:
            logger.error(f"[_get_or_create_scope_id] Missing channel_id or channel_secret in config")
            return None
        
        logger.debug(f"[_get_or_create_scope_id] Channel ID: {channel_id}, Secret: {len(channel_secret)} chars")
        
        amojo_id = await _get_amojo_id()
        if not amojo_id:
            logger.error(f"[_get_or_create_scope_id] Failed to get amojo_id")
            return None
        
        logger.info(f"[_get_or_create_scope_id] Got amojo_id: {amojo_id}")
        
        scope_id = await _connect_channel(channel_id, channel_secret, amojo_id)
        
        if scope_id:
            logger.info(f"[_get_or_create_scope_id] Channel connected successfully, scope_id: {scope_id}")
            # Сохраняем в кэше
            _cached_scope_id = scope_id
            return scope_id
        else:
            logger.error(f"[_get_or_create_scope_id] Failed to connect channel")
            return None
        
        return None
