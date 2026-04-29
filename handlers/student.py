import asyncio

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from logger import setup_logger
import json
from repositories.user_repository import (
    get_task,
    get_visit_card,
    get_test,
    TaskDetails,
    VisitCardDetails,
    TestDetails,
)
from database.homework_service import get_pending_homework_by_student_id
from crm.crm_service import get_crm_lead
from database.models import Homework, HomeworkStatus, User, UserRole
from repositories.task_repository import (
    create_task,
    mark_task_as_failed,
    TaskMessageData,
)
from database.user_service import get_by_id
from database.task_service import get_mentor_task_notification, upsert_mentor_task_notification
from keyboards import (
    get_confirmation_keyboard,
    get_task_review_keyboard,
    get_start_homework_keyboard,
    get_edit_homework_keyboard,
)
from messages import (
    GREETING_WITH_NAME_TEMPLATE,
    STUDENT_NO_TASK,
    TASK,
    TASK_DEADLINE,
    REQUEST_TASK_ANSWER,
    TASK_ANSWER_RECEIVED,
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
    TASK_ANSWERS_REVIEW_HEADER,
    TASK_ANSWERS_REVIEW_QUESTION,
    CHANGE_TASK_1_BUTTON,
    CHANGE_TASK_2_BUTTON,
    CHANGE_TASK_3_BUTTON,
    CONFIRM_ALL_BUTTON,
    HW_NEW_ASSIGNMENT,
    HW_EDIT_NOTIFICATION,
)
from keyboards import get_check_task_keyboard
from handlers.utils import (
    send_error_message,
    delete_user_message,
    send_media_to_chat,
    parse_message_reference,
)

logger = setup_logger(__name__)

# Conversation states (for student flow only)
WAITING_FOR_FIRST_TASK_ANSWER = 1
WAITING_FOR_FIRST_TASK_CONFIRMATION = 2
WAITING_FOR_SECOND_TASK_ANSWER = 3
WAITING_FOR_SECOND_TASK_CONFIRMATION = 4
WAITING_FOR_THIRD_TASK_ANSWER = 5
WAITING_FOR_THIRD_TASK_CONFIRMATION = 6
WAITING_FOR_REVIEW = 7
WAITING_FOR_VISIT_CARD_VIDEO = 8
WAITING_FOR_VISIT_CARD_CONFIRMATION = 9
# Test states
ASKING_QUESTION = 10
ASKING_CASE = 11

# Import test handlers for callback handling (after defining states to avoid circular import)
from handlers.test import handle_question_answer, handle_case_answer


