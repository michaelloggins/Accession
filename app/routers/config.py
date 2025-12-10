"""Configuration management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List
from pydantic import BaseModel
import logging

from app.database import get_db, engine, Base
from app.services.config_service import ConfigService
from app.models.extraction_batch import ExtractionBatch
from app.models.document import Document
from app.models.system_config import SystemConfig
from app.models.test import Test, TestSpecimenType
from app.models.species import Species

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfigUpdateRequest(BaseModel):
    """Request to update a configuration value."""
    value: str


class ConfigItem(BaseModel):
    """Configuration item response."""
    key: str
    value: Optional[str | int | float | bool | dict | list]
    value_type: str
    description: Optional[str]
    category: Optional[str]
    display_order: Optional[str]
    source: str  # 'default' or 'database'
    updated_at: Optional[str]
    updated_by: Optional[str]


class ConfigListResponse(BaseModel):
    """Response for configuration list."""
    configs: List[ConfigItem]
    categories: List[str]


class QueueStatusResponse(BaseModel):
    """Response for extraction queue status."""
    queued_count: int
    processing_count: int
    extracted_count: int
    failed_count: int
    total_batches: int
    active_batches: int


class QueueDocumentItem(BaseModel):
    """Document item in the processing queue."""
    id: int
    accession_number: str
    filename: str
    processing_status: str
    batch_id: Optional[str]
    extraction_attempts: int
    last_error: Optional[str]
    queued_at: Optional[str]
    extraction_started_at: Optional[str]


class BatchItem(BaseModel):
    """Extraction batch item."""
    id: str
    status: str
    document_count: int
    successful_count: int
    failed_count: int
    attempt_number: int
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    error_message: Optional[str]


# ============================================
# Configuration Endpoints
# ============================================

@router.get("/", response_model=ConfigListResponse)
async def get_all_configs(
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all configuration settings."""
    config_service = ConfigService(db)
    configs = config_service.get_all(category=category)
    categories = config_service.get_categories()

    return ConfigListResponse(
        configs=[ConfigItem(**c) for c in configs],
        categories=categories
    )


# =============================================================================
# Species CRUD Endpoints (must be before /{key} to avoid route conflicts)
# =============================================================================

@router.get("/species")
async def list_species(
    include_inactive: bool = False,
    db: Session = Depends(get_db)
):
    """List all species."""
    query = db.query(Species)
    if not include_inactive:
        query = query.filter(Species.is_active == 1)

    species_list = query.order_by(Species.name).all()

    return {
        "species": [
            {
                "id": s.id,
                "name": s.name,
                "common_name": s.common_name,
                "description": s.description,
                "test_category": s.test_category,
                "is_active": s.is_active == 1
            }
            for s in species_list
        ]
    }


@router.get("/species/{species_id}")
async def get_species(species_id: int, db: Session = Depends(get_db)):
    """Get a single species by ID."""
    species = db.query(Species).filter(Species.id == species_id).first()
    if not species:
        raise HTTPException(status_code=404, detail="Species not found")

    return {
        "id": species.id,
        "name": species.name,
        "common_name": species.common_name,
        "description": species.description,
        "test_category": species.test_category,
        "is_active": species.is_active == 1
    }


@router.post("/species")
async def create_species(data: dict, db: Session = Depends(get_db)):
    """Create a new species."""
    # Check for duplicate name
    existing = db.query(Species).filter(Species.name == data.get("name")).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Species '{data.get('name')}' already exists")

    species = Species(
        name=data.get("name"),
        common_name=data.get("common_name"),
        description=data.get("description"),
        test_category=data.get("test_category", "veterinary"),
        is_active=1 if data.get("is_active", True) else 0
    )

    db.add(species)
    db.commit()
    db.refresh(species)

    logger.info(f"Created species: {species.name}")

    return {
        "id": species.id,
        "name": species.name,
        "common_name": species.common_name,
        "description": species.description,
        "test_category": species.test_category,
        "is_active": species.is_active == 1
    }


