import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
from database.broadcast_service import (
    get_response_by_id,
    get_response_answers,
    save_answer,
    mark_response_started,
    mark_response_completed,
)
from messages import ERROR_MESSAGE, SURVEY_INTRODUCTION
from keyboards import get_support_keyboard
from repositories.survey_repository import (
    update_survey_lead_on_submit,
    update_survey_lead_status_on_start,
)

logger = setup_logger(__name__)

# Rating thresholds for follow-up questions
RATING_LOW_MAX = 5
RATING_MID_MIN = 6
RATING_MID_MAX = 7
RATING_HIGH_MIN = 8

SURVEY_QUESTIONS = [
    {
        "key": "q1",
        "text": "Оцените насколько наставник был вовлечен на встрече?\n\nГде: 1 - наставник был слабо вовлечён, 10 - наставник был максимально вовлечён, хочется сохранить этот формат.",
        "type": "scale",
        "allow_skip": False,
    },
    {
        "key": "q1_followup_low",
        "text": "Ого, какая низкая оценка, расскажите, пожалуйста в 2-3 тезисах (текстом), чего не хватило на встрече?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q1_followup_mid",
        "text": "Расскажите, чего не хватило на встрече, чтобы было 10 баллов?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q1_followup_high",
        "text": "Спасибо за высокую оценку, поделитесь, по желанию, что больше всего понравилось (текстом)?",
        "type": "text",
        "allow_skip": True,
    },
    {
        "key": "q2",
        "text": "Оцените, на сколько было комфортно на встрече (место, организация, атмосфера).\n\nГде: 10 - всё отлично, 1 - на встрече было не комфортно, важно указать, что именно не понравилось.",
        "type": "scale",
        "allow_skip": False,
    },
    {
        "key": "q2_followup_low",
        "text": "Расскажите, что было некомфортно текстом в 1-2 тезиса или предложения.",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q2_followup_mid",
        "text": "Чего не хватило до 10 баллов комфорта, напишите текстом, пожалуйста.",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q2_followup_high",
        "text": "Спасибо, за высокую оценку! По желанию, расскажите, что было хорошо - текстом 1-2 тезиса.",
        "type": "text",
        "allow_skip": True,
    },
    {
        "key": "q3",
        "text": "Оцените, насколько было полезным и интересным содержание встречи (темы, обсуждения, знания и т. д.)\n\nГде 10 - очень интересно, 1 - бесполезно/неинтересно.",
        "type": "scale",
        "allow_skip": False,
    },
    {
        "key": "q3_followup_low",
        "text": "Что не понравилось, чего не хватило или что было лишним? Ответьте, текстом в сообщении, пожалуйста.",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q3_followup_mid",
        "text": "Чего не хватило для 10 баллов?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q3_followup_high",
        "text": "Спасибо за высокую оценку. Поделитесь, по желанию, что больше всего понравилось (текстом)?",
        "type": "text",
        "allow_skip": True,
    },
    {
        "key": "q4",
        "text": "*Хотите ещё что-то добавить? Здесь можно оставить пожелания, выразить благодарность или поделиться еще чем-то важным.*\nНапишите сообщением боту.",
        "type": "text",
        "allow_skip": True,
    },
]

# Conversation states - dynamic based on question count
ANSWERING_QUESTION = 1


def get_survey_question(question_index: int) -> dict | None:
    """Get question by index."""
    if 0 <= question_index < len(SURVEY_QUESTIONS):
        return SURVEY_QUESTIONS[question_index]
    return None


def create_question_keyboard(question: dict) -> InlineKeyboardMarkup | None:
    """Create keyboard for question based on type."""
    question_type = question.get("type")
    keyboard = []

    if question_type == "buttons":
        options = question.get("options", [])
        for option in options:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        option, callback_data=f"answer_{question['key']}_{option}"
                    )
                ]
            )
        if question.get("allow_skip", False):
            keyboard.append(
                [InlineKeyboardButton("Пропустить", callback_data=f"skip_{question['key']}")]
            )

    elif question_type == "scale":
        # Create scale 1-10
        scale_row = []
        for i in range(1, 11):
            scale_row.append(
                InlineKeyboardButton(str(i), callback_data=f"answer_{question['key']}_{i}")
            )
            if len(scale_row) == 5:
                keyboard.append(scale_row)
                scale_row = []
        if scale_row:
            keyboard.append(scale_row)
        if question.get("allow_skip", False):
            keyboard.append(
                [InlineKeyboardButton("Пропустить", callback_data=f"skip_{question['key']}")]
            )

    elif question_type == "text":
        # For text questions, add skip button if allowed
        if question.get("allow_skip", False):
            keyboard.append(
                [InlineKeyboardButton("Пропустить", callback_data=f"skip_{question['key']}")]
            )
            return InlineKeyboardMarkup(keyboard)
        return None

    if keyboard:
        return InlineKeyboardMarkup(keyboard)
    return None