async def handle_student(
    user, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(
        GREETING_WITH_NAME_TEMPLATE.format(name=user.first_name),
        reply_markup=ReplyKeyboardRemove(),
    )

    # Проверяем есть ли задание на прохождение теста
    test = get_test(user)
    if test:
        from handlers.test import start_test

        return await start_test(user, test, update, context)

    # Проверяем есть ли задание на отправку видеовизитки
    visit_card = get_visit_card(user)
    if visit_card:
        return await send_visit_card_message(visit_card, update, context)

    # Проверяем есть ли задание от ментора
    task = get_task(user)
    if task:
        return await send_task_message(task, update, context)

    # Проверяем есть ли домашнее задание
    homework = get_pending_homework_by_student_id(user.id)
    if homework:
        return await send_homework_start_message(homework, update, context)

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

    # Store task details in context
    context.user_data["task_details"] = {
        "first_task": task.first_task,
        "second_task": task.second_task,
        "third_task": task.third_task,
        "lead_id": task.lead_id,
        "deadline": task.deadline,
    }

    # Initialize answers storage with placeholders for existing tasks
    task_answers: dict[str, str | None] = {"1": None}
    if task.second_task:
        task_answers["2"] = None
    if task.third_task:
        task_answers["3"] = None
    context.user_data["task_answers"] = task_answers

    deadline_block = (
        TASK_DEADLINE.format(deadline=task.deadline) if task.deadline else ""
    )
    message = TASK.format(text=task.first_task) + deadline_block
    await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(
        REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
    )
    return WAITING_FOR_FIRST_TASK_ANSWER


async def send_homework_start_message(
    homework: Homework, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if homework.status == HomeworkStatus.EDIT_FROM_MENTOR:
        text = (
            HW_EDIT_NOTIFICATION.format(reason=homework.edit_reason_from_mentor)
            if homework.edit_reason_from_mentor
            else HW_EDIT_NOTIFICATION.split("\n\n")[0]
        )
        await update.message.reply_text(
            text,
            reply_markup=get_edit_homework_keyboard(homework.id),
        )
    elif homework.status == HomeworkStatus.EDIT:
        edit_reason = None
        try:
            loop = asyncio.get_running_loop()
            lead = await loop.run_in_executor(None, get_crm_lead, homework.lead_id)
            if lead:
                edit_reason = getattr(lead, "hw_edit_reason", None)
        except Exception as e:
            logger.warning(f"Failed to fetch edit_reason from CRM for hw={homework.id}: {e}")
        text = (
            HW_EDIT_NOTIFICATION.format(reason=edit_reason)
            if edit_reason
            else HW_EDIT_NOTIFICATION.split("\n\n")[0]
        )
        await update.message.reply_text(
            text,
            reply_markup=get_edit_homework_keyboard(homework.id),
        )
    else:
        await update.message.reply_text(
            HW_NEW_ASSIGNMENT,
            reply_markup=get_start_homework_keyboard(homework.id),
        )
    return ConversationHandler.END


def extract_file_id(update: Update) -> str | None:
    """Extract file_id from different media types."""
    if update.message.video:
        return update.message.video.file_id
    elif update.message.video_note:
        return update.message.video_note.file_id
    elif update.message.audio:
        return update.message.audio.file_id
    elif update.message.document:
        return update.message.document.file_id
    elif update.message.photo:
        # Use the largest photo
        return update.message.photo[-1].file_id
    elif update.message.voice:
        return update.message.voice.file_id
    elif update.message.text:
        # Store message reference instead of converting to file
        return create_message_reference(
            update.effective_chat.id, update.message.message_id
        )
    return None


def _get_next_unanswered_task(
    task_answers: dict[str, str | None], current_task_number: str
) -> str | None:
    """Return next task number with no answer (None) after current, or None."""
    sorted_task_numbers = sorted(task_answers.keys(), key=int)
    try:
        current_index = sorted_task_numbers.index(current_task_number)
    except ValueError:
        return None

    for task_number in sorted_task_numbers[current_index + 1 :]:
        if task_answers.get(task_number) is None:
            return task_number
    return None


def _get_task_text(task_details: dict, task_number: str) -> str:
    """Return the task text for the given task number."""
    mapping = {
        "1": task_details.get("first_task"),
        "2": task_details.get("second_task"),
        "3": task_details.get("third_task"),
    }
    return mapping.get(task_number) or ""


async def receive_first_task_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle received answer for first task."""
    file_id = extract_file_id(update)

    if file_id:
        context.user_data["task_answers"]["1"] = file_id
        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(TASK_ANSWER_RECEIVED, reply_markup=reply_markup)
        return WAITING_FOR_FIRST_TASK_CONFIRMATION
    else:
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_FIRST_TASK_ANSWER


async def receive_second_task_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle received answer for second task."""
    file_id = extract_file_id(update)

    if file_id:
        context.user_data["task_answers"]["2"] = file_id
        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(TASK_ANSWER_RECEIVED, reply_markup=reply_markup)
        return WAITING_FOR_SECOND_TASK_CONFIRMATION
    else:
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_SECOND_TASK_ANSWER


async def receive_third_task_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle received answer for third task."""
    file_id = extract_file_id(update)

    if file_id:
        context.user_data["task_answers"]["3"] = file_id
        reply_markup = get_confirmation_keyboard()
        await update.message.reply_text(TASK_ANSWER_RECEIVED, reply_markup=reply_markup)
        return WAITING_FOR_THIRD_TASK_CONFIRMATION
    else:
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_THIRD_TASK_ANSWER


async def confirm_first_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle first task confirmation."""
    text = update.message.text
    await delete_user_message(update.message)

    if text == CONFIRM_BUTTON:
        task_details = context.user_data.get("task_details", {})
        task_answers = context.user_data.get("task_answers", {})

        next_task = _get_next_unanswered_task(task_answers, "1")
        if next_task:
            task_text = _get_task_text(task_details, next_task)
            deadline_block = (
                TASK_DEADLINE.format(deadline=task_details.get("deadline"))
                if task_details.get("deadline")
                else ""
            )
            message = TASK.format(text=task_text) + deadline_block
            await update.message.reply_text(
                message,
                reply_markup=ReplyKeyboardRemove(),
            )
            await update.message.reply_text(
                REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
            )
            return (
                WAITING_FOR_SECOND_TASK_ANSWER
                if next_task == "2"
                else WAITING_FOR_THIRD_TASK_ANSWER
            )

        # No more unanswered tasks, go to review
        return await show_review_screen(update, context)
    elif text == CANCEL_BUTTON:
        # Reset answer and ask again
        context.user_data["task_answers"]["1"] = None
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_FIRST_TASK_ANSWER

    await update.message.reply_text(
        TASK_ANSWER_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_FIRST_TASK_CONFIRMATION


async def confirm_second_task(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle second task confirmation."""
    text = update.message.text
    await delete_user_message(update.message)

    if text == CONFIRM_BUTTON:
        task_details = context.user_data.get("task_details", {})
        task_answers = context.user_data.get("task_answers", {})

        next_task = _get_next_unanswered_task(task_answers, "2")
        if next_task:
            task_text = _get_task_text(task_details, next_task)
            deadline_block = (
                TASK_DEADLINE.format(deadline=task_details.get("deadline"))
                if task_details.get("deadline")
                else ""
            )
            message = TASK.format(text=task_text) + deadline_block
            await update.message.reply_text(
                message,
                reply_markup=ReplyKeyboardRemove(),
            )
            await update.message.reply_text(
                REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
            )
            return (
                WAITING_FOR_THIRD_TASK_ANSWER
                if next_task == "3"
                else WAITING_FOR_REVIEW
            )

        # No more unanswered tasks, go to review
        return await show_review_screen(update, context)
    elif text == CANCEL_BUTTON:
        # Reset answer and ask again
        context.user_data["task_answers"]["2"] = None
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_SECOND_TASK_ANSWER

    await update.message.reply_text(
        TASK_ANSWER_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_SECOND_TASK_CONFIRMATION


async def confirm_third_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle third task confirmation."""
    text = update.message.text
    await delete_user_message(update.message)

    if text == CONFIRM_BUTTON:
        # All tasks done or changing, go to review
        return await show_review_screen(update, context)
    elif text == CANCEL_BUTTON:
        # Reset answer and ask again
        context.user_data["task_answers"]["3"] = None
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_THIRD_TASK_ANSWER

    await update.message.reply_text(
        TASK_ANSWER_RECEIVED, reply_markup=get_confirmation_keyboard()
    )
    return WAITING_FOR_THIRD_TASK_CONFIRMATION


async def show_review_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show review screen with all answers."""
    task_answers = context.user_data.get("task_answers", {})
    task_details = context.user_data.get("task_details", {})
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        TASK_ANSWERS_REVIEW_HEADER, reply_markup=ReplyKeyboardRemove()
    )

    # Send actual task messages in order
    if "1" in task_answers and task_answers.get("1"):
        await send_media_to_chat(context.bot, chat_id, task_answers["1"])

    if (
        "2" in task_answers
        and task_answers.get("2")
        and task_details.get("second_task")
    ):
        await send_media_to_chat(context.bot, chat_id, task_answers["2"])

    if "3" in task_answers and task_answers.get("3") and task_details.get("third_task"):
        await send_media_to_chat(context.bot, chat_id, task_answers["3"])

    keyboard = get_task_review_keyboard(
        has_task_2=bool(task_details.get("second_task")),
        has_task_3=bool(task_details.get("third_task")),
    )

    await update.message.reply_text(TASK_ANSWERS_REVIEW_QUESTION, reply_markup=keyboard)
    return WAITING_FOR_REVIEW


async def handle_review_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle review screen selection (change or confirm)."""
    text = update.message.text
    await delete_user_message(update.message)
    task_details = context.user_data.get("task_details", {})
    task_answers = context.user_data.get("task_answers", {})

    if text == CONFIRM_ALL_BUTTON:
        # Final confirmation - create task with all answers
        return await finalize_task_submission(update, context)
    elif text == CHANGE_TASK_1_BUTTON:
        context.user_data["task_answers"]["1"] = None
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_FIRST_TASK_ANSWER
    elif text == CHANGE_TASK_2_BUTTON and "2" in task_answers:
        context.user_data["task_answers"]["2"] = None
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_SECOND_TASK_ANSWER
    elif text == CHANGE_TASK_3_BUTTON and "3" in task_answers:
        context.user_data["task_answers"]["3"] = None
        await update.message.reply_text(
            REQUEST_TASK_ANSWER, reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_FOR_THIRD_TASK_ANSWER

    # Invalid selection, show review again
    return await show_review_screen(update, context)


async def finalize_task_submission(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Finalize task submission and create task with all TaskMessages."""
    try:
        task_answers = context.user_data.get("task_answers", {})
        if not task_answers:
            logger.warning("No task answers found when finalizing")
            await send_error_message(update)
            context.user_data.clear()
            return ConversationHandler.END

        # Build TaskMessageData list
        task_messages = [
            TaskMessageData(file_id=file_id, task_number=int(task_num))
            for task_num, file_id in task_answers.items()
            if file_id
        ]

        # Ensure all answers are provided
        expected_count = len(task_answers)
        if len(task_messages) < expected_count:
            logger.warning("Attempted to finalize with missing answers")
            await show_review_screen(update, context)
            return WAITING_FOR_REVIEW

        student_tg_id = update.effective_user.id
        task = create_task(student_tg_id=student_tg_id, task_messages=task_messages)

        # Send task notification to mentor if they have tg_id
        if task and task.mentor_id:
            mentor = get_by_id(task.mentor_id)
            if mentor and mentor.tg_id:
                try:
                    old_notification = get_mentor_task_notification(mentor.id)
                    if old_notification:
                        try:
                            await context.bot.delete_message(
                                chat_id=old_notification.chat_id,
                                message_id=old_notification.message_id,
                            )
                        except Exception:
                            pass

                    keyboard = get_check_task_keyboard(task.id)
                    sent = await context.bot.send_message(
                        chat_id=mentor.tg_id,
                        text=MENTOR_NEW_TASK_NOTIFICATION,
                        reply_markup=keyboard,
                    )

                    upsert_mentor_task_notification(
                        mentor_id=mentor.id,
                        message_id=sent.message_id,
                        chat_id=mentor.tg_id,
                    )
                    logger.info(
                        f"Sent task notification to mentor {mentor.id} (tg_id: {mentor.tg_id})"
                    )
                except Exception as e:
                    mark_task_as_failed(task.id)
                    logger.error(
                        f"Failed to send task notification to mentor {task.mentor_id}: {e}"
                    )

        await update.message.reply_text(
            VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        await send_error_message(update)

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the task conversation."""
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
    from repositories.visit_card_repository import (
        process_visit_card_video,
        VisitCardProcessingError,
    )

    text = update.message.text
    await delete_user_message(update.message)

    if text == CONFIRM_BUTTON:
        file_id = context.user_data.get("visit_card_file_id")

        if not file_id:
            logger.warning("No file_id found in context for visit card")
            await send_error_message(update)
            context.user_data.clear()
            return ConversationHandler.END

        # Send uploading message
        uploading_msg = await update.message.reply_text(
            VISIT_CARD_UPLOADING, reply_markup=ReplyKeyboardRemove()
        )

        try:
            # Download video from Telegram
            file = await context.bot.get_file(file_id)
            file_bytes = await file.download_as_bytearray()

            # Process visit card video (upload to Drive + send to chat)
            await process_visit_card_video(
                telegram_user_id=update.effective_user.id, file_bytes=bytes(file_bytes)
            )

            await uploading_msg.delete()
            await update.message.reply_text(
                VISIT_CARD_VIDEO_CONFIRMED, reply_markup=ReplyKeyboardRemove()
            )

        except VisitCardProcessingError as e:
            logger.error(f"Visit card processing failed: {e}")
            await uploading_msg.delete()
            await send_error_message(update)
        except Exception as e:
            logger.error(
                f"Unexpected error in visit card video handler: {e}", exc_info=True
            )
            await uploading_msg.delete()
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
            WAITING_FOR_FIRST_TASK_ANSWER: [
                MessageHandler(~filters.COMMAND, receive_first_task_answer),
            ],
            WAITING_FOR_FIRST_TASK_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_first_task),
            ],
            WAITING_FOR_SECOND_TASK_ANSWER: [
                MessageHandler(~filters.COMMAND, receive_second_task_answer),
            ],
            WAITING_FOR_SECOND_TASK_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_second_task),
            ],
            WAITING_FOR_THIRD_TASK_ANSWER: [
                MessageHandler(~filters.COMMAND, receive_third_task_answer),
            ],
            WAITING_FOR_THIRD_TASK_CONFIRMATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_third_task),
            ],
            WAITING_FOR_REVIEW: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_review_selection
                ),
            ],
            WAITING_FOR_VISIT_CARD_VIDEO: [
                MessageHandler(~filters.COMMAND, receive_visit_card_video),
            ],
            WAITING_FOR_VISIT_CARD_CONFIRMATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, confirm_visit_card_video
                ),
            ],
            ASKING_QUESTION: [
                CallbackQueryHandler(
                    handle_question_answer, pattern=r"^answer_(yes|no)_\d+$"
                )
            ],
            ASKING_CASE: [
                CallbackQueryHandler(handle_case_answer, pattern=r"^case_\d+_[A-D]$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_task)],
        allow_reentry=True,  # Allow /start to restart conversation
        per_message=False,
        name="student_conversation",
        persistent=True,
        conversation_timeout=60 * 60 * 24 * 3,  # 3 дня
    )
