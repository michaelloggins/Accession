"""Test catalog/menu models."""

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Test(Base):
    """Test catalog - available tests that can be ordered."""

    __tablename__ = "tests"

    id = Column(Integer, primary_key=True, index=True)
    test_number = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "310", "316"
    test_code = Column(String(50), nullable=True, index=True)  # Alternative test code
    test_name = Column(String(255), nullable=False, index=True)  # Short name (e.g., "Histoplasma Ag")
    full_name = Column(String(500), nullable=True)  # Full name (e.g., "MVista® Histoplasma Ag Quantitative EIA")
    common_name = Column(String(255), nullable=True)  # Common/display name (e.g., "Histo Antigen")
    test_type = Column(String(100), nullable=False, index=True)
    # Test types: Antigen Test, Antibody Test, Panel - General/Geographic,
    #             Panel - Syndrome, Panel - Pathogen, Drug Monitoring

    species = Column(String(50), nullable=True, index=True, default="Any")
    # Species: Any, Human, K9, Feline, Equine, etc.

    cpt_code = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)

    # Relationships
    specimen_types = relationship("TestSpecimenType", back_populates="test", cascade="all, delete-orphan")
    order_tests = relationship("OrderTest", back_populates="test")

    __table_args__ = (
        Index("idx_test_name", "test_name"),
        Index("idx_test_type", "test_type"),
    )

    def __repr__(self):
        return f"<Test {self.test_number}: {self.test_name}>"


class TestSpecimenType(Base):
    """Valid specimen types for each test with minimum volumes (can be species-specific)."""

    __tablename__ = "test_specimen_types"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False, index=True)
    specimen_type = Column(String(50), nullable=False)
    # Specimen types: Blood, Urine, Serum, Plasma, CSF, BAL, Tissue, Swab, etc.

    species_id = Column(Integer, ForeignKey("species.id"), nullable=True, index=True)
    # NULL = applies to all species, otherwise species-specific requirement

    minimum_volume_ml = Column(Float, nullable=True)
    preferred_container = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    test = relationship("Test", back_populates="specimen_types")
    species = relationship("Species", back_populates="test_specimen_types")

    __table_args__ = (
        Index("idx_test_specimen", "test_id", "specimen_type"),
        Index("idx_test_specimen_species", "test_id", "specimen_type", "species_id"),
    )

    def __repr__(self):
        species_info = f" (Species: {self.species_id})" if self.species_id else ""
        return f"<TestSpecimenType {self.specimen_type} for Test {self.test_id}{species_info}>"
