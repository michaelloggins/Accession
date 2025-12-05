"""Document model for lab requisition forms."""

from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean, Text, Index, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Document(Base):
    """Document model representing a scanned/uploaded lab requisition form."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)  # Linked order (after extraction)

    filename = Column(String(255), nullable=False)
    blob_name = Column(String(500), nullable=True)  # Nullable for manual entries
    upload_date = Column(DateTime, server_default=func.now())
    uploaded_by = Column(String(100), nullable=False)

    @property
    def accession_number(self):
        """Generate accession number in format A########."""
        return f"A{self.id:08d}"

    # Extraction results (encrypted JSON)
    extracted_data = Column(Text, nullable=True)
    confidence_score = Column(Numeric(5, 4), nullable=True)

    # Processing queue status (for background extraction)
    processing_status = Column(String(50), default="queued")  # queued, processing, extracted, failed, manual
    batch_id = Column(String(36), ForeignKey("extraction_batches.id"), nullable=True)
    extraction_attempts = Column(Integer, default=0)
    last_extraction_error = Column(Text, nullable=True)
    queued_at = Column(DateTime, server_default=func.now())
    extraction_started_at = Column(DateTime, nullable=True)
    extraction_completed_at = Column(DateTime, nullable=True)

    # Review status
    status = Column(String(50), default="pending")
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    # Corrected data (encrypted JSON)
    corrected_data = Column(Text, nullable=True)

    # Lab submission
    submitted_to_lab = Column(Boolean, default=False)
    lab_submission_date = Column(DateTime, nullable=True)
    lab_confirmation_id = Column(String(100), nullable=True)

    # Metadata
    reviewer_notes = Column(Text, nullable=True)
    document_type = Column(String(50), nullable=True)
    source = Column(String(50), nullable=True)

    # Scan station metadata
    scan_station_id = Column(Integer, ForeignKey("scanning_stations.id"), nullable=True)
    scan_station_name = Column(String(100), nullable=True)  # Denormalized for easy filtering
    scanned_by = Column(String(100), nullable=True)  # Username who performed the scan
    scanned_at = Column(DateTime, nullable=True)  # Timestamp when document was scanned

    # Facility matching
    matched_facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True, index=True)
    epr_status = Column(String(50), nullable=True)  # NULL, "pending", "created", "sent"

    # Audit
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    order = relationship("Order", back_populates="documents", foreign_keys=[order_id])
    extraction_batch = relationship("ExtractionBatch", back_populates="documents", foreign_keys=[batch_id])
    matched_facility = relationship("Facility", foreign_keys=[matched_facility_id])
    facility_match_logs = relationship("FacilityMatchLog", back_populates="document")

    __table_args__ = (
        Index("idx_status", "status"),
        Index("idx_upload_date", "upload_date"),
        Index("idx_reviewed_at", "reviewed_at"),
        Index("idx_order_id", "order_id"),
        Index("idx_processing_status", "processing_status"),
        Index("idx_batch_id", "batch_id"),
        Index("idx_queued_at", "queued_at"),
    )

    # Processing status constants
    PROC_STATUS_QUEUED = "queued"
    PROC_STATUS_PROCESSING = "processing"
    PROC_STATUS_EXTRACTED = "extracted"
    PROC_STATUS_FAILED = "failed"
    PROC_STATUS_MANUAL = "manual"  # Manual entry, no extraction needed
    PROC_STATUS_PENDING = "pending"  # Awaiting manual extraction trigger (AUTO_EXTRACT_ENABLED=false)
