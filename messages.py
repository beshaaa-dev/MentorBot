from config import SUPPORT_CONTACT_LINK

ERROR_MESSAGE = "Что-то пошло не так. Введите команду /start и попробуйте еще раз. Если ошибка повторится, то обратитесь в поддержку."
SUPPORT_BUTTON_TEXT = "Написать в поддержку"
TASK_CHECKING = "Проверяем задание..."
MENTOR_GREETING_TEMPLATE = "Привет! Проверяем новые работы студентов"
CHECK_TASKS_BUTTON = "Проверить задания"
INVITE_FRIEND_BUTTON = "Пригласить друга"
INVITE_FRIEND_LINK_MESSAGE = "Вот твоя реферальная ссылка 🔗\n\n<code>{link}</code>\n\nНажми на ссылку, чтобы скопировать её."
INVITE_FRIEND_NO_LINK = "Реферальная ссылка пока не назначена. Обратись к своему наставнику."
STUDENT_MENU_INFO = """ 
Привет, {name}! Это бот проекта «Поколение».
Выберите действие:
"""
STUDENT_NO_TASK = """
Сейчас задания не отображаются.
Если вы ожидали задание — пожалуйста, напишите своему куратору или в службу заботы: @pokoleniecare
"""
MENTOR_NO_TASK = "Заданий на проверку пока нет."
MENTOR_NOTHING_TO_REVIEW = "Нет ничего на проверку"
TASK = "У вас есть новое задание 🧡\n\n{text}\n\n"
TASK_DEADLINE = "Дедлайн: {deadline} по МСК\n\n"
REQUEST_TASK_ANSWER = "Пожалуйста, отправь ответ."
VIDEO_RECEIVED = "Отправить ответ ментору?"
VIDEO_CONFIRMED = "Ваш ответ отправлен ментору! Ожидайте фидбек"
VIDEO_CANCELLED = "Отправка видео отменена."
CONFIRM_BUTTON = "Да, отправить"
CANCEL_BUTTON = "Нет, попробовать ещё раз"
APPROVE_BUTTON = "Одобрить"
DISAPPROVE_BUTTON = "Отказать"
BACK_BUTTON = "Предыдущие задания"
MENU_INFO = (
    "Вот, что Вы можете сделать в боте:\n\n"
    "• *Проверить новое задание* — проверить следующую работу\n"
    "• *Предыдущие задания* — посмотреть историю и изменить решение\n"
    "• *Отложенные заявки* — вернуться к отложенным работам\n"
    "• *Одобренные заявки* — список участников с принятыми заявками\n"
    "• *Отклонённые заявки* — список участников с отклонёнными заявками"
)
MENTOR_NEW_TASK_NOTIFICATION = "У вас новое задание на проверку!"
CHECK_TASK_BUTTON = "Посмотреть"
NO_PREVIOUS_TASKS = "Проверенных заданий нет."
TASK_STATUS_APPROVED = "✅ Одобрено"
TASK_STATUS_DISAPPROVED = "❌ Отклонено"
TASK_STATUS_UNCHECKED = "👀 Не проверено"
DONE_BUTTON = "Готово"
TO_MENU_BUTTON = "В меню"
APPROVED_STUDENTS_BUTTON = "Одобренные студенты"
DISAPPROVED_STUDENTS_BUTTON = "Отклонённые студенты"
APPROVED_STUDENTS_HEADER = "✅ Одобренные студенты:"
DISAPPROVED_STUDENTS_HEADER = "❌ Отклонённые студенты:"
STUDENT_LIST_EMPTY_MESSAGE = "Список пуст."
STUDENT_LIST_CONTINUATION_LABEL = "Продолжение списка ⬇️"
TASK_INFO_TEMPLATE = (
    "*{student_name}*\n\n" "*Текущий статус*: {status}\n" "*Отправлено*: {created_at}"
)
SUPPORT_MESSAGE = "Если нужна помощь или есть вопрос — напишите в поддержку."
CHECK_NEW_TASK_BUTTON = "Проверить новое задание"
POSTPONE_TASK_BUTTON = "Сомневаюсь"
POSTPONED_TASKS_BUTTON = "Отложенные заявки"
TASK_STATUS_POSTPONED = "🕐 Отложено"
NO_POSTPONED_TASKS = "Отложенных заявок нет."
UNKNOWN_MESSAGE = "Чтобы начать работу с ботом, отправьте /start"

TASK_STATUS_CHANGE_NOT_ALLOWED = (
    "Заявка уже закрыта, поэтому статус изменить невозможно"
)

