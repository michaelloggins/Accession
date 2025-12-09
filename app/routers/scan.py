"""Scanner integration API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status
from sqlalchemy.orm import Session
from typing import List
import logging
import uuid
import json
from datetime import datetime

from app.database import get_db
from app.config import settings
from app.services.auth_service import get_current_user_from_request
from app.services.document_service import DocumentService
from app.services.audit_service import AuditService
from app.services.config_service import ConfigService
from app.services.document_intelligence_service import get_document_intelligence_service
from app.models.document import Document
from app.models.workstation import UserWorkstationPreference, ScanningStation
from app.services.training_service import TrainingService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_ai_service_config(db: Session) -> dict:
    """Get AI service configuration from database."""
    try:
        config_service = ConfigService(db)
        config_json = config_service.get("AI_SERVICE_CONFIG", "{}")
        return json.loads(config_json)
    except Exception:
        return {"doc_intel_classify": True, "openai_extract": True}


def get_user_scan_station(db: Session, user_id: str) -> dict:
    """Get the user's preferred scanning station."""
    try:
        pref = db.query(UserWorkstationPreference).filter(
            UserWorkstationPreference.user_id == user_id
        ).first()

        if pref and pref.scanning_station_id:
            station = db.query(ScanningStation).filter(
                ScanningStation.id == pref.scanning_station_id,
                ScanningStation.is_active == True
            ).first()

            if station:
                return {
                    "id": station.id,
                    "name": station.name,
                    "location": station.location
                }

        return {"id": None, "name": None, "location": None}
    except Exception:
        return {"id": None, "name": None, "location": None}