@router.put("/species/{species_id}")
async def update_species(species_id: int, data: dict, db: Session = Depends(get_db)):
    """Update an existing species."""
    species = db.query(Species).filter(Species.id == species_id).first()
    if not species:
        raise HTTPException(status_code=404, detail="Species not found")

    # Check for duplicate name (excluding current)
    if data.get("name") and data.get("name") != species.name:
        existing = db.query(Species).filter(Species.name == data.get("name")).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Species '{data.get('name')}' already exists")

    if "name" in data:
        species.name = data["name"]
    if "common_name" in data:
        species.common_name = data["common_name"]
    if "description" in data:
        species.description = data["description"]
    if "test_category" in data:
        species.test_category = data["test_category"]
    if "is_active" in data:
        species.is_active = 1 if data["is_active"] else 0

    db.commit()
    db.refresh(species)

    logger.info(f"Updated species: {species.name}")

    return {
        "id": species.id,
        "name": species.name,
        "common_name": species.common_name,
        "description": species.description,
        "test_category": species.test_category,
        "is_active": species.is_active == 1
    }


@router.delete("/species/{species_id}")
async def delete_species(species_id: int, db: Session = Depends(get_db)):
    """Deactivate a species (soft delete)."""
    species = db.query(Species).filter(Species.id == species_id).first()
    if not species:
        raise HTTPException(status_code=404, detail="Species not found")

    # Check if species is in use by any patients
    if species.patients:
        # Soft delete - just deactivate
        species.is_active = 0
        db.commit()
        logger.info(f"Deactivated species: {species.name} (in use by patients)")
        return {"status": "deactivated", "message": f"Species '{species.name}' deactivated (in use by patients)"}

    # Hard delete if not in use
    db.delete(species)
    db.commit()
    logger.info(f"Deleted species: {species.name}")

    return {"status": "deleted", "message": f"Species '{species.name}' deleted"}


# ============================================
# Configuration Key Endpoints (/{key} routes must come after specific routes)
# ============================================

@router.get("/{key}")
async def get_config(key: str, db: Session = Depends(get_db)):
    """Get a specific configuration value."""
    config_service = ConfigService(db)
    value = config_service.get(key)

    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration key '{key}' not found"
        )

    return {"key": key, "value": value}


@router.put("/{key}")
async def update_config(
    key: str,
    request: ConfigUpdateRequest,
    db: Session = Depends(get_db)
):
    """Update a configuration value."""
    config_service = ConfigService(db)

    # Check if key exists in defaults or database
    current_value = config_service.get(key)
    if current_value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration key '{key}' not found"
        )

    success = config_service.set(key, request.value, updated_by="admin")

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration"
        )

    logger.info(f"Configuration '{key}' updated to '{request.value}'")

    return {
        "status": "success",
        "key": key,
        "value": config_service.get(key)
    }


# ============================================
# Extraction Queue Endpoints
# ============================================

@router.get("/queue/status", response_model=QueueStatusResponse)
async def get_queue_status(db: Session = Depends(get_db)):
    """Get extraction queue status summary."""
    queued = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_QUEUED
    ).count()

    processing = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_PROCESSING
    ).count()

    extracted = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_EXTRACTED
    ).count()

    failed = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_FAILED
    ).count()

    total_batches = db.query(ExtractionBatch).count()

    active_batches = db.query(ExtractionBatch).filter(
        ExtractionBatch.status.in_([
            ExtractionBatch.STATUS_QUEUED,
            ExtractionBatch.STATUS_PROCESSING
        ])
    ).count()

    return QueueStatusResponse(
        queued_count=queued,
        processing_count=processing,
        extracted_count=extracted,
        failed_count=failed,
        total_batches=total_batches,
        active_batches=active_batches
    )


