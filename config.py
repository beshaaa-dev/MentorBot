import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mentor_bot.db")

CRM_SUBDOMAIN = "honestcrm"
CRM_CLIENT_ID = os.getenv("CRM_CLIENT_ID")
CRM_CLIENT_SECRET = os.getenv("CRM_CLIENT_SECRET")
CRM_AUTH_CODE = os.getenv("CRM_AUTH_CODE")
CRM_REDIRECT_URL = "https://ya.ru"

SUPPORT_CONTACT_LINK = "https://t.me/Pokolenez_bot"
