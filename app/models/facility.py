"""Ordering Facility model for veterinary clinics/hospitals."""

from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import relationship
from app.database import Base


class Facility(Base):
    """Ordering facility (veterinary clinic/hospital)."""

    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(String(50), unique=True, nullable=True, index=True)  # External facility code
    facility_name = Column(String(255), nullable=False, index=True)
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(2), nullable=True)
    zipcode = Column(String(10), nullable=True)
    laboratory_contact = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    fax = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)

    # Relationships
    patients = relationship("Patient", back_populates="facility")
    orders = relationship("Order", back_populates="facility")
    physicians = relationship("FacilityPhysician", back_populates="facility", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_facility_name", "facility_name"),
        Index("idx_facility_city_state", "city", "state"),
    )

    def __repr__(self):
        return f"<Facility {self.facility_name}>"
