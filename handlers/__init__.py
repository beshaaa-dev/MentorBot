from handlers.common import (
    video_conversation_handler,
    support_command_handler,
    unknown_message_handler,
)
from handlers.homework_student import hw_student_conversation_handler
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
from handlers.broadcast_admin import (
    admin_command_handler,
    admin_menu_callback_handler,
)
from handlers.broadcast_creation import survey_creation_handler
from handlers.survey_questions import survey_questions_handler, submit_survey_handler
from handlers.chat_events import (
    chat_message_handler,
    chat_member_handler,
    bot_added_handler,
)

handlers = [
    # Chat event handlers (must be early to track group messages before other handlers)
    bot_added_handler,
    chat_member_handler,
    chat_message_handler,
    # Broadcast system handlers (need to be early for callbacks)
    admin_command_handler,
    survey_creation_handler,  # Must be before admin_menu_callback_handler to catch admin_send_broadcast callback
    survey_questions_handler,
    submit_survey_handler,  # Handle survey submission confirmation
    admin_menu_callback_handler,  # Broad pattern, must be after specific handlers
    # Homework handlers
    hw_student_conversation_handler,
    # Mentor handlers
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
