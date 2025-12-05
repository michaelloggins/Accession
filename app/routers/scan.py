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

    logger.info(f"Processing scan batch: {len(files)} pages from {current_user['user_email']}")
    logger.info(f"AI config: doc_intel={use_doc_intel}, openai_extract={use_openai_extract}")

    try:
        batch_id = str(uuid.uuid4())[:8]
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

            # Generate filename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"scan_{batch_id}_{doc_idx + 1:03d}_{timestamp}.png"

            # Upload to blob storage
            blob_name = await doc_service.upload_bytes_to_blob(doc_content, filename, source="scanner")

            # Determine processing status based on config
            if use_openai_extract:
                processing_status = Document.PROC_STATUS_QUEUED
                doc_status = "processing"
                queued_at = datetime.utcnow()
            else:
                processing_status = Document.PROC_STATUS_PENDING
                doc_status = "pending"
                queued_at = None

            # Create document record
            document = Document(
                filename=filename,
                blob_name=blob_name,
                source="scanner",
                uploaded_by=current_user["user_email"],
                processing_status=processing_status,
                status=doc_status,
                queued_at=queued_at,
                extraction_attempts=0
            )

            # Store classification info in notes or metadata
            if doc_type != "unknown":
                document.notes = f"Classified as: {doc_type} (confidence: {confidence:.2f})"

            db.add(document)
            db.commit()
            db.refresh(document)

            documents_created.append({
                "id": document.id,
                "accession_number": document.accession_number,
                "filename": filename,
                "document_type": doc_type,
                "pages": page_indices,
                "confidence": confidence,
                "queued_for_extraction": use_openai_extract
            })

            # Log upload action
            audit_service.log_action(
                user_id=current_user["user_id"],
                user_email=current_user["user_email"],
                action="CREATE",
                resource_type="DOCUMENT",
                resource_id=str(document.id),
                details=f"Scanned document batch {batch_id}, type: {doc_type}",
                success=True
            )

            logger.info(f"Created document {document.id} from scan batch {batch_id} (type: {doc_type})")

        return {
            "success": True,
            "batch_id": batch_id,
            "pages_received": len(page_contents),
            "documents_created": len(documents_created),
            "doc_intelligence_used": use_doc_intel,
            "openai_extraction_queued": use_openai_extract,
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
