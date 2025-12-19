from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
import json
from repositories.user_repository import (
    get_task,
    get_visit_card,
    TaskDetails,
    VisitCardDetails,
)
from repositories.task_repository import create_task, mark_task_as_failed
from database.user_service import get_by_id
from database.models import User, UserRole
from keyboards import get_confirmation_keyboard
from messages import (
    GREETING_WITH_NAME_TEMPLATE,
    STUDENT_NO_TASK,
    TASK,
    TASK_DEADLINE,
    REQUEST_VIDEO,
    VIDEO_RECEIVED,
    VIDEO_CONFIRMED,
    VIDEO_CANCELLED,
    CONFIRM_BUTTON,
    CANCEL_BUTTON,
    MENTOR_NEW_TASK_NOTIFICATION,
    VISIT_CARD_TASK,
    REQUEST_VISIT_CARD_VIDEO,
    INVALID_MEDIA_TYPE,
    FILE_TOO_LARGE,
    VISIT_CARD_VIDEO_RECEIVED,
    VISIT_CARD_UPLOADING,
    VISIT_CARD_VIDEO_CONFIRMED,
)
from keyboards import get_check_task_keyboard
from handlers.utils import send_error_message, delete_user_message

logger = setup_logger(__name__)

# Conversation states (for student flow only)
WAITING_FOR_VIDEO = 1
WAITING_FOR_CONFIRMATION = 2
WAITING_FOR_VISIT_CARD_VIDEO = 3
WAITING_FOR_VISIT_CARD_CONFIRMATION = 4


