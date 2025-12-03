"""Order models for lab requisitions."""

from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Float, Index, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class Order(Base):
    """Lab order/requisition."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    facility_id = Column(Integer, ForeignKey("facilities.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)

    # Order details
    ordering_veterinarian = Column(String(100), nullable=False)
    specimen_collection_date = Column(Date, nullable=False, index=True)
    specimen_collection_time = Column(String(10), nullable=True)  # HH:MM format
    specimen_storage_temperature = Column(String(50), nullable=True)
    # Storage options: Stored Ambient, Stored Frozen, Stored Refrigerated

    # Order metadata
    order_date = Column(DateTime, server_default=func.now(), index=True)
    status = Column(String(50), default="pending", index=True)
    # Status: pending, reviewed, approved, rejected, submitted

    # Review information
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewer_notes = Column(Text, nullable=True)

    # Lab submission
    submitted_to_lab = Column(Integer, default=0)  # 0 = false, 1 = true (SQLite compatible)
    lab_submission_date = Column(DateTime, nullable=True)
    lab_confirmation_id = Column(String(100), nullable=True)

    # StarLIMS Integration fields
    starlims_accession = Column(String(100), nullable=True, index=True)  # StarLIMS accession number
    starlims_status = Column(String(50), nullable=True)  # Status from StarLIMS
    starlims_error = Column(Text, nullable=True)  # Error message from StarLIMS
    lab_support_ticket = Column(String(100), nullable=True, index=True)  # Support ticket number

    # Source document reference
    source_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    extracted_json = Column(Text, nullable=True)  # Full JSON from AI extraction

    # Audit
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    facility = relationship("Facility", back_populates="orders")
    patient = relationship("Patient", back_populates="orders")
    order_tests = relationship("OrderTest", back_populates="order", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="order", foreign_keys="Document.order_id")
    source_document = relationship("Document", foreign_keys=[source_document_id], uselist=False)

    __table_args__ = (
        Index("idx_order_status", "status"),
        Index("idx_order_collection_date", "specimen_collection_date"),
        Index("idx_order_facility_patient", "facility_id", "patient_id"),
    )

    def __repr__(self):
        return f"<Order {self.id} - Patient {self.patient_id}>"


class OrderTest(Base):
    """Tests requested on a specific order (junction table)."""

    __tablename__ = "order_tests"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    test_id = Column(Integer, ForeignKey("tests.id"), nullable=False, index=True)

    # Actual specimen information for this test on this order
    specimen_type = Column(String(50), nullable=True)
    specimen_volume_ml = Column(Float, nullable=True)
    specimen_notes = Column(Text, nullable=True)

    # Relationships
    order = relationship("Order", back_populates="order_tests")
    test = relationship("Test", back_populates="order_tests")

    __table_args__ = (
        Index("idx_order_test", "order_id", "test_id"),
    )

    def __repr__(self):
        return f"<OrderTest Order={self.order_id} Test={self.test_id}>"
