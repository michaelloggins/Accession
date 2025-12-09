"""Training data models for document classification learning."""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_eastern


class DocumentType(Base):
    """Learned document type from GPT-4 Vision analysis."""

    __tablename__ = "document_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    # Distinguishing features identified by GPT-4
    visual_features = Column(Text, nullable=True)  # JSON: headers, logos, layouts
    text_patterns = Column(Text, nullable=True)    # JSON: key phrases, field labels
    structural_features = Column(Text, nullable=True)  # JSON: sections, tables, checkboxes

    # Extraction rules learned
    extraction_fields = Column(Text, nullable=True)  # JSON: fields to extract and their locations

    # Training control - per document type
    training_enabled = Column(Boolean, default=True)  # Allow training for this type
    use_form_recognizer = Column(Boolean, default=False)  # Use FR extraction model if available
    form_recognizer_model_id = Column(String(200), nullable=True)  # Custom FR model ID for this type
    fr_confidence_threshold = Column(Float, default=0.90)  # Fallback to OpenAI below this

    # Statistics
    sample_count = Column(Integer, default=0)
    avg_confidence = Column(Float, default=0.0)
    fr_extraction_count = Column(Integer, default=0)  # Times extracted by Form Recognizer
    openai_extraction_count = Column(Integer, default=0)  # Times extracted by OpenAI
    openai_fallback_count = Column(Integer, default=0)  # Times FR fell back to OpenAI

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_eastern)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)
    created_by = Column(String(100), nullable=True)

    # Relationships
    samples = relationship("TrainingSample", back_populates="document_type")

    def __repr__(self):
        return f"<DocumentType {self.name}>"


class TrainingSample(Base):
    """Individual training sample for a document type."""

    __tablename__ = "training_samples"

    id = Column(Integer, primary_key=True, index=True)
    document_type_id = Column(Integer, ForeignKey("document_types.id"), nullable=False, index=True)

    # Source document reference
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    blob_name = Column(String(500), nullable=True)

    # GPT-4 analysis results
    gpt_classification = Column(String(100), nullable=True)  # What GPT-4 classified it as
    gpt_confidence = Column(Float, nullable=True)
    gpt_reasoning = Column(Text, nullable=True)  # Why GPT-4 made this classification
    gpt_features = Column(Text, nullable=True)   # JSON: features GPT-4 identified

    # Extraction results from this sample
    extracted_fields = Column(Text, nullable=True)  # JSON: what was extracted

    # Verification
    is_verified = Column(Boolean, default=False)  # Human verified
    verified_by = Column(String(100), nullable=True)
    verified_at = Column(DateTime, nullable=True)

    # If classification was corrected
    corrected_type = Column(String(100), nullable=True)

    # Metadata
    created_at = Column(DateTime, default=now_eastern)

    # Relationships
    document_type = relationship("DocumentType", back_populates="samples")
    source_document = relationship("Document", foreign_keys=[document_id])

    def __repr__(self):
        return f"<TrainingSample doc_type={self.document_type_id}>"


class ExtractionRule(Base):
    """Learned extraction rules for a document type."""

    __tablename__ = "extraction_rules"

    id = Column(Integer, primary_key=True, index=True)
    document_type_id = Column(Integer, ForeignKey("document_types.id"), nullable=False, index=True)

    # Field info
    field_name = Column(String(100), nullable=False)  # e.g., "patient_name", "date_of_birth"
    field_type = Column(String(50), nullable=True)    # text, date, number, checkbox, etc.
    field_description = Column(Text, nullable=True)

    # Location hints learned from samples
    location_hints = Column(Text, nullable=True)  # JSON: where to find this field
    extraction_prompt = Column(Text, nullable=True)  # Prompt addition for GPT-4

    # Validation rules
    validation_regex = Column(String(500), nullable=True)
    required = Column(Boolean, default=False)

    # Statistics
    extraction_success_rate = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_eastern)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    def __repr__(self):
        return f"<ExtractionRule {self.field_name} for doc_type={self.document_type_id}>"
