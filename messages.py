from config import SUPPORT_CONTACT_LINK

ERROR_MESSAGE = "Что-то пошло не так. Введите команду /start и попробуйте еще раз. Если ошибка повторится, то обратитесь в поддержку."
SUPPORT_BUTTON_TEXT = "Написать в поддержку"
GREETING_WITH_NAME_TEMPLATE = "Привет, {name}! Проверяем задание..."
MENTOR_GREETING_TEMPLATE = "Привет! Проверяем новые работы студентов"
FINDING_USER = "Ищем пользователя..."
USER_NOT_FOUND = "Не удалось найти вас. Обратитесь к своему куратору"
STUDENT_NO_TASK = "Задания пока нет."
MENTOR_NO_TASK = "Заданий на проверку пока нет."
TASK = "*У вас есть новое задание 🧡*\n\n" "{text}\n\n"
TASK_DEADLINE = "*Дедлайн*: {deadline}\n\n"
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

# Visit card flow messages
VISIT_CARD_TASK = "*У вас есть новое задание 🧡*\n\n{text}\n\n"
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

# Broadcast system messages
ADMIN_MENU_TITLE = (
    "📋 *Меню администратора*\n\n"
    "Вот что вы можете сделать:\n\n"
    "• *Отправить рассылку* — создать новую рассылку (сообщение или опрос) в выбранные чаты\n"
    "• *Запланированные рассылки* — просмотреть, изменить или отменить запланированные рассылки\n"
    "• *Выгрузить отчет* — получить файл со всеми данными опросов\n\n"
    "Рассылки отправляются участникам чатов через личные сообщения."
)
SEND_BROADCAST_BUTTON = "Отправить рассылку"
SCHEDULED_BROADCASTS_BUTTON = "Запланированные рассылки"
EXPORT_DATA_BUTTON = "Выгрузить отчет"

# Survey creation flow messages
SELECT_CHATS_MESSAGE = "Выберите чаты для отправки опроса (можно выбрать несколько):"
NO_CHATS_AVAILABLE = "У вас нет доступа ни к одному чату."
SELECT_BROADCAST_TYPE_MESSAGE = "Выберите тип рассылки:"
MESSAGE_TYPE_BUTTON = "Сообщение"
SURVEY_TYPE_BUTTON = "Опрос"
ENTER_MESSAGE_CONTENT_MESSAGE = "Введите текст сообщения для рассылки:"
MESSAGE_CONTENT_EMPTY_ERROR = "Сообщение не может быть пустым. Пожалуйста, введите текст."
MESSAGE_CONTENT_TOO_LONG_ERROR = "Сообщение слишком длинное (максимум 4096 символов). Пожалуйста, сократите текст."
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
