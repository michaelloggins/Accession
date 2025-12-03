"""Document schemas for request/response validation."""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime, date
import re


class ExtractedData(BaseModel):
    """Schema for extracted document data - accepts both legacy flat format and new nested format."""

    # Allow passthrough of nested structure (facility, patient, order, etc.)
    model_config = ConfigDict(extra='allow')

    # Legacy flat fields (for backward compatibility)
    patient_name: Optional[str] = None  # First Middle Last
    date_of_birth: Optional[str] = None  # YYYY-MM-DD format
    ordering_physician: Optional[str] = None  # Name, NPI if available
    tests_requested: Optional[List[Any]] = []  # Array of test names or test objects
    specimen_type: Optional[str] = None  # Blood, Urine, Tissue, Swab, Other
    collection_date: Optional[str] = None  # YYYY-MM-DD format

    # OPTIONAL PATIENT FIELDS
    patient_gender: Optional[str] = None  # M, F, Other
    patient_address: Optional[str] = None
    patient_phone: Optional[str] = None  # (XXX) XXX-XXXX format
    patient_email: Optional[str] = None
    medical_record_number: Optional[str] = None  # MRN

    # OPTIONAL PHYSICIAN FIELDS
    ordering_physician_npi: Optional[str] = None  # 10-digit number
    physician_phone: Optional[str] = None
    physician_fax: Optional[str] = None

    # OPTIONAL COLLECTION FIELDS
    collection_time: Optional[str] = None  # HH:MM format

    # OPTIONAL ADMINISTRATIVE FIELDS
    priority: Optional[str] = None  # STAT or Routine
    special_instructions: Optional[str] = None

    # EXTRACTION METADATA
    confidence_score: Optional[float] = None
    extraction_notes: Optional[str] = None

    # NEW NESTED FORMAT FIELDS (optional)
    facility: Optional[Dict[str, Any]] = None
    patient: Optional[Dict[str, Any]] = None
    order: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentUploadResponse(BaseModel):
    """Response after uploading a document."""
    id: int
    accession_number: str
    filename: str
    status: str
    confidence_score: Optional[float] = None
    extracted_data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None  # Status message for queued documents


class DocumentResponse(BaseModel):
    """Full document response with all details."""
    id: int
    accession_number: str
    filename: str
    upload_date: datetime
    uploaded_by: str
    confidence_score: Optional[float] = None
    status: str
    extracted_data: Optional[Dict[str, Any]] = None
    document_url: Optional[str] = None
    document_url_expires: Optional[datetime] = None


class DocumentListItem(BaseModel):
    """Document item for list views."""
    id: int
    accession_number: str
    filename: str
    upload_date: datetime
    confidence_score: Optional[float] = None
    status: str
    processing_status: Optional[str] = None
    facility_name: Optional[str] = None
    facility_id: Optional[str] = None
    how_received: Optional[str] = None  # Source of document: upload, email, fax, scanner, api, manual
    last_extraction_error: Optional[str] = None  # Error message for failed extractions


class DocumentListResponse(BaseModel):
    """Response for document list."""
    total: int
    documents: List[DocumentListItem]


class ReviewRequest(BaseModel):
    """Request to review and approve a document."""
    corrected_data: ExtractedData
    reviewer_notes: Optional[str] = None
    approved: bool = True


class LabSubmissionResult(BaseModel):
    """Lab submission result."""
    submitted: bool
    confirmation_id: Optional[str] = None


class ReviewResponse(BaseModel):
    """Response after reviewing a document."""
    status: str
    document_status: str
    lab_result: Optional[LabSubmissionResult] = None


class RejectRequest(BaseModel):
    """Request to reject a document."""
    reason: str = Field(..., min_length=1, max_length=1000)


class RejectResponse(BaseModel):
    """Response after rejecting a document."""
    status: str
    document_status: str


class ManualOrderCreate(BaseModel):
    """Schema for manually creating an order."""
    # Required fields
    patient_name: str = Field(..., min_length=2, max_length=100)
    date_of_birth: str
    ordering_physician: str = Field(..., min_length=2, max_length=100)
    tests_requested: List[str] = Field(..., min_items=1)
    specimen_type: str
    collection_date: str

    # Optional patient fields
    patient_gender: Optional[str] = None
    medical_record_number: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_email: Optional[str] = None
    patient_address: Optional[str] = None

    # Optional physician fields
    ordering_physician_npi: Optional[str] = None
    physician_phone: Optional[str] = None
    physician_fax: Optional[str] = None

    # Optional collection fields
    collection_time: Optional[str] = None

    # Optional administrative fields
    priority: Optional[str] = "Routine"
    special_instructions: Optional[str] = None

    @field_validator("patient_name")
    @classmethod
    def validate_patient_name(cls, v):
        if not re.match(r"^[a-zA-Z\s\-\.]+$", v):
            raise ValueError("Patient name must contain only letters, spaces, hyphens, and periods")
        return v

    @field_validator("patient_email")
    @classmethod
    def validate_email(cls, v):
        if v and not re.match(r"^[^@]+@[^@]+\.[^@]+$", v):
            raise ValueError("Invalid email format")
        return v