async def start_survey(
    update: Update, context: ContextTypes.DEFAULT_TYPE, response_id: int
) -> int:
    """Start survey for a user."""
    response = get_response_by_id(response_id)
    if not response:
        await update.message.reply_text(ERROR_MESSAGE, reply_markup=get_support_keyboard())
        return ConversationHandler.END

    # Mark as started
    mark_response_started(response_id)

    # Update CRM lead status when the user starts the survey.
    try:
        tg_id = response.user_tg_id
        tg_nickname = update.effective_user.username if update.effective_user else None

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            update_survey_lead_status_on_start,
            tg_id,
            tg_nickname,
            response.broadcast_id,
        )
    except Exception as e:
        logger.warning(
            "CRM survey lead status update failed on start for tg_id=%s: %s",
            response.user_tg_id,
            e,
        )

    context.user_data["response_id"] = response_id
    context.user_data["current_question"] = 0

    # Show first question
    return await show_next_question(update, context)


async def show_next_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Show next question or complete survey."""
    question_index = context.user_data.get("current_question", 0)
    question = get_survey_question(question_index)

    if not question:
        # No more questions - complete survey
        return await complete_survey(update, context)

    question_text = question.get("text", "")
    keyboard = create_question_keyboard(question)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            question_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(question_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    return ANSWERING_QUESTION


async def handle_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle user's answer to a question."""
    query = update.callback_query
    if not query:
        return ANSWERING_QUESTION

    await query.answer()

    response_id = context.user_data.get("response_id")
    if not response_id:
        return ConversationHandler.END

    question_index = context.user_data.get("current_question", 0)
    question = get_survey_question(question_index)
    if not question:
        return ConversationHandler.END

    callback_data = query.data

    # Handle skip
    if callback_data.startswith("skip_"):
        # If skipping a follow-up question, jump to next main question
        if "_followup_" in question["key"]:
            base_key = question["key"].split("_")[0]
            next_main_question_num = int(base_key[1]) + 1
            next_main_key = f"q{next_main_question_num}"
            
            for idx, q in enumerate(SURVEY_QUESTIONS):
                if q["key"] == next_main_key:
                    context.user_data["current_question"] = idx
                    return await show_next_question(update, context)
        
        # For non-follow-up questions, just move to next
        context.user_data["current_question"] = question_index + 1
        return await show_next_question(update, context)

    # Handle answer
    if callback_data.startswith(f"answer_{question['key']}_"):
        answer_value = callback_data.split("_")[-1]

        # Save answer
        if question.get("type") == "scale":
            rating = int(answer_value)
            save_answer(response_id, question["key"], answer_text=None, answer_value=rating)
            
            # Determine which follow-up question to show based on rating
            if question["key"] in ["q1", "q2", "q3"]:
                if 1 <= rating <= RATING_LOW_MAX:
                    followup_suffix = "_followup_low"
                elif RATING_MID_MIN <= rating <= RATING_MID_MAX:
                    followup_suffix = "_followup_mid"
                else:  # RATING_HIGH_MIN-10
                    followup_suffix = "_followup_high"
                
                # Find the index of the appropriate follow-up question
                followup_key = question["key"] + followup_suffix
                for idx, q in enumerate(SURVEY_QUESTIONS):
                    if q["key"] == followup_key:
                        context.user_data["current_question"] = idx
                        return await show_next_question(update, context)
        else:
            save_answer(response_id, question["key"], answer_text=answer_value, answer_value=None)

        # Move to next question (for non-scale or if no follow-up found)
        context.user_data["current_question"] = question_index + 1
        return await show_next_question(update, context)

    return ANSWERING_QUESTION


