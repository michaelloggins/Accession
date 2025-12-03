"""Pytest configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db


# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """Create a test client with overridden database dependency."""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user():
    """Sample user data for testing."""
    return {
        "id": "test-user-123",
        "email": "testuser@example.com",
        "full_name": "Test User",
        "role": "reviewer"
    }


@pytest.fixture
def sample_document():
    """Sample document data for testing."""
    return {
        "filename": "test_requisition.pdf",
        "blob_name": "2025/01/17/uuid/test_requisition.pdf",
        "source": "upload",
        "uploaded_by": "test-user-123"
    }


@pytest.fixture
def sample_extracted_data():
    """Sample extracted data for testing."""
    return {
        "patient_name": "John Doe",
        "date_of_birth": "1980-05-15",
        "ordering_physician": "Dr. Jane Smith",
        "tests_requested": ["CBC", "CMP", "Lipid Panel"],
        "specimen_type": "Blood",
        "collection_date": "2025-01-17",
        "patient_address": "123 Main St, City, ST 12345",
        "patient_phone": "(555) 123-4567",
        "patient_email": "john.doe@example.com",
        "insurance_provider": "Blue Cross",
        "policy_number": "XYZ123456",
        "icd10_codes": ["E11.9", "I10"],
        "medical_record_number": "MRN001234",
        "special_instructions": "Fasting required",
        "priority": "Routine"
    }


@pytest.fixture
def auth_headers():
    """Authentication headers for API requests."""
    # In production, generate actual JWT token
    return {
        "Authorization": "Bearer test-token",
        "Content-Type": "application/json"
    }
