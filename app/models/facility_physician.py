"""Facility Physician model for tracking ordering physicians/veterinarians."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class FacilityPhysician(Base):
    """Ordering physician/veterinarian tied to a facility."""

    __tablename__ = "facility_physicians"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False, index=True)
    name = Column(String(150), nullable=False, index=True)  # "Dr. John Smith, DVM"
    npi = Column(String(20), nullable=True)  # National Provider Identifier
    specialty = Column(String(100), nullable=True)  # "Internal Medicine", "Oncology", etc.
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    facility = relationship("Facility", back_populates="physicians")

    __table_args__ = (
        UniqueConstraint("facility_id", "name", name="uq_facility_physician"),
        Index("idx_facility_physicians_facility", "facility_id"),
        Index("idx_facility_physicians_name", "name"),
    )

    def __repr__(self):
        return f"<FacilityPhysician {self.name} @ Facility {self.facility_id}>"
