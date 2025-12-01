from handlers.common import video_conversation_handler, support_command_handler, unknown_message_handler
from handlers.mentor import (
    mentor_back_button_handler,
    mentor_action_handler,
    mentor_check_task_handler,
    mentor_history_nav_handler,
    mentor_history_change_handler,
    mentor_history_done_handler,
    mentor_student_list_handler,
)

handlers = [
    mentor_history_nav_handler,
    mentor_history_change_handler,
    mentor_history_done_handler,
    mentor_check_task_handler,  # Must be before conversation handler
    mentor_student_list_handler,
    video_conversation_handler,
    mentor_back_button_handler,
    mentor_action_handler,
    support_command_handler,
    unknown_message_handler,  # Must be last - catches all unhandled messages
]
