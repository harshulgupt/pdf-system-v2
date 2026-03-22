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
            # 1. Add dedicated TSVECTOR column
            conn.execute(text("ALTER TABLE pdf_chunks ADD COLUMN IF NOT EXISTS search_vector TSVECTOR"))
            
            # 2. Create Trigger Function
            conn.execute(text(
                "CREATE OR REPLACE FUNCTION pdf_chunks_tsvector_trigger() RETURNS trigger AS $$ "
                "BEGIN "
                "  NEW.search_vector := to_tsvector('english', coalesce(NEW.extracted_text, '')); "
                "  RETURN NEW; "
                "END "
                "$$ LANGUAGE plpgsql;"
            ))
            
            # 3. Attach Trigger
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
            
            # 4. Backfill existing data
            conn.execute(text(
                "UPDATE pdf_chunks SET search_vector = to_tsvector('english', coalesce(extracted_text, '')) "
                "WHERE search_vector IS NULL"
            ))
            
            # 5. Create GIN Index strictly on the dedicated column
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_chunks_search_vector "
                "ON pdf_chunks USING gin(search_vector)"
            ))
            conn.commit()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
