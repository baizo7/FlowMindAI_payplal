"""
Database setup. Deliberately SQLite + create_all() instead of
Postgres + Alembic: zero extra infra to stand up, zero migration
ceremony, same demo value for a 3-day solo build. If you later need
Postgres, swap DATABASE_URL and this file barely has to change
(SQLAlchemy handles both).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # Import models so they're registered on Base before create_all
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