async def handle_text_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle text answer input."""
    if not update.message:
        return ANSWERING_QUESTION

    response_id = context.user_data.get("response_id")
    if not response_id:
        return ConversationHandler.END

    question_index = context.user_data.get("current_question", 0)
    question = get_survey_question(question_index)
    if not question or question.get("type") != "text":
        return ANSWERING_QUESTION

    answer_text = update.message.text

    # Save answer
    save_answer(response_id, question["key"], answer_text=answer_text, answer_value=None)

    # If this is a follow-up question, skip to the next main question
    if "_followup_" in question["key"]:
        # Extract the base question number (q1, q2, q3)
        base_key = question["key"].split("_")[0]
        
        # Find the next main question after all follow-ups
        next_main_question_num = int(base_key[1]) + 1
        next_main_key = f"q{next_main_question_num}"
        
        # Find the index of the next main question
        for idx, q in enumerate(SURVEY_QUESTIONS):
            if q["key"] == next_main_key:
                context.user_data["current_question"] = idx
                return await show_next_question(update, context)
    
    # Move to next question (for non-follow-up questions)
    context.user_data["current_question"] = question_index + 1
    return await show_next_question(update, context)


async def complete_survey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Mark survey as completed."""
    response_id = context.user_data.get("response_id")
    if not response_id:
        return ConversationHandler.END

    mark_response_completed(response_id)

    completion_message = "Спасибо за Ваши ответы!"
    
    # Create submit button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить ответы", callback_data=f"submit_survey_{response_id}")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(completion_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(completion_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    context.user_data.clear()
    return ConversationHandler.END


async def handle_start_survey_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle start survey callback."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()

    try:
        response_id = int(query.data.split("_")[-1])
        return await start_survey(update, context, response_id)
    except (ValueError, IndexError) as e:
        logger.error(f"Invalid start_survey callback data: {query.data}")
        await query.message.reply_text(ERROR_MESSAGE, reply_markup=get_support_keyboard())
        return ConversationHandler.END


async def handle_submit_survey(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle survey submission confirmation."""
    query = update.callback_query
    if not query:
        return

    await query.answer("Ваши ответы отправлены!")
    try:
        response_id = int(query.data.split("_")[-1])
        response = get_response_by_id(response_id)
        if response:
            answers = get_response_answers(response_id)
            answer_dict = {a.question_key: a for a in answers}

            def _extract_scale_text(scale_key: str) -> str | None:
                scale_answer = answer_dict.get(scale_key)
                scale_rating = (
                    scale_answer.answer_value if scale_answer else None
                )
                return str(scale_rating) if scale_rating is not None else None

            def _extract_followup_text(
                followup_keys: list[str],
            ) -> str | None:
                for k in followup_keys:
                    a = answer_dict.get(k)
                    if a and a.answer_text:
                        return a.answer_text
                return None

            q1_text = _extract_scale_text("q1")
            q1_addition_text = _extract_followup_text(
                ["q1_followup_low", "q1_followup_mid", "q1_followup_high"]
            )
            q2_text = _extract_scale_text("q2")
            q2_addition_text = _extract_followup_text(
                ["q2_followup_low", "q2_followup_mid", "q2_followup_high"]
            )
            q3_text = _extract_scale_text("q3")
            q3_addition_text = _extract_followup_text(
                ["q3_followup_low", "q3_followup_mid", "q3_followup_high"]
            )

            q4_answer = answer_dict.get("q4")
            q4_text = q4_answer.answer_text if q4_answer else None
            q4_addition_text = None

            tg_nickname = (
                update.effective_user.username if update.effective_user else None
            )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                update_survey_lead_on_submit,
                response.user_tg_id,
                tg_nickname,
                response.broadcast_id,
                q1_text,
                q2_text,
                q3_text,
                q4_text,
                q1_addition_text,
                q2_addition_text,
                q3_addition_text,
                q4_addition_text,
            )
    except Exception as e:
        logger.warning("CRM survey update failed on submit: %s", e, exc_info=True)

    await query.edit_message_text(
        "✅ Спасибо! Ваши ответы успешно отправлены."
    )


# Conversation handler for survey questions
survey_questions_handler = ConversationHandler(
    name="survey_questions",
    persistent=True,
    allow_reentry=True,
    entry_points=[
        CallbackQueryHandler(
            handle_start_survey_callback,
            pattern="^start_survey_\\d+$",
        )
    ],
    states={
        ANSWERING_QUESTION: [
            CallbackQueryHandler(handle_answer, pattern="^(answer_|skip_)"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer),
        ],
    },
    fallbacks=[
        MessageHandler(filters.COMMAND, lambda u, c: ConversationHandler.END),
    ],
)

# Handler for submit survey button (outside conversation)
submit_survey_handler = CallbackQueryHandler(
    handle_submit_survey,
    pattern="^submit_survey_\\d+$",
)
