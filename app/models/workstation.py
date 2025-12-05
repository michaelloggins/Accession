"""Workstation equipment models for scanning stations and label printers."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_eastern


class ScanningStation(Base):
    """Scanning station configuration."""

    __tablename__ = "scanning_stations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    location = Column(String(255), nullable=True)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_eastern)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    def __repr__(self):
        return f"<ScanningStation {self.name}>"


class LabelPrinter(Base):
    """Label printer configuration."""

    __tablename__ = "label_printers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    location = Column(String(255), nullable=True)
    printer_type = Column(String(50), nullable=True)  # e.g., "Zebra", "DYMO", "Brother"
    connection_string = Column(String(500), nullable=True)  # IP address, USB path, etc.
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_eastern)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    def __repr__(self):
        return f"<LabelPrinter {self.name}>"


class UserWorkstationPreference(Base):
    """Stores user's workstation preferences (selected station and printer)."""

    __tablename__ = "user_workstation_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, unique=True, index=True)
    scanning_station_id = Column(Integer, ForeignKey("scanning_stations.id"), nullable=True)
    label_printer_id = Column(Integer, ForeignKey("label_printers.id"), nullable=True)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    # Relationships
    scanning_station = relationship("ScanningStation")
    label_printer = relationship("LabelPrinter")

    def __repr__(self):
        return f"<UserWorkstationPreference user={self.user_id}>"
