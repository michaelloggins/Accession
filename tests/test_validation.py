"""Tests for data validation in schemas."""

import pytest
from pydantic import ValidationError
from app.schemas.document import ExtractedData


class TestExtractedDataValidation:
    """Test suite for ExtractedData schema validation."""

    def test_valid_patient_name(self):
        """Test valid patient names."""
        valid_names = [
            "John Doe",
            "Jane M. Smith",
            "Robert Johnson-Williams",
            "Ana Maria Garcia"
        ]

        for name in valid_names:
            data = ExtractedData(patient_name=name)
            assert data.patient_name == name

    def test_invalid_patient_name_characters(self):
        """Test patient name with invalid characters."""
        with pytest.raises(ValidationError):
            ExtractedData(patient_name="John123 Doe")

        with pytest.raises(ValidationError):
            ExtractedData(patient_name="Jane@Smith")

    def test_patient_name_length(self):
        """Test patient name length validation."""
        # Too short
        with pytest.raises(ValidationError):
            ExtractedData(patient_name="J")

        # Too long (over 100 chars)
        with pytest.raises(ValidationError):
            ExtractedData(patient_name="A" * 101)

    def test_valid_phone_numbers(self):
        """Test valid phone number formats."""
        valid_phones = [
            "(555) 123-4567",
            "555-123-4567",
            "5551234567",
            "(555)123-4567"
        ]

        for phone in valid_phones:
            data = ExtractedData(patient_phone=phone)
            assert data.patient_phone == phone

    def test_invalid_phone_number(self):
        """Test invalid phone numbers."""
        with pytest.raises(ValidationError):
            ExtractedData(patient_phone="123")  # Too short

        with pytest.raises(ValidationError):
            ExtractedData(patient_phone="12345678901")  # Too long

    def test_valid_email(self):
        """Test valid email addresses."""
        valid_emails = [
            "user@example.com",
            "user.name@domain.org",
            "user123@sub.domain.com"
        ]

        for email in valid_emails:
            data = ExtractedData(patient_email=email)
            assert data.patient_email == email

    def test_invalid_email(self):
        """Test invalid email addresses."""
        with pytest.raises(ValidationError):
            ExtractedData(patient_email="not-an-email")

        with pytest.raises(ValidationError):
            ExtractedData(patient_email="missing@domain")

    def test_optional_fields(self):
        """Test that optional fields can be None or empty."""
        data = ExtractedData(
            patient_name="John Doe",
            date_of_birth="1990-01-01"
            # All other fields are optional
        )

        assert data.patient_address is None
        assert data.insurance_provider is None
        assert data.icd10_codes == []
        assert data.tests_requested == []

    def test_complete_valid_data(self):
        """Test with complete valid extracted data."""
        data = ExtractedData(
            patient_name="Jane Doe",
            date_of_birth="1985-06-15",
            ordering_physician="Dr. Robert Smith",
            tests_requested=["CBC", "CMP", "TSH"],
            specimen_type="Blood",
            collection_date="2025-01-17",
            patient_address="123 Main St, City, ST 12345",
            patient_phone="(555) 123-4567",
            patient_email="jane@example.com",
            insurance_provider="Aetna",
            policy_number="XYZ12345",
            icd10_codes=["E11.9"],
            medical_record_number="MRN001",
            special_instructions="Fasting required",
            priority="STAT",
            confidence_score=0.92
        )

        assert data.patient_name == "Jane Doe"
        assert len(data.tests_requested) == 3
        assert data.priority == "STAT"
        assert data.confidence_score == 0.92
