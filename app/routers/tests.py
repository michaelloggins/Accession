"""Test catalog management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.database import get_db
from app.models.test import Test, TestSpecimenType
from app.models.species import Species
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


# Schemas
class SpecimenTypeInfo(BaseModel):
    specimen_type: str
    minimum_volume_ml: Optional[float] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class TestResponse(BaseModel):
    id: int
    test_number: str
    test_name: str
    test_type: str
    species: Optional[str] = "Any"
    eligible_specimens: List[str]
    minimum_sample_ml: Optional[float] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class TestCreate(BaseModel):
    test_number: str
    test_name: str
    test_type: str = "Antigen Test"
    species: Optional[str] = "Any"
    eligible_specimens: List[str]
    minimum_sample_ml: Optional[float] = None
    notes: Optional[str] = None


class TestUpdate(BaseModel):
    test_name: Optional[str] = None
    test_type: Optional[str] = None
    species: Optional[str] = None
    eligible_specimens: Optional[List[str]] = None
    minimum_sample_ml: Optional[float] = None
    notes: Optional[str] = None


@router.get("", response_model=List[TestResponse])
async def get_all_tests(
    db: Session = Depends(get_db),
    active_only: bool = True
):
    """Get all tests with their eligible specimen types."""
    tests = db.query(Test).all()

    result = []
    for test in tests:
        # Get unique specimen types for this test
        specimen_types = db.query(TestSpecimenType.specimen_type).filter(
            TestSpecimenType.test_id == test.id
        ).distinct().all()

        eligible_specimens = [st[0] for st in specimen_types]

        # Get minimum sample volume (use the first one if multiple)
        min_sample = None
        first_specimen = db.query(TestSpecimenType).filter(
            TestSpecimenType.test_id == test.id
        ).first()
        if first_specimen:
            min_sample = first_specimen.minimum_volume_ml

        result.append(TestResponse(
            id=test.id,
            test_number=test.test_number,
            test_name=test.test_name,
            test_type=test.test_type,
            species=test.species or "Any",
            eligible_specimens=eligible_specimens,
            minimum_sample_ml=min_sample,
            notes=test.description
        ))

    return result


@router.get("/{test_id}", response_model=TestResponse)
async def get_test(
    test_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific test by ID."""
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test not found"
        )

    # Get specimen types
    specimen_types = db.query(TestSpecimenType.specimen_type).filter(
        TestSpecimenType.test_id == test.id
    ).distinct().all()

    eligible_specimens = [st[0] for st in specimen_types]

    # Get minimum sample volume
    min_sample = None
    first_specimen = db.query(TestSpecimenType).filter(
        TestSpecimenType.test_id == test.id
    ).first()
    if first_specimen:
        min_sample = first_specimen.minimum_volume_ml

    return TestResponse(
        id=test.id,
        test_number=test.test_number,
        test_name=test.test_name,
        test_type=test.test_type,
        species=test.species or "Any",
        eligible_specimens=eligible_specimens,
        minimum_sample_ml=min_sample,
        notes=test.description
    )


@router.post("", response_model=TestResponse, status_code=status.HTTP_201_CREATED)
async def create_test(
    test_data: TestCreate,
    db: Session = Depends(get_db)
):
    """Create a new test."""
    # Check if test number already exists
    existing = db.query(Test).filter(Test.test_number == test_data.test_number).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Test with number {test_data.test_number} already exists"
        )

    # Create test
    new_test = Test(
        test_number=test_data.test_number,
        test_name=test_data.test_name,
        test_type=test_data.test_type,
        species=test_data.species or "Any",
        description=test_data.notes
    )
    db.add(new_test)
    db.flush()  # Get the ID without committing

    # Create specimen types
    for specimen_type in test_data.eligible_specimens:
        specimen = TestSpecimenType(
            test_id=new_test.id,
            specimen_type=specimen_type,
            minimum_volume_ml=test_data.minimum_sample_ml
        )
        db.add(specimen)

    db.commit()
    db.refresh(new_test)

    logger.info(f"Created test: {test_data.test_number} - {test_data.test_name}")

    return TestResponse(
        id=new_test.id,
        test_number=new_test.test_number,
        test_name=new_test.test_name,
        test_type=new_test.test_type,
        species=new_test.species or "Any",
        eligible_specimens=test_data.eligible_specimens,
        minimum_sample_ml=test_data.minimum_sample_ml,
        notes=test_data.notes
    )


@router.put("/{test_id}", response_model=TestResponse)
async def update_test(
    test_id: int,
    test_data: TestUpdate,
    db: Session = Depends(get_db)
):
    """Update an existing test."""
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test not found"
        )

    # Update test fields
    if test_data.test_name is not None:
        test.test_name = test_data.test_name
    if test_data.test_type is not None:
        test.test_type = test_data.test_type
    if test_data.species is not None:
        test.species = test_data.species
    if test_data.notes is not None:
        test.description = test_data.notes

    # Update specimen types if provided
    if test_data.eligible_specimens is not None:
        # Remove existing specimen types
        db.query(TestSpecimenType).filter(TestSpecimenType.test_id == test_id).delete()

        # Add new specimen types
        for specimen_type in test_data.eligible_specimens:
            specimen = TestSpecimenType(
                test_id=test.id,
                specimen_type=specimen_type,
                minimum_volume_ml=test_data.minimum_sample_ml
            )
            db.add(specimen)

    db.commit()
    db.refresh(test)

    # Get updated specimen types
    specimen_types = db.query(TestSpecimenType.specimen_type).filter(
        TestSpecimenType.test_id == test.id
    ).distinct().all()
    eligible_specimens = [st[0] for st in specimen_types]

    logger.info(f"Updated test: {test.test_number}")

    return TestResponse(
        id=test.id,
        test_number=test.test_number,
        test_name=test.test_name,
        test_type=test.test_type,
        species=test.species or "Any",
        eligible_specimens=eligible_specimens,
        minimum_sample_ml=test_data.minimum_sample_ml,
        notes=test.description
    )


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(
    test_id: int,
    db: Session = Depends(get_db)
):
    """Delete a test."""
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test not found"
        )

    # Delete associated specimen types (cascade should handle this, but being explicit)
    db.query(TestSpecimenType).filter(TestSpecimenType.test_id == test_id).delete()

    db.delete(test)
    db.commit()

    logger.info(f"Deleted test: {test.test_number}")

    return None