@router.get("/queue/documents")
async def get_queue_documents(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get documents in the processing queue."""
    query = db.query(Document).filter(
        Document.processing_status.in_([
            Document.PROC_STATUS_QUEUED,
            Document.PROC_STATUS_PROCESSING,
            Document.PROC_STATUS_FAILED
        ])
    )

    if status:
        query = query.filter(Document.processing_status == status)

    total = query.count()
    documents = query.order_by(Document.queued_at.asc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "documents": [
            {
                "id": doc.id,
                "accession_number": doc.accession_number,
                "filename": doc.filename,
                "processing_status": doc.processing_status,
                "batch_id": doc.batch_id,
                "extraction_attempts": doc.extraction_attempts,
                "last_error": doc.last_extraction_error,
                "queued_at": doc.queued_at.isoformat() if doc.queued_at else None,
                "extraction_started_at": doc.extraction_started_at.isoformat() if doc.extraction_started_at else None
            }
            for doc in documents
        ]
    }


@router.get("/queue/batches")
async def get_batches(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get extraction batches."""
    query = db.query(ExtractionBatch)

    if status:
        query = query.filter(ExtractionBatch.status == status)

    total = query.count()
    batches = query.order_by(ExtractionBatch.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "batches": [
            {
                "id": batch.id,
                "status": batch.status,
                "document_count": batch.document_count,
                "successful_count": batch.successful_count,
                "failed_count": batch.failed_count,
                "attempt_number": batch.attempt_number,
                "created_at": batch.created_at.isoformat() if batch.created_at else None,
                "started_at": batch.started_at.isoformat() if batch.started_at else None,
                "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
                "error_message": batch.error_message
            }
            for batch in batches
        ]
    }


@router.post("/queue/requeue/{document_id}")
async def requeue_document(document_id: int, db: Session = Depends(get_db)):
    """Requeue a failed document for extraction."""
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if document.processing_status not in [Document.PROC_STATUS_FAILED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document is not in failed status (current: {document.processing_status})"
        )

    # Reset for reprocessing
    document.processing_status = Document.PROC_STATUS_QUEUED
    document.extraction_attempts = 0
    document.batch_id = None
    document.last_extraction_error = None

    db.commit()

    logger.info(f"Document {document_id} requeued for extraction")

    return {"status": "success", "message": f"Document {document_id} requeued"}


@router.post("/queue/requeue-all-failed")
async def requeue_all_failed(db: Session = Depends(get_db)):
    """Requeue all failed documents for extraction."""
    failed_docs = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_FAILED
    ).all()

    count = 0
    for doc in failed_docs:
        doc.processing_status = Document.PROC_STATUS_QUEUED
        doc.extraction_attempts = 0
        doc.batch_id = None
        doc.last_extraction_error = None
        count += 1

    db.commit()

    logger.info(f"Requeued {count} failed documents")

    return {"status": "success", "requeued_count": count}


@router.get("/worker/status")
async def get_worker_status():
    """Get extraction worker status."""
    from app.services.extraction_worker import get_worker_status
    return get_worker_status()


@router.get("/blob-watcher/status")
async def get_blob_watcher_status():
    """Get blob watcher status."""
    from app.services.blob_watcher import get_blob_watcher_status
    return get_blob_watcher_status()


@router.post("/blob-watcher/scan")
async def trigger_blob_scan():
    """Trigger an immediate blob container scan."""
    from app.services.blob_watcher import _watcher_instance

    if _watcher_instance is None or not _watcher_instance.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Blob watcher is not running"
        )

    # Trigger a full scan
    await _watcher_instance._full_scan()
    await _watcher_instance._poll_for_new_blobs()

    return {
        "status": "success",
        "message": "Blob scan completed",
        "known_blobs": len(_watcher_instance._known_blobs)
    }


# ============================================
# Database Seeding Endpoints
# ============================================

@router.post("/seed/database")
async def seed_database(db: Session = Depends(get_db)):
    """Ensure all database tables exist and seed initial data."""
    try:
        # Create all tables that don't exist
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified")

        # Initialize config defaults
        config_service = ConfigService(db)
        config_service.initialize_defaults()

        return {
            "status": "success",
            "message": "Database tables created and configuration initialized"
        }
    except Exception as e:
        logger.error(f"Database seeding failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database seeding failed: {str(e)}"
        )


