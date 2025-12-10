"""Workstation equipment API endpoints for scanning stations, label printers, and laser printers."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
import logging

from app.database import get_db
from app.models.workstation import ScanningStation, LabelPrinter, LaserPrinter, UserWorkstationPreference
from app.utils.timezone import now_eastern

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# Schemas
# =============================================================================

class ScanningStationCreate(BaseModel):
    name: str
    location: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class ScanningStationUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ScanningStationResponse(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    description: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class LabelPrinterCreate(BaseModel):
    name: str
    location: Optional[str] = None
    printer_type: Optional[str] = None
    connection_string: Optional[str] = None
    is_active: bool = True


class LabelPrinterUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    printer_type: Optional[str] = None
    connection_string: Optional[str] = None
    is_active: Optional[bool] = None


class LabelPrinterResponse(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    printer_type: Optional[str] = None
    connection_string: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class LaserPrinterCreate(BaseModel):
    name: str
    location: Optional[str] = None
    printer_type: Optional[str] = None
    model: Optional[str] = None
    connection_string: Optional[str] = None
    print_method: str = "universal_print"
    default_paper_size: str = "Letter"
    supports_duplex: bool = True
    supports_color: bool = False
    default_tray: Optional[str] = None
    is_active: bool = True


class LaserPrinterUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    printer_type: Optional[str] = None
    model: Optional[str] = None
    connection_string: Optional[str] = None
    print_method: Optional[str] = None
    default_paper_size: Optional[str] = None
    supports_duplex: Optional[bool] = None
    supports_color: Optional[bool] = None
    default_tray: Optional[str] = None
    is_active: Optional[bool] = None


class LaserPrinterResponse(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    printer_type: Optional[str] = None
    model: Optional[str] = None
    connection_string: Optional[str] = None
    print_method: str = "universal_print"
    default_paper_size: str = "Letter"
    supports_duplex: bool = True
    supports_color: bool = False
    default_tray: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class UserPreferenceUpdate(BaseModel):
    scanning_station_id: Optional[int] = None
    label_printer_id: Optional[int] = None
    laser_printer_id: Optional[int] = None


class UserPreferenceResponse(BaseModel):
    user_id: str
    scanning_station_id: Optional[int] = None
    scanning_station_name: Optional[str] = None
    label_printer_id: Optional[int] = None
    label_printer_name: Optional[str] = None
    laser_printer_id: Optional[int] = None
    laser_printer_name: Optional[str] = None


# =============================================================================
# Scanning Stations Endpoints
# =============================================================================

@router.get("/stations", response_model=List[ScanningStationResponse])
async def list_scanning_stations(
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """List all scanning stations."""
    query = db.query(ScanningStation)
    if active_only:
        query = query.filter(ScanningStation.is_active == True)
    stations = query.order_by(ScanningStation.name).all()
    return stations


@router.get("/stations/{station_id}", response_model=ScanningStationResponse)
async def get_scanning_station(
    station_id: int,
    db: Session = Depends(get_db)
):
    """Get a scanning station by ID."""
    station = db.query(ScanningStation).filter(ScanningStation.id == station_id).first()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scanning station not found"
        )
    return station


@router.post("/stations", response_model=ScanningStationResponse, status_code=status.HTTP_201_CREATED)
async def create_scanning_station(
    station: ScanningStationCreate,
    db: Session = Depends(get_db)
):
    """Create a new scanning station."""
    db_station = ScanningStation(
        name=station.name,
        location=station.location,
        description=station.description,
        is_active=station.is_active
    )
    db.add(db_station)
    db.commit()
    db.refresh(db_station)
    logger.info(f"Created scanning station: {db_station.name}")
    return db_station


@router.put("/stations/{station_id}", response_model=ScanningStationResponse)
async def update_scanning_station(
    station_id: int,
    station: ScanningStationUpdate,
    db: Session = Depends(get_db)
):
    """Update a scanning station."""
    db_station = db.query(ScanningStation).filter(ScanningStation.id == station_id).first()
    if not db_station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scanning station not found"
        )

    if station.name is not None:
        db_station.name = station.name
    if station.location is not None:
        db_station.location = station.location
    if station.description is not None:
        db_station.description = station.description
    if station.is_active is not None:
        db_station.is_active = station.is_active

    db_station.updated_at = now_eastern()
    db.commit()
    db.refresh(db_station)
    logger.info(f"Updated scanning station: {db_station.name}")
    return db_station


@router.delete("/stations/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scanning_station(
    station_id: int,
    db: Session = Depends(get_db)
):
    """Delete a scanning station."""
    db_station = db.query(ScanningStation).filter(ScanningStation.id == station_id).first()
    if not db_station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scanning station not found"
        )

    # Clear any user preferences referencing this station
    db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.scanning_station_id == station_id
    ).update({"scanning_station_id": None})

    db.delete(db_station)
    db.commit()
    logger.info(f"Deleted scanning station: {db_station.name}")


# =============================================================================
# Label Printers Endpoints
# =============================================================================

@router.get("/printers", response_model=List[LabelPrinterResponse])
async def list_label_printers(
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """List all label printers."""
    query = db.query(LabelPrinter)
    if active_only:
        query = query.filter(LabelPrinter.is_active == True)
    printers = query.order_by(LabelPrinter.name).all()
    return printers


@router.get("/printers/{printer_id}", response_model=LabelPrinterResponse)
async def get_label_printer(
    printer_id: int,
    db: Session = Depends(get_db)
):
    """Get a label printer by ID."""
    printer = db.query(LabelPrinter).filter(LabelPrinter.id == printer_id).first()
    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label printer not found"
        )
    return printer


@router.post("/printers", response_model=LabelPrinterResponse, status_code=status.HTTP_201_CREATED)
async def create_label_printer(
    printer: LabelPrinterCreate,
    db: Session = Depends(get_db)
):
    """Create a new label printer."""
    db_printer = LabelPrinter(
        name=printer.name,
        location=printer.location,
        printer_type=printer.printer_type,
        connection_string=printer.connection_string,
        is_active=printer.is_active
    )
    db.add(db_printer)
    db.commit()
    db.refresh(db_printer)
    logger.info(f"Created label printer: {db_printer.name}")
    return db_printer


@router.put("/printers/{printer_id}", response_model=LabelPrinterResponse)
async def update_label_printer(
    printer_id: int,
    printer: LabelPrinterUpdate,
    db: Session = Depends(get_db)
):
    """Update a label printer."""
    db_printer = db.query(LabelPrinter).filter(LabelPrinter.id == printer_id).first()
    if not db_printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label printer not found"
        )

    if printer.name is not None:
        db_printer.name = printer.name
    if printer.location is not None:
        db_printer.location = printer.location
    if printer.printer_type is not None:
        db_printer.printer_type = printer.printer_type
    if printer.connection_string is not None:
        db_printer.connection_string = printer.connection_string
    if printer.is_active is not None:
        db_printer.is_active = printer.is_active

    db_printer.updated_at = now_eastern()
    db.commit()
    db.refresh(db_printer)
    logger.info(f"Updated label printer: {db_printer.name}")
    return db_printer


@router.delete("/printers/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label_printer(
    printer_id: int,
    db: Session = Depends(get_db)
):
    """Delete a label printer."""
    db_printer = db.query(LabelPrinter).filter(LabelPrinter.id == printer_id).first()
    if not db_printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Label printer not found"
        )

    # Clear any user preferences referencing this printer
    db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.label_printer_id == printer_id
    ).update({"label_printer_id": None})

    db.delete(db_printer)
    db.commit()
    logger.info(f"Deleted label printer: {db_printer.name}")


# =============================================================================
# Laser Printers Endpoints
# =============================================================================

@router.get("/laser-printers", response_model=List[LaserPrinterResponse])
async def list_laser_printers(
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """List all laser printers."""
    query = db.query(LaserPrinter)
    if active_only:
        query = query.filter(LaserPrinter.is_active == True)
    printers = query.order_by(LaserPrinter.name).all()
    return printers


@router.get("/laser-printers/{printer_id}", response_model=LaserPrinterResponse)
async def get_laser_printer(
    printer_id: int,
    db: Session = Depends(get_db)
):
    """Get a laser printer by ID."""
    printer = db.query(LaserPrinter).filter(LaserPrinter.id == printer_id).first()
    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Laser printer not found"
        )
    return printer


@router.post("/laser-printers", response_model=LaserPrinterResponse, status_code=status.HTTP_201_CREATED)
async def create_laser_printer(
    printer: LaserPrinterCreate,
    db: Session = Depends(get_db)
):
    """Create a new laser printer."""
    db_printer = LaserPrinter(
        name=printer.name,
        location=printer.location,
        printer_type=printer.printer_type,
        model=printer.model,
        connection_string=printer.connection_string,
        print_method=printer.print_method,
        default_paper_size=printer.default_paper_size,
        supports_duplex=printer.supports_duplex,
        supports_color=printer.supports_color,
        default_tray=printer.default_tray,
        is_active=printer.is_active
    )
    db.add(db_printer)
    db.commit()
    db.refresh(db_printer)
    logger.info(f"Created laser printer: {db_printer.name}")
    return db_printer


@router.put("/laser-printers/{printer_id}", response_model=LaserPrinterResponse)
async def update_laser_printer(
    printer_id: int,
    printer: LaserPrinterUpdate,
    db: Session = Depends(get_db)
):
    """Update a laser printer."""
    db_printer = db.query(LaserPrinter).filter(LaserPrinter.id == printer_id).first()
    if not db_printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Laser printer not found"
        )

    if printer.name is not None:
        db_printer.name = printer.name
    if printer.location is not None:
        db_printer.location = printer.location
    if printer.printer_type is not None:
        db_printer.printer_type = printer.printer_type
    if printer.model is not None:
        db_printer.model = printer.model
    if printer.connection_string is not None:
        db_printer.connection_string = printer.connection_string
    if printer.print_method is not None:
        db_printer.print_method = printer.print_method
    if printer.default_paper_size is not None:
        db_printer.default_paper_size = printer.default_paper_size
    if printer.supports_duplex is not None:
        db_printer.supports_duplex = printer.supports_duplex
    if printer.supports_color is not None:
        db_printer.supports_color = printer.supports_color
    if printer.default_tray is not None:
        db_printer.default_tray = printer.default_tray
    if printer.is_active is not None:
        db_printer.is_active = printer.is_active

    db_printer.updated_at = now_eastern()
    db.commit()
    db.refresh(db_printer)
    logger.info(f"Updated laser printer: {db_printer.name}")
    return db_printer


@router.delete("/laser-printers/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_laser_printer(
    printer_id: int,
    db: Session = Depends(get_db)
):
    """Delete a laser printer."""
    db_printer = db.query(LaserPrinter).filter(LaserPrinter.id == printer_id).first()
    if not db_printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Laser printer not found"
        )

    # Clear any user preferences referencing this printer
    db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.laser_printer_id == printer_id
    ).update({"laser_printer_id": None})

    db.delete(db_printer)
    db.commit()
    logger.info(f"Deleted laser printer: {db_printer.name}")


# =============================================================================
# User Preferences Endpoints
# =============================================================================

@router.get("/preferences/{user_id}", response_model=UserPreferenceResponse)
async def get_user_preferences(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get user's workstation preferences."""
    pref = db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.user_id == user_id
    ).first()

    if not pref:
        return UserPreferenceResponse(
            user_id=user_id,
            scanning_station_id=None,
            scanning_station_name=None,
            label_printer_id=None,
            label_printer_name=None,
            laser_printer_id=None,
            laser_printer_name=None
        )

    station_name = pref.scanning_station.name if pref.scanning_station else None
    label_printer_name = pref.label_printer.name if pref.label_printer else None
    laser_printer_name = pref.laser_printer.name if pref.laser_printer else None

    return UserPreferenceResponse(
        user_id=user_id,
        scanning_station_id=pref.scanning_station_id,
        scanning_station_name=station_name,
        label_printer_id=pref.label_printer_id,
        label_printer_name=label_printer_name,
        laser_printer_id=pref.laser_printer_id,
        laser_printer_name=laser_printer_name
    )


