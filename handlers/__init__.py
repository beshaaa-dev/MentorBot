from handlers.greeting import video_conversation_handler
from handlers.mentor import (
    mentor_back_button_handler,
    mentor_action_handler,
    mentor_check_task_handler,
)

handlers = [
    mentor_check_task_handler,  # Must be before conversation handler
    video_conversation_handler,
    mentor_back_button_handler,
    mentor_action_handler,
]
