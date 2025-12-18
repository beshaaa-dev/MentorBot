from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from config import SUPPORT_CONTACT_LINK
from messages import (
    SUPPORT_BUTTON_TEXT,
    CONFIRM_BUTTON,
    CANCEL_BUTTON,
    APPROVE_BUTTON,
    DISAPPROVE_BUTTON,
    BACK_BUTTON,
    CHECK_TASK_BUTTON,
    TO_MENU_BUTTON,
    APPROVED_STUDENTS_BUTTON,
    DISAPPROVED_STUDENTS_BUTTON,
    CHECK_NEW_TASK_BUTTON,
    POSTPONE_TASK_BUTTON,
    POSTPONED_TASKS_BUTTON,
)


def get_support_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(SUPPORT_BUTTON_TEXT, url=SUPPORT_CONTACT_LINK)]]
    return InlineKeyboardMarkup(keyboard)


def get_confirmation_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(CONFIRM_BUTTON),
            KeyboardButton(CANCEL_BUTTON),
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_mentor_task_decision_keyboard(
    task_id: int, is_check_later_button_hidden: bool = False
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(APPROVE_BUTTON, callback_data=f"approve_{task_id}"),
            InlineKeyboardButton(
                DISAPPROVE_BUTTON, callback_data=f"disapprove_{task_id}"
            ),
        ],
    ]

    if not is_check_later_button_hidden:
        keyboard.append(
            [
                InlineKeyboardButton(
                    POSTPONE_TASK_BUTTON, callback_data=f"postpone_{task_id}"
                ),
            ]
        )

    return InlineKeyboardMarkup(keyboard)


def get_check_task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Create inline keyboard with button to check a specific task."""
    keyboard = [
        [
            InlineKeyboardButton(
                CHECK_TASK_BUTTON,
                callback_data=f"check_task_{task_id}",
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_mentor_menu_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown after mentor approves/disapproves a task."""
    keyboard = [
        [KeyboardButton(CHECK_NEW_TASK_BUTTON)],
        [KeyboardButton(POSTPONED_TASKS_BUTTON), KeyboardButton(BACK_BUTTON)],
        [
            KeyboardButton(APPROVED_STUDENTS_BUTTON),
            KeyboardButton(DISAPPROVED_STUDENTS_BUTTON),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_decided_task_navigation_keyboard(
    older_task_id: int | None,
    newer_task_id: int | None,
) -> ReplyKeyboardMarkup:
    """Reply keyboard for navigating decided tasks within the last hour."""
    navigation_row: list[KeyboardButton] = []
    if older_task_id is not None:
        navigation_row.append(KeyboardButton("Назад"))
    if newer_task_id is not None:
        navigation_row.append(KeyboardButton("Вперёд"))
    menu_row = [KeyboardButton(TO_MENU_BUTTON)]

    rows: list[list[KeyboardButton]] = []
    if navigation_row:
        rows.append(navigation_row)
    rows.append(menu_row)

    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def get_postponed_task_navigation_keyboard(
    older_task_id: int | None,
    newer_task_id: int | None,
) -> ReplyKeyboardMarkup:
    navigation_row: list[KeyboardButton] = []
    if older_task_id is not None:
        navigation_row.append(KeyboardButton("Предыдущая заявка"))
    if newer_task_id is not None:
        navigation_row.append(KeyboardButton("Следующая заявка"))

    menu_row = [KeyboardButton("В меню")]

    rows: list[list[KeyboardButton]] = []
    if navigation_row:
        rows.append(navigation_row)
    rows.append(menu_row)

    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)
