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
    VIEW_ALL_BUTTON,
    CHECK_NEW_TASK_BUTTON,
    POSTPONE_TASK_BUTTON,
    POSTPONED_TASKS_BUTTON,
    TASK_REVIEW_CHANGE_BUTTON,
    TASK_START_BUTTON,
    TASK_EDIT_BUTTON,
    TASK_CONFIRM_ALL_BUTTON,
    TASK_CONFIRM_YES_BUTTON,
    TASK_CONFIRM_RETRY_BUTTON,
    HW_CONFIRM_ALL_BUTTON,
    HW_REVIEW_CHANGE_BUTTON,
    HW_CONFIRM_YES_BUTTON,
    HW_CONFIRM_RETRY_BUTTON,
    HW_CHECK_BUTTON,
    HW_POSTPONE_BUTTON,
    HW_APPROVE_HW_BUTTON,
    HW_EDIT_FROM_MENTOR_BUTTON,
    HW_SKIP_BUTTON,
    MENTOR_HW_CHECK_NEW_BUTTON,
    MENTOR_HW_CHECK_POSTPONED_BUTTON,
    MENTOR_HW_CHECK_HISTORY_BUTTON,
    MENTOR_HW_NAV_PREV,
    MENTOR_HW_NAV_NEXT,
    CHECK_TASKS_BUTTON,
    INVITE_FRIEND_BUTTON,
    BROADCAST_DELIVERY_STATS_BUTTON,
)

STUDENT_CHECK_TASKS_CB = "student_check_tasks"
STUDENT_INVITE_FRIEND_CB = "student_invite_friend"


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


def get_view_all_tasks_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(VIEW_ALL_BUTTON)], [KeyboardButton(TO_MENU_BUTTON)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_student_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(CHECK_TASKS_BUTTON, callback_data=STUDENT_CHECK_TASKS_CB)],
        [InlineKeyboardButton(INVITE_FRIEND_BUTTON, callback_data=STUDENT_INVITE_FRIEND_CB)],
    ]
    return InlineKeyboardMarkup(keyboard)


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


def get_task_review_keyboard(question_count: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(TASK_REVIEW_CHANGE_BUTTON.format(n=n))]
        for n in range(1, question_count + 1)
    ]
    rows.append([KeyboardButton(TASK_CONFIRM_ALL_BUTTON)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def get_task_answer_confirmation_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(TASK_CONFIRM_YES_BUTTON),
            KeyboardButton(TASK_CONFIRM_RETRY_BUTTON),
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_start_task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(TASK_START_BUTTON, callback_data=f"start_task_{task_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_edit_task_keyboard(task_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(TASK_EDIT_BUTTON, callback_data=f"edit_task_{task_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_edit_homework_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(TASK_EDIT_BUTTON, callback_data=f"edit_homework_{hw_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_start_homework_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(TASK_START_BUTTON, callback_data=f"start_homework_{hw_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_answer_confirmation_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(HW_CONFIRM_YES_BUTTON), KeyboardButton(HW_CONFIRM_RETRY_BUTTON)]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_hw_review_keyboard(question_count: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(HW_REVIEW_CHANGE_BUTTON.format(n=n))]
        for n in range(1, question_count + 1)
    ]
    rows.append([KeyboardButton(HW_CONFIRM_ALL_BUTTON)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def get_check_homework_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(HW_CHECK_BUTTON, callback_data=f"check_homework_{hw_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_hw_mentor_decision_keyboard(hw_id: int, show_postpone: bool = True) -> InlineKeyboardMarkup:
    keyboard = []
    if show_postpone:
        keyboard.append([InlineKeyboardButton(HW_POSTPONE_BUTTON, callback_data=f"hw_postpone_{hw_id}")])
    keyboard.append([InlineKeyboardButton(HW_APPROVE_HW_BUTTON, callback_data=f"hw_approve_{hw_id}")])
    keyboard.append([InlineKeyboardButton(HW_EDIT_FROM_MENTOR_BUTTON, callback_data=f"hw_edit_from_mentor_{hw_id}")])
    return InlineKeyboardMarkup(keyboard)


def get_mentor_homework_menu_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура меню домашних заданий ментора."""
    keyboard = [
        [KeyboardButton(MENTOR_HW_CHECK_NEW_BUTTON)],
        [KeyboardButton(MENTOR_HW_CHECK_POSTPONED_BUTTON)],
        [KeyboardButton(MENTOR_HW_CHECK_HISTORY_BUTTON)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_hw_navigation_keyboard(
    older_hw_id: int | None,
    newer_hw_id: int | None,
) -> ReplyKeyboardMarkup:
    """Клавиатура навигации по домашним заданиям (предыдущее/следующее + В меню)."""
    navigation_row: list[KeyboardButton] = []
    if older_hw_id is not None:
        navigation_row.append(KeyboardButton(MENTOR_HW_NAV_PREV))
    if newer_hw_id is not None:
        navigation_row.append(KeyboardButton(MENTOR_HW_NAV_NEXT))

    menu_row = [KeyboardButton(TO_MENU_BUTTON)]

    rows: list[list[KeyboardButton]] = []
    if navigation_row:
        rows.append(navigation_row)
    rows.append(menu_row)

    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def get_hw_rating_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(str(n), callback_data=f"hw_rate_val_{hw_id}_{n}")
            for n in range(0, 6)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_hw_rating_with_skip_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    """Клавиатура оценки с кнопкой 'Пропустить'."""
    keyboard = [
        [
            InlineKeyboardButton(str(n), callback_data=f"hw_rate_val_{hw_id}_{n}")
            for n in range(0, 6)
        ],
        [InlineKeyboardButton(HW_SKIP_BUTTON, callback_data=f"hw_skip_rate_{hw_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_hw_edit_reason_skip_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Пропустить' для причины возврата на переработку."""
    keyboard = [
        [InlineKeyboardButton(HW_SKIP_BUTTON, callback_data=f"hw_skip_edit_reason_{hw_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_hw_feedback_skip_keyboard(hw_id: int) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Пропустить' для обратной связи."""
    keyboard = [
        [InlineKeyboardButton(HW_SKIP_BUTTON, callback_data=f"hw_skip_feedback_{hw_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_broadcast_delivery_stats_keyboard(broadcast_id: int) -> InlineKeyboardMarkup:
    keyboard = [[
        InlineKeyboardButton(
            BROADCAST_DELIVERY_STATS_BUTTON,
            callback_data=f"broadcast_delivery_stats_{broadcast_id}",
        )
    ]]
    return InlineKeyboardMarkup(keyboard)