@router.post("/process-batch")
async def process_scan_batch(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Process a batch of scanned pages.

    Workflow:
    1. Receive multiple scanned page images
    2. If Doc Intelligence enabled: classify and separate into documents
    3. Upload each document to blob storage
    4. Queue for OpenAI extraction (if enabled)

    Returns the number of documents created.
    """
    current_user = get_current_user_from_request(request, db)
    doc_service = DocumentService(db)
    audit_service = AuditService(db)
    doc_intel_service = get_document_intelligence_service()

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )

    # Get AI service config
    ai_config = get_ai_service_config(db)
    use_doc_intel = ai_config.get("doc_intel_classify", True) and doc_intel_service.is_configured
    use_openai_extract = ai_config.get("openai_extract", True)
    learning_mode = ai_config.get("learning_mode", False)

    # Get user's scan station
    scan_station = get_user_scan_station(db, current_user.get("user_id", current_user["user_email"]))
    scanned_by = current_user["user_email"]

    # Initialize training service if learning mode is enabled
    training_service = TrainingService(db) if learning_mode else None

    logger.info(f"Processing scan batch: {len(files)} pages from {scanned_by}")
    logger.info(f"Scan station: {scan_station.get('name', 'None')}")
    logger.info(f"AI config: doc_intel={use_doc_intel}, openai_extract={use_openai_extract}, learning={learning_mode}")

    try:
        batch_id = str(uuid.uuid4())[:8]
        scan_timestamp = datetime.utcnow()
        documents_created = []

        # Read all page contents
        page_contents = []
        for file in files:
            if not file.content_type or not file.content_type.startswith('image/'):
                logger.warning(f"Skipping non-image file: {file.filename}")
                continue
            content = await file.read()
            page_contents.append(content)
            await file.seek(0)

        if not page_contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid image files provided"
            )

        # Step 1: Document separation using Document Intelligence
        if use_doc_intel:
            logger.info(f"Using Document Intelligence for classification/separation")
            document_groups = await doc_intel_service.classify_and_split(
                page_contents,
                split_mode="auto"
            )
        else:
            # Fallback: each page is a separate document
            logger.info(f"Doc Intelligence disabled, treating each page as separate document")
            document_groups = [
                {"document_type": "unknown", "pages": [i], "confidence": 1.0}
                for i in range(len(page_contents))
            ]

        logger.info(f"Separated into {len(document_groups)} documents")

        # Step 2: Create document records for each separated document
        for doc_idx, doc_group in enumerate(document_groups):
            page_indices = doc_group.get("pages", [doc_idx])
            doc_type = doc_group.get("document_type", "unknown")
            confidence = doc_group.get("confidence", 0.0)

            # Combine pages belonging to this document
            # For single page docs, just use that page
            # For multi-page, we could combine into PDF (future enhancement)
            if len(page_indices) == 1:
                # Single page document
                page_idx = page_indices[0] if isinstance(page_indices, list) else page_indices
                if isinstance(page_idx, list):
                    page_idx = page_idx[0] if page_idx else 0
                doc_content = page_contents[page_idx] if page_idx < len(page_contents) else page_contents[0]
            else:
                # Multi-page document - for now, use first page
                # TODO: Combine into multi-page TIFF or PDF
                first_page = page_indices[0] if isinstance(page_indices, list) else page_indices
                if isinstance(first_page, list):
                    first_page = first_page[0] if first_page else 0
                doc_content = page_contents[first_page] if first_page < len(page_contents) else page_contents[0]
                logger.info(f"Multi-page document detected (pages {page_indices}), using first page for now")

            # Generate filename with station name if available
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            station_prefix = scan_station.get("name", "").replace(" ", "_")[:20] if scan_station.get("name") else ""
            if station_prefix:
                filename = f"scan_{station_prefix}_{batch_id}_{doc_idx + 1:03d}_{timestamp}.png"
            else:
                filename = f"scan_{batch_id}_{doc_idx + 1:03d}_{timestamp}.png"

            # Upload to blob storage with metadata
            blob_metadata = {
                "scanned_by": scanned_by,
                "scanned_at": scan_timestamp.isoformat(),
                "scan_station_id": str(scan_station.get("id", "")),
                "scan_station_name": scan_station.get("name", ""),
                "batch_id": batch_id,
                "document_type": doc_type
            }
            blob_name = await doc_service.upload_bytes_to_blob(
                doc_content, filename, source="scanner", metadata=blob_metadata
            )

            # Determine processing status based on config
            if use_openai_extract:
                processing_status = Document.PROC_STATUS_QUEUED
                doc_status = "processing"
                queued_at = datetime.utcnow()
            else:
                processing_status = Document.PROC_STATUS_PENDING
                doc_status = "pending"
                queued_at = None

            # Create document record with scan station metadata
            document = Document(
                filename=filename,
                blob_name=blob_name,
                source="scanner",
                uploaded_by=scanned_by,
                scanned_by=scanned_by,
                scanned_at=scan_timestamp,
                scan_station_id=scan_station.get("id"),
                scan_station_name=scan_station.get("name"),
                processing_status=processing_status,
                status=doc_status,
                queued_at=queued_at,
                extraction_attempts=0
            )

            # Store classification info in notes or metadata
            if doc_type != "unknown":
                document.reviewer_notes = f"Classified as: {doc_type} (confidence: {confidence:.2f})"

            db.add(document)
            db.commit()
            db.refresh(document)

            # Learning mode: analyze with GPT-4 Vision to learn document type
            learned_type = None
            if training_service and training_service.is_configured:
                try:
                    logger.info(f"Learning mode: analyzing document {document.id} with GPT-4 Vision")
                    analysis_result = await training_service.analyze_document(
                        image_bytes=doc_content,
                        document_id=document.id,
                        blob_name=blob_name,
                        user_email=scanned_by
                    )
                    if analysis_result.get("success"):
                        learned_type = analysis_result.get("analysis", {}).get("document_type", {}).get("name")
                        logger.info(f"Learned document type: {learned_type}")
                except Exception as learn_err:
                    logger.warning(f"Learning analysis failed: {learn_err}")

            documents_created.append({
                "id": document.id,
                "accession_number": document.accession_number,
                "filename": filename,
                "document_type": learned_type or doc_type,
                "pages": page_indices,
                "confidence": confidence,
                "queued_for_extraction": use_openai_extract,
                "learned": learned_type is not None
            })

            # Log upload action
            audit_service.log_action(
                user_id=current_user["user_id"],
                user_email=current_user["user_email"],
                action="CREATE",
                resource_type="DOCUMENT",
                resource_id=str(document.id),
                details=f"Scanned document batch {batch_id}, type: {learned_type or doc_type}",
                success=True
            )

            logger.info(f"Created document {document.id} from scan batch {batch_id} (type: {learned_type or doc_type})")

        return {
            "success": True,
            "batch_id": batch_id,
            "pages_received": len(page_contents),
            "documents_created": len(documents_created),
            "doc_intelligence_used": use_doc_intel,
            "openai_extraction_queued": use_openai_extract,
            "learning_mode": learning_mode,
            "documents": documents_created
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scan batch processing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process scan batch: {str(e)}"
        )


@router.get("/config")
async def get_scan_config(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get current scan processing configuration."""
    get_current_user_from_request(request, db)

    ai_config = get_ai_service_config(db)
    doc_intel_service = get_document_intelligence_service()

    return {
        "doc_intelligence": {
            "enabled": ai_config.get("doc_intel_classify", True),
            "configured": doc_intel_service.is_configured,
            "has_classifier": doc_intel_service.has_classifier
        },
        "openai_extract": {
            "enabled": ai_config.get("openai_extract", True),
            "configured": bool(settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_API_KEY)
        }
    }


@router.get("/sas-token")
async def get_sas_token(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Generate a short-lived SAS token for direct blob upload from scanner.

    This allows the browser to upload scanned images directly to Azure Blob Storage
    without going through the backend for each file.
    """
    get_current_user_from_request(request, db)

    # TODO: Implement SAS token generation
    return {
        "message": "Direct upload not yet implemented. Use /process-batch endpoint.",
        "use_endpoint": "/api/scan/process-batch"
    }


# Training Mode Endpoints
@router.get("/training/stats")
async def get_training_stats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get training statistics for learned document types."""
    get_current_user_from_request(request, db)

    training_service = TrainingService(db)
    stats = training_service.get_training_stats()

    return {
        "success": True,
        "stats": stats
    }


@router.get("/training/types")
async def get_learned_types(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get all learned document types."""
    get_current_user_from_request(request, db)

    training_service = TrainingService(db)
    types = training_service.get_learned_types()

    return {
        "success": True,
        "document_types": types
    }


@router.get("/training/export")
async def export_training_data(
    request: Request,
    db: Session = Depends(get_db)
):
    """Export all training data for Document Intelligence classifier training."""
    get_current_user_from_request(request, db)

    training_service = TrainingService(db)
    export_data = training_service.export_training_data()

    if "error" in export_data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=export_data["error"]
        )

    return export_data


@router.delete("/training/clear")
async def clear_training_data(
    request: Request,
    db: Session = Depends(get_db)
):
    """Clear all training data. Use with caution."""
    current_user = get_current_user_from_request(request, db)
    audit_service = AuditService(db)

    training_service = TrainingService(db)
    success = training_service.clear_training_data()

    if success:
        audit_service.log_action(
            user_id=current_user["user_id"],
            user_email=current_user["user_email"],
            action="DELETE",
            resource_type="TRAINING_DATA",
            resource_id="all",
            details="Cleared all training data",
            success=True
        )
        return {"success": True, "message": "Training data cleared"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear training data"
        )


@router.post("/training/build-classifier")
async def build_and_deploy_classifier(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Build a Document Intelligence classifier from learned data and disable learning mode.

    This endpoint:
    1. Exports training data from GPT-4 learned document types
    2. Builds a custom classifier in Document Intelligence
    3. Updates config with new classifier ID
    4. Disables learning mode
    """
    current_user = get_current_user_from_request(request, db)
    audit_service = AuditService(db)
    config_service = ConfigService(db)
    training_service = TrainingService(db)
    doc_intel_service = get_document_intelligence_service()

    # Check prerequisites
    if not doc_intel_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document Intelligence is not configured"
        )

    # Get training stats
    stats = training_service.get_training_stats()
    if stats.get("document_types", 0) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No document types learned yet. Scan some documents with learning mode enabled first."
        )

    if stats.get("total_samples", 0) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Need at least 5 training samples, currently have {stats.get('total_samples', 0)}. Scan more documents."
        )

    try:
        # Export training data
        export_data = training_service.export_training_data()
        if "error" in export_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to export training data: {export_data['error']}"
            )

        # Generate classifier ID
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        classifier_id = f"accession-classifier-{timestamp}"

        # Prepare document types for classifier
        doc_types_for_training = []
        for dt in export_data.get("document_types", []):
            samples = dt.get("samples", [])
            if len(samples) >= 1:  # Need at least 1 sample per type
                doc_types_for_training.append({
                    "name": dt["name"],
                    "samples": [s["blob_name"] for s in samples if s.get("blob_name")]
                })

        if not doc_types_for_training:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No document types have valid blob samples for training"
            )

        # Get blob container URL with SAS for training
        # For now, we'll use the existing blob storage setup
        from app.services.document_service import DocumentService
        doc_service = DocumentService(db)
        container_url = doc_service.get_training_container_sas_url()

        if not container_url:
            # Fallback: try to build without blob references (limited functionality)
            logger.warning("No blob SAS URL available, attempting simple classifier build")

            # Build using document type definitions only
            simple_doc_types = {}
            for dt in export_data.get("document_types", []):
                type_key = dt["name"].replace(" ", "_").lower()
                simple_doc_types[type_key] = {
                    "description": dt.get("description", ""),
                    "features": dt.get("visual_features", {})
                }

            result = {"success": False, "error": "Blob-based training not yet configured. Training data exported but classifier not built."}
        else:
            # Build the classifier
            result = await doc_intel_service.build_classifier(
                classifier_id=classifier_id,
                document_types=doc_types_for_training,
                blob_container_url=container_url
            )

        if result.get("success"):
            # Update config with new classifier ID
            ai_config = get_ai_service_config(db)
            ai_config["learning_mode"] = False  # Disable learning
            config_service.set("AI_SERVICE_CONFIG", json.dumps(ai_config))

            # Store the classifier ID
            config_service.set("DOC_INTELLIGENCE_CLASSIFIER_ID", classifier_id)

            audit_service.log_action(
                user_id=current_user["user_id"],
                user_email=current_user["user_email"],
                action="CREATE",
                resource_type="CLASSIFIER",
                resource_id=classifier_id,
                details=f"Built classifier with {len(doc_types_for_training)} document types, learning mode disabled",
                success=True
            )

            return {
                "success": True,
                "classifier_id": classifier_id,
                "document_types_trained": len(doc_types_for_training),
                "learning_mode_disabled": True,
                "message": "Classifier built and learning mode disabled"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Classifier build failed: {result.get('error', 'Unknown error')}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Build classifier error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build classifier: {str(e)}"
        )


