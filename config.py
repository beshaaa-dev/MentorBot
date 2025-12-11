import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mentor_bot.db")

CRM_CLIENT_ID = os.getenv("CRM_CLIENT_ID")
CRM_CLIENT_SECRET = os.getenv("CRM_CLIENT_SECRET")
CRM_AUTH_CODE = os.getenv("CRM_AUTH_CODE")
CRM_SUBDOMAIN = os.getenv("CRM_SUBDOMAIN")
CRM_REDIRECT_URL = "https://ya.ru"
CRM_PIPELINE_ID = os.getenv("CRM_PIPELINE_ID")
# Отправлено тестовое
CRM_TASK_STATUS_IS_READY = os.getenv("CRM_TASK_STATUS_IS_READY")
# Тестовое отправлено наставнику
CRM_TASK_STATUS_IS_DONE = os.getenv("CRM_TASK_STATUS_IS_DONE")
# Наставник отклонил
CRM_TASK_STATUS_IS_DISAPPROVED = os.getenv("CRM_TASK_STATUS_IS_DISAPPROVED")
# Наставник принял
CRM_TASK_STATUS_IS_APPROVED = os.getenv("CRM_TASK_STATUS_IS_APPROVED")

SUPPORT_CONTACT_LINK = "https://t.me/Pokolenez_bot"
