"""Facility management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import logging

from app.database import get_db
from app.models.facility import Facility
from app.models.facility_physician import FacilityPhysician
from app.models.facility_match_log import FacilityMatchLog
from app.services.facility_matching_service import FacilityMatchingService
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


# Schemas
class FacilityResponse(BaseModel):
    id: int
    facility_id: Optional[str] = None
    facility_name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    laboratory_contact: Optional[str] = None
    phone: Optional[str] = None
    fax: Optional[str] = None
    email: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/by-facility-id/{facility_id}", response_model=FacilityResponse)
async def get_facility_by_code(
    facility_id: str,
    db: Session = Depends(get_db)
):
    """Get facility by facility_id (external code)."""
    facility = db.query(Facility).filter(Facility.facility_id == facility_id).first()
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Facility with ID '{facility_id}' not found"
        )

    logger.info(f"Retrieved facility: {facility_id} - {facility.facility_name}")
    return facility


@router.get("/{id}", response_model=FacilityResponse)
async def get_facility(
    id: int,
    db: Session = Depends(get_db)
):
    """Get facility by database ID."""
    facility = db.query(Facility).filter(Facility.id == id).first()
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facility not found"
        )

    return facility


# Additional Schemas for Facility Matching
class FacilityMatchRequest(BaseModel):
    """Request body for facility matching."""
    facility_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    fax: Optional[str] = None
    phone: Optional[str] = None
    document_id: Optional[int] = None


class DiscrepancyInfo(BaseModel):
    """Field discrepancy between extracted and database values."""
    extracted: str
    database: str


class FacilityMatchResponse(BaseModel):
    """Single facility match result."""
    facility_id: int
    facility_name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None
    fax: Optional[str] = None
    phone: Optional[str] = None
    confidence: float
    method: str
    details: str
    discrepancies: Dict[str, DiscrepancyInfo]

    class Config:
        from_attributes = True


class MatchResultResponse(BaseModel):
    """Complete facility matching result."""
    best_match: Optional[FacilityMatchResponse] = None
    alternatives: List[FacilityMatchResponse]
    extracted_data: Dict[str, Any]
    log_id: Optional[int] = None


class PhysicianResponse(BaseModel):
    """Physician information."""
    id: int
    facility_id: int
    name: str
    npi: Optional[str] = None
    specialty: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


class PhysicianCreateRequest(BaseModel):
    """Request to create a new physician."""
    name: str
    npi: Optional[str] = None
    specialty: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class ConfirmMatchRequest(BaseModel):
    """Request to confirm a facility match."""
    document_id: int
    facility_id: int


# Facility Matching Endpoints
@router.post("/match", response_model=MatchResultResponse)
async def match_facility(
    request: FacilityMatchRequest,
    db: Session = Depends(get_db)
):
    """
    Match extracted facility data against database records.

    Uses multi-tier matching:
    1. Exact fax number match (highest confidence)
    2. Fuzzy name matching
    3. Address matching
    4. Phone matching

    Returns best match and alternatives with confidence scores.
    """
    matching_service = FacilityMatchingService(db)

    result = matching_service.find_matches(
        extracted_name=request.facility_name,
        extracted_address=request.address,
        extracted_city=request.city,
        extracted_state=request.state,
        extracted_zipcode=request.zipcode,
        extracted_fax=request.fax,
        extracted_phone=request.phone,
        document_id=request.document_id,
    )

    # Convert to response format
    def match_to_response(match) -> FacilityMatchResponse:
        return FacilityMatchResponse(
            facility_id=match.facility_id,
            facility_name=match.facility.facility_name,
            address=match.facility.address,
            city=match.facility.city,
            state=match.facility.state,
            zipcode=match.facility.zipcode,
            fax=match.facility.fax,
            phone=match.facility.phone,
            confidence=match.confidence,
            method=match.method,
            details=match.details,
            discrepancies={
                k: DiscrepancyInfo(extracted=v["extracted"], database=v["database"])
                for k, v in match.discrepancies.items()
            },
        )

    return MatchResultResponse(
        best_match=match_to_response(result.best_match) if result.best_match else None,
        alternatives=[match_to_response(alt) for alt in result.alternatives],
        extracted_data=result.extracted_data,
        log_id=result.log_id,
    )


@router.post("/confirm-match")
async def confirm_facility_match(
    request: ConfirmMatchRequest,
    http_request: Request,
    db: Session = Depends(get_db)
):
    """Confirm a facility match for a document."""
    matching_service = FacilityMatchingService(db)

    # Get user from request (set by auth middleware)
    user_email = getattr(http_request.state, "user_email", "unknown")

    success = matching_service.confirm_match(
        document_id=request.document_id,
        facility_id=request.facility_id,
        confirmed_by=user_email,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to confirm match"
        )

    return {"success": True, "message": "Match confirmed"}


@router.get("/search")
async def search_facilities(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Search facilities by name (for autocomplete)."""
    if not q or len(q) < 2:
        return []

    matching_service = FacilityMatchingService(db)
    facilities = matching_service.search_facilities(q, limit)

    return [
        {
            "id": f.id,
            "facility_id": f.facility_id,
            "facility_name": f.facility_name,
            "city": f.city,
            "state": f.state,
        }
        for f in facilities
    ]


# Physician Endpoints
@router.get("/{facility_id}/physicians", response_model=List[PhysicianResponse])
async def get_facility_physicians(
    facility_id: int,
    db: Session = Depends(get_db)
):
    """Get all physicians for a facility."""
    matching_service = FacilityMatchingService(db)
    physicians = matching_service.get_facility_physicians(facility_id)
    return physicians


@router.post("/{facility_id}/physicians", response_model=PhysicianResponse)
async def add_facility_physician(
    facility_id: int,
    request: PhysicianCreateRequest,
    db: Session = Depends(get_db)
):
    """Add a new physician to a facility."""
    # Verify facility exists
    facility = db.query(Facility).filter(Facility.id == facility_id).first()
    if not facility:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facility not found"
        )

    matching_service = FacilityMatchingService(db)
    physician = matching_service.add_physician(
        facility_id=facility_id,
        name=request.name,
        npi=request.npi,
        specialty=request.specialty,
        phone=request.phone,
        email=request.email,
    )

    if not physician:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add physician"
        )

    return physician


@router.get("/{id}/match-history")
async def get_facility_match_history(
    id: int,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get recent match history for a facility."""
    logs = (
        db.query(FacilityMatchLog)
        .filter(FacilityMatchLog.matched_facility_id == id)
        .order_by(FacilityMatchLog.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": log.id,
            "document_id": log.document_id,
            "extracted_name": log.extracted_name,
            "match_confidence": float(log.match_confidence) if log.match_confidence else None,
            "match_method": log.match_method,
            "user_confirmed": log.user_confirmed,
            "confirmed_by": log.confirmed_by,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
