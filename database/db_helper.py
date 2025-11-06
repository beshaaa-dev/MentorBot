from contextlib import contextmanager
from sqlalchemy import create_engine
from logger import setup_logger
from sqlalchemy.orm import sessionmaker, declarative_base


logger = setup_logger(__name__)

from config import DATABASE_URL

Base = declarative_base()
engine = create_engine(DATABASE_URL)  # echo=True для отладки SQL запросов
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