@router.post("/seed/species")
async def seed_species(db: Session = Depends(get_db)):
    """Seed species reference data."""
    species_data = [
        {"name": "Human", "common_name": "Humans", "test_category": "human", "description": "Human patients"},
        {"name": "Dog", "common_name": "Canine", "test_category": "veterinary", "description": "Dogs/Canines"},
        {"name": "Cat", "common_name": "Feline", "test_category": "veterinary", "description": "Cats/Felines"},
        {"name": "Horse", "common_name": "Equine", "test_category": "veterinary", "description": "Horses/Equines"},
        {"name": "Bovine", "common_name": "Cattle", "test_category": "veterinary", "description": "Cattle/Bovines"},
        {"name": "Avian", "common_name": "Birds", "test_category": "veterinary", "description": "Birds/Avians"},
        {"name": "Exotic", "common_name": "Exotic Animals", "test_category": "veterinary", "description": "Exotic/Other animals"},
    ]

    created = 0
    for sp in species_data:
        existing = db.query(Species).filter(Species.name == sp["name"]).first()
        if not existing:
            species = Species(**sp)
            db.add(species)
            created += 1

    db.commit()
    logger.info(f"Seeded {created} species records")

    return {
        "status": "success",
        "created": created,
        "total": len(species_data)
    }