@router.put("/preferences/{user_id}", response_model=UserPreferenceResponse)
async def update_user_preferences(
    user_id: str,
    preferences: UserPreferenceUpdate,
    db: Session = Depends(get_db)
):
    """Update user's workstation preferences."""
    # Validate station exists if provided
    if preferences.scanning_station_id is not None and preferences.scanning_station_id > 0:
        station = db.query(ScanningStation).filter(
            ScanningStation.id == preferences.scanning_station_id
        ).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scanning station not found"
            )

    # Validate label printer exists if provided
    if preferences.label_printer_id is not None and preferences.label_printer_id > 0:
        printer = db.query(LabelPrinter).filter(
            LabelPrinter.id == preferences.label_printer_id
        ).first()
        if not printer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Label printer not found"
            )

    # Validate laser printer exists if provided
    if preferences.laser_printer_id is not None and preferences.laser_printer_id > 0:
        laser = db.query(LaserPrinter).filter(
            LaserPrinter.id == preferences.laser_printer_id
        ).first()
        if not laser:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Laser printer not found"
            )

    # Get or create preference record
    pref = db.query(UserWorkstationPreference).filter(
        UserWorkstationPreference.user_id == user_id
    ).first()

    if not pref:
        pref = UserWorkstationPreference(user_id=user_id)
        db.add(pref)

    # Update preferences
    if preferences.scanning_station_id is not None:
        pref.scanning_station_id = preferences.scanning_station_id if preferences.scanning_station_id > 0 else None
    if preferences.label_printer_id is not None:
        pref.label_printer_id = preferences.label_printer_id if preferences.label_printer_id > 0 else None
    if preferences.laser_printer_id is not None:
        pref.laser_printer_id = preferences.laser_printer_id if preferences.laser_printer_id > 0 else None

    pref.updated_at = now_eastern()
    db.commit()
    db.refresh(pref)

    station_name = pref.scanning_station.name if pref.scanning_station else None
    label_printer_name = pref.label_printer.name if pref.label_printer else None
    laser_printer_name = pref.laser_printer.name if pref.laser_printer else None

    logger.info(f"Updated workstation preferences for user {user_id}")

    return UserPreferenceResponse(
        user_id=user_id,
        scanning_station_id=pref.scanning_station_id,
        scanning_station_name=station_name,
        label_printer_id=pref.label_printer_id,
        label_printer_name=label_printer_name,
        laser_printer_id=pref.laser_printer_id,
        laser_printer_name=laser_printer_name
    )
