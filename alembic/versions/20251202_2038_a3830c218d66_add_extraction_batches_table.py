"""add_extraction_batches_table

Revision ID: a3830c218d66
Revises: 6f256120fb1b
Create Date: 2025-12-02 20:38:06.536023+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3830c218d66'
down_revision: Union[str, None] = '6f256120fb1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create extraction_batches table
    op.create_table(
        'extraction_batches',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('status', sa.String(50), default='queued'),
        sa.Column('document_count', sa.Integer, default=0),
        sa.Column('successful_count', sa.Integer, default=0),
        sa.Column('failed_count', sa.Integer, default=0),
        sa.Column('attempt_number', sa.Integer, default=1),
        sa.Column('parent_batch_id', sa.String(36), sa.ForeignKey('extraction_batches.id'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
    )

    # Create indexes
    op.create_index('idx_batch_status', 'extraction_batches', ['status'])
    op.create_index('idx_batch_created', 'extraction_batches', ['created_at'])

    # Add batch_id column to documents table if it doesn't exist
    # Use try/except since column might already exist
    try:
        op.add_column('documents', sa.Column('batch_id', sa.String(36), sa.ForeignKey('extraction_batches.id'), nullable=True))
        op.create_index('idx_batch_id', 'documents', ['batch_id'])
    except Exception:
        # Column already exists
        pass


def downgrade() -> None:
    # Remove batch_id from documents
    try:
        op.drop_index('idx_batch_id', 'documents')
        op.drop_column('documents', 'batch_id')
    except Exception:
        pass

    # Drop extraction_batches table
    op.drop_index('idx_batch_created', 'extraction_batches')
    op.drop_index('idx_batch_status', 'extraction_batches')
    op.drop_table('extraction_batches')