# Test flow messages
TEST_TASK_TEXT = """Супер, ты на месте 🧡

Сейчас нужно пройти короткий тест.

⏳ Дедлайн: 12 часов
(время уже идёт)

Тест занимает до 10 минут.

Важно:
— отвечай так, как есть на самом деле
— здесь нет правильных или неправильных ответов

Тест — часть первого этапа.
Без него мы не сможем перейти к рассмотрению заявки.

Тест откроется в следующем сообщении 👇
"""

# Visit card flow messages
VISIT_CARD_TASK = "*У вас есть новое задание 🧡*\n\n{text}\n\n"
VISIT_CARD_TEXT = """🎥 Задание — видеовизитка

Отправь видеокружок в Telegram
длительностью до 1 минуты.

В видео ответь на вопрос:
«Короткий случай из жизни, который хорошо тебя характеризует».

Это видео — не отдельный этап, а дополнение к анкете.
Оно помогает нам лучше тебя понять.

Здесь не нужно готовиться или делать идеально.
Можно записать с первого раза, без подготовки — так, как тебе комфортно.

Важно:
— только видеокружок в Telegram
— монтаж не нужен
— видно лицо и хорошо слышно
— отправить видео нужно в этот бот

Если видео не загружается, попробуй включить VPN или проверь соединение с интернетом.

⏳ Дедлайн: 24 часа с момента получения задания.

После отправки заявка перейдёт на этап рассмотрения 🧡
"""
REQUEST_VISIT_CARD_VIDEO = "Пожалуйста, отправьте видео-кружок."
INVALID_MEDIA_TYPE = (
    "Принимаются только видео или кружок. Пожалуйста, попробуйте снова."
)
FILE_TOO_LARGE = "Видео слишком большое (максимум 20 МБ). Пожалуйста, отправьте файл меньшего размера."
VISIT_CARD_VIDEO_RECEIVED = "Отправить видео-визитку?"
VISIT_CARD_UPLOADING = "Загружаем видео..."
VISIT_CARD_VIDEO_CONFIRMED = "Ваша видео-визитка отправлена! Ожидайте ответа."

# Multiple task answers flow messages
TASK_ANSWER_RECEIVED = "Отправить этот ответ?"
TASK_ANSWERS_REVIEW_HEADER = "Вот твои ответы"
TASK_ANSWERS_REVIEW_QUESTION = "Хочешь что-то изменить?"
CHANGE_TASK_1_BUTTON = "Изменить задание 1"
CHANGE_TASK_2_BUTTON = "Изменить задание 2"
CHANGE_TASK_3_BUTTON = "Изменить задание 3"
CONFIRM_ALL_BUTTON = "Всё верно, отправить"

# Homework flow messages
HW_NEW_ASSIGNMENT = "У вас новое домашнее задание 🧡"
HW_QUESTION_PROMPT = "Вопрос {n} из {total}:\n\n{question}"
HW_ANSWER_CONFIRM_PROMPT = "Отправить этот ответ?"
HW_CONFIRM_YES_BUTTON = "Да"
HW_CONFIRM_RETRY_BUTTON = "Нет, попробовать ещё раз"
HW_REVIEW_HEADER = "Ваши ответы на домашнее задание:\n\n{answers}"
HW_REVIEW_CHANGE_PROMPT = "Хотите что-то изменить?"
HW_REVIEW_CHANGE_BUTTON = "Изменить вопрос {n}"
HW_CONFIRM_ALL_BUTTON = "Всё верно, отправить"
HW_SUBMITTED = "Ваше домашнее задание отправлено! Ожидайте обратной связи 🧡"
HW_NOT_FOUND = "Задание не найдено. Введите /start для продолжения."
HW_MEDIA_LABEL = "[медиафайл]"
HW_EDIT_NOTIFICATION = (
    "Ваше домашнее задание отправлено на доработку.\n\nПричина: {reason}"
)
HW_ACCEPTED_NOTIFICATION = "Ваше домашнее задание успешно проверено ✅"
HW_ACCEPTED_RATING = "\nОценка: {rating}/5"
HW_ACCEPTED_FEEDBACK = "\nОбратная связь: {feedback}"
HW_FOR_MENTOR_NOTIFICATION = "Новое домашнее задание для проверки"
HW_CHECK_BUTTON = "Проверить"
HW_NO_PENDING_MENTOR = "Домашних заданий на проверку пока нет."
HW_POSTPONE_BUTTON = "Проверить позже"
HW_FEEDBACK_BUTTON = "Дать обратную связь"
HW_RATE_BUTTON = "Оценить"
HW_REEDIT_BUTTON = "Отправить на доработку"
HW_APPROVE_HW_BUTTON = "Одобрить"
HW_EDIT_FROM_MENTOR_BUTTON = "На доработку"
HW_FEEDBACK_PROMPT = "Введите обратную связь для студента:"
HW_FEEDBACK_CANCELLED = "Ввод обратной связи отменён."
HW_RATE_PROMPT = "Оцените домашнее задание (0–5):"
HW_RATE_SAVED = "Оценка сохранена."
HW_SKIP_BUTTON = "Пропустить"
HW_EDIT_REASON_PROMPT = "Укажите причину возврата на переработку:"
HW_APPROVE_CANCELLED = "Одобрение отменено."
HW_EDIT_FROM_MENTOR_CANCELLED = "Возврат на доработку отменён."
HW_MENTOR_QUESTION_HEADER = "*Вопрос {n}:* {question}"
HW_POSTPONED_HW_HEADER = "Отложенные домашние задания:"

