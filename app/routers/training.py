"""Training data API router for AI Learning management."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.training_data import DocumentType, TrainingSample
from app.models.document import Document
from app.utils.timezone import now_eastern

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_training_stats(db: Session = Depends(get_db)):
    """Get overall training statistics for the AI Learning dashboard."""
    try:
        # Get document types with sample counts
        doc_types = db.query(DocumentType).filter(DocumentType.is_active == True).all()

        total_samples = db.query(func.count(TrainingSample.id)).scalar() or 0
        verified_samples = db.query(func.count(TrainingSample.id)).filter(
            TrainingSample.is_verified == True
        ).scalar() or 0
        pending_verification = total_samples - verified_samples

        # Calculate FR extraction rate
        total_fr = sum(dt.fr_extraction_count or 0 for dt in doc_types)
        total_openai = sum(dt.openai_extraction_count or 0 for dt in doc_types)
        total_extractions = total_fr + total_openai
        fr_rate = round((total_fr / total_extractions * 100) if total_extractions > 0 else 0)

        # Build document types list with verified counts
        doc_types_data = []
        for dt in doc_types:
            verified_count = db.query(func.count(TrainingSample.id)).filter(
                TrainingSample.document_type_id == dt.id,
                TrainingSample.is_verified == True
            ).scalar() or 0

            doc_types_data.append({
                "id": dt.id,
                "name": dt.name,
                "description": dt.description,
                "sample_count": dt.sample_count or 0,
                "verified_count": verified_count,
                "avg_confidence": dt.avg_confidence,
                "form_recognizer_model_id": dt.form_recognizer_model_id,
                "training_enabled": dt.training_enabled,
                "use_form_recognizer": dt.use_form_recognizer
            })

        return {
            "total_document_types": len(doc_types),
            "total_samples": total_samples,
            "verified_count": verified_samples,
            "pending_verification": pending_verification,
            "fr_extraction_rate": fr_rate,
            "document_types": doc_types_data
        }
    except Exception as e:
        logger.error(f"Error getting training stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/samples")
async def list_training_samples(
    document_type_id: Optional[int] = Query(None),
    verified: Optional[bool] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db)
):
    """List training samples with optional filtering."""
    try:
        query = db.query(TrainingSample)

        if document_type_id:
            query = query.filter(TrainingSample.document_type_id == document_type_id)
        if verified is not None:
            query = query.filter(TrainingSample.is_verified == verified)

        total = query.count()
        samples = query.order_by(TrainingSample.created_at.desc()).offset(offset).limit(limit).all()

        samples_data = []
        for s in samples:
            # Get document type name
            doc_type = db.query(DocumentType).filter(DocumentType.id == s.document_type_id).first()

            # Get document URL if available
            document_url = None
            if s.document_id:
                doc = db.query(Document).filter(Document.id == s.document_id).first()
                if doc and doc.blob_name:
                    document_url = f"/api/documents/{doc.id}/view"

            samples_data.append({
                "id": s.id,
                "document_type_id": s.document_type_id,
                "document_type_name": doc_type.name if doc_type else None,
                "document_id": s.document_id,
                "blob_name": s.blob_name,
                "gpt_classification": s.gpt_classification,
                "gpt_confidence": s.gpt_confidence,
                "gpt_reasoning": s.gpt_reasoning,
                "is_verified": s.is_verified,
                "verified_by": s.verified_by,
                "verified_at": s.verified_at.isoformat() if s.verified_at else None,
                "corrected_type": s.corrected_type,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "document_url": document_url
            })

        return {
            "samples": samples_data,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error listing training samples: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/samples/{sample_id}")
async def get_training_sample(sample_id: int, db: Session = Depends(get_db)):
    """Get a single training sample with full details."""
    sample = db.query(TrainingSample).filter(TrainingSample.id == sample_id).first()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    doc_type = db.query(DocumentType).filter(DocumentType.id == sample.document_type_id).first()

    # Get document URL
    document_url = None
    if sample.document_id:
        doc = db.query(Document).filter(Document.id == sample.document_id).first()
        if doc and doc.blob_name:
            document_url = f"/api/documents/{doc.id}/view"

    return {
        "id": sample.id,
        "document_type_id": sample.document_type_id,
        "document_type_name": doc_type.name if doc_type else None,
        "document_id": sample.document_id,
        "blob_name": sample.blob_name,
        "gpt_classification": sample.gpt_classification,
        "gpt_confidence": sample.gpt_confidence,
        "gpt_reasoning": sample.gpt_reasoning,
        "gpt_features": sample.gpt_features,
        "extracted_fields": sample.extracted_fields,
        "is_verified": sample.is_verified,
        "verified_by": sample.verified_by,
        "verified_at": sample.verified_at.isoformat() if sample.verified_at else None,
        "corrected_type": sample.corrected_type,
        "created_at": sample.created_at.isoformat() if sample.created_at else None,
        "document_url": document_url
    }


@router.put("/samples/{sample_id}/verify")
async def verify_training_sample(
    sample_id: int,
    data: dict,
    db: Session = Depends(get_db)
):
    """Verify a training sample classification."""
    sample = db.query(TrainingSample).filter(TrainingSample.id == sample_id).first()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    is_correct = data.get("is_correct", True)
    corrected_type_id = data.get("corrected_type_id")

    sample.is_verified = True
    sample.verified_at = now_eastern()
    sample.verified_by = data.get("verified_by", "admin")  # TODO: Get from auth context

    if not is_correct and corrected_type_id:
        # Get the corrected document type name
        corrected_type = db.query(DocumentType).filter(DocumentType.id == corrected_type_id).first()
        if corrected_type:
            sample.corrected_type = corrected_type.name

            # Optionally move the sample to the correct document type
            old_doc_type = db.query(DocumentType).filter(DocumentType.id == sample.document_type_id).first()
            if old_doc_type:
                old_doc_type.sample_count = max(0, (old_doc_type.sample_count or 1) - 1)

            sample.document_type_id = corrected_type_id
            corrected_type.sample_count = (corrected_type.sample_count or 0) + 1

    db.commit()
    logger.info(f"Verified training sample {sample_id}, correct={is_correct}")

    return {"status": "success", "sample_id": sample_id}


@router.get("/document-types")
async def list_document_types(
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db)
):
    """List all document types."""
    query = db.query(DocumentType)
    if not include_inactive:
        query = query.filter(DocumentType.is_active == True)

    doc_types = query.order_by(DocumentType.name).all()

    return {
        "document_types": [
            {
                "id": dt.id,
                "name": dt.name,
                "description": dt.description,
                "sample_count": dt.sample_count or 0,
                "avg_confidence": dt.avg_confidence,
                "training_enabled": dt.training_enabled,
                "use_form_recognizer": dt.use_form_recognizer,
                "form_recognizer_model_id": dt.form_recognizer_model_id,
                "is_active": dt.is_active
            }
            for dt in doc_types
        ]
    }


@router.post("/build-classifier")
async def build_classifier(db: Session = Depends(get_db)):
    """Build a Document Intelligence classifier from training data."""
    # This is a placeholder - actual implementation would:
    # 1. Export training samples to Azure Blob Storage
    # 2. Call Azure Document Intelligence API to build custom classifier
    # 3. Store the model ID back in the database

    doc_types = db.query(DocumentType).filter(
        DocumentType.is_active == True,
        DocumentType.sample_count >= 1
    ).all()

    if len(doc_types) < 2:
        raise HTTPException(
            status_code=400,
            detail="Need at least 2 document types to build classifier"
        )

    total_samples = sum(dt.sample_count or 0 for dt in doc_types)
    if total_samples < 5:
        raise HTTPException(
            status_code=400,
            detail="Need at least 5 training samples to build classifier"
        )

    # TODO: Implement actual classifier building
    logger.info(f"Building classifier with {len(doc_types)} document types, {total_samples} samples")

    return {
        "status": "success",
        "message": "Classifier build initiated",
        "model_id": "placeholder-model-id",
        "document_types": len(doc_types),
        "total_samples": total_samples
    }
