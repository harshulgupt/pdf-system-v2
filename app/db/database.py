"""
Database layer — SQLite locally, PostgreSQL in production.

To swap database on Render:
  1. Create a Postgres instance on Render
  2. Copy the "Internal Database URL" 
  3. Set DATABASE_URL env var on your web service to that URL
  4. Redeploy — done. No code changes needed.

SQLAlchemy handles both dialects identically.
The only differences handled here:
  - SQLite needs check_same_thread=False (threading safety flag)
  - Render Postgres URLs start with postgres:// but SQLAlchemy needs postgresql://
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pdf_store.db")

# Render gives postgres:// but SQLAlchemy requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite needs this; Postgres does not
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
