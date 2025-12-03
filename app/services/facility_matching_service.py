"""Facility Matching Service for intelligent facility lookup and matching."""

import json
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session
from rapidfuzz import fuzz, process

from app.models.facility import Facility
from app.models.facility_match_log import FacilityMatchLog
from app.models.facility_physician import FacilityPhysician
from app.models.document import Document

logger = logging.getLogger(__name__)


@dataclass
class FacilityMatch:
    """Result of a facility matching attempt."""
    facility_id: int
    facility: Facility
    confidence: float
    method: str
    details: str
    discrepancies: Dict[str, Dict[str, str]]  # field -> {extracted, database}


@dataclass
class MatchResult:
    """Complete result of facility matching including alternatives."""
    best_match: Optional[FacilityMatch]
    alternatives: List[FacilityMatch]
    extracted_data: Dict[str, Any]
    log_id: Optional[int] = None


class FacilityMatchingService:
    """Service for matching extracted facility data to database records."""

    # Confidence thresholds
    EXACT_MATCH_THRESHOLD = 0.95
    HIGH_CONFIDENCE_THRESHOLD = 0.80
    LOW_CONFIDENCE_THRESHOLD = 0.60

    # Weights for different matching criteria
    WEIGHTS = {
        "name": 0.40,
        "fax": 0.25,
        "address": 0.20,
        "city_state": 0.10,
        "phone": 0.05,
    }

    def __init__(self, db: Session):
        self.db = db

    def normalize_phone(self, phone: Optional[str]) -> str:
        """Normalize phone/fax number to digits only."""
        if not phone:
            return ""
        return re.sub(r'\D', '', phone)

    def normalize_name(self, name: Optional[str]) -> str:
        """Normalize facility name for comparison."""
        if not name:
            return ""
        # Lowercase, remove common suffixes, remove extra whitespace
        name = name.lower().strip()
        # Remove common suffixes
        suffixes = [
            "veterinary clinic", "veterinary hospital", "animal hospital",
            "animal clinic", "vet clinic", "vet hospital", "veterinary",
            "clinic", "hospital", "llc", "inc", "pc", "pllc", "dvm",
        ]
        for suffix in suffixes:
            name = re.sub(rf'\b{suffix}\b', '', name, flags=re.IGNORECASE)
        # Remove extra whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    def normalize_address(self, address: Optional[str]) -> str:
        """Normalize address for comparison."""
        if not address:
            return ""
        address = address.lower().strip()
        # Common abbreviations
        replacements = {
            r'\bstreet\b': 'st',
            r'\bavenue\b': 'ave',
            r'\bdrive\b': 'dr',
            r'\broad\b': 'rd',
            r'\bboulevard\b': 'blvd',
            r'\blane\b': 'ln',
            r'\bcourt\b': 'ct',
            r'\bsuite\b': 'ste',
            r'\bnorth\b': 'n',
            r'\bsouth\b': 's',
            r'\beast\b': 'e',
            r'\bwest\b': 'w',
        }
        for pattern, replacement in replacements.items():
            address = re.sub(pattern, replacement, address)
        # Remove extra whitespace and punctuation
        address = re.sub(r'[.,#]', '', address)
        address = re.sub(r'\s+', ' ', address).strip()
        return address

    def calculate_name_similarity(self, extracted: str, database: str) -> float:
        """Calculate similarity between two facility names."""
        norm_extracted = self.normalize_name(extracted)
        norm_database = self.normalize_name(database)

        if not norm_extracted or not norm_database:
            return 0.0

        # Use token_sort_ratio to handle word order differences
        return fuzz.token_sort_ratio(norm_extracted, norm_database) / 100.0

    def calculate_address_similarity(self, extracted: str, database: str) -> float:
        """Calculate similarity between two addresses."""
        norm_extracted = self.normalize_address(extracted)
        norm_database = self.normalize_address(database)

        if not norm_extracted or not norm_database:
            return 0.0

        return fuzz.token_sort_ratio(norm_extracted, norm_database) / 100.0

    def match_by_fax(self, fax: str) -> List[Facility]:
        """Find facilities with matching fax number."""
        normalized_fax = self.normalize_phone(fax)
        if len(normalized_fax) < 7:  # Must have at least 7 digits
            return []

        # Query all facilities and check normalized fax
        facilities = self.db.query(Facility).filter(Facility.fax.isnot(None)).all()
        matches = []
        for facility in facilities:
            if self.normalize_phone(facility.fax) == normalized_fax:
                matches.append(facility)
        return matches

    def match_by_phone(self, phone: str) -> List[Facility]:
        """Find facilities with matching phone number."""
        normalized_phone = self.normalize_phone(phone)
        if len(normalized_phone) < 7:
            return []

        facilities = self.db.query(Facility).filter(Facility.phone.isnot(None)).all()
        matches = []
        for facility in facilities:
            if self.normalize_phone(facility.phone) == normalized_phone:
                matches.append(facility)
        return matches

    def calculate_match_score(
        self,
        facility: Facility,
        extracted_name: Optional[str],
        extracted_address: Optional[str],
        extracted_city: Optional[str],
        extracted_state: Optional[str],
        extracted_fax: Optional[str],
        extracted_phone: Optional[str],
    ) -> Tuple[float, str, Dict[str, float]]:
        """
        Calculate overall match score for a facility.
        Returns (score, method, component_scores).
        """
        scores = {}
        method_parts = []

        # Name similarity
        if extracted_name and facility.facility_name:
            scores["name"] = self.calculate_name_similarity(
                extracted_name, facility.facility_name
            )
            if scores["name"] >= 0.95:
                method_parts.append("exact_name")
            elif scores["name"] >= 0.80:
                method_parts.append("fuzzy_name")
        else:
            scores["name"] = 0.0

        # Fax match (binary - either matches or doesn't)
        if extracted_fax and facility.fax:
            norm_extracted = self.normalize_phone(extracted_fax)
            norm_db = self.normalize_phone(facility.fax)
            if norm_extracted and norm_db and norm_extracted == norm_db:
                scores["fax"] = 1.0
                method_parts.append("fax")
            else:
                scores["fax"] = 0.0
        else:
            scores["fax"] = 0.0

        # Address similarity
        if extracted_address and facility.address:
            scores["address"] = self.calculate_address_similarity(
                extracted_address, facility.address
            )
            if scores["address"] >= 0.80:
                method_parts.append("address")
        else:
            scores["address"] = 0.0

        # City/State match
        city_state_score = 0.0
        if extracted_city and facility.city:
            city_similarity = fuzz.ratio(
                extracted_city.lower(), facility.city.lower()
            ) / 100.0
            city_state_score += city_similarity * 0.6
        if extracted_state and facility.state:
            if extracted_state.upper() == facility.state.upper():
                city_state_score += 0.4
        scores["city_state"] = city_state_score

        # Phone match
        if extracted_phone and facility.phone:
            norm_extracted = self.normalize_phone(extracted_phone)
            norm_db = self.normalize_phone(facility.phone)
            if norm_extracted and norm_db and norm_extracted == norm_db:
                scores["phone"] = 1.0
                method_parts.append("phone")
            else:
                scores["phone"] = 0.0
        else:
            scores["phone"] = 0.0

        # Calculate weighted total
        total_score = sum(
            scores[key] * self.WEIGHTS[key]
            for key in self.WEIGHTS
        )

        # Determine method string
        if not method_parts:
            method = "fuzzy"
        else:
            method = "+".join(method_parts)

        return total_score, method, scores

    def get_discrepancies(
        self,
        facility: Facility,
        extracted_name: Optional[str],
        extracted_address: Optional[str],
        extracted_city: Optional[str],
        extracted_state: Optional[str],
        extracted_zipcode: Optional[str],
        extracted_fax: Optional[str],
        extracted_phone: Optional[str],
    ) -> Dict[str, Dict[str, str]]:
        """
        Find discrepancies between extracted and database values.
        Returns dict of field -> {extracted, database}.
        """
        discrepancies = {}

        def add_if_different(field: str, extracted: Optional[str], database: Optional[str]):
            if not extracted or not database:
                return
            # Normalize for comparison
            if field in ("fax", "phone"):
                norm_ext = self.normalize_phone(extracted)
                norm_db = self.normalize_phone(database)
                if norm_ext != norm_db:
                    discrepancies[field] = {
                        "extracted": extracted,
                        "database": database,
                    }
            elif field == "facility_name":
                # Use fuzzy match for names
                similarity = self.calculate_name_similarity(extracted, database)
                if similarity < 0.90:
                    discrepancies[field] = {
                        "extracted": extracted,
                        "database": database,
                    }
            elif field == "address":
                similarity = self.calculate_address_similarity(extracted, database)
                if similarity < 0.85:
                    discrepancies[field] = {
                        "extracted": extracted,
                        "database": database,
                    }
            else:
                # Simple comparison for other fields
                if extracted.lower().strip() != database.lower().strip():
                    discrepancies[field] = {
                        "extracted": extracted,
                        "database": database,
                    }

        add_if_different("facility_name", extracted_name, facility.facility_name)
        add_if_different("address", extracted_address, facility.address)
        add_if_different("city", extracted_city, facility.city)
        add_if_different("state", extracted_state, facility.state)
        add_if_different("zipcode", extracted_zipcode, facility.zipcode)
        add_if_different("fax", extracted_fax, facility.fax)
        add_if_different("phone", extracted_phone, facility.phone)

        return discrepancies

    def find_matches(
        self,
        extracted_name: Optional[str] = None,
        extracted_address: Optional[str] = None,
        extracted_city: Optional[str] = None,
        extracted_state: Optional[str] = None,
        extracted_zipcode: Optional[str] = None,
        extracted_fax: Optional[str] = None,
        extracted_phone: Optional[str] = None,
        document_id: Optional[int] = None,
        max_results: int = 5,
    ) -> MatchResult:
        """
        Find matching facilities for extracted data.
        Returns best match and alternatives.
        """
        candidates: List[Tuple[Facility, float, str]] = []

        # Strategy 1: Exact fax match (high confidence)
        if extracted_fax:
            fax_matches = self.match_by_fax(extracted_fax)
            for facility in fax_matches:
                score, method, _ = self.calculate_match_score(
                    facility, extracted_name, extracted_address,
                    extracted_city, extracted_state, extracted_fax, extracted_phone
                )
                # Boost score for fax match
                score = min(score + 0.15, 1.0)
                candidates.append((facility, score, method))

        # Strategy 2: Fuzzy name search
        if extracted_name:
            all_facilities = self.db.query(Facility).all()

            # Use rapidfuzz process to find best name matches
            facility_names = {f.id: f.facility_name for f in all_facilities}
            name_matches = process.extract(
                self.normalize_name(extracted_name),
                {fid: self.normalize_name(name) for fid, name in facility_names.items()},
                scorer=fuzz.token_sort_ratio,
                limit=10,
            )

            # Add facilities not already in candidates
            existing_ids = {f.id for f, _, _ in candidates}
            for match_name, match_score, facility_id in name_matches:
                if facility_id not in existing_ids and match_score >= 50:
                    facility = next(
                        (f for f in all_facilities if f.id == facility_id), None
                    )
                    if facility:
                        score, method, _ = self.calculate_match_score(
                            facility, extracted_name, extracted_address,
                            extracted_city, extracted_state, extracted_fax, extracted_phone
                        )
                        candidates.append((facility, score, method))
                        existing_ids.add(facility_id)

        # Strategy 3: Phone match (if no good candidates yet)
        if extracted_phone and len(candidates) < 3:
            phone_matches = self.match_by_phone(extracted_phone)
            existing_ids = {f.id for f, _, _ in candidates}
            for facility in phone_matches:
                if facility.id not in existing_ids:
                    score, method, _ = self.calculate_match_score(
                        facility, extracted_name, extracted_address,
                        extracted_city, extracted_state, extracted_fax, extracted_phone
                    )
                    candidates.append((facility, score, method))

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Build result
        extracted_data = {
            "facility_name": extracted_name,
            "address": extracted_address,
            "city": extracted_city,
            "state": extracted_state,
            "zipcode": extracted_zipcode,
            "fax": extracted_fax,
            "phone": extracted_phone,
        }

        best_match = None
        alternatives = []

        for facility, score, method in candidates[:max_results]:
            discrepancies = self.get_discrepancies(
                facility, extracted_name, extracted_address,
                extracted_city, extracted_state, extracted_zipcode,
                extracted_fax, extracted_phone
            )

            match = FacilityMatch(
                facility_id=facility.id,
                facility=facility,
                confidence=score,
                method=method,
                details=self._build_match_details(score, method),
                discrepancies=discrepancies,
            )

            if best_match is None and score >= self.LOW_CONFIDENCE_THRESHOLD:
                best_match = match
            else:
                alternatives.append(match)

        # If no match meets threshold, move first to alternatives
        if best_match is None and candidates:
            first_facility, first_score, first_method = candidates[0]
            discrepancies = self.get_discrepancies(
                first_facility, extracted_name, extracted_address,
                extracted_city, extracted_state, extracted_zipcode,
                extracted_fax, extracted_phone
            )
            alternatives.insert(0, FacilityMatch(
                facility_id=first_facility.id,
                facility=first_facility,
                confidence=first_score,
                method=first_method,
                details=f"Low confidence match ({first_score:.0%})",
                discrepancies=discrepancies,
            ))

        # Log the match attempt
        log_id = self._log_match_attempt(
            document_id=document_id,
            extracted_data=extracted_data,
            best_match=best_match,
            alternatives=alternatives,
        )

        return MatchResult(
            best_match=best_match,
            alternatives=alternatives,
            extracted_data=extracted_data,
            log_id=log_id,
        )

    def _build_match_details(self, score: float, method: str) -> str:
        """Build human-readable match details."""
        if score >= self.EXACT_MATCH_THRESHOLD:
            confidence_level = "High confidence"
        elif score >= self.HIGH_CONFIDENCE_THRESHOLD:
            confidence_level = "Good confidence"
        elif score >= self.LOW_CONFIDENCE_THRESHOLD:
            confidence_level = "Moderate confidence"
        else:
            confidence_level = "Low confidence"

        method_descriptions = {
            "exact_name": "exact name match",
            "fuzzy_name": "similar name",
            "fax": "fax number match",
            "phone": "phone number match",
            "address": "address match",
        }

        method_parts = method.split("+")
        method_text = ", ".join(
            method_descriptions.get(m, m) for m in method_parts
        )

        return f"{confidence_level} ({score:.0%}) - matched by {method_text}"

    def _log_match_attempt(
        self,
        document_id: Optional[int],
        extracted_data: Dict[str, Any],
        best_match: Optional[FacilityMatch],
        alternatives: List[FacilityMatch],
    ) -> Optional[int]:
        """Log the matching attempt for auditing."""
        try:
            alternatives_data = [
                {
                    "facility_id": alt.facility_id,
                    "facility_name": alt.facility.facility_name,
                    "confidence": alt.confidence,
                    "method": alt.method,
                }
                for alt in alternatives[:5]  # Limit to 5 alternatives
            ]

            log = FacilityMatchLog(
                document_id=document_id,
                extracted_name=extracted_data.get("facility_name"),
                extracted_address=extracted_data.get("address"),
                extracted_city=extracted_data.get("city"),
                extracted_state=extracted_data.get("state"),
                extracted_zipcode=extracted_data.get("zipcode"),
                extracted_fax=extracted_data.get("fax"),
                extracted_phone=extracted_data.get("phone"),
                matched_facility_id=best_match.facility_id if best_match else None,
                match_confidence=Decimal(str(best_match.confidence)) if best_match else None,
                match_method=best_match.method if best_match else None,
                match_details=best_match.details if best_match else "No match found",
                alternatives_json=json.dumps(alternatives_data) if alternatives_data else None,
                user_confirmed=False,
            )
            self.db.add(log)
            self.db.commit()
            return log.id
        except Exception as e:
            logger.error(f"Failed to log match attempt: {e}")
            self.db.rollback()
            return None

    def confirm_match(
        self,
        document_id: int,
        facility_id: int,
        confirmed_by: str,
    ) -> bool:
        """Confirm a facility match for a document."""
        from datetime import datetime

        try:
            # Update document
            document = self.db.query(Document).filter(Document.id == document_id).first()
            if document:
                document.matched_facility_id = facility_id

            # Update match log
            log = (
                self.db.query(FacilityMatchLog)
                .filter(FacilityMatchLog.document_id == document_id)
                .order_by(FacilityMatchLog.created_at.desc())
                .first()
            )
            if log:
                log.matched_facility_id = facility_id
                log.user_confirmed = True
                log.confirmed_by = confirmed_by
                log.confirmed_at = datetime.utcnow()

            self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to confirm match: {e}")
            self.db.rollback()
            return False

    def get_facility_physicians(self, facility_id: int) -> List[FacilityPhysician]:
        """Get all physicians for a facility."""
        return (
            self.db.query(FacilityPhysician)
            .filter(
                FacilityPhysician.facility_id == facility_id,
                FacilityPhysician.is_active == True,
            )
            .order_by(FacilityPhysician.name)
            .all()
        )

    def add_physician(
        self,
        facility_id: int,
        name: str,
        npi: Optional[str] = None,
        specialty: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[FacilityPhysician]:
        """Add a new physician to a facility."""
        try:
            physician = FacilityPhysician(
                facility_id=facility_id,
                name=name,
                npi=npi,
                specialty=specialty,
                phone=phone,
                email=email,
            )
            self.db.add(physician)
            self.db.commit()
            return physician
        except Exception as e:
            logger.error(f"Failed to add physician: {e}")
            self.db.rollback()
            return None

    def search_facilities(
        self,
        query: str,
        limit: int = 10,
    ) -> List[Facility]:
        """Search facilities by name (for autocomplete/search)."""
        if not query or len(query) < 2:
            return []

        all_facilities = self.db.query(Facility).all()

        # Use rapidfuzz for fuzzy search
        facility_names = {f.id: f.facility_name for f in all_facilities}
        matches = process.extract(
            query,
            facility_names,
            scorer=fuzz.partial_ratio,
            limit=limit,
        )

        result = []
        for _, score, facility_id in matches:
            if score >= 50:  # Minimum score threshold
                facility = next(
                    (f for f in all_facilities if f.id == facility_id), None
                )
                if facility:
                    result.append(facility)

        return result
