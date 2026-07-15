"""
Shared CRM plumbing for student answer flows (homework and tasks).

Holds everything that is identical between the two: resolving a lead's contacts,
two-way user/contact sync, uploading answer media to AmoCRM Drive, and pushing
answers into the contact's CRM chat with a note fallback.
"""

import asyncio
from datetime import date, datetime, timezone

from amocrm.v2.entity.note import COMMON_TYPE
from telegram import Bot

from crm.crm_chat_service import send_media_to_chat, send_video_to_chat
from crm.crm_service import (
    get_crm_contact_by_id,
    save_entity,
    upload_file,
    upload_video,
)
from crm.crm_models import Contact, Lead
from database.models import User
from database.user_service import find_by_tg_id, update_user
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter

logger = setup_logger(__name__)


# ── Lead helpers ──────────────────────────────────────────────────────────────


def fetch_lead_contacts(lead: Lead) -> list[Contact]:
    contact_refs = (lead._data.get("_embedded") or {}).get("contacts") or []
    contacts = []
    for ref in contact_refs:
        contact = get_crm_contact_by_id(ref["id"])
        if contact is not None:
            contacts.append(contact)
    return contacts


def get_contact_info(lead: Lead) -> tuple[int | None, str]:
    contacts = fetch_lead_contacts(lead)
    if contacts:
        return contacts[0].id, getattr(contacts[0], "name", "") or ""
    logger.warning(
        f"[get_contact_info] Не найден контакт для сделки {getattr(lead, 'id', '?')}"
    )
    return None, ""


def append_lead_tag(lead: Lead, tag: str) -> None:
    for t in lead.tags:
        if getattr(t, "name", None) == tag:
            return
    lead.tags.append(tag)


def create_lead_note(lead: Lead, text: str) -> None:
    with amo_crm_rate_limiter.limit():
        lead.notes.objects.create(text=text, note_type=COMMON_TYPE)


def extract_student_and_mentor(lead: Lead) -> tuple[int, str | None]:
    contact_refs = (lead._data.get("_embedded") or {}).get("contacts")
    if not contact_refs:
        raise ValueError(f"Lead {lead.id} has no embedded contacts")

    for contact in fetch_lead_contacts(lead):
        raw_tg_id = contact.telegram_id
        if raw_tg_id:
            try:
                tg_id = int(str(raw_tg_id).strip())
            except ValueError:
                continue
            mentor_nickname = getattr(lead, "mentor_tg_nickname", None)
            user = find_by_tg_id(tg_id)
            if user:
                sync_contact_from_user(contact, user)
            sync_user_from_contact(tg_id, contact, user=user)
            return tg_id, mentor_nickname

    raise ValueError(f"No contact with telegram_id found on lead {lead.id}")


def sync_users_from_lead(lead: Lead) -> None:
    for contact in fetch_lead_contacts(lead):
        raw_tg_id = contact.telegram_id
        if raw_tg_id:
            try:
                tg_id = int(str(raw_tg_id).strip())
                sync_user_from_contact(tg_id, contact)
            except (ValueError, TypeError):
                pass


def sync_user_from_contact(tg_id: int, contact, *, user: User | None = None) -> None:
    try:
        if user is None:
            user = find_by_tg_id(tg_id)
        if not user:
            return

        contact_name = getattr(contact, "name", None) or ""
        tg_nickname = getattr(contact, "telegram_nickname", None)

        parts = contact_name.strip().split(maxsplit=1)
        first_name = parts[0] if parts else None
        last_name = parts[1] if len(parts) > 1 else None

        update_kwargs = {}
        if first_name:
            update_kwargs["first_name"] = first_name
        if last_name:
            update_kwargs["last_name"] = last_name
        if tg_nickname:
            update_kwargs["tg_nickname"] = tg_nickname.lstrip("@")

        if update_kwargs:
            update_user(user.id, **update_kwargs)
            logger.info(f"Synced user tg_id={tg_id} from CRM contact: {update_kwargs}")
    except Exception as e:
        logger.warning(f"Failed to sync user tg_id={tg_id} from CRM contact: {e}")


