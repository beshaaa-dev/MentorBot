"""Shared answer-collection helpers for the homework and task student flows."""

from collections.abc import Awaitable, Callable
from datetime import datetime

from telegram import Message
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from messages import HW_MEDIA_LABEL, TASK_DEADLINE, VOICE_MESSAGES_FORBIDDEN
from timezone_utils import format_moscow


def clear_flow_data(context: ContextTypes.DEFAULT_TYPE, prefix: str) -> None:
    """
    Drop only this flow's keys from user_data.

    user_data is shared per user across every ConversationHandler, so a blanket
    clear() here would wipe the state of another flow the student has in flight.
    """
    for key in [k for k in context.user_data if k.startswith(prefix)]:
        del context.user_data[key]


def with_deadline(text: str, deadline: datetime | None) -> str:
    """Append the deadline (rendered in Moscow time) to an assignment message."""
    if not deadline:
        return text
    return f"{text}\n\n{TASK_DEADLINE.format(deadline=format_moscow(deadline, '%d.%m.%Y %H:%M'))}"


MAX_ANSWER_FILE_SIZE_BYTES = 20 * 1024 * 1024  # Telegram Bot API getFile download limit


def media_exceeds_size_limit(message: Message) -> bool:
    """True if the message's attached media is larger than Telegram's 20 MB download limit."""
    media = (
        message.video
        or message.video_note
        or message.audio
        or message.voice
        or message.document
        or (message.photo[-1] if message.photo else None)
    )
    file_size = getattr(media, "file_size", None)
    return bool(file_size and file_size > MAX_ANSWER_FILE_SIZE_BYTES)


def store_answer(
    q_num: int, message: Message, answers: dict[int, dict]
) -> None:
    """Extract file_id + media_type from a student's message into `answers`."""
    file_id: str | None = None
    media_type: str = "text"
    if message.text:
        pass
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.video_note:
        file_id = message.video_note.file_id
        media_type = "video_note"
    elif message.audio:
        file_id = message.audio.file_id
        media_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        media_type = "voice"
    elif message.document:
        file_id = message.document.file_id
        media_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"

    answers[q_num] = {
        "text": message.text if media_type == "text" else None,
        "file_id": file_id,
        "media_type": media_type,
    }
    if message.document:
        answers[q_num]["file_name"] = message.document.file_name
        answers[q_num]["mime_type"] = message.document.mime_type


async def _send_or_ask_voice(
    send: Callable[[int, str], Awaitable[Message]],
    chat_id: int,
    file_id: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> Message | None:
    """Send a voice/video-note answer, or ask the student to allow them if Telegram blocks it.

    Telegram raises Voice_messages_forbidden when the recipient has disabled
    receiving voice messages and video notes in their privacy settings, so the
    stored answer can never be replayed until they lift that restriction.
    """
    try:
        return await send(chat_id, file_id)
    except BadRequest as exc:
        if "voice_messages_forbidden" not in str(exc).lower():
            raise
        await context.bot.send_message(chat_id, VOICE_MESSAGES_FORBIDDEN)
        return None


async def send_answer_content(
    answer_data: dict, chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> Message | None:
    """Replay a stored answer back into a chat, by media type."""
    media_type = answer_data.get("media_type", "text")
    if media_type == "text":
        text = answer_data.get("text") or ""
        if text:
            return await context.bot.send_message(chat_id, text)
        return None
    file_id = answer_data.get("file_id")
    if not file_id:
        return None
    match media_type:
        case "video":
            return await context.bot.send_video(chat_id, file_id)
        case "video_note":
            return await _send_or_ask_voice(
                context.bot.send_video_note, chat_id, file_id, context
            )
        case "audio":
            return await context.bot.send_audio(chat_id, file_id)
        case "voice":
            return await _send_or_ask_voice(
                context.bot.send_voice, chat_id, file_id, context
            )
        case "document":
            return await context.bot.send_document(chat_id, file_id)
        case "photo":
            return await context.bot.send_photo(chat_id, file_id)
        case _:
            return await context.bot.send_message(chat_id, HW_MEDIA_LABEL)


def answers_from_rows(rows) -> dict[int, dict]:
    """Rebuild the user_data answers dict from persisted HomeworkAnswer/TaskAnswer rows."""
    answers: dict[int, dict] = {}
    for row in rows or []:
        if row.media_type == "text":
            answers[row.question_number] = {
                "text": row.answer_content,
                "file_id": None,
                "media_type": "text",
            }
        else:
            answers[row.question_number] = {
                "text": None,
                "file_id": row.answer_content,
                "media_type": row.media_type,
            }
    return answers
