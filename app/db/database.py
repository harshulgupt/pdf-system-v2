from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    pool_pre_ping=True,    # detect stale connections
    pool_size=5,           # keep 5 connections open (ignored by SQLite)
    max_overflow=10,       # allow up to 10 extra connections under load
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """Create all tables on startup."""
    from app.models import models  # noqa: F401 — needed for Base.metadata
    Base.metadata.create_all(bind=engine)

    if "postgresql" in settings.database_url:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunks_fts "
                "ON pdf_chunks USING gin(to_tsvector('english', extracted_text))"
            ))
            conn.commit()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