def sync_contact_from_user(contact: Contact, user: User) -> None:
    try:
        updates: dict[str, str] = {}

        crm_tg_id = getattr(contact, "telegram_id", None)
        if not crm_tg_id and user.tg_id:
            contact.telegram_id = str(user.tg_id)
            updates["telegram_id"] = str(user.tg_id)

        db_nickname = user.tg_nickname
        if db_nickname:
            crm_nickname = getattr(contact, "telegram_nickname", None)
            crm_norm = (crm_nickname or "").lstrip("@").strip().lower()
            db_norm = db_nickname.lstrip("@").strip().lower()
            if crm_norm != db_norm:
                contact.telegram_nickname = db_nickname
                updates["telegram_nickname"] = db_nickname

        if updates:
            with amo_crm_rate_limiter.limit():
                save_entity(contact)
            logger.info(
                f"Synced CRM contact {contact.id} from DB user tg_id={user.tg_id}: {updates}"
            )
    except Exception as e:
        logger.warning(
            f"Failed to sync CRM contact {contact.id} from DB user tg_id={user.tg_id}: {e}"
        )


def read_deadline(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def is_deadline_missed(deadline: datetime | None) -> bool:
    if not deadline:
        return False
    return datetime.now(timezone.utc).replace(tzinfo=None) > deadline


# ── Media upload ──────────────────────────────────────────────────────────────


async def upload_answer_video(
    bot: Bot, file_id: str | None, q_num: int, prefix: str = "hw"
) -> tuple[str | None, int, str]:
    filename = f"{prefix}_{q_num}_{(file_id or 'unknown')[:8]}.mp4"
    if not file_id:
        logger.warning(f"[upload_answer_video] file_id отсутствует для вопроса {q_num}")
        return None, 0, filename
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        download_url, _ = await upload_video(bytes(file_bytes), filename)
        return download_url, len(file_bytes), filename
    except Exception as e:
        logger.error(f"Failed to upload media for question {q_num}: {e}", exc_info=True)
        return None, 0, filename


async def upload_answer_audio(
    bot: Bot, file_id: str | None, q_num: int, media_type: str | None, prefix: str = "hw"
) -> tuple[str | None, str | None, int, str, str | None]:
    """Returns (file_uuid, version_uuid, file_size, filename, download_url). UUIDs are None on failure."""
    ext = "ogg" if media_type == "voice" else "mp3"
    content_type = "audio/ogg" if media_type == "voice" else "audio/mpeg"
    filename = f"{prefix}_{q_num}_{(file_id or 'unknown')[:8]}.{ext}"
    if not file_id:
        return None, None, 0, filename, None
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_uuid, version_uuid, _, download_url = await upload_file(
            bytes(file_bytes), filename, content_type
        )
        return file_uuid, version_uuid, len(file_bytes), filename, download_url
    except Exception as e:
        logger.error(f"Failed to upload audio for question {q_num}: {e}", exc_info=True)
        return None, None, 0, filename, None


async def upload_answer_image(
    bot: Bot, file_id: str | None, q_num: int, prefix: str = "hw"
) -> tuple[str | None, str | None, int, str, str | None]:
    """Returns (file_uuid, version_uuid, file_size, filename, download_url). UUIDs are None on failure."""
    filename = f"{prefix}_{q_num}_{(file_id or 'unknown')[:8]}.jpg"
    if not file_id:
        return None, None, 0, filename, None
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_uuid, version_uuid, _, download_url = await upload_file(
            bytes(file_bytes), filename, "image/jpeg"
        )
        return file_uuid, version_uuid, len(file_bytes), filename, download_url
    except Exception as e:
        logger.error(f"Failed to upload image for question {q_num}: {e}", exc_info=True)
        return None, None, 0, filename, None


async def upload_answer_document(
    bot: Bot,
    file_id: str | None,
    q_num: int,
    original_filename: str | None = None,
    mime_type: str | None = None,
    prefix: str = "hw",
) -> tuple[str | None, str | None, int, str, str | None]:
    """Returns (file_uuid, version_uuid, file_size, filename, download_url)."""
    filename = original_filename or f"{prefix}_{q_num}_{(file_id or 'unknown')[:8]}.bin"
    content_type = mime_type or "application/octet-stream"
    if not file_id:
        return None, None, 0, filename, None
    try:
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_uuid, version_uuid, _, download_url = await upload_file(
            bytes(file_bytes), filename, content_type
        )
        return file_uuid, version_uuid, len(file_bytes), filename, download_url
    except Exception as e:
        logger.error(
            f"Failed to upload document for question {q_num}: {e}", exc_info=True
        )
        return None, None, 0, filename, None


# ── Answer preparation and CRM push ───────────────────────────────────────────


async def prepare_answers(
    bot: Bot, answers: dict[int, dict], file_prefix: str = "hw"
) -> tuple[list[dict], list[dict]]:
    """
    Upload every media answer to AmoCRM Drive.

    `answers` format: {question_number: {"text": str|None, "file_id": str|None, "media_type": str}}
    media_type: "text" | "video" | "video_note" | "audio" | "voice" | "photo" | "document".

    Returns (answer_rows, answer_info):
        answer_rows — ready to persist via upsert_*_answers
        answer_info — ready to hand to push_answers_to_crm
    """
    answer_rows: list[dict] = []
    answer_info: list[dict] = []

    for q_num in sorted(answers.keys()):
        data = answers[q_num]
        text: str | None = data.get("text")
        file_id: str | None = data.get("file_id")
        media_type: str = data.get("media_type", "text")

        if media_type == "text" and text:
            content = text
            answer_info.append({"q_num": q_num, "type": "text", "text": text})
        elif media_type in ("video", "video_note"):
            download_url, file_size, filename = await upload_answer_video(
                bot, file_id, q_num, file_prefix
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "video",
                    "url": download_url,
                    "filename": filename,
                    "file_size": file_size,
                }
            )
        elif media_type in ("audio", "voice"):
            _, _, file_size, filename, download_url = await upload_answer_audio(
                bot, file_id, q_num, media_type, file_prefix
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "audio",
                    "filename": filename,
                    "file_size": file_size,
                    "download_url": download_url,
                }
            )
        elif media_type == "photo":
            _, _, file_size, filename, download_url = await upload_answer_image(
                bot, file_id, q_num, file_prefix
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "image",
                    "filename": filename,
                    "file_size": file_size,
                    "download_url": download_url,
                }
            )
        elif media_type == "document":
            _, _, file_size, filename, download_url = await upload_answer_document(
                bot,
                file_id,
                q_num,
                original_filename=data.get("file_name"),
                mime_type=data.get("mime_type"),
                prefix=file_prefix,
            )
            content = file_id or ""
            answer_info.append(
                {
                    "q_num": q_num,
                    "type": "document",
                    "filename": filename,
                    "file_size": file_size,
                    "download_url": download_url,
                }
            )
        else:
            content = file_id or ""
            answer_info.append({"q_num": q_num, "type": "other"})

        answer_rows.append(
            {
                "question_number": q_num,
                "answer_content": content,
                "media_type": media_type,
            }
        )

    return answer_rows, answer_info


