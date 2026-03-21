from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    # For SQLite (dev fallback) we need this flag; ignored by Postgres
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    pool_pre_ping=True,   # detect stale connections
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """Create all tables. In prod you'd use Alembic migrations."""
    from app.models import models  # noqa: F401 — imports needed for Base.metadata
    Base.metadata.create_all(bind=engine)

    # Create a simple full-text search index on extracted_text if using Postgres
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
