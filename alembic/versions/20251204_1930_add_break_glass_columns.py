"""add_break_glass_columns

Revision ID: b4c7e891a2d5
Revises: a3830c218d66
Create Date: 2025-12-04 19:30:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c7e891a2d5'
down_revision: Union[str, None] = 'a3830c218d66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add break glass authentication columns to users table."""
    # Add hashed_password column for break glass accounts
    op.add_column('users', sa.Column('hashed_password', sa.String(255), nullable=True))

    # Add is_break_glass flag
    op.add_column('users', sa.Column('is_break_glass', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    """Remove break glass authentication columns from users table."""
    op.drop_column('users', 'is_break_glass')
    op.drop_column('users', 'hashed_password')
