import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mentor_bot.db")
