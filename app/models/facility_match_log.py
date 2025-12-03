"""Facility Match Log model for tracking matching attempts."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, Text, Index
from sqlalchemy.orm import relationship
from app.database import Base


class FacilityMatchLog(Base):
    """Log of facility matching attempts for auditing and improvement."""

    __tablename__ = "facility_match_log"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)

    # Extracted values from document
    extracted_name = Column(String(255), nullable=True)
    extracted_address = Column(String(255), nullable=True)
    extracted_city = Column(String(100), nullable=True)
    extracted_state = Column(String(2), nullable=True)
    extracted_zipcode = Column(String(10), nullable=True)
    extracted_fax = Column(String(20), nullable=True)
    extracted_phone = Column(String(20), nullable=True)

    # Match result
    matched_facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=True, index=True)
    match_confidence = Column(Numeric(5, 4), nullable=True)  # 0.0000 to 1.0000
    match_method = Column(String(50), nullable=True)  # "exact", "fuzzy_name", "fax", "address", "ai_assisted"
    match_details = Column(Text, nullable=True)  # Human-readable explanation

    # Alternative matches (JSON array)
    alternatives_json = Column(Text, nullable=True)

    # User confirmation
    user_confirmed = Column(Boolean, default=False)
    confirmed_by = Column(String(100), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    document = relationship("Document", back_populates="facility_match_logs")
    matched_facility = relationship("Facility")

    __table_args__ = (
        Index("idx_match_log_document", "document_id"),
        Index("idx_match_log_facility", "matched_facility_id"),
    )

    def __repr__(self):
        return f"<FacilityMatchLog doc={self.document_id} -> facility={self.matched_facility_id}>"
