"""
Database migration script to add Entra ID fields to users table on Azure SQL.

This script adds the following columns:
- entra_id: Azure AD Object ID
- entra_upn: User Principal Name from Entra ID
- auth_provider: Authentication provider (local or entra_id)
- last_synced_at: Last SCIM sync timestamp
"""

import sys
import os

# Force Azure SQL connection
AZURE_DB_URL = "mssql+pyodbc://sqladmin:DocIntel2024!Secure#@mvd-docintel-sql.database.windows.net/docintel-db?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"

from sqlalchemy import create_engine, text, inspect
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create engine directly with Azure connection
engine = create_engine(AZURE_DB_URL)


def add_entra_id_fields():
    """Add Entra ID fields to users table."""

    # Use SQLAlchemy inspector to check existing columns
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns('users')]
    logger.info(f"Existing columns in users table: {existing_columns}")

    columns_to_add = [
        {
            "name": "entra_id",
            "definition": "NVARCHAR(100) NULL",
        },
        {
            "name": "entra_upn",
            "definition": "NVARCHAR(255) NULL",
        },
        {
            "name": "auth_provider",
            "definition": "NVARCHAR(50) DEFAULT 'local'",
        },
        {
            "name": "last_synced_at",
            "definition": "DATETIME2 NULL",
        }
    ]

    logger.info("Database type: SQL Server (Azure)")

    with engine.connect() as conn:
        for col in columns_to_add:
            try:
                if col["name"] in existing_columns:
                    logger.info(f"Column '{col['name']}' already exists in users table")
                    continue

                # Add the column
                sql = f"ALTER TABLE users ADD {col['name']} {col['definition']}"
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

        # Create indexes
        try:
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
    logger.info("Starting Entra ID fields migration on Azure SQL...")
    add_entra_id_fields()
    verify_migration()