@router.post("/seed/tests")
async def seed_test_catalog(db: Session = Depends(get_db)):
    """Seed MiraVista test catalog data."""
    # MiraVista Diagnostics Test Menu
    tests_data = [
        # Antigen Tests
        {"test_number": "310", "test_name": "Histoplasma Ag", "full_name": "MVista Histoplasma Antigen Quantitative EIA", "test_type": "Antigen Test", "species": "Any", "specimens": ["Urine", "Serum", "BAL", "CSF"], "min_volume": 1.0},
        {"test_number": "311", "test_name": "Histoplasma Ag (Urine)", "full_name": "MVista Histoplasma Antigen EIA - Urine", "test_type": "Antigen Test", "species": "Any", "specimens": ["Urine"], "min_volume": 1.0},
        {"test_number": "312", "test_name": "Histoplasma Ag (Serum)", "full_name": "MVista Histoplasma Antigen EIA - Serum", "test_type": "Antigen Test", "species": "Any", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "316", "test_name": "Blastomyces Ag", "full_name": "MVista Blastomyces Antigen Quantitative EIA", "test_type": "Antigen Test", "species": "Any", "specimens": ["Urine", "Serum", "BAL", "CSF"], "min_volume": 1.0},
        {"test_number": "317", "test_name": "Blastomyces Ag (Urine)", "full_name": "MVista Blastomyces Antigen EIA - Urine", "test_type": "Antigen Test", "species": "Any", "specimens": ["Urine"], "min_volume": 1.0},
        {"test_number": "318", "test_name": "Blastomyces Ag (Serum)", "full_name": "MVista Blastomyces Antigen EIA - Serum", "test_type": "Antigen Test", "species": "Any", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "320", "test_name": "Coccidioides Ag", "full_name": "MVista Coccidioides Antigen Quantitative EIA", "test_type": "Antigen Test", "species": "Any", "specimens": ["Urine", "Serum", "BAL", "CSF"], "min_volume": 1.0},
        {"test_number": "330", "test_name": "Aspergillus Ag", "full_name": "MVista Aspergillus Antigen Quantitative EIA", "test_type": "Antigen Test", "species": "Any", "specimens": ["Serum", "BAL", "CSF"], "min_volume": 1.0},
        {"test_number": "340", "test_name": "Cryptococcus Ag", "full_name": "Cryptococcus Antigen Latex Agglutination", "test_type": "Antigen Test", "species": "Any", "specimens": ["Serum", "CSF"], "min_volume": 0.5},

        # Antibody Tests
        {"test_number": "410", "test_name": "Histoplasma Ab", "full_name": "Histoplasma Antibody Immunodiffusion", "test_type": "Antibody Test", "species": "Human", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "411", "test_name": "Histoplasma Ab CF", "full_name": "Histoplasma Antibody Complement Fixation", "test_type": "Antibody Test", "species": "Human", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "416", "test_name": "Blastomyces Ab", "full_name": "Blastomyces Antibody Immunodiffusion", "test_type": "Antibody Test", "species": "Human", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "420", "test_name": "Coccidioides Ab", "full_name": "Coccidioides Antibody Immunodiffusion", "test_type": "Antibody Test", "species": "Human", "specimens": ["Serum", "CSF"], "min_volume": 1.0},
        {"test_number": "421", "test_name": "Coccidioides Ab CF", "full_name": "Coccidioides Antibody Complement Fixation", "test_type": "Antibody Test", "species": "Human", "specimens": ["Serum", "CSF"], "min_volume": 1.0},
        {"test_number": "430", "test_name": "Aspergillus Ab", "full_name": "Aspergillus Antibody Immunodiffusion", "test_type": "Antibody Test", "species": "Human", "specimens": ["Serum"], "min_volume": 1.0},

        # Panels - General
        {"test_number": "500", "test_name": "Fungal Antigen Panel", "full_name": "Comprehensive Fungal Antigen Panel (Histo, Blasto, Cocci)", "test_type": "Panel - General", "species": "Any", "specimens": ["Urine", "Serum"], "min_volume": 2.0},
        {"test_number": "510", "test_name": "Endemic Mycoses Panel", "full_name": "Endemic Mycoses Antigen & Antibody Panel", "test_type": "Panel - General", "species": "Human", "specimens": ["Urine", "Serum"], "min_volume": 3.0},
        {"test_number": "520", "test_name": "Immunocompromised Host Panel", "full_name": "Immunocompromised Host Fungal Panel", "test_type": "Panel - General", "species": "Human", "specimens": ["Serum", "BAL"], "min_volume": 3.0},

        # Panels - Geographic
        {"test_number": "550", "test_name": "Ohio River Valley Panel", "full_name": "Ohio River Valley Endemic Fungi Panel", "test_type": "Panel - Geographic", "species": "Any", "specimens": ["Urine", "Serum"], "min_volume": 2.0},
        {"test_number": "551", "test_name": "Mississippi River Panel", "full_name": "Mississippi River Valley Endemic Fungi Panel", "test_type": "Panel - Geographic", "species": "Any", "specimens": ["Urine", "Serum"], "min_volume": 2.0},
        {"test_number": "552", "test_name": "Southwest US Panel", "full_name": "Southwestern US Endemic Fungi Panel (Cocci focus)", "test_type": "Panel - Geographic", "species": "Any", "specimens": ["Urine", "Serum"], "min_volume": 2.0},

        # Panels - Syndrome Based
        {"test_number": "600", "test_name": "Pneumonia Panel", "full_name": "Community-Acquired Pneumonia Fungal Panel", "test_type": "Panel - Syndrome", "species": "Human", "specimens": ["Urine", "Serum", "BAL"], "min_volume": 3.0},
        {"test_number": "610", "test_name": "Meningitis Panel", "full_name": "Fungal Meningitis Panel", "test_type": "Panel - Syndrome", "species": "Human", "specimens": ["CSF", "Serum"], "min_volume": 2.0},
        {"test_number": "620", "test_name": "Disseminated Disease Panel", "full_name": "Disseminated Fungal Disease Panel", "test_type": "Panel - Syndrome", "species": "Human", "specimens": ["Urine", "Serum"], "min_volume": 3.0},

        # Veterinary-Specific Tests
        {"test_number": "710", "test_name": "Canine Histo Ag", "full_name": "Canine Histoplasma Antigen EIA", "test_type": "Antigen Test", "species": "Dog", "specimens": ["Urine", "Serum"], "min_volume": 1.0},
        {"test_number": "716", "test_name": "Canine Blasto Ag", "full_name": "Canine Blastomyces Antigen EIA", "test_type": "Antigen Test", "species": "Dog", "specimens": ["Urine", "Serum"], "min_volume": 1.0},
        {"test_number": "720", "test_name": "Canine Cocci Ag", "full_name": "Canine Coccidioides Antigen EIA", "test_type": "Antigen Test", "species": "Dog", "specimens": ["Urine", "Serum"], "min_volume": 1.0},
        {"test_number": "730", "test_name": "Feline Crypto Ag", "full_name": "Feline Cryptococcus Antigen", "test_type": "Antigen Test", "species": "Cat", "specimens": ["Serum"], "min_volume": 0.5},
        {"test_number": "750", "test_name": "Veterinary Fungal Panel", "full_name": "Comprehensive Veterinary Fungal Antigen Panel", "test_type": "Panel - General", "species": "Any", "specimens": ["Urine", "Serum"], "min_volume": 2.0},

        # Drug Monitoring
        {"test_number": "800", "test_name": "Itraconazole Level", "full_name": "Itraconazole Drug Level (Trough)", "test_type": "Drug Monitoring", "species": "Any", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "810", "test_name": "Voriconazole Level", "full_name": "Voriconazole Drug Level (Trough)", "test_type": "Drug Monitoring", "species": "Any", "specimens": ["Serum"], "min_volume": 1.0},
        {"test_number": "820", "test_name": "Posaconazole Level", "full_name": "Posaconazole Drug Level (Trough)", "test_type": "Drug Monitoring", "species": "Any", "specimens": ["Serum"], "min_volume": 1.0},
    ]

    created_tests = 0
    created_specimens = 0

    for test_data in tests_data:
        # Check if test already exists
        existing = db.query(Test).filter(Test.test_number == test_data["test_number"]).first()
        if existing:
            continue

        # Create test
        test = Test(
            test_number=test_data["test_number"],
            test_name=test_data["test_name"],
            full_name=test_data.get("full_name"),
            test_type=test_data["test_type"],
            species=test_data.get("species", "Any")
        )
        db.add(test)
        db.flush()  # Get the ID
        created_tests += 1

        # Create specimen types
        for specimen in test_data.get("specimens", []):
            specimen_type = TestSpecimenType(
                test_id=test.id,
                specimen_type=specimen,
                minimum_volume_ml=test_data.get("min_volume")
            )
            db.add(specimen_type)
            created_specimens += 1

    db.commit()
    logger.info(f"Seeded {created_tests} tests with {created_specimens} specimen types")

    return {
        "status": "success",
        "tests_created": created_tests,
        "specimen_types_created": created_specimens,
        "total_tests": len(tests_data)
    }


