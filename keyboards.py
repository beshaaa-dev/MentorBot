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
    CHANGE_STATUS_BUTTON,
    DONE_BUTTON,
    APPROVED_STUDENTS_BUTTON,
    DISAPPROVED_STUDENTS_BUTTON,
    CHECK_NEW_TASK_BUTTON,
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


def get_mentor_action_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(APPROVE_BUTTON),
            KeyboardButton(DISAPPROVE_BUTTON),
        ],
        [
            KeyboardButton(APPROVED_STUDENTS_BUTTON),
            KeyboardButton(DISAPPROVED_STUDENTS_BUTTON),
        ],
        [KeyboardButton(BACK_BUTTON)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)



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
        [KeyboardButton(BACK_BUTTON)],
        [KeyboardButton(APPROVED_STUDENTS_BUTTON), KeyboardButton(DISAPPROVED_STUDENTS_BUTTON)],
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
    change_status_row = [KeyboardButton(CHANGE_STATUS_BUTTON)]
    done_row = [KeyboardButton(DONE_BUTTON)]

    rows: list[list[KeyboardButton]] = []
    if navigation_row:
        rows.append(navigation_row)
    rows.append(change_status_row)
    rows.append(done_row)

    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)