# Document Type Management Endpoints
@router.get("/training/document-types")
async def list_document_types(
    request: Request,
    include_inactive: bool = False,
    db: Session = Depends(get_db)
):
    """
    List all document types with their training status and statistics.
    """
    get_current_user_from_request(request, db)

    from app.models.training_data import DocumentType, TrainingSample

    query = db.query(DocumentType)
    if not include_inactive:
        query = query.filter(DocumentType.is_active == True)

    doc_types = query.order_by(DocumentType.sample_count.desc()).all()

    result = []
    for dt in doc_types:
        # Get sample counts
        verified_count = db.query(TrainingSample).filter(
            TrainingSample.document_type_id == dt.id,
            TrainingSample.is_verified == True
        ).count()

        result.append({
            "id": dt.id,
            "name": dt.name,
            "description": dt.description,
            "is_active": dt.is_active,
            "training_enabled": dt.training_enabled,
            "use_form_recognizer": dt.use_form_recognizer,
            "form_recognizer_model_id": dt.form_recognizer_model_id,
            "fr_confidence_threshold": float(dt.fr_confidence_threshold) if dt.fr_confidence_threshold else 0.90,
            "sample_count": dt.sample_count or 0,
            "verified_count": verified_count,
            "avg_confidence": round(float(dt.avg_confidence), 2) if dt.avg_confidence else 0.0,
            "fr_extraction_count": dt.fr_extraction_count or 0,
            "openai_extraction_count": dt.openai_extraction_count or 0,
            "openai_fallback_count": dt.openai_fallback_count or 0,
            "created_at": dt.created_at.isoformat() if dt.created_at else None,
            "updated_at": dt.updated_at.isoformat() if dt.updated_at else None,
            "created_by": dt.created_by
        })

    return {
        "success": True,
        "document_types": result,
        "total": len(result)
    }


