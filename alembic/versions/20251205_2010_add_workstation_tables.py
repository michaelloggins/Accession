"""Add workstation equipment tables

Revision ID: add_workstation_tables
Revises:
Create Date: 2025-12-05 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_workstation_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create scanning_stations table
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='scanning_stations' AND xtype='U')
        CREATE TABLE scanning_stations (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(100) NOT NULL,
            location NVARCHAR(255) NULL,
            description NVARCHAR(500) NULL,
            is_active BIT NOT NULL DEFAULT 1,
            created_at DATETIME2 DEFAULT GETDATE(),
            updated_at DATETIME2 DEFAULT GETDATE()
        )
    """)

    # Create index on name
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'ix_scanning_stations_name')
        CREATE INDEX ix_scanning_stations_name ON scanning_stations(name)
    """)

    # Create label_printers table
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='label_printers' AND xtype='U')
        CREATE TABLE label_printers (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(100) NOT NULL,
            location NVARCHAR(255) NULL,
            printer_type NVARCHAR(50) NULL,
            connection_string NVARCHAR(500) NULL,
            is_active BIT NOT NULL DEFAULT 1,
            created_at DATETIME2 DEFAULT GETDATE(),
            updated_at DATETIME2 DEFAULT GETDATE()
        )
    """)

    # Create index on name
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'ix_label_printers_name')
        CREATE INDEX ix_label_printers_name ON label_printers(name)
    """)

    # Create user_workstation_preferences table
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='user_workstation_preferences' AND xtype='U')
        CREATE TABLE user_workstation_preferences (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id NVARCHAR(100) NOT NULL,
            scanning_station_id INT NULL,
            label_printer_id INT NULL,
            updated_at DATETIME2 DEFAULT GETDATE(),
            CONSTRAINT FK_user_workstation_preferences_station
                FOREIGN KEY (scanning_station_id) REFERENCES scanning_stations(id),
            CONSTRAINT FK_user_workstation_preferences_printer
                FOREIGN KEY (label_printer_id) REFERENCES label_printers(id)
        )
    """)

    # Create unique index on user_id
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'ix_user_workstation_preferences_user_id')
        CREATE UNIQUE INDEX ix_user_workstation_preferences_user_id ON user_workstation_preferences(user_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_workstation_preferences")
    op.execute("DROP TABLE IF EXISTS label_printers")
    op.execute("DROP TABLE IF EXISTS scanning_stations")
