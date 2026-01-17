import os
import json
import hashlib
import hmac
import aiohttp
import asyncio
import time
from email.utils import formatdate
from typing import Optional
import logging

from amocrm.v2 import tokens
import config
from async_rate_limiter import async_amo_crm_rate_limiter

logger = logging.getLogger(__name__)

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
    file_size: int = 0
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
    # Get or create scope_id (auto-connects channel if needed)
    scope_id = await _get_or_create_scope_id()
    
    if not scope_id:
        logger.error("Failed to get scope_id")
        return False
    
    channel_secret = config.CRM_CHAT_CHANNEL_SECRET
    
    if not channel_secret:
        logger.error("Missing channel_secret in config")
        return False
        
    try:
        # Step 1: Create chat
        logger.info(f"Creating chat for contact {contact_id}")
        
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
                    if response.status not in (200, 201):
                        text = await response.text()
                        logger.error(f"Failed to create chat: {response.status} - {text}")
                        return False
                    
                    result = await response.json()
                    chat_id = result.get("id")
        
        if not chat_id:
            logger.error(f"No chat ID in response: {result}")
            return False
        
        logger.info(f"Chat created: {chat_id}")
        
        # Step 2: Attach chat to contact
        logger.info(f"Attaching chat {chat_id} to contact {contact_id}")
        
        from crm.crm_service import get_access_token
        access_token = await get_access_token()
        
        attach_url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/contacts/chats"
        attach_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        attach_body = [{"contact_id": contact_id, "chat_id": chat_id}]
        
        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(attach_url, headers=attach_headers, json=attach_body, timeout=aiohttp.ClientTimeout(total=30)) as attach_response:
                    if attach_response.status not in (200, 201):
                        text = await attach_response.text()
                        logger.warning(f"Failed to attach chat: {attach_response.status} - {text}")
                        # Continue anyway
                    else:
                        logger.info(f"Chat attached to contact {contact_id}")
        
        # Step 3: Send video message
        logger.info(f"Sending video message to chat {chat_id}")
        
        msgid = f"tgbot-video-{int(time.time() * 1000)}"
        sender_id = f"tgbot-contact-{int(time.time())}"
        
        sender = {
            "id": sender_id,
            "name": contact_name,
        }
        
        payload = {
            "timestamp": int(time.time()),
            "msec_timestamp": int(time.time() * 1000),
            "msgid": msgid,
            "conversation_ref_id": chat_id,  # CRITICAL: Use conversation_ref_id for AMoCRM-generated IDs
            "sender": sender,
            "message": {
                "type": "video",
                "media": video_url,
                "file_name": filename,
                "file_size": file_size
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
                    if response.status in (200, 201):
                        logger.info(f"Video sent successfully to contact {contact_id}, lead {lead_id}")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"Failed to send video: {response.status} - {text}")
                        return False
            
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        return False


async def _get_amojo_id() -> str:
    try:
        from crm.crm_service import get_access_token
        access_token = await get_access_token()
        url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/account?with=amojo_id"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        result = await response.json()
                        amojo_id = result.get("amojo_id")
                        if amojo_id:
                            logger.info(f"Retrieved amojo_id: {amojo_id}")
                            return amojo_id
                    
                    logger.error(f"Failed to get amojo_id: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error getting amojo_id: {e}")
        return None


async def _connect_channel(channel_id: str, channel_secret: str, amojo_id: str, bot_name: str = "TG BOT") -> str:
    """Connect chat channel to AMoCRM account."""
    try:
        body = {
            "account_id": amojo_id,
            "title": bot_name,
            "hook_api_version": "v2",
        }
        
        request_body = json.dumps(body, separators=(',', ':'))
        method = "POST"
        content_type = "application/json"
        date = formatdate(timeval=None, localtime=False, usegmt=True)
        path = f"/v2/origin/custom/{channel_id}/connect"
        
        content_md5 = hashlib.md5(request_body.encode()).hexdigest()
        signature_string = "\n".join([method.upper(), content_md5, content_type, date, path])
        signature = hmac.new(channel_secret.encode(), signature_string.encode(), hashlib.sha1).hexdigest()
        
        headers = {
            "Date": date,
            "Content-Type": content_type,
            "Content-MD5": content_md5.lower(),
            "X-Signature": signature.lower(),
        }
        
        url = f"https://amojo.amocrm.ru{path}"
        
        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(url, headers=headers, data=request_body, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status in (200, 201):
                        result = await response.json()
                        scope_id = result.get("scope_id")
                        if scope_id:
                            logger.info(f"Channel connected successfully")
                            return scope_id
                    
                    logger.error(f"Failed to connect channel: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error connecting channel: {e}")
        return None


async def _get_or_create_scope_id() -> str:
    """
    Возвращает scope_id аккаунта.

    Существует только в рамках текущей сессии.  
    """
    global _cached_scope_id
    
    # Проверяем если в кэше (быстрая проверка без блокировки)
    if _cached_scope_id:
        return _cached_scope_id
    
    # Используем блокировку для thread-safe инициализации
    async with _scope_id_lock:
        # Двойная проверка после получения блокировки
        if _cached_scope_id:
            return _cached_scope_id
        
        # Подключаем аккаут к каналу чатов 
        logger.info("Connecting channel to get scope_id...")
        
        channel_id = config.CRM_CHAT_CHANNEL_ID
        channel_secret = config.CRM_CHAT_CHANNEL_SECRET
        bot_name = config.CRM_CHAT_BOT_NAME
        
        if not all([channel_id, channel_secret]):
            logger.error("Missing channel_id or channel_secret")
            return None
        
        amojo_id = await _get_amojo_id()
        if not amojo_id:
            return None
        
        scope_id = await _connect_channel(channel_id, channel_secret, amojo_id, bot_name)
        
        if scope_id:
            logger.info("✅ Channel connected")
            # Сохраняем в кэше
            _cached_scope_id = scope_id  
            return scope_id
        
        return None
