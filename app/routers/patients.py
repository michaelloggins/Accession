"""Patient lookup and management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import date
import logging

from app.database import get_db
from app.models.patient import Patient
from app.services.patient_lookup_service import PatientLookupService
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


# Schemas
class PatientLookupRequest(BaseModel):
    """Request body for patient lookup."""
    facility_id: int
    owner_last_name: Optional[str] = None
    owner_first_name: Optional[str] = None
    pet_name: Optional[str] = None
    species_id: Optional[int] = None
    medical_record_number: Optional[str] = None


class PatientMatchResponse(BaseModel):
    """Single patient match result."""
    patient_id: int
    owner_last_name: str
    owner_first_name: str
    owner_middle_name: Optional[str] = None
    pet_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    species_id: Optional[int] = None
    species_name: Optional[str] = None
    medical_record_number: Optional[str] = None
    confidence: float
    match_details: str

    class Config:
        from_attributes = True


class PatientLookupResponse(BaseModel):
    """Patient lookup result."""
    matches: List[PatientMatchResponse]
    is_exact_match: bool
    has_multiple: bool


class PatientDetailsResponse(BaseModel):
    """Full patient details for auto-fill."""
    patient_id: int
    owner_last_name: str
    owner_first_name: str
    owner_middle_name: Optional[str] = None
    pet_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    species_id: Optional[int] = None
    species_name: Optional[str] = None
    medical_record_number: Optional[str] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None

    class Config:
        from_attributes = True


class PatientCreateRequest(BaseModel):
    """Request to create a new patient."""
    facility_id: int
    species_id: int
    owner_last_name: str
    owner_first_name: str
    owner_middle_name: Optional[str] = None
    pet_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    medical_record_number: Optional[str] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zipcode: Optional[str] = None


class SpeciesResponse(BaseModel):
    """Species information."""
    id: int
    common_name: str
    scientific_name: Optional[str] = None
    is_human: bool


# Patient Lookup Endpoints
@router.post("/lookup", response_model=PatientLookupResponse)
async def lookup_patient(
    request: PatientLookupRequest,
    db: Session = Depends(get_db)
):
    """
    Look up patients matching the given criteria.

    For veterinary patients: match on owner_last_name + pet_name
    For human patients: match on owner_last_name + owner_first_name

    Returns list of matching patients with confidence scores.
    """
    lookup_service = PatientLookupService(db)

    result = lookup_service.lookup_patient(
        facility_id=request.facility_id,
        owner_last_name=request.owner_last_name,
        owner_first_name=request.owner_first_name,
        pet_name=request.pet_name,
        species_id=request.species_id,
        medical_record_number=request.medical_record_number,
    )

    # Convert to response format
    matches = []
    for match in result.matches:
        patient = match.patient
        # Get species name
        species_name = None
        if patient.species:
            species_name = patient.species.common_name

        matches.append(PatientMatchResponse(
            patient_id=match.patient_id,
            owner_last_name=patient.owner_last_name,
            owner_first_name=patient.owner_first_name,
            owner_middle_name=patient.owner_middle_name,
            pet_name=patient.pet_name,
            date_of_birth=patient.date_of_birth,
            species_id=patient.species_id,
            species_name=species_name,
            medical_record_number=patient.medical_record_number,
            confidence=match.confidence,
            match_details=match.match_details,
        ))

    return PatientLookupResponse(
        matches=matches,
        is_exact_match=result.is_exact_match,
        has_multiple=result.has_multiple,
    )


@router.get("/search")
async def search_patients(
    facility_id: int,
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Search patients by any field (for autocomplete)."""
    if not q or len(q) < 2:
        return []

    lookup_service = PatientLookupService(db)
    patients = lookup_service.search_patients(facility_id, q, limit)

    return [
        {
            "patient_id": p.id,
            "owner_last_name": p.owner_last_name,
            "owner_first_name": p.owner_first_name,
            "pet_name": p.pet_name,
            "medical_record_number": p.medical_record_number,
            "display_name": f"{p.owner_last_name}, {p.owner_first_name}" + (f" ({p.pet_name})" if p.pet_name else ""),
        }
        for p in patients
    ]


@router.get("/{patient_id}", response_model=PatientDetailsResponse)
async def get_patient_details(
    patient_id: int,
    db: Session = Depends(get_db)
):
    """Get full patient details for auto-fill."""
    lookup_service = PatientLookupService(db)
    details = lookup_service.get_patient_details(patient_id)

    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found"
        )

    return PatientDetailsResponse(**details)


@router.post("/", response_model=PatientDetailsResponse)
async def create_patient(
    request: PatientCreateRequest,
    db: Session = Depends(get_db)
):
    """Create a new patient record."""
    lookup_service = PatientLookupService(db)

    patient = lookup_service.create_patient(
        facility_id=request.facility_id,
        species_id=request.species_id,
        owner_last_name=request.owner_last_name,
        owner_first_name=request.owner_first_name,
        owner_middle_name=request.owner_middle_name,
        pet_name=request.pet_name,
        date_of_birth=request.date_of_birth,
        medical_record_number=request.medical_record_number,
        gender=request.gender,
        phone=request.phone,
        email=request.email,
        address=request.address,
        city=request.city,
        state=request.state,
        zipcode=request.zipcode,
    )

    if not patient:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create patient"
        )

    # Get details for response
    details = lookup_service.get_patient_details(patient.id)
    return PatientDetailsResponse(**details)


@router.get("/species/list", response_model=List[SpeciesResponse])
async def get_species_list(
    db: Session = Depends(get_db)
):
    """Get list of all species for dropdown."""
    lookup_service = PatientLookupService(db)
    species_list = lookup_service.get_species_list()
    return [SpeciesResponse(**s) for s in species_list]


@router.get("/is-human/{species_id}")
async def check_is_human(
    species_id: int,
    db: Session = Depends(get_db)
):
    """Check if a species ID represents a human patient."""
    lookup_service = PatientLookupService(db)
    is_human = lookup_service.is_human_patient(species_id)
    return {"is_human": is_human}
