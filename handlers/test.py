from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
)
from logger import setup_logger
from messages import TEST_TASK_TEXT
from repositories.test_repository import (
    save_test_results,
    send_test_results_to_crm,
    update_lead_status_to_in_progress,
    update_lead_status_to_visit_card,
    update_contact_test_scores,
    TestScores,
)

logger = setup_logger(__name__)

# Данные теста из test.md
TEST_QUESTIONS = [
    "Мне легко признать ошибку перед другим человеком.",
    "Иногда я скрываю ошибки, чтобы избежать неприятных последствий.",
    "Я часто соглашаюсь, чтобы не спорить, даже если думаю иначе.",
    "Я умею спокойно выслушивать честную обратную связь.",
    "Мне бывает трудно и стыдно признать, что я чего-то не знаю, или что я не справился.",
    "Мне иногда бывает трудно начать дело, даже если оно важно.",
    "Когда меня что-то по-настоящему интересует, я могу долго разбираться сам.",
    "Когда мне становится сложно, я быстро теряю интерес.",
    "Мне важно развиваться, даже если результат виден не сразу.",
    "Похоже на то, что я нередко делаю что-то только ради оценки или одобрения.",
    "Я точно не буду общаться с человеком, который ни к чему не стремится.",
    "Мне интересно обсуждать с людьми, какие книги они прочитали, какие курсы прошли.",
    "Я обычно довожу начатое дело до конца.",
    "Нередко бывает, что я откладываю важные дела.",
    "Если я пообещал, то я выполняю; если я не уверен, то я не буду давать обещание.",
    "Если мне не напомнят, то я могу забывать о задачах, которые необходимо сделать.",
    "Если мне что-то необходимо сделать, то я делаю это без напоминаний.",
    "В новой компании мне комфортно начинать разговор первым.",
    "В компании незнакомых людей я часто молчу, потому что боюсь сказать что-то не то.",
    "В команде я стараюсь помогать другим.",
    "Я избегаю групповых задач, мне больше нравится работать в одиночку.",
    "Мне нравится работать вместе с кем-то, потому что даже если я не сделаю свою часть задач, то это могут сделать другие.",
    "В сложной ситуации я могу сохранять ясность мыслей.",
    "Когда меня критикуют, я долго переживаю.",
    "Если что-то идёт не так, я довольно быстро восстанавливаюсь.",
    "Я обязательно выполняю взятые на себя обязательства, даже если задача перестала мне нравиться.",
    "Я быстро теряю интерес, если задача становится рутинной.",
    "Даже когда нет вдохновения, я могу продолжать работу.",
    "Мне интересно быть частью долгосрочного проекта.",
    "Я могу пропустить важную встречу, если нет настроения.",
]

# Реверсивные вопросы (где Нет = 1 балл)
REVERSE_QUESTIONS = {2, 3, 5, 6, 8, 10, 14, 16, 19, 21, 22, 24, 27, 30}

# Границы блоков (индексы вопросов, начиная с 1)
BLOCK_RANGES = [
    (1, 6),  # Блок 1: вопросы 1-6
    (7, 12),  # Блок 2: вопросы 7-12
    (13, 17),  # Блок 3: вопросы 13-17
    (18, 22),  # Блок 4: вопросы 18-22
    (23, 25),  # Блок 5: вопросы 23-25
    (26, 30),  # Блок 6: вопросы 26-30
]

