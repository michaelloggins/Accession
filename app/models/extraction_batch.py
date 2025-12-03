"""Extraction batch model for tracking batch processing."""

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class ExtractionBatch(Base):
    """Tracks batches of documents sent to AI extraction."""

    __tablename__ = "extraction_batches"

    id = Column(String(36), primary_key=True)  # UUID
    status = Column(String(50), default="queued")  # queued, processing, completed, failed, split

    # Counts
    document_count = Column(Integer, default=0)
    successful_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    # Retry tracking
    attempt_number = Column(Integer, default=1)
    parent_batch_id = Column(String(36), ForeignKey("extraction_batches.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Relationships
    parent_batch = relationship("ExtractionBatch", remote_side=[id], backref="child_batches")
    documents = relationship("Document", back_populates="extraction_batch", foreign_keys="Document.batch_id")

    __table_args__ = (
        Index("idx_batch_status", "status"),
        Index("idx_batch_created", "created_at"),
    )

    # Status constants
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_SPLIT = "split"  # Batch was split into individual documents after failure
