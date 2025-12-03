"""
Database Connection and Session Management

Supports:
- SQLite (local development)
- Azure SQL Database (Standard and Serverless)
"""

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool
import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Configure engine based on database type
if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite for local development
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=settings.DEBUG
    )
elif "database.windows.net" in settings.DATABASE_URL:
    # Azure SQL Database (including Serverless)
    # Serverless can auto-pause, so we need:
    # - pool_pre_ping to detect stale connections
    # - shorter pool_recycle for connection refresh
    # - connection timeout for wake-up time (serverless can take ~60s)
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,  # Smaller pool for serverless cost efficiency
        max_overflow=10,
        pool_pre_ping=True,  # Critical for serverless auto-pause recovery
        pool_recycle=1800,  # Recycle connections every 30 mins
        pool_timeout=60,  # Wait up to 60s for connection (serverless wake-up)
        connect_args={
            "timeout": 60,  # Connection timeout for serverless wake-up
        },
        echo=settings.DEBUG
    )
else:
    # Other SQL Server instances
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.DEBUG
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")

    # Set document ID to start from 1001 for new databases (SQLite only)
    if settings.DATABASE_URL.startswith("sqlite"):
        try:
            from sqlalchemy import text

            with engine.begin() as conn:  # Use begin() for auto-commit
                # Check if documents table is empty
                result = conn.execute(text("SELECT COUNT(*) FROM documents"))
                count = result.scalar()

                if count == 0:
                    # Check if sqlite_sequence table exists and has documents entry
                    try:
                        result = conn.execute(text(
                            "SELECT seq FROM sqlite_sequence WHERE name = 'documents'"
                        ))
                        row = result.fetchone()

                        if row:
                            # Update existing sequence
                            conn.execute(text(
                                "UPDATE sqlite_sequence SET seq = 1000 WHERE name = 'documents'"
                            ))
                            logger.info("Updated document ID sequence to start from 1001")
                        else:
                            # Insert new sequence entry
                            conn.execute(text(
                                "INSERT INTO sqlite_sequence (name, seq) VALUES ('documents', 1000)"
                            ))
                            logger.info("Created document ID sequence to start from 1001")
                    except Exception as seq_error:
                        # sqlite_sequence table doesn't exist yet - will be created on first insert
                        logger.info("sqlite_sequence not found - will be created on first document insert at ID 1001")
        except Exception as e:
            logger.warning(f"Could not set document ID sequence: {e}")


def health_check():
    """Check database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
