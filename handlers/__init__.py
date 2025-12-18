from handlers.common import (
    video_conversation_handler,
    support_command_handler,
    unknown_message_handler,
)
from handlers.mentor import (
    mentor_back_button_handler,
    mentor_check_task_handler,
    mentor_approve_disapprove_handler,
    mentor_history_nav_handler,
    mentor_to_menu_handler,
    mentor_student_list_handler,
    mentor_postpone_handler,
    mentor_check_new_task_handler,
    mentor_postponed_tasks_handler,
    mentor_postponed_nav_handler,
)

handlers = [
    mentor_to_menu_handler,
    mentor_postponed_nav_handler,
    mentor_history_nav_handler,
    mentor_check_task_handler,
    mentor_approve_disapprove_handler,
    mentor_postpone_handler,
    mentor_student_list_handler,
    mentor_check_new_task_handler,
    mentor_postponed_tasks_handler,
    video_conversation_handler,
    mentor_back_button_handler,
    support_command_handler,
    unknown_message_handler,  # Must be last - catches all unhandled messages
]
