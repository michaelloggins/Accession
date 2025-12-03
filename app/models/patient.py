"""Patient model for both human and veterinary patients."""

from sqlalchemy import Column, Integer, String, Date, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.database import Base


class Patient(Base):
    """Patient information - supports both human and veterinary patients."""

    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False, index=True)
    species_id = Column(Integer, ForeignKey("species.id"), nullable=False, index=True)

    # For VETERINARY: Owner info + pet info
    # For HUMAN: Patient's own name goes in owner fields, pet_name can be NULL
    owner_last_name = Column(String(100), nullable=False, index=True)
    owner_first_name = Column(String(100), nullable=False)
    owner_middle_name = Column(String(100), nullable=True)

    # Pet/Patient name (NULL for human patients, or use for patient's preferred name)
    pet_name = Column(String(100), nullable=True, index=True)
    date_of_birth = Column(Date, nullable=True)

    # Additional patient identifiers
    medical_record_number = Column(String(50), nullable=True, index=True)
    patient_id = Column(String(50), nullable=True)  # External patient ID

    # Contact information (for human patients)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(2), nullable=True)
    zipcode = Column(String(10), nullable=True)

    # Gender (for humans: M/F/Other; for animals: M/F/Neutered/Spayed)
    gender = Column(String(20), nullable=True)

    # Relationships
    facility = relationship("Facility", back_populates="patients")
    species = relationship("Species", back_populates="patients")
    orders = relationship("Order", back_populates="patient")

    __table_args__ = (
        Index("idx_owner_name", "owner_last_name", "owner_first_name"),
        Index("idx_pet_name", "pet_name"),
        Index("idx_species_id", "species_id"),
        Index("idx_mrn", "medical_record_number"),
    )

    def __repr__(self):
        if self.pet_name:
            return f"<Patient {self.pet_name} - Owner: {self.owner_last_name}>"
        else:
            return f"<Patient {self.owner_first_name} {self.owner_last_name}>"