CASE_STUDIES = [
    {
        "title": "Кейс 1. «Срыв дедлайна в команде»",
        "description": (
            "Команда должна подготовить идею мини-проекта к встрече с наставником завтра утром. "
            "Вы заранее договорились распределить задачи, но к вечеру двое участников не отвечают, "
            "а один пишет, что «не успеет, потому что много уроков». Вы понимаете, что если ничего "
            "не сделать сейчас, команда провалится на встрече. Наставник сегодня недоступен.\n\n"
            "Ваше действие:"
        ),
        "options": [
            "A) Жду — ответственность у команды общая, это не моя задача.",
            "B) Напомню ещё раз в чате и подожду, что ответят.",
            "C) Возьму на себя инициативу, соберу имеющиеся идеи и подготовлю рабочий черновик, чтобы команда могла доработать.",
            "D) Напишу взрослым/организаторам, чтобы они решили, как поступить.",
        ],
    },
    {
        "title": "Кейс 2: «Недопонимание в команде»",
        "description": (
            "Команда готовит общее задание. Двое участников по-разному поняли, что нужно делать:\n"
            "- Один собирает данные, другой делает презентацию.\n"
            "- Оба уверены, что правы, спорят и обвиняют друг друга в «непонимании наставника».\n"
            "- Оставшаяся часть команды замолкла, работа остановилась. До сдачи задания — два часа. Наставник на встрече и не отвечает.\n\n"
            "Ваше действие:"
        ),
        "options": [
            "A) Пусть сами разберутся — это их ответственность.",
            "B) Скажу каждому продолжать свою версию, а потом решим, какая лучше.",
            "C) Останавливаю обсуждение, уточняю цель задания и вместе с командой договариваюсь о едином формате работы.",
            "D) Быстро выбираю один из вариантов и прошу всех следовать ему, чтобы не терять время.",
        ],
    },
]

PROFILE_FEEDBACK = {
    "Внутренняя опора": (
        "🟢 *ПРОФИЛЬ «ВНУТРЕННЯЯ ОПОРА»*\n\n"
        "По результатам теста у тебя сформирована устойчивая внутренняя база. "
        "Ты умеешь опираться на себя, понимать свои действия и сохранять включённость в важных для тебя задачах.\n\n"
        "Ты особенно хорошо раскрываешься, когда:\n"
        "• Задачи имеют понятную цель и длительный горизонт;\n"
        "• Есть возможность брать на себя ответственность;\n"
        "• Задачи требуют последовательности и самостоятельности;\n"
        "• Необходимо договариваться и работать вместе;\n"
        "• Ритм работы остаётся стабильным и понятным."
    ),
    "Движение и поиск": (
        "🟡 *ПРОФИЛЬ «ДВИЖЕНИЕ И ПОИСК»*\n\n"
        "Результаты теста показывают, что твоя включённость во многом зависит от смысла и условий, в которых ты действуешь.\n\n"
        "Ты особенно хорошо раскрываешься, когда:\n"
        "• Понимаешь, зачем нужна задача и какой ожидается результат;\n"
        "• Есть чёткая структура и понятные шаги;\n"
        "• Можно задавать вопросы и прояснять детали;\n"
        "• Рядом поддерживающая среда;\n"
        "• Сохраняется ощущение смысла в происходящем."
    ),
    "Ресурс и чувствительность": (
        "🔵 *ПРОФИЛЬ «РЕСУРС И ЧУВСТВИТЕЛЬНОСТЬ»*\n\n"
        "По результатам теста видно, что ты внимательно относишься к своему состоянию и сильно реагируешь на нагрузку и атмосферу вокруг.\n\n"
        "Ты особенно хорошо раскрываешься, когда:\n"
        "• Задача вызывает интерес или эмоциональный отклик;\n"
        "• Понятен смысл происходящего;\n"
        "• Учитывается твой темп и состояние;\n"
        "• Среда остаётся спокойной и поддерживающей;\n"
        "• Есть возможность обсудить свои мысли и чувства.\n\n"
        "Тест не является диагнозом и не указывает на «хорошо»/«плохо», а показывает текущие способы реагирования."
    ),
}