@router.post("/seed/config")
async def seed_config(db: Session = Depends(get_db)):
    """Seed system configuration with default values."""
    try:
        config_service = ConfigService(db)

        # Count existing configs
        existing_count = db.query(SystemConfig).count()

        # Initialize defaults
        config_service.initialize_defaults()

        # Count after initialization
        new_count = db.query(SystemConfig).count()
        created_count = new_count - existing_count

        return {
            "status": "success",
            "message": f"Configuration seeded successfully",
            "configs_created": created_count,
            "total_configs": new_count
        }
    except Exception as e:
        logger.error(f"Config seeding failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Config seeding failed: {str(e)}"
        )


@router.post("/seed/all")
async def seed_all_data(db: Session = Depends(get_db)):
    """Seed all reference data (database tables, species, tests)."""
    results = {}

    # Seed database tables
    try:
        Base.metadata.create_all(bind=engine)
        config_service = ConfigService(db)
        config_service.initialize_defaults()
        results["database"] = "success"
    except Exception as e:
        results["database"] = f"error: {str(e)}"
        logger.error(f"Database seeding error: {e}")

    # Seed species
    try:
        species_result = await seed_species(db)
        results["species"] = species_result
    except Exception as e:
        results["species"] = f"error: {str(e)}"
        logger.error(f"Species seeding error: {e}")

    # Seed tests
    try:
        tests_result = await seed_test_catalog(db)
        results["tests"] = tests_result
    except Exception as e:
        results["tests"] = f"error: {str(e)}"
        logger.error(f"Tests seeding error: {e}")

    return {
        "status": "completed",
        "results": results
    }
