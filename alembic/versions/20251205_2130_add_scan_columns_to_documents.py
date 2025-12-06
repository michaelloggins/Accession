"""Add scan station columns to documents table

Revision ID: d6e9f013c4f7
Revises: c5d8f902b3e6
Create Date: 2025-12-05 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd6e9f013c4f7'
down_revision = 'c5d8f902b3e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add scan_station_id column
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scan_station_id')
        ALTER TABLE documents ADD scan_station_id INT NULL
    """)

    # Add scan_station_name column (denormalized for easy filtering)
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scan_station_name')
        ALTER TABLE documents ADD scan_station_name NVARCHAR(100) NULL
    """)

    # Add scanned_by column
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scanned_by')
        ALTER TABLE documents ADD scanned_by NVARCHAR(100) NULL
    """)

    # Add scanned_at column
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scanned_at')
        ALTER TABLE documents ADD scanned_at DATETIME2 NULL
    """)

    # Add foreign key constraint for scan_station_id (only if scanning_stations table exists)
    op.execute("""
        IF EXISTS (SELECT * FROM sysobjects WHERE name='scanning_stations' AND xtype='U')
        AND NOT EXISTS (SELECT * FROM sys.foreign_keys WHERE name = 'FK_documents_scan_station')
        BEGIN
            ALTER TABLE documents ADD CONSTRAINT FK_documents_scan_station
                FOREIGN KEY (scan_station_id) REFERENCES scanning_stations(id)
        END
    """)


def downgrade() -> None:
    # Drop foreign key first
    op.execute("""
        IF EXISTS (SELECT * FROM sys.foreign_keys WHERE name = 'FK_documents_scan_station')
        ALTER TABLE documents DROP CONSTRAINT FK_documents_scan_station
    """)

    # Drop columns
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scan_station_id')
        ALTER TABLE documents DROP COLUMN scan_station_id
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scan_station_name')
        ALTER TABLE documents DROP COLUMN scan_station_name
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scanned_by')
        ALTER TABLE documents DROP COLUMN scanned_by
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'scanned_at')
        ALTER TABLE documents DROP COLUMN scanned_at
    """)
