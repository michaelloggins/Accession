"""Mock extraction service for testing without API keys."""

import random
from fastapi import UploadFile
import logging

logger = logging.getLogger(__name__)


class MockExtractionService:
    """Mock service that returns sample data for testing."""

    async def extract_data(self, file: UploadFile) -> tuple:
        """Return mock extracted data for testing."""
        logger.info(f"Mock extraction for file: {file.filename}")

        # Sample data that mimics real extraction
        mock_data = {
            "patient_name": "John Michael Doe",
            "date_of_birth": "1985-03-15",
            "ordering_physician": "Dr. Sarah Johnson, MD",
            "tests_requested": ["Complete Blood Count (CBC)", "Comprehensive Metabolic Panel", "Lipid Panel"],
            "specimen_type": "Blood",
            "collection_date": "2025-01-17",
            "patient_address": "123 Main Street, Apt 4B, Springfield, IL 62701",
            "patient_phone": "(555) 123-4567",
            "patient_email": "john.doe@email.com",
            "insurance_provider": "Blue Cross Blue Shield",
            "policy_number": "BCBS123456789",
            "icd10_codes": ["E11.9", "I10", "E78.5"],
            "medical_record_number": "MRN-2025-001234",
            "special_instructions": "Fasting required - 12 hours",
            "priority": "Routine"
        }

        # Random confidence score between 0.75 and 0.98
        confidence_score = round(random.uniform(0.75, 0.98), 4)

        logger.info(f"Mock extraction completed with confidence: {confidence_score}")
        return mock_data, confidence_score
