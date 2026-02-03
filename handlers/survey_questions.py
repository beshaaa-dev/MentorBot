from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from logger import setup_logger
from database.broadcast_service import (
    get_broadcast_by_id,
    get_response_by_id,
    save_answer,
    mark_response_started,
    mark_response_completed,
)
from messages import ERROR_MESSAGE
from keyboards import get_support_keyboard

logger = setup_logger(__name__)

SURVEY_QUESTIONS = [
    {
        "key": "q1",
        "text": "Оцени насколько наставник был вовлечен на встрече?",
        "type": "scale",
        "allow_skip": False,
    },
    {
        "key": "q1_followup_low",
        "text": "Расскажи, чего не хватило",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q1_followup_mid",
        "text": "Чего не хватило до 10 баллов?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q1_followup_high",
        "text": "Что больше всего понравилось",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q2",
        "text": "Оцени на сколько было комфортно на встрече (место, организация, атмосфера)",
        "type": "scale",
        "allow_skip": False,
    },
    {
        "key": "q2_followup_low",
        "text": "Что не понравилось?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q2_followup_mid",
        "text": "Что хотелось бы улучшить?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q2_followup_high",
        "text": "Что понравилось",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q3",
        "text": "Оцени, содержание встречи (темы, обсуждения, знания и т. д.)",
        "type": "scale",
        "allow_skip": False,
    },
    {
        "key": "q3_followup_low",
        "text": "Что не понравилось, чего не хватило или что было лишним?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q3_followup_mid",
        "text": "Чего не хватило?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q3_followup_high",
        "text": "Что понравилось?",
        "type": "text",
        "allow_skip": False,
    },
    {
        "key": "q4",
        "text": "Здесь можно ещё что-то добавить, если хочется",
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
        # No keyboard - wait for text input
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
            question_text, reply_markup=keyboard
        )
    else:
        await update.message.reply_text(question_text, reply_markup=keyboard)

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
                if 1 <= rating <= 5:
                    followup_suffix = "_followup_low"
                elif 6 <= rating <= 7:
                    followup_suffix = "_followup_mid"
                else:  # 8-10
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

    completion_message = "Спасибо! Опрос завершен."

    if update.callback_query:
        await update.callback_query.edit_message_text(completion_message)
    else:
        await update.message.reply_text(completion_message)

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
