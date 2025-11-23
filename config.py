import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mentor_bot.db")

CRM_CLIENT_ID = os.getenv("CRM_CLIENT_ID")
CRM_CLIENT_SECRET = os.getenv("CRM_CLIENT_SECRET")
CRM_AUTH_CODE = os.getenv("CRM_AUTH_CODE")
CRM_SUBDOMAIN = "mainpokolenie"
CRM_REDIRECT_URL = "https://ya.ru"
CRM_PIPELINE_ID = "9395722"
# Отправлено тестовое
CRM_TASK_STATUS_IS_READY = 76914298
# Тестовое отправлено наставнику
CRM_TASK_STATUS_IS_DONE = 76914306
# Наставник отклонил
CRM_TASK_STATUS_IS_DISAPPROVED = 81677538
# Наставник принял
CRM_TASK_STATUS_IS_APPROVED = 81677542

SUPPORT_CONTACT_LINK = "https://t.me/Pokolenez_bot"
