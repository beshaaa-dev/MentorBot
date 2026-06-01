from telegram import Update, Message, Message as TelegramMessage, MessageId
from logger import setup_logger
from keyboards import get_support_keyboard
from messages import ERROR_MESSAGE
import json

logger = setup_logger(__name__)

async def send_error_message(update: Update):
    reply_markup = get_support_keyboard()
    await update.effective_chat.send_message(ERROR_MESSAGE, reply_markup=reply_markup)


async def delete_user_message(message: Message | None) -> None:
    """Best-effort deletion of the triggering user message."""
    if not message:
        return
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete user message: {e}")


def parse_message_reference(file_id: str) -> tuple[int, int] | None:
    """Parse message reference from file_id field. Returns (chat_id, message_id) or None."""
    if file_id.startswith("msg:"):
        try:
            data = json.loads(file_id[4:])
            return (data["chat_id"], data["message_id"])
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Error parsing message reference: {e}")
            return None
    return None


async def try_send_media_types(
    bot, chat_id: int, file_id: str, reply_markup=None
) -> TelegramMessage | MessageId:
    """Try to send media as different types (video, video_note, audio, document, photo, voice)."""
    try:
        return await bot.send_video(
            chat_id=chat_id, video=file_id, reply_markup=reply_markup
        )
    except Exception:
        try:
            return await bot.send_video_note(
                chat_id=chat_id, video_note=file_id, reply_markup=reply_markup
            )
        except Exception:
            try:
                return await bot.send_audio(
                    chat_id=chat_id, audio=file_id, reply_markup=reply_markup
                )
            except Exception:
                try:
                    return await bot.send_document(
                        chat_id=chat_id, document=file_id, reply_markup=reply_markup
                    )
                except Exception:
                    try:
                        return await bot.send_photo(
                            chat_id=chat_id, photo=file_id, reply_markup=reply_markup
                        )
                    except Exception:
                        try:
                            return await bot.send_voice(
                                chat_id=chat_id,
                                voice=file_id,
                                reply_markup=reply_markup,
                            )
                        except Exception as e:
                            logger.error(
                                f"Could not send media with file_id {file_id} to chat {chat_id}: {e}"
                            )
                            raise


async def send_media_to_chat(
    bot, chat_id: int, file_id: str, reply_markup=None
) -> TelegramMessage | MessageId:
    """Send task media directly to a chat and return the Telegram message metadata."""
    # Check if it's a message reference (text message)
    msg_ref = parse_message_reference(file_id)
    if msg_ref:
        from_chat_id, message_id = msg_ref
        # Copy the original message
        return await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    else:
        # It's a regular file_id, try to send as different media types
        return await try_send_media_types(
            bot, chat_id, file_id, reply_markup=reply_markup
        )
