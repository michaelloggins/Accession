"""Workstation equipment models for scanning stations, label printers, and laser printers."""

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

    # Universal Print integration
    universal_print_id = Column(String(255), nullable=True)  # Microsoft Graph printer ID
    print_method = Column(String(50), default="universal_print")  # "universal_print", "direct_ip", "local"

    # ZPL settings
    label_width_dpi = Column(Integer, default=203)  # 203 or 300 DPI
    label_width_inches = Column(String(10), default="2")  # e.g., "2", "4"
    label_height_inches = Column(String(10), default="1")  # e.g., "1", "6"

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_eastern)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    def __repr__(self):
        return f"<LabelPrinter {self.name}>"

    @property
    def label_width_dots(self) -> int:
        """Calculate label width in dots based on DPI and inches."""
        try:
            return int(float(self.label_width_inches) * self.label_width_dpi)
        except (ValueError, TypeError):
            return 406  # Default 2" at 203 DPI

    @property
    def label_height_dots(self) -> int:
        """Calculate label height in dots based on DPI and inches."""
        try:
            return int(float(self.label_height_inches) * self.label_width_dpi)
        except (ValueError, TypeError):
            return 203  # Default 1" at 203 DPI


class LaserPrinter(Base):
    """Laser printer configuration for document printing."""

    __tablename__ = "laser_printers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    location = Column(String(255), nullable=True)
    printer_type = Column(String(50), nullable=True)  # e.g., "HP", "Canon", "Brother", "Lexmark"
    model = Column(String(100), nullable=True)  # e.g., "LaserJet Pro M404n"
    connection_string = Column(String(500), nullable=True)  # IP address, network path, etc.

    # Universal Print integration
    universal_print_id = Column(String(255), nullable=True)  # Microsoft Graph printer ID
    print_method = Column(String(50), default="universal_print")  # "universal_print", "direct_ip", "network_share"

    # Print settings
    default_paper_size = Column(String(20), default="Letter")  # "Letter", "Legal", "A4"
    supports_duplex = Column(Boolean, default=True)
    supports_color = Column(Boolean, default=False)
    default_tray = Column(String(50), nullable=True)  # e.g., "Tray 1", "Auto"

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_eastern)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    def __repr__(self):
        return f"<LaserPrinter {self.name}>"


class UserWorkstationPreference(Base):
    """Stores user's workstation preferences (selected station and printers)."""

    __tablename__ = "user_workstation_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False, unique=True, index=True)
    scanning_station_id = Column(Integer, ForeignKey("scanning_stations.id"), nullable=True)
    label_printer_id = Column(Integer, ForeignKey("label_printers.id"), nullable=True)
    laser_printer_id = Column(Integer, ForeignKey("laser_printers.id"), nullable=True)
    updated_at = Column(DateTime, default=now_eastern, onupdate=now_eastern)

    # Relationships
    scanning_station = relationship("ScanningStation")
    label_printer = relationship("LabelPrinter")
    laser_printer = relationship("LaserPrinter")

    def __repr__(self):
        return f"<UserWorkstationPreference user={self.user_id}>"
