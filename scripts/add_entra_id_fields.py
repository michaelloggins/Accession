"""
Database migration script to add Entra ID fields to users table.

This script adds the following columns:
- entra_id: Azure AD Object ID
- entra_upn: User Principal Name from Entra ID
- auth_provider: Authentication provider (local or entra_id)
- last_synced_at: Last SCIM sync timestamp

Run this script to update the database schema.
Supports both SQLite (local dev) and SQL Server (Azure).
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from app.database import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def is_sql_server():
    """Check if we're connected to SQL Server (Azure) or SQLite."""
    return "mssql" in str(engine.url) or "pyodbc" in str(engine.url)


def add_entra_id_fields():
    """Add Entra ID fields to users table."""

    # Use SQLAlchemy inspector to check existing columns
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns('users')]
    logger.info(f"Existing columns in users table: {existing_columns}")

    columns_to_add = [
        {
            "name": "entra_id",
            "sqlite_def": "VARCHAR(100) NULL",
            "mssql_def": "NVARCHAR(100) NULL",
        },
        {
            "name": "entra_upn",
            "sqlite_def": "VARCHAR(255) NULL",
            "mssql_def": "NVARCHAR(255) NULL",
        },
        {
            "name": "auth_provider",
            "sqlite_def": "VARCHAR(50) DEFAULT 'local'",
            "mssql_def": "NVARCHAR(50) DEFAULT 'local'",
        },
        {
            "name": "last_synced_at",
            "sqlite_def": "DATETIME NULL",
            "mssql_def": "DATETIME2 NULL",
        }
    ]

    is_mssql = is_sql_server()
    logger.info(f"Database type: {'SQL Server (Azure)' if is_mssql else 'SQLite (local)'}")

    with engine.connect() as conn:
        for col in columns_to_add:
            try:
                if col["name"] in existing_columns:
                    logger.info(f"Column '{col['name']}' already exists in users table")
                    continue

                # Choose the right column definition based on database type
                col_def = col["mssql_def"] if is_mssql else col["sqlite_def"]

                # Add the column
                sql = f"ALTER TABLE users ADD {col['name']} {col_def}"
                logger.info(f"Executing: {sql}")
                conn.execute(text(sql))
                conn.commit()
                logger.info(f"Added column '{col['name']}' to users table")

            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    logger.info(f"Column '{col['name']}' already exists (caught in exception)")
                else:
                    logger.error(f"Error processing column '{col['name']}': {e}")
                    raise

        # Create indexes for SQL Server
        if is_mssql:
            try:
                # Unique filtered index for entra_id (only non-null values)
                conn.execute(text("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_entra_id' AND object_id = OBJECT_ID('users'))
                    CREATE UNIQUE INDEX idx_entra_id ON users(entra_id) WHERE entra_id IS NOT NULL
                """))
                conn.commit()
                logger.info("Created unique index on entra_id")
            except Exception as e:
                logger.warning(f"Could not create entra_id index: {e}")

            try:
                conn.execute(text("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_auth_provider' AND object_id = OBJECT_ID('users'))
                    CREATE INDEX idx_auth_provider ON users(auth_provider)
                """))
                conn.commit()
                logger.info("Created index on auth_provider")
            except Exception as e:
                logger.warning(f"Could not create auth_provider index: {e}")

    logger.info("Entra ID fields migration completed successfully!")


def verify_migration():
    """Verify the migration was successful."""
    inspector = inspect(engine)
    columns = inspector.get_columns('users')

    entra_columns = [c for c in columns if c['name'] in ('entra_id', 'entra_upn', 'auth_provider', 'last_synced_at')]

    logger.info("\nVerification - Entra ID columns in users table:")
    logger.info("-" * 60)
    for col in entra_columns:
        logger.info(f"  {col['name']}: {col['type']} (nullable={col.get('nullable', 'unknown')})")

    if len(entra_columns) == 4:
        logger.info("\nAll 4 Entra ID columns are present!")
        return True
    else:
        logger.warning(f"\nExpected 4 columns, found {len(entra_columns)}")
        return False


if __name__ == "__main__":
    logger.info("Starting Entra ID fields migration...")
    add_entra_id_fields()
    verify_migration()
