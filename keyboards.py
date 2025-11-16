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
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_mentor_action_with_back_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(APPROVE_BUTTON),
            KeyboardButton(DISAPPROVE_BUTTON),
        ],
        [KeyboardButton(BACK_BUTTON)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_back_only_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(BACK_BUTTON)]]
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
