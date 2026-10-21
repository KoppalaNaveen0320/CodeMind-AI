import logging
from typing import Generator, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.engine import Engine
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

def create_db_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif "postgres" in database_url:
        connect_args["connect_timeout"] = 3

    return create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True
    )

engine = create_db_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    """Dependency that yields an active database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import re

def _mask_sensitive_db_error(error_msg: str) -> str:
    """Masks credentials, passwords, and sensitive host info from database exceptions."""
    if not error_msg:
        return "Database connection error"
    # Mask password in URI if present
    sanitized = re.sub(r':[^:@/]+@', ':***@', error_msg)
    # Mask password parameters
    sanitized = re.sub(r'password=[^\s,]+', 'password=***', sanitized)
    return sanitized

def check_db_connection() -> Tuple[bool, str, str]:
    """
    Checks database reachability.
    Returns: (is_connected, dialect_name, detail_message)
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            dialect = engine.dialect.name
            return True, dialect, f"Successfully connected to {dialect} database."
    except Exception as e:
        dialect = engine.dialect.name if hasattr(engine, "dialect") else "unknown"
        masked_err = _mask_sensitive_db_error(str(e))
        return False, dialect, f"Database unreachable ({dialect}): {masked_err}"


def get_db_diagnostics() -> dict:
    """
    Returns full database diagnostic information including pgvector extension status.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            dialect = engine.dialect.name
            pgvector_available = False
            if dialect == "postgresql":
                try:
                    res = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).fetchone()
                    pgvector_available = bool(res)
                except Exception:
                    pgvector_available = False
            return {
                "connected": True,
                "dialect": dialect,
                "pgvector_available": pgvector_available,
                "detail": f"Connected to {dialect} database.",
            }
    except Exception as e:
        dialect = engine.dialect.name if hasattr(engine, "dialect") else "unknown"
        masked_err = _mask_sensitive_db_error(str(e))
        return {
            "connected": False,
            "dialect": dialect,
            "pgvector_available": False,
            "detail": f"Database unreachable ({dialect}): {masked_err}",
        }