async def handle_student(
    user, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(
        GREETING_WITH_NAME_TEMPLATE.format(name=user.first_name),
        reply_markup=ReplyKeyboardRemove(),
    )

    # Проверяем есть ли задание на отправку видеовизитки
    visit_card = get_visit_card(user.crm_id)
    if visit_card:
        return await send_visit_card_message(visit_card, update, context)

    # Проверяем есть ли задание от ментора
    task = get_task(user.crm_id)
    if task:
        return await send_task_message(task, update, context)

    # Задание не найдено
    return await send_task_message(None, update, context)


async def send_task_message(
    task: TaskDetails | None, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not task:
        await update.message.reply_text(
            STUDENT_NO_TASK, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return ConversationHandler.END
    deadline_block = (
        TASK_DEADLINE.format(deadline=task.deadline) if task.deadline else ""
    )
    message = TASK.format(text=task.text) + deadline_block
    await update.message.reply_text(
        message, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_VIDEO


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle received media of any type (text, video, audio, photo, document, etc.)."""
    file_id = None

    # Extract file_id from different media types
    if update.message.video:
        file_id = update.message.video.file_id
    elif update.message.video_note:
        file_id = update.message.video_note.file_id
    elif update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.document:
        file_id = update.message.document.file_id
    elif update.message.photo:
        # Use the largest photo
        file_id = update.message.photo[-1].file_id
    elif update.message.voice:
        file_id = update.message.voice.file_id
    elif update.message.text:
        # Store message reference instead of converting to file
        file_id = create_message_reference(
            update.effective_chat.id, update.message.message_id
        )

    if file_id:
        # Store file_id in context
        context.user_data["file_id"] = file_id

        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(VIDEO_RECEIVED, reply_markup=reply_markup)
        return WAITING_FOR_CONFIRMATION
    else:
        await update.message.reply_text(
            REQUEST_VIDEO, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VIDEO


async def confirm_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle media confirmation."""
    text = update.message.text
    await delete_user_message(update.message)
    if text == CONFIRM_BUTTON:
        await update.message.reply_text(
            VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
        )
        # Create task with file_id
        try:
            file_id = context.user_data.get("file_id")
            if file_id:
                student_tg_id = update.effective_user.id
                task = create_task(student_tg_id=student_tg_id, file_id=file_id)
                # Send task notification to mentor if they have tg_id
                if task and task.mentor_id:
                    mentor = get_by_id(task.mentor_id)
                    if mentor and mentor.tg_id:
                        try:
                            # Send invitation message with button
                            keyboard = get_check_task_keyboard(task.id)
                            await context.bot.send_message(
                                chat_id=mentor.tg_id,
                                text=MENTOR_NEW_TASK_NOTIFICATION,
                                reply_markup=keyboard,
                            )
                            logger.info(
                                f"Sent task notification to mentor {mentor.id} (tg_id: {mentor.tg_id})"
                            )
                        except Exception as e:
                            mark_task_as_failed(task.id)
                            logger.error(
                                f"Failed to send task notification to mentor {task.mentor_id}: {e}"
                            )
            else:
                logger.warning("No file_id found in context when confirming")
                await send_error_message(update)
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            await send_error_message(update)
        context.user_data.clear()
        return ConversationHandler.END
    elif text == CANCEL_BUTTON:
        # Clear the stored file_id since user wants to send again
        context.user_data.pop("file_id", None)
        await update.message.reply_text(
            REQUEST_VIDEO, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VIDEO

    await update.message.reply_text(
        VIDEO_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_CONFIRMATION


async def cancel_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the video conversation."""
    await delete_user_message(update.message)
    await update.message.reply_text(VIDEO_CANCELLED, reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


def create_message_reference(chat_id: int, message_id: int) -> str:
    """Create a message reference string to store in file_id field."""
    return f"msg:{json.dumps({'chat_id': chat_id, 'message_id': message_id})}"


# ============== Visit Card Flow ==============


async def send_visit_card_message(
    visit_card: VisitCardDetails | None,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Send visit card task to student and prompt for video."""
    if not visit_card:
        await update.message.reply_text(
            STUDENT_NO_TASK, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        return ConversationHandler.END

    message = VISIT_CARD_TASK.format(text=visit_card.text)
    await update.message.reply_text(
        message, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        REQUEST_VISIT_CARD_VIDEO, reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_VISIT_CARD_VIDEO


MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB - Telegram Bot API download limit


async def receive_visit_card_video(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle received media for visit card - accepts video, video_note, or video document."""
    file_id = None
    file_size = None

    # Accept video, video_note, or document with video mime type
    if update.message.video:
        file_id = update.message.video.file_id
        file_size = update.message.video.file_size
    elif update.message.video_note:
        file_id = update.message.video_note.file_id
        file_size = update.message.video_note.file_size
    elif update.message.document:
        mime_type = update.message.document.mime_type or ""
        if mime_type.startswith("video/"):
            file_id = update.message.document.file_id
            file_size = update.message.document.file_size
        else:
            await update.message.reply_text(
                INVALID_MEDIA_TYPE, reply_markup=ReplyKeyboardRemove()
            )
            return WAITING_FOR_VISIT_CARD_VIDEO
    else:
        # Reject all other media types
        await update.message.reply_text(
            INVALID_MEDIA_TYPE, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VISIT_CARD_VIDEO

    # Check file size limit (Telegram Bot API can only download files up to 20 MB)
    if file_size and file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            FILE_TOO_LARGE, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VISIT_CARD_VIDEO

    if file_id:
        context.user_data["visit_card_file_id"] = file_id
        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(
            VISIT_CARD_VIDEO_RECEIVED, reply_markup=reply_markup
        )
        return WAITING_FOR_VISIT_CARD_CONFIRMATION

    await update.message.reply_text(
        REQUEST_VISIT_CARD_VIDEO, reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_VISIT_CARD_VIDEO


async def confirm_visit_card_video(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle visit card video confirmation."""
    from crm.crm_service import (
        upload_file_to_lead,
        update_lead_status_by_lead,
        get_crm_lead,
    )
    from config import CRM_VISIT_CARD_IS_SENT_STATUS
    from database.user_service import find_by_tg_id

    text = update.message.text
    await delete_user_message(update.message)

    if text == CONFIRM_BUTTON:
        try:
            file_id = context.user_data.get("visit_card_file_id")

            # Get lead_id from database
            user = find_by_tg_id(update.effective_user.id)
            if not user or not user.crm_id:
                logger.warning(
                    f"User not found or no crm_id for tg_id={update.effective_user.id}"
                )
                await send_error_message(update)
                context.user_data.clear()
                return ConversationHandler.END

            visit_card = get_visit_card(user.crm_id)
            lead_id = visit_card.lead_id if visit_card else None

            if file_id and lead_id:
                # Send uploading message
                uploading_msg = await update.message.reply_text(
                    VISIT_CARD_UPLOADING, reply_markup=ReplyKeyboardRemove()
                )

                # Download video from Telegram
                file = await context.bot.get_file(file_id)
                file_bytes = await file.download_as_bytearray()

                # Upload to AmoCRM
                filename = f"visit_card_{lead_id}.mp4"
                upload_success = upload_file_to_lead(
                    int(lead_id), bytes(file_bytes), filename
                )

                if not upload_success:
                    logger.error(
                        f"Failed to upload visit card video for lead {lead_id}"
                    )
                    await uploading_msg.delete()
                    await send_error_message(update)
                    context.user_data.clear()
                    return ConversationHandler.END

                # Обновляем статус
                lead = get_crm_lead(int(lead_id))
                if lead:
                    update_lead_status_by_lead(lead, CRM_VISIT_CARD_IS_SENT_STATUS)
                    logger.info(
                        f"Updated lead {lead_id} status to CRM_VISIT_CARD_IS_SENT_STATUS"
                    )

                await update.message.reply_text(
                    VISIT_CARD_VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
                )
            else:
                logger.warning("No file_id or lead_id found in context for visit card")
                await send_error_message(update)
        except Exception as e:
            logger.error(f"Error processing visit card video: {e}")
            await send_error_message(update)

        context.user_data.clear()
        return ConversationHandler.END

    elif text == CANCEL_BUTTON:
        context.user_data.pop("visit_card_file_id", None)
        await update.message.reply_text(
            REQUEST_VISIT_CARD_VIDEO, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_VISIT_CARD_VIDEO

    await update.message.reply_text(
        VISIT_CARD_VIDEO_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_VISIT_CARD_CONFIRMATION


# Student conversation handler factory (video submission flow)
def create_student_conversation_handler(
    start_handler: CommandHandler,
) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            start_handler,
        ],
        states={
            WAITING_FOR_VIDEO: [
                MessageHandler(~filters.COMMAND, receive_video),
            ],
            WAITING_FOR_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_video),
            ],
            WAITING_FOR_VISIT_CARD_VIDEO: [
                MessageHandler(~filters.COMMAND, receive_visit_card_video),
            ],
            WAITING_FOR_VISIT_CARD_CONFIRMATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, confirm_visit_card_video
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_video)],
        allow_reentry=True,  # Allow /start to restart conversation
    )
