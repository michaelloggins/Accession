"""Add training and Form Recognizer columns to document_types and extraction_method to documents

Revision ID: e7f0g124d5h8
Revises: d6e9f013c4f7
Create Date: 2025-12-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e7f0g124d5h8'
down_revision = 'd6e9f013c4f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add training_enabled column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'training_enabled')
        ALTER TABLE document_types ADD training_enabled BIT NOT NULL DEFAULT 1
    """)

    # Add use_form_recognizer column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'use_form_recognizer')
        ALTER TABLE document_types ADD use_form_recognizer BIT NOT NULL DEFAULT 0
    """)

    # Add form_recognizer_model_id column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'form_recognizer_model_id')
        ALTER TABLE document_types ADD form_recognizer_model_id NVARCHAR(200) NULL
    """)

    # Add fr_confidence_threshold column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'fr_confidence_threshold')
        ALTER TABLE document_types ADD fr_confidence_threshold FLOAT NOT NULL DEFAULT 0.90
    """)

    # Add fr_extraction_count column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'fr_extraction_count')
        ALTER TABLE document_types ADD fr_extraction_count INT NOT NULL DEFAULT 0
    """)

    # Add openai_extraction_count column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'openai_extraction_count')
        ALTER TABLE document_types ADD openai_extraction_count INT NOT NULL DEFAULT 0
    """)

    # Add openai_fallback_count column to document_types
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'openai_fallback_count')
        ALTER TABLE document_types ADD openai_fallback_count INT NOT NULL DEFAULT 0
    """)

    # Add extraction_method column to documents
    op.execute("""
        IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'extraction_method')
        ALTER TABLE documents ADD extraction_method NVARCHAR(50) NULL
    """)


def downgrade() -> None:
    # Drop extraction_method from documents
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('documents') AND name = 'extraction_method')
        ALTER TABLE documents DROP COLUMN extraction_method
    """)

    # Drop columns from document_types
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'training_enabled')
        ALTER TABLE document_types DROP COLUMN training_enabled
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'use_form_recognizer')
        ALTER TABLE document_types DROP COLUMN use_form_recognizer
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'form_recognizer_model_id')
        ALTER TABLE document_types DROP COLUMN form_recognizer_model_id
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'fr_confidence_threshold')
        ALTER TABLE document_types DROP COLUMN fr_confidence_threshold
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'fr_extraction_count')
        ALTER TABLE document_types DROP COLUMN fr_extraction_count
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'openai_extraction_count')
        ALTER TABLE document_types DROP COLUMN openai_extraction_count
    """)
    op.execute("""
        IF EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('document_types') AND name = 'openai_fallback_count')
        ALTER TABLE document_types DROP COLUMN openai_fallback_count
    """)