_CHAT_MEDIA_TYPE = {"audio": "voice", "image": "picture", "document": "file"}
_MEDIA_LABEL = {"audio": "аудио", "image": "фото", "document": "файл"}


async def push_answers_to_crm(
    *,
    lead: Lead,
    lead_id: str,
    answer_info: list[dict],
    label: str,
    contact_id: int | None,
    contact_name: str,
) -> None:
    """
    Push each prepared answer into the contact's CRM chat, falling back to a lead
    note when the chat send fails or the media could not be uploaded.

    `label` names the work in note texts, e.g. "Д/З" or "задание".
    """
    loop = asyncio.get_running_loop()

    def _create_note(text: str) -> None:
        create_lead_note(lead, text)

    for info in answer_info:
        q_num = info["q_num"]
        kind = info["type"]
        prefix = f"Ответ на {label} № {q_num}"

        if kind == "text":
            await loop.run_in_executor(
                None, _create_note, f"{prefix}: {info['text']}"
            )
            continue

        if kind == "other":
            await loop.run_in_executor(
                None, _create_note, f"{prefix} (медиафайл): передан в Telegram"
            )
            continue

        if kind == "video":
            media_url = info.get("url")
            chat_media_type = "video"
            what = "видео"
        else:
            media_url = info.get("download_url")
            chat_media_type = _CHAT_MEDIA_TYPE[kind]
            what = _MEDIA_LABEL[kind]

        if not media_url or not contact_id:
            logger.warning(
                f"[push_answers_to_crm] lead={lead_id} q={q_num} {what}: "
                f"url={'есть' if media_url else 'нет'}, contact_id={contact_id}"
            )
            await loop.run_in_executor(
                None,
                _create_note,
                f"{prefix} ({what}): {media_url or 'не удалось загрузить'}",
            )
            continue

        if kind == "video":
            sent = await send_video_to_chat(
                video_url=media_url,
                contact_id=contact_id,
                filename=info["filename"],
                lead_id=int(lead_id),
                contact_name=contact_name,
                file_size=info["file_size"],
                text=prefix,
            )
        else:
            sent = await send_media_to_chat(
                media_url=media_url,
                contact_id=contact_id,
                filename=info["filename"],
                media_type=chat_media_type,
                lead_id=int(lead_id),
                contact_name=contact_name,
                file_size=info.get("file_size", 0),
                text=f"{prefix} ({what})",
            )

        if not sent:
            await loop.run_in_executor(
                None, _create_note, f"{prefix} ({what}): {media_url}"
            )