@router.get("/training/document-types/{type_id}")
async def get_document_type(
    type_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get details of a specific document type including samples."""
    get_current_user_from_request(request, db)

    from app.models.training_data import DocumentType, TrainingSample

    doc_type = db.query(DocumentType).filter(DocumentType.id == type_id).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found")

    # Get recent samples
    samples = db.query(TrainingSample).filter(
        TrainingSample.document_type_id == type_id
    ).order_by(TrainingSample.created_at.desc()).limit(20).all()

    import json
    return {
        "id": doc_type.id,
        "name": doc_type.name,
        "description": doc_type.description,
        "is_active": doc_type.is_active,
        "training_enabled": doc_type.training_enabled,
        "use_form_recognizer": doc_type.use_form_recognizer,
        "form_recognizer_model_id": doc_type.form_recognizer_model_id,
        "fr_confidence_threshold": float(doc_type.fr_confidence_threshold) if doc_type.fr_confidence_threshold else 0.90,
        "visual_features": json.loads(doc_type.visual_features) if doc_type.visual_features else {},
        "text_patterns": json.loads(doc_type.text_patterns) if doc_type.text_patterns else {},
        "extraction_fields": json.loads(doc_type.extraction_fields) if doc_type.extraction_fields else [],
        "sample_count": doc_type.sample_count or 0,
        "avg_confidence": round(float(doc_type.avg_confidence), 2) if doc_type.avg_confidence else 0.0,
        "fr_extraction_count": doc_type.fr_extraction_count or 0,
        "openai_extraction_count": doc_type.openai_extraction_count or 0,
        "openai_fallback_count": doc_type.openai_fallback_count or 0,
        "created_at": doc_type.created_at.isoformat() if doc_type.created_at else None,
        "samples": [
            {
                "id": s.id,
                "document_id": s.document_id,
                "blob_name": s.blob_name,
                "gpt_classification": s.gpt_classification,
                "gpt_confidence": round(float(s.gpt_confidence), 2) if s.gpt_confidence else 0.0,
                "is_verified": s.is_verified,
                "verified_by": s.verified_by,
                "created_at": s.created_at.isoformat() if s.created_at else None
            }
            for s in samples
        ]
    }


@router.put("/training/document-types/{type_id}")
async def update_document_type(
    type_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update document type settings (training toggle, FR settings, etc.)."""
    current_user = get_current_user_from_request(request, db)
    audit_service = AuditService(db)

    from app.models.training_data import DocumentType

    doc_type = db.query(DocumentType).filter(DocumentType.id == type_id).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found")

    data = await request.json()

    # Update allowed fields
    if "training_enabled" in data:
        doc_type.training_enabled = bool(data["training_enabled"])
    if "is_active" in data:
        doc_type.is_active = bool(data["is_active"])
    if "use_form_recognizer" in data:
        doc_type.use_form_recognizer = bool(data["use_form_recognizer"])
    if "form_recognizer_model_id" in data:
        doc_type.form_recognizer_model_id = data["form_recognizer_model_id"]
    if "fr_confidence_threshold" in data:
        threshold = float(data["fr_confidence_threshold"])
        if 0.0 <= threshold <= 1.0:
            doc_type.fr_confidence_threshold = threshold
    if "description" in data:
        doc_type.description = data["description"]

    db.commit()

    audit_service.log_action(
        user_id=current_user["user_id"],
        user_email=current_user["user_email"],
        action="UPDATE",
        resource_type="DOCUMENT_TYPE",
        resource_id=str(type_id),
        details=f"Updated document type '{doc_type.name}': {list(data.keys())}",
        success=True
    )

    return {
        "success": True,
        "message": f"Document type '{doc_type.name}' updated",
        "document_type": {
            "id": doc_type.id,
            "name": doc_type.name,
            "training_enabled": doc_type.training_enabled,
            "use_form_recognizer": doc_type.use_form_recognizer,
            "fr_confidence_threshold": float(doc_type.fr_confidence_threshold) if doc_type.fr_confidence_threshold else 0.90
        }
    }


@router.delete("/training/document-types/{type_id}")
async def delete_document_type(
    type_id: int,
    request: Request,
    hard_delete: bool = False,
    db: Session = Depends(get_db)
):
    """Delete or deactivate a document type."""
    current_user = get_current_user_from_request(request, db)
    audit_service = AuditService(db)

    from app.models.training_data import DocumentType, TrainingSample, ExtractionRule

    doc_type = db.query(DocumentType).filter(DocumentType.id == type_id).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found")

    type_name = doc_type.name

    if hard_delete:
        # Delete samples and rules first
        db.query(TrainingSample).filter(TrainingSample.document_type_id == type_id).delete()
        db.query(ExtractionRule).filter(ExtractionRule.document_type_id == type_id).delete()
        db.delete(doc_type)
        action_detail = f"Hard deleted document type '{type_name}' and all samples"
    else:
        # Soft delete - just deactivate
        doc_type.is_active = False
        doc_type.training_enabled = False
        action_detail = f"Deactivated document type '{type_name}'"

    db.commit()

    audit_service.log_action(
        user_id=current_user["user_id"],
        user_email=current_user["user_email"],
        action="DELETE",
        resource_type="DOCUMENT_TYPE",
        resource_id=str(type_id),
        details=action_detail,
        success=True
    )

    return {
        "success": True,
        "message": action_detail,
        "hard_deleted": hard_delete
    }


@router.get("/training/document-types/{type_id}/samples")
async def get_document_type_samples(
    type_id: int,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    verified_only: bool = False,
    db: Session = Depends(get_db)
):
    """Get training samples for a document type."""
    get_current_user_from_request(request, db)

    from app.models.training_data import DocumentType, TrainingSample

    doc_type = db.query(DocumentType).filter(DocumentType.id == type_id).first()
    if not doc_type:
        raise HTTPException(status_code=404, detail="Document type not found")

    query = db.query(TrainingSample).filter(TrainingSample.document_type_id == type_id)
    if verified_only:
        query = query.filter(TrainingSample.is_verified == True)

    total = query.count()
    samples = query.order_by(TrainingSample.created_at.desc()).offset(offset).limit(limit).all()

    import json
    return {
        "document_type": doc_type.name,
        "total": total,
        "limit": limit,
        "offset": offset,
        "samples": [
            {
                "id": s.id,
                "document_id": s.document_id,
                "blob_name": s.blob_name,
                "gpt_classification": s.gpt_classification,
                "gpt_confidence": round(float(s.gpt_confidence), 2) if s.gpt_confidence else 0.0,
                "gpt_reasoning": s.gpt_reasoning,
                "gpt_features": json.loads(s.gpt_features) if s.gpt_features else {},
                "is_verified": s.is_verified,
                "verified_by": s.verified_by,
                "verified_at": s.verified_at.isoformat() if s.verified_at else None,
                "corrected_type": s.corrected_type,
                "created_at": s.created_at.isoformat() if s.created_at else None
            }
            for s in samples
        ]
    }


@router.put("/training/samples/{sample_id}/verify")
async def verify_training_sample(
    sample_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Mark a training sample as verified or correct its classification."""
    current_user = get_current_user_from_request(request, db)

    from app.models.training_data import TrainingSample, DocumentType
    from datetime import datetime

    sample = db.query(TrainingSample).filter(TrainingSample.id == sample_id).first()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    data = await request.json()

    sample.is_verified = True
    sample.verified_by = current_user["user_email"]
    sample.verified_at = datetime.utcnow()

    # If classification was corrected
    if "corrected_type" in data and data["corrected_type"]:
        sample.corrected_type = data["corrected_type"]

        # Optionally move to different document type
        if data.get("move_to_corrected_type"):
            # Find or create the corrected type
            corrected_doc_type = db.query(DocumentType).filter(
                DocumentType.name == data["corrected_type"]
            ).first()

            if corrected_doc_type:
                # Update counts
                old_doc_type = sample.document_type
                if old_doc_type:
                    old_doc_type.sample_count = max(0, (old_doc_type.sample_count or 0) - 1)
                corrected_doc_type.sample_count = (corrected_doc_type.sample_count or 0) + 1

                sample.document_type_id = corrected_doc_type.id

    db.commit()

    return {
        "success": True,
        "message": "Sample verified",
        "sample_id": sample_id,
        "verified_by": current_user["user_email"],
        "corrected_type": sample.corrected_type
    }


@router.get("/training/extraction-stats")
async def get_extraction_stats(
    request: Request,
    db: Session = Depends(get_db)
):
    """Get overall extraction statistics by method."""
    get_current_user_from_request(request, db)

    from app.models.training_data import DocumentType
    from sqlalchemy import func

    # Aggregate stats across all document types
    stats = db.query(
        func.sum(DocumentType.fr_extraction_count).label("total_fr"),
        func.sum(DocumentType.openai_extraction_count).label("total_openai"),
        func.sum(DocumentType.openai_fallback_count).label("total_fallback"),
        func.sum(DocumentType.sample_count).label("total_samples")
    ).filter(DocumentType.is_active == True).first()

    total_fr = stats.total_fr or 0
    total_openai = stats.total_openai or 0
    total_fallback = stats.total_fallback or 0
    total_samples = stats.total_samples or 0
    total_extractions = total_fr + total_openai

    return {
        "total_extractions": total_extractions,
        "form_recognizer_extractions": total_fr,
        "openai_extractions": total_openai,
        "openai_fallback_count": total_fallback,
        "total_training_samples": total_samples,
        "fr_percentage": round((total_fr / total_extractions * 100), 1) if total_extractions > 0 else 0,
        "fallback_rate": round((total_fallback / total_fr * 100), 1) if total_fr > 0 else 0
    }
