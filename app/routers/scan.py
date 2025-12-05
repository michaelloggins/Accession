"""Scanner integration API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, status
from sqlalchemy.orm import Session
from typing import List
import logging
import uuid
from datetime import datetime

from app.database import get_db
from app.config import settings
from app.services.auth_service import get_current_user_from_request
from app.services.document_service import DocumentService
from app.services.audit_service import AuditService
from app.models.document import Document

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/process-batch")
async def process_scan_batch(
    request: Request,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Process a batch of scanned pages.

    This endpoint:
    1. Receives multiple scanned page images
    2. Sends them to Azure Document Intelligence for classification/separation
    3. Creates document records for each detected document
    4. Queues them for extraction

    Returns the number of documents created.
    """
    current_user = get_current_user_from_request(request, db)
    doc_service = DocumentService(db)
    audit_service = AuditService(db)

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )

    logger.info(f"Processing scan batch: {len(files)} pages from {current_user['user_email']}")

    try:
        documents_created = []
        batch_id = str(uuid.uuid4())[:8]

        # For now, treat each page as a separate document
        # TODO: Integrate Azure Document Intelligence for classification/separation
        for idx, file in enumerate(files):
            # Validate file
            if not file.content_type or not file.content_type.startswith('image/'):
                logger.warning(f"Skipping non-image file: {file.filename}")
                continue

            # Generate filename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"scan_{batch_id}_{idx + 1:03d}_{timestamp}.png"

            # Read file content
            content = await file.read()
            await file.seek(0)

            # Upload to blob storage
            blob_name = await doc_service.upload_bytes_to_blob(content, filename)

            # Create document record
            document = Document(
                filename=filename,
                blob_name=blob_name,
                source="scanner",
                uploaded_by=current_user["user_email"],
                processing_status=Document.PROC_STATUS_QUEUED,
                status="processing",
                queued_at=datetime.utcnow(),
                extraction_attempts=0
            )

            db.add(document)
            db.commit()
            db.refresh(document)

            documents_created.append({
                "id": document.id,
                "accession_number": document.accession_number,
                "filename": filename
            })

            # Log upload action
            audit_service.log_action(
                user_id=current_user["user_id"],
                user_email=current_user["user_email"],
                action="CREATE",
                resource_type="DOCUMENT",
                resource_id=str(document.id),
                details=f"Scanned document batch {batch_id}",
                success=True
            )

            logger.info(f"Created document {document.id} from scan batch {batch_id}")

        return {
            "success": True,
            "batch_id": batch_id,
            "pages_received": len(files),
            "documents_created": len(documents_created),
            "documents": documents_created
        }

    except Exception as e:
        logger.error(f"Scan batch processing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process scan batch: {str(e)}"
        )


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
    current_user = get_current_user_from_request(request, db)

    # TODO: Implement SAS token generation
    # For now, return a placeholder response indicating this feature is not yet implemented
    return {
        "message": "Direct upload not yet implemented. Use /process-batch endpoint.",
        "use_endpoint": "/api/scan/process-batch"
    }
