import logging
from typing import Generator, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine = None
_SessionFactory = None


def get_engine():
    """Lazily initialize and return the SQLAlchemy engine for PostgreSQL."""
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine

    db_url = settings.DATABASE_URL.strip()
    if not db_url:
        logger.warning("DATABASE_URL is not configured in .env. PostgreSQL connection pending.")
        return None

    try:
        # pool_pre_ping tests connection liveness before checkout (essential for serverless cloud databases like Neon)
        _engine = create_engine(
            db_url,
            echo=settings.DATABASE_ECHO,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=10,
            max_overflow=20,
            pool_timeout=15
        )
        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        logger.info("Successfully initialized PostgreSQL database engine.")
        return _engine
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL engine with URL '{db_url}': {e}")
        return None


def init_db() -> bool:
    """Create all tables in PostgreSQL if engine is available."""
    engine = get_engine()
    if engine is None:
        logger.warning("Skipping table creation: PostgreSQL engine is not initialized.")
        return False
    try:
        # Import models so Base has metadata registered
        import storage.db_models  # noqa
        Base.metadata.create_all(bind=engine)

        # Run lightweight migrations for schema updates
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);"))
            conn.commit()

        logger.info("PostgreSQL tables verified and created successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to create PostgreSQL tables: {e}")
        return False


def get_session_factory():
    """Return the sessionmaker factory, initializing engine if needed."""
    get_engine()
    return _SessionFactory


def get_db() -> Generator[Optional[Session], None, None]:
    """FastAPI dependency for obtaining a database session."""
    factory = get_session_factory()
    if factory is None:
        yield None
        return

    session = factory()
    try:
        yield session
    finally:
        session.close()


def is_db_configured() -> bool:
    """Return True if DATABASE_URL is set and engine can be initialized."""
    return bool(settings.DATABASE_URL.strip())
