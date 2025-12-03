"""Patient Lookup Service for intelligent patient matching and auto-fill."""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from rapidfuzz import fuzz

from app.models.patient import Patient
from app.models.species import Species

logger = logging.getLogger(__name__)


@dataclass
class PatientMatch:
    """Result of a patient lookup."""
    patient_id: int
    patient: Patient
    confidence: float
    match_details: str


@dataclass
class PatientLookupResult:
    """Complete result of patient lookup."""
    matches: List[PatientMatch]
    is_exact_match: bool
    has_multiple: bool


class PatientLookupService:
    """Service for looking up and matching patients."""

    # Human species ID (typically ID=1 for "Human")
    HUMAN_SPECIES_NAME = "Human"

    def __init__(self, db: Session):
        self.db = db
        self._human_species_id: Optional[int] = None

    @property
    def human_species_id(self) -> Optional[int]:
        """Get the species ID for humans (cached)."""
        if self._human_species_id is None:
            species = (
                self.db.query(Species)
                .filter(Species.common_name.ilike(self.HUMAN_SPECIES_NAME))
                .first()
            )
            if species:
                self._human_species_id = species.id
        return self._human_species_id

    def normalize_name(self, name: Optional[str]) -> str:
        """Normalize a name for comparison."""
        if not name:
            return ""
        # Lowercase, strip whitespace, remove extra spaces
        name = " ".join(name.lower().strip().split())
        return name

    def lookup_patient(
        self,
        facility_id: int,
        owner_last_name: Optional[str] = None,
        owner_first_name: Optional[str] = None,
        pet_name: Optional[str] = None,
        species_id: Optional[int] = None,
        medical_record_number: Optional[str] = None,
    ) -> PatientLookupResult:
        """
        Look up patients matching the given criteria.

        For veterinary patients: match on owner_last_name + pet_name
        For human patients: match on owner_last_name + owner_first_name

        Returns list of matching patients with confidence scores.
        """
        # Start with base query filtered by facility
        query = self.db.query(Patient).filter(Patient.facility_id == facility_id)

        # If MRN provided, try exact match first
        if medical_record_number:
            mrn_match = query.filter(
                Patient.medical_record_number == medical_record_number
            ).first()
            if mrn_match:
                return PatientLookupResult(
                    matches=[PatientMatch(
                        patient_id=mrn_match.id,
                        patient=mrn_match,
                        confidence=1.0,
                        match_details="Exact MRN match",
                    )],
                    is_exact_match=True,
                    has_multiple=False,
                )

        # Get all patients for this facility to do fuzzy matching
        all_patients = query.all()

        if not all_patients:
            return PatientLookupResult(
                matches=[],
                is_exact_match=False,
                has_multiple=False,
            )

        # Score each patient
        scored_patients: List[PatientMatch] = []

        for patient in all_patients:
            score, details = self._calculate_patient_match_score(
                patient=patient,
                owner_last_name=owner_last_name,
                owner_first_name=owner_first_name,
                pet_name=pet_name,
                species_id=species_id,
            )

            if score >= 0.5:  # Minimum threshold
                scored_patients.append(PatientMatch(
                    patient_id=patient.id,
                    patient=patient,
                    confidence=score,
                    match_details=details,
                ))

        # Sort by confidence descending
        scored_patients.sort(key=lambda x: x.confidence, reverse=True)

        # Determine if exact match
        is_exact = len(scored_patients) > 0 and scored_patients[0].confidence >= 0.95
        has_multiple = len(scored_patients) > 1

        return PatientLookupResult(
            matches=scored_patients[:10],  # Limit to top 10
            is_exact_match=is_exact,
            has_multiple=has_multiple,
        )

    def _calculate_patient_match_score(
        self,
        patient: Patient,
        owner_last_name: Optional[str],
        owner_first_name: Optional[str],
        pet_name: Optional[str],
        species_id: Optional[int],
    ) -> tuple[float, str]:
        """Calculate match score for a patient. Returns (score, details)."""
        scores = []
        match_parts = []

        # Owner last name (most important for both human and vet)
        if owner_last_name and patient.owner_last_name:
            norm_search = self.normalize_name(owner_last_name)
            norm_db = self.normalize_name(patient.owner_last_name)
            last_name_score = fuzz.ratio(norm_search, norm_db) / 100.0
            scores.append(("last_name", last_name_score, 0.4))
            if last_name_score >= 0.9:
                match_parts.append("last name")

        # Check if this is likely a human patient (no pet name in DB)
        is_human_patient = patient.pet_name is None or patient.species_id == self.human_species_id

        if is_human_patient:
            # For humans: match on owner_first_name (patient's first name)
            if owner_first_name and patient.owner_first_name:
                norm_search = self.normalize_name(owner_first_name)
                norm_db = self.normalize_name(patient.owner_first_name)
                first_name_score = fuzz.ratio(norm_search, norm_db) / 100.0
                scores.append(("first_name", first_name_score, 0.4))
                if first_name_score >= 0.9:
                    match_parts.append("first name")
        else:
            # For veterinary: match on pet_name
            if pet_name and patient.pet_name:
                norm_search = self.normalize_name(pet_name)
                norm_db = self.normalize_name(patient.pet_name)
                pet_name_score = fuzz.ratio(norm_search, norm_db) / 100.0
                scores.append(("pet_name", pet_name_score, 0.4))
                if pet_name_score >= 0.9:
                    match_parts.append("pet name")

            # Also check owner first name with lower weight
            if owner_first_name and patient.owner_first_name:
                norm_search = self.normalize_name(owner_first_name)
                norm_db = self.normalize_name(patient.owner_first_name)
                first_name_score = fuzz.ratio(norm_search, norm_db) / 100.0
                scores.append(("first_name", first_name_score, 0.1))

        # Species match (bonus)
        if species_id and patient.species_id:
            if species_id == patient.species_id:
                scores.append(("species", 1.0, 0.1))
                match_parts.append("species")

        # Calculate weighted average
        if not scores:
            return 0.0, "No matching criteria"

        total_weight = sum(w for _, _, w in scores)
        weighted_sum = sum(s * w for _, s, w in scores)
        final_score = weighted_sum / total_weight if total_weight > 0 else 0.0

        details = f"Matched by: {', '.join(match_parts)}" if match_parts else "Partial match"
        details += f" ({final_score:.0%} confidence)"

        return final_score, details

    def search_patients(
        self,
        facility_id: int,
        query: str,
        limit: int = 10,
    ) -> List[Patient]:
        """
        Search patients by any field (for autocomplete).
        Searches: owner_last_name, owner_first_name, pet_name, MRN.
        """
        if not query or len(query) < 2:
            return []

        norm_query = self.normalize_name(query)

        # Get all patients for this facility
        patients = (
            self.db.query(Patient)
            .filter(Patient.facility_id == facility_id)
            .all()
        )

        # Score each patient
        scored: List[tuple[Patient, float]] = []
        for patient in patients:
            # Check each searchable field
            max_score = 0.0

            fields_to_check = [
                patient.owner_last_name,
                patient.owner_first_name,
                patient.pet_name,
                patient.medical_record_number,
            ]

            for field in fields_to_check:
                if field:
                    norm_field = self.normalize_name(field)
                    # Use partial_ratio for substring matching
                    score = fuzz.partial_ratio(norm_query, norm_field) / 100.0
                    max_score = max(max_score, score)

            if max_score >= 0.6:  # Minimum threshold for search
                scored.append((patient, max_score))

        # Sort by score and return top results
        scored.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in scored[:limit]]

    def get_patient_details(self, patient_id: int) -> Optional[Dict[str, Any]]:
        """Get patient details for auto-fill."""
        patient = self.db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return None

        # Get species info
        species = (
            self.db.query(Species)
            .filter(Species.id == patient.species_id)
            .first()
        )

        return {
            "patient_id": patient.id,
            "owner_last_name": patient.owner_last_name,
            "owner_first_name": patient.owner_first_name,
            "owner_middle_name": patient.owner_middle_name,
            "pet_name": patient.pet_name,
            "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
            "species_id": patient.species_id,
            "species_name": species.common_name if species else None,
            "medical_record_number": patient.medical_record_number,
            "gender": patient.gender,
            "phone": patient.phone,
            "email": patient.email,
            "address": patient.address,
            "city": patient.city,
            "state": patient.state,
            "zipcode": patient.zipcode,
        }

    def is_human_patient(self, species_id: Optional[int]) -> bool:
        """Check if the species ID represents a human patient."""
        if species_id is None:
            return False
        return species_id == self.human_species_id

    def get_species_list(self) -> List[Dict[str, Any]]:
        """Get list of all species for dropdown."""
        species_list = self.db.query(Species).order_by(Species.common_name).all()
        return [
            {
                "id": s.id,
                "common_name": s.common_name,
                "scientific_name": s.scientific_name,
                "is_human": s.common_name.lower() == "human",
            }
            for s in species_list
        ]

    def create_patient(
        self,
        facility_id: int,
        species_id: int,
        owner_last_name: str,
        owner_first_name: str,
        owner_middle_name: Optional[str] = None,
        pet_name: Optional[str] = None,
        date_of_birth: Optional[date] = None,
        medical_record_number: Optional[str] = None,
        gender: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        zipcode: Optional[str] = None,
    ) -> Optional[Patient]:
        """Create a new patient record."""
        try:
            patient = Patient(
                facility_id=facility_id,
                species_id=species_id,
                owner_last_name=owner_last_name,
                owner_first_name=owner_first_name,
                owner_middle_name=owner_middle_name,
                pet_name=pet_name,
                date_of_birth=date_of_birth,
                medical_record_number=medical_record_number,
                gender=gender,
                phone=phone,
                email=email,
                address=address,
                city=city,
                state=state,
                zipcode=zipcode,
            )
            self.db.add(patient)
            self.db.commit()
            self.db.refresh(patient)
            return patient
        except Exception as e:
            logger.error(f"Failed to create patient: {e}")
            self.db.rollback()
            return None
