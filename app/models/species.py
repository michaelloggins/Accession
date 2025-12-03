"""Species reference table for both human and veterinary testing."""

from sqlalchemy import Column, Integer, String, Text, Index
from sqlalchemy.orm import relationship
from app.database import Base


class Species(Base):
    """Species reference table - defines available species for testing."""

    __tablename__ = "species"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    # e.g., "Human", "Dog", "Cat", "Horse", "Bovine", "Avian", etc.

    common_name = Column(String(100), nullable=True)
    # e.g., "Humans", "Canine", "Feline", "Equine", "Cattle", "Birds"

    description = Column(Text, nullable=True)
    test_category = Column(String(50), nullable=False, default="veterinary")
    # "human" or "veterinary" - determines which test menu to show

    is_active = Column(Integer, default=1)  # 0 = inactive, 1 = active

    # Relationships
    patients = relationship("Patient", back_populates="species")
    test_specimen_types = relationship("TestSpecimenType", back_populates="species")

    __table_args__ = (
        Index("idx_species_name", "name"),
        Index("idx_species_category", "test_category"),
    )

    def __repr__(self):
        return f"<Species {self.name}>"
