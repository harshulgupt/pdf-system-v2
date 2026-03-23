import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db() -> None:
    """Create tables and set up Postgres FTS infrastructure on first boot."""
    from app.models import models  # noqa: F401 — registers models with Base

    Base.metadata.create_all(bind=engine)

    if "postgresql" not in settings.database_url:
        return

    with engine.connect() as conn:
        # 1. Dedicated TSVECTOR column
        conn.execute(text(
            "ALTER TABLE pdf_chunks ADD COLUMN IF NOT EXISTS search_vector TSVECTOR"
        ))

        # 2. Trigger function — keeps search_vector in sync automatically
        conn.execute(text(
            "CREATE OR REPLACE FUNCTION pdf_chunks_tsvector_trigger() RETURNS trigger AS $$ "
            "BEGIN "
            "  NEW.search_vector := to_tsvector('english', coalesce(NEW.extracted_text, '')); "
            "  RETURN NEW; "
            "END "
            "$$ LANGUAGE plpgsql;"
        ))

        # 3. Attach trigger (idempotent)
        conn.execute(text(
            "DO $$ "
            "BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'tsvectorupdate') THEN "
            "    CREATE TRIGGER tsvectorupdate "
            "    BEFORE INSERT OR UPDATE ON pdf_chunks "
            "    FOR EACH ROW EXECUTE PROCEDURE pdf_chunks_tsvector_trigger(); "
            "  END IF; "
            "END "
            "$$;"
        ))

        # 4. GIN index for fast FTS queries
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_search_vector "
            "ON pdf_chunks USING gin(search_vector)"
        ))

        # 5. Backfill only rows that are missing a search_vector.
        #    Capped at 500 rows per boot so startup never blocks health checks.
        #    Any remaining rows are picked up on subsequent restarts.
        result = conn.execute(text(
            "SELECT COUNT(*) FROM pdf_chunks WHERE search_vector IS NULL"
        ))
        missing = result.scalar() or 0
        if missing > 0:
            logger.info("Backfilling search_vector for up to 500 rows (%d total missing).", missing)
            conn.execute(text(
                "UPDATE pdf_chunks "
                "SET search_vector = to_tsvector('english', coalesce(extracted_text, '')) "
                "WHERE id IN ("
                "  SELECT id FROM pdf_chunks WHERE search_vector IS NULL LIMIT 500"
                ")"
            ))

        conn.commit()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