async def start_test(
    user, test_details, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    from handlers.student import ASKING_QUESTION, ASKING_CASE

    context.user_data["test_user"] = user
    context.user_data["test_lead_id"] = test_details.lead_id
    context.user_data["test_answers"] = []
    context.user_data["current_question"] = 0

    try:
        update_lead_status_to_in_progress(test_details.lead_id)
    except Exception as e:
        logger.error(f"Failed to update lead status: {e}")

    await update.message.reply_text(TEST_TASK_TEXT, parse_mode="Markdown")

    return await ask_next_question(update, context)


async def ask_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from handlers.student import ASKING_QUESTION

    question_num = context.user_data.get("current_question", 0)

    if question_num < len(TEST_QUESTIONS):
        question_text = TEST_QUESTIONS[question_num]

        keyboard = [
            [
                InlineKeyboardButton("Да", callback_data=f"answer_yes_{question_num}"),
                InlineKeyboardButton("Нет", callback_data=f"answer_no_{question_num}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message_text = f"*Вопрос {question_num + 1} из 30*\n\n{question_text}"

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message_text, reply_markup=reply_markup, parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                message_text, reply_markup=reply_markup, parse_mode="Markdown"
            )

        return ASKING_QUESTION
    else:
        return await ask_first_case(update, context)


async def handle_question_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    from handlers.student import ASKING_QUESTION
    
    query = update.callback_query
    await query.answer()

    data = query.data

    if not data.startswith("answer_"):
        logger.warning(f"Invalid question answer callback data: {data}")
        return ASKING_QUESTION

    try:
        question_num_from_callback = int(data.split("_")[-1])
        current_question = context.user_data.get("current_question", 0)

        if question_num_from_callback != current_question:
            logger.warning(
                f"Question number mismatch: expected {current_question}, got {question_num_from_callback}"
            )
            return ASKING_QUESTION
    except (ValueError, IndexError):
        logger.error(f"Failed to parse question number from callback data: {data}")
        return ASKING_QUESTION

    answer = "Да" if "yes" in data else "Нет"

    # Defensive check for test_answers
    if "test_answers" not in context.user_data:
        logger.error("test_answers not found in user_data")
        return ConversationHandler.END
    
    context.user_data["test_answers"].append(answer)
    context.user_data["current_question"] = context.user_data.get("current_question", 0) + 1

    return await ask_next_question(update, context)


async def ask_first_case(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["current_case"] = 0
    return await ask_case(update, context)


async def ask_case(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from handlers.student import ASKING_CASE

    case_num = context.user_data.get("current_case", 0)

    if case_num < len(CASE_STUDIES):
        case = CASE_STUDIES[case_num]

        keyboard = [
            [InlineKeyboardButton(opt[0], callback_data=f"case_{case_num}_{opt[0]}")]
            for opt in case["options"]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        options_text = "\n".join(case["options"])
        message_text = f"*{case['title']}*\n\n{case['description']}\n\n{options_text}"

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message_text, reply_markup=reply_markup, parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                message_text, reply_markup=reply_markup, parse_mode="Markdown"
            )

        return ASKING_CASE
    else:
        return await calculate_and_send_results(update, context)


async def handle_case_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from handlers.student import ASKING_CASE
    
    query = update.callback_query
    await query.answer()

    data = query.data

    if not data.startswith("case_"):
        logger.warning(f"Invalid case answer callback data: {data}")
        return ASKING_CASE

    try:
        parts = data.split("_")
        case_num_from_callback = int(parts[1])
        current_case = context.user_data.get("current_case", 0)

        if case_num_from_callback != current_case:
            logger.warning(
                f"Case number mismatch: expected {current_case}, got {case_num_from_callback}"
            )
            return ASKING_CASE
    except (ValueError, IndexError):
        logger.error(f"Failed to parse case number from callback data: {data}")
        return ASKING_CASE

    answer = data.split("_")[-1]

    # Defensive check for test_answers
    if "test_answers" not in context.user_data:
        logger.error("test_answers not found in user_data")
        return ConversationHandler.END
    
    context.user_data["test_answers"].append(answer)
    context.user_data["current_case"] = context.user_data.get("current_case", 0) + 1

    return await ask_case(update, context)


async def calculate_and_send_results(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.callback_query.edit_message_text("Грузим результаты...")

    # Defensive checks for required user_data
    answers = context.user_data.get("test_answers")
    user = context.user_data.get("test_user")
    lead_id = context.user_data.get("test_lead_id")
    
    if not answers or not user or not lead_id:
        logger.error(f"Missing required data: answers={bool(answers)}, user={bool(user)}, lead_id={bool(lead_id)}")
        await update.callback_query.edit_message_text(
            "Произошла ошибка при обработке результатов. Попробуйте начать тест заново."
        )
        return ConversationHandler.END
    
    # Validate we have all answers (30 questions + 2 cases)
    if len(answers) != 32:
        logger.error(f"Invalid number of answers: expected 32, got {len(answers)}")
        await update.callback_query.edit_message_text(
            "Произошла ошибка при обработке результатов. Попробуйте начать тест заново."
        )
        return ConversationHandler.END

    block_scores = []
    for start, end in BLOCK_RANGES:
        score = 0
        for i in range(start - 1, end):
            question_num = i + 1
            answer = answers[i]

            if question_num in REVERSE_QUESTIONS:
                score += 1 if answer == "Нет" else 0
            else:
                score += 1 if answer == "Да" else 0

        block_scores.append(score)

    case1_answer = answers[30]
    case2_answer = answers[31]

    # Кейс 1 scoring
    case1_scores = {"A": 1, "B": 2, "C": 4, "D": 3}
    case1_score = case1_scores.get(case1_answer, 0)

    # Кейс 2 scoring
    case2_scores = {"A": 1, "B": 2, "C": 4, "D": 3}
    case2_score = case2_scores.get(case2_answer, 0)

    total_score = sum(block_scores) + case1_score + case2_score

    if total_score >= 24:
        profile_type = "Внутренняя опора"
    elif total_score >= 18:
        profile_type = "Движение и поиск"
    else:
        profile_type = "Ресурс и чувствительность"

    # # Case 1 explanation
    # case1_explanations = {
    #     "A": "низкая инициативность и попустительство (низкая включенность в общее дело)",
    #     "B": "средне-низкая инициативность, средняя включенность",
    #     "C": "высокая инициативность, высокая включенность",
    #     "D": "средне-высокая инициативность, средне-высокая включенность"
    # }
    # case1_explanation = case1_explanations.get(case1_answer, "")
    #
    # # Case 2 explanation
    # case2_explanations = {
    #     "A": "низкие коммуникативные навыки, низкая целенаправленность, орг способности и умение мыслить в понятиях результата",
    #     "B": "средне-низкие коммуникативные навыки, средне-низкая целенаправленность, орг способности и умение мыслить в понятиях результата",
    #     "C": "высокие коммуникативные навыки, высокая целенаправленность, орг способности и умение мыслить в понятиях результата",
    #     "D": "средне-высокие коммуникативные навыки, средне-высокая целенаправленность, орг способности и умение мыслить в понятиях результата"
    # }
    # case2_explanation = case2_explanations.get(case2_answer, "")

    scores = TestScores(
        block1_score=block_scores[0],
        block2_score=block_scores[1],
        block3_score=block_scores[2],
        block4_score=block_scores[3],
        block5_score=block_scores[4],
        block6_score=block_scores[5],
        case1_score=case1_score,
        case2_score=case2_score,
        total_score=total_score,
        profile_type=profile_type,
    )

    save_test_results(user.id, lead_id, scores)

    try:
        send_test_results_to_crm(
            user.id, lead_id, scores, answers, case1_answer, case2_answer
        )
    except Exception as e:
        logger.error(f"Failed to send test results to CRM: {e}")

    try:
        update_contact_test_scores(int(user.crm_id), scores)
    except Exception as e:
        logger.error(f"Failed to update contact test scores: {e}")

    try:
        update_lead_status_to_visit_card(lead_id)
    except Exception as e:
        logger.error(f"Failed to update lead status after test: {e}")

    feedback = PROFILE_FEEDBACK[profile_type]

    # # Build complete feedback with case explanations
    # complete_feedback = f"*Тест завершён!*\n\n{feedback}\n\n"
    #
    # if case1_explanation:
    #     complete_feedback += f"*Кейс 1 ({case1_score} балла):* {case1_explanation}\n\n"
    #
    # if case2_explanation:
    #     complete_feedback += f"*Кейс 2 ({case2_score} балла):* {case2_explanation}"

    await update.callback_query.edit_message_text(
        f"*Тест завершён!*\n\n{feedback}", parse_mode="Markdown"
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Тест отменён.")
    context.user_data.clear()
    return ConversationHandler.END