# Mentor homework menu
MENTOR_HW_MENU_INFO = (
    "Вот, что Вы можете сделать:\n\n"
    "• *Проверить новые Д/З* — узнать есть ли домашняя работа на проверке\n"
    "• *Отложенные Д/З* — вернуться к отложенным работам\n"
    "• *История Д/З* — посмотреть уже одобренные работы"
)
MENTOR_HW_CHECK_NEW_BUTTON = "Проверить новые Д/З"
MENTOR_HW_CHECK_POSTPONED_BUTTON = "Отложенные Д/З"
MENTOR_HW_CHECK_HISTORY_BUTTON = "История Д/З"
MENTOR_HW_NO_POSTPONED = "Отложенных Д/З нет."
MENTOR_HW_NO_HISTORY = "Проверенных Д/З нет."
MENTOR_HW_NAV_PREV = "Предыдущее Д/З"
MENTOR_HW_NAV_NEXT = "Следующее Д/З"

# Broadcast system messages
ADMIN_MENU_TITLE = (
    "📋 *Меню администратора*\n\n"
    "Вот что вы можете сделать:\n\n"
    "• *Отправить рассылку* — создать новую рассылку (сообщение или опрос) в выбранные чаты\n"
    "• *Запланированные рассылки* — просмотреть, изменить или отменить запланированные рассылки\n"
    "• *Выгрузить отчет* — получить файл со всеми данными\n\n"
    "Рассылки отправляются участникам чатов через личные сообщения."
)
SEND_BROADCAST_BUTTON = "Отправить рассылку"
SCHEDULED_BROADCASTS_BUTTON = "Запланированные рассылки"
EXPORT_DATA_BUTTON = "Выгрузить отчет"
EXPORT_GENERATING_MESSAGE = "Генерирую файл с данными..."
EXPORT_DATA_CAPTION = "Выгрузка данных"
EXPORT_ERROR_MESSAGE = "Ошибка при генерации файла. Попробуйте позже."

# Survey creation flow messages
SELECT_CHATS_MESSAGE = "Выберите чаты для отправки опроса (можно выбрать несколько):"
NO_CHATS_AVAILABLE = "У вас нет доступа ни к одному чату."
SELECT_BROADCAST_TYPE_MESSAGE = "Выберите тип рассылки:"
MESSAGE_TYPE_BUTTON = "Сообщение"
SURVEY_TYPE_BUTTON = "Опрос"
ENTER_MESSAGE_CONTENT_MESSAGE = "Введите текст сообщения для рассылки:"
MESSAGE_CONTENT_EMPTY_ERROR = (
    "Сообщение не может быть пустым. Пожалуйста, введите текст."
)
MESSAGE_CONTENT_TOO_LONG_ERROR = (
    "Сообщение слишком длинное (максимум 4096 символов). Пожалуйста, сократите текст."
)
SELECT_TIMING_MESSAGE = "Выберите тип отправки:"
SEND_NOW_BUTTON = "Отправить сейчас"
SCHEDULED_SEND_BUTTON = "Отложенная отправка"
ENTER_DATETIME_MESSAGE = (
    "Введите дату и время отправки в формате DD.MM.YYYY HH:MM (московское время):\n"
    "Например: 01.01.2026 10:00"
)
INVALID_DATETIME_FORMAT = (
    "Неверный формат даты. Используйте формат DD.MM.YYYY HH:MM\n"
    "Например: 01.01.2026 10:00"
)
PAST_DATETIME_ERROR = "Дата должна быть в будущем. Пожалуйста, введите будущую дату."
SURVEY_CANCELLED = "Создание опроса отменено."

# Survey messages
SURVEY_INTRODUCTION = (
    "Спасибо за участие во встрече. Нам важно Ваше мнение: что прошло хорошо, что можно улучшить. "
    "Ответьте, пожалуйста, на несколько вопросов — это займёт пару минут.\n\n"
    "Результаты опроса важны и для Вашего Наставника и для проекта."
)
