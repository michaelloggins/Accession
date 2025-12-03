"""Tests for PHI encryption service."""

import pytest
from app.services.encryption_service import EncryptionService
from app.config import PHI_FIELDS


class TestEncryptionService:
    """Test suite for encryption service."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = EncryptionService()

    def test_encrypt_decrypt_string(self):
        """Test basic string encryption and decryption."""
        original = "John Doe"
        encrypted = self.service.encrypt_string(original)
        decrypted = self.service.decrypt_string(encrypted)

        assert decrypted == original
        assert encrypted != original
        assert encrypted.startswith("gAAAAA")  # Fernet token format

    def test_encrypt_phi_fields(self):
        """Test encryption of PHI fields in dictionary."""
        data = {
            "patient_name": "Jane Doe",
            "date_of_birth": "1990-01-01",
            "phone": "(555) 123-4567",
            "non_phi_field": "This should not be encrypted"
        }

        encrypted = self.service.encrypt_phi_fields(data)

        # PHI fields should be encrypted
        assert encrypted["patient_name"] != data["patient_name"]
        assert encrypted["date_of_birth"] != data["date_of_birth"]
        assert encrypted["phone"] != data["phone"]

        # Non-PHI field should remain unchanged
        assert encrypted["non_phi_field"] == data["non_phi_field"]

    def test_decrypt_phi_fields(self):
        """Test decryption of PHI fields in dictionary."""
        original_data = {
            "patient_name": "Jane Doe",
            "date_of_birth": "1990-01-01",
            "ordering_physician": "Dr. Smith"
        }

        encrypted = self.service.encrypt_phi_fields(original_data)
        decrypted = self.service.decrypt_phi_fields(encrypted)

        assert decrypted["patient_name"] == original_data["patient_name"]
        assert decrypted["date_of_birth"] == original_data["date_of_birth"]

    def test_encrypt_phi_fields_with_none_values(self):
        """Test that None values are not encrypted."""
        data = {
            "patient_name": "John",
            "ssn": None,
            "address": None
        }

        encrypted = self.service.encrypt_phi_fields(data)

        assert encrypted["ssn"] is None
        assert encrypted["address"] is None
        assert encrypted["patient_name"] != "John"

    def test_round_trip_encryption(self):
        """Test complete encryption/decryption round trip."""
        original_data = {
            "patient_name": "Alice Smith",
            "date_of_birth": "1985-03-20",
            "patient_address": "456 Oak Street",
            "patient_phone": "(555) 987-6543",
            "patient_email": "alice@example.com",
            "policy_number": "POL12345678",
            "medical_record_number": "MRN789",
            "ssn": "1234",  # Last 4 digits
            "tests_requested": ["CBC"],  # Non-string, should not be encrypted
            "confidence_score": 0.95  # Non-string
        }

        encrypted = self.service.encrypt_phi_fields(original_data)
        decrypted = self.service.decrypt_phi_fields(encrypted)

        # All PHI string fields should match
        for field in PHI_FIELDS:
            if field in original_data and isinstance(original_data[field], str):
                assert decrypted[field] == original_data[field]

        # Non-string fields should remain unchanged
        assert decrypted["tests_requested"] == original_data["tests_requested"]
        assert decrypted["confidence_score"] == original_data["confidence_score"]

    def test_is_encrypted_check(self):
        """Test detection of encrypted values."""
        original = "Test Value"
        encrypted = self.service.encrypt_string(original)

        assert self.service._is_encrypted(encrypted) is True
        assert self.service._is_encrypted(original) is False
        assert self.service._is_encrypted("short") is False
