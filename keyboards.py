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
