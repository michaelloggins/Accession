"""add_facility_matching_tables

Revision ID: 6f256120fb1b
Revises:
Create Date: 2025-12-02 16:49:25.808116+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f256120fb1b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create facility_physicians table
    op.create_table(
        'facility_physicians',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('facility_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('npi', sa.String(length=20), nullable=True),
        sa.Column('specialty', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('facility_id', 'name', name='uq_facility_physician')
    )
    op.create_index('idx_facility_physicians_facility', 'facility_physicians', ['facility_id'], unique=False)
    op.create_index('idx_facility_physicians_name', 'facility_physicians', ['name'], unique=False)

    # Create facility_match_log table
    op.create_table(
        'facility_match_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('extracted_name', sa.String(length=255), nullable=True),
        sa.Column('extracted_address', sa.String(length=255), nullable=True),
        sa.Column('extracted_city', sa.String(length=100), nullable=True),
        sa.Column('extracted_state', sa.String(length=2), nullable=True),
        sa.Column('extracted_zipcode', sa.String(length=10), nullable=True),
        sa.Column('extracted_fax', sa.String(length=20), nullable=True),
        sa.Column('extracted_phone', sa.String(length=20), nullable=True),
        sa.Column('matched_facility_id', sa.Integer(), nullable=True),
        sa.Column('match_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('match_method', sa.String(length=50), nullable=True),
        sa.Column('match_details', sa.Text(), nullable=True),
        sa.Column('alternatives_json', sa.Text(), nullable=True),
        sa.Column('user_confirmed', sa.Boolean(), nullable=True, default=False),
        sa.Column('confirmed_by', sa.String(length=100), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.ForeignKeyConstraint(['matched_facility_id'], ['facilities.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_match_log_document', 'facility_match_log', ['document_id'], unique=False)
    op.create_index('idx_match_log_facility', 'facility_match_log', ['matched_facility_id'], unique=False)

    # Add columns to documents table
    op.add_column('documents', sa.Column('matched_facility_id', sa.Integer(), nullable=True))
    op.add_column('documents', sa.Column('epr_status', sa.String(length=50), nullable=True))
    op.create_foreign_key('fk_documents_matched_facility', 'documents', 'facilities', ['matched_facility_id'], ['id'])
    op.create_index('idx_documents_matched_facility', 'documents', ['matched_facility_id'], unique=False)


def downgrade() -> None:
    # Remove columns from documents
    op.drop_index('idx_documents_matched_facility', table_name='documents')
    op.drop_constraint('fk_documents_matched_facility', 'documents', type_='foreignkey')
    op.drop_column('documents', 'epr_status')
    op.drop_column('documents', 'matched_facility_id')

    # Drop facility_match_log table
    op.drop_index('idx_match_log_facility', table_name='facility_match_log')
    op.drop_index('idx_match_log_document', table_name='facility_match_log')
    op.drop_table('facility_match_log')

    # Drop facility_physicians table
    op.drop_index('idx_facility_physicians_name', table_name='facility_physicians')
    op.drop_index('idx_facility_physicians_facility', table_name='facility_physicians')
    op.drop_table('facility_physicians')
