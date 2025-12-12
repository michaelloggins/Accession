"""Add photo_url column to users table for storing EntraID profile pictures

Revision ID: f8g1h235e6i9
Revises: e7f0g124d5h8
Create Date: 2025-12-12 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f8g1h235e6i9'
down_revision = 'e7f0g124d5h8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add photo_url column to users table (TEXT for base64 data URI)
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'photo_url')
        ALTER TABLE users ADD photo_url NVARCHAR(MAX) NULL
    """)


def downgrade() -> None:
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'photo_url')
        ALTER TABLE users DROP COLUMN photo_url
    """)
