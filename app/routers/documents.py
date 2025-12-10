"""Document management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, BackgroundTasks, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import logging
import os
import uuid
import asyncio
from datetime import datetime

from app.database import get_db
from app.config import settings
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentResponse,
    DocumentListResponse,
    DocumentListItem,
    ReviewRequest,
    ReviewResponse,
    RejectRequest,
    ManualOrderCreate,
)
from app.services.document_service import DocumentService
from app.services.extraction_factory import get_extraction_service
from app.services.lab_integration_service import LabIntegrationService
from app.services.audit_service import AuditService
from app.services.auth_service import get_current_user_from_request
from app.services.background_tasks import process_bulk_upload, BackgroundTaskManager
from app.services.config_service import get_config_bool
from app.models.document import Document

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    source: str = Form("upload"),
    db: Session = Depends(get_db)
):
    """Upload a document for AI extraction (queued for background processing)."""
    doc_service = DocumentService(db)
    audit_service = AuditService(db)
    current_user = get_current_user_from_request(request, db)

    try:
        # Validate file
        doc_service.validate_file(file)

        # Upload to blob storage with standardized filename
        blob_name = await doc_service.upload_to_blob(file, user_email=current_user["user_email"])

        # Check if auto-extraction is enabled
        auto_extract = get_config_bool(db, "AUTO_EXTRACT_ENABLED", default=True)

        if auto_extract:
            # Queue for automatic extraction
            processing_status = Document.PROC_STATUS_QUEUED
            doc_status = "processing"
            queued_at = datetime.utcnow()
            message = "Document uploaded and queued for AI extraction"
        else:
            # Manual mode - require explicit re-extract action
            processing_status = Document.PROC_STATUS_PENDING
            doc_status = "pending"
            queued_at = None
            message = "Document uploaded. Use 'Re-Extract with AI' to process."

        # Create document record
        document = Document(
            filename=file.filename,
            blob_name=blob_name,
            source=source,
            uploaded_by=current_user["user_email"],
            processing_status=processing_status,
            status=doc_status,
            queued_at=queued_at,
            extraction_attempts=0
        )

        db.add(document)
        db.commit()
        db.refresh(document)

        # Log upload action
        audit_service.log_action(
            user_id=current_user["user_id"],
            user_email=current_user["user_email"],
            action="CREATE",
            resource_type="DOCUMENT",
            resource_id=str(document.id),
            success=True
        )

        logger.info(f"Document {document.id} uploaded: {file.filename} (auto_extract={auto_extract})")

        return DocumentUploadResponse(
            id=document.id,
            accession_number=document.accession_number,
            filename=document.filename,
            status=processing_status,
            confidence_score=None,
            extracted_data=None,
            message=message
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document upload failed"
        )


@router.post("/bulk-upload")
async def bulk_upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    source: str = Form("upload"),
    db: Session = Depends(get_db)
):
    """Upload multiple documents for processing.

    For <= 4 files: Queue directly for Extraction Worker (faster for small batches)
    For > 4 files: Use Background Jobs system (better progress tracking for large batches)
    """
    if len(files) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided"
        )

    doc_service = DocumentService(db)
    audit_service = AuditService(db)
    current_user = get_current_user_from_request(request, db)

    # For larger uploads (>4 files), use Background Jobs for better progress tracking
    if len(files) > 4:
        # Read all file contents first (needed for background processing)
        files_data = []
        validation_errors = []

        for file in files:
            try:
                # Validate file first
                doc_service.validate_file(file)

                # Read content
                content = await file.read()
                files_data.append({
                    'filename': file.filename,
                    'content': content,
                    'content_type': file.content_type or 'application/pdf'
                })
            except Exception as e:
                logger.error(f"Failed to validate {file.filename}: {e}")
                validation_errors.append({
                    "filename": file.filename,
                    "error": str(e)
                })

        if not files_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid files to process"
            )

        # Create background job
        job_id = str(uuid.uuid4())
        db_url = settings.DATABASE_URL

        # Queue the background task
        background_tasks.add_task(
            process_bulk_upload,
            job_id=job_id,
            files_data=files_data,
            source=source,
            uploaded_by=current_user["user_email"],
            db_url=db_url
        )

        logger.info(f"Background job {job_id} created for {len(files_data)} files")

        return {
            "status": "background_job_created",
            "job_id": job_id,
            "total_files": len(files),
            "queued_count": len(files_data),
            "error_count": len(validation_errors),
            "errors": validation_errors,
            "message": f"Background job created to process {len(files_data)} documents. Track progress in Admin > Background Jobs."
        }

    # For small batches (<=4 files), use direct queue approach
    uploaded_docs = []
    errors = []

    # Check if auto-extraction is enabled
    auto_extract = get_config_bool(db, "AUTO_EXTRACT_ENABLED", default=True)

    for file in files:
        try:
            # Validate file
            doc_service.validate_file(file)

            # Upload to blob storage with standardized filename
            blob_name = await doc_service.upload_to_blob(file, user_email=current_user["user_email"])

            # Create document record based on auto-extract setting
            if auto_extract:
                processing_status = Document.PROC_STATUS_QUEUED
                doc_status = "processing"
                queued_at = datetime.utcnow()
            else:
                processing_status = Document.PROC_STATUS_PENDING
                doc_status = "pending"
                queued_at = None

            document = Document(
                filename=file.filename,
                blob_name=blob_name,
                source=source,
                uploaded_by=current_user["user_email"],
                processing_status=processing_status,
                status=doc_status,
                queued_at=queued_at,
                extraction_attempts=0
            )

            db.add(document)
            db.commit()
            db.refresh(document)

            uploaded_docs.append({
                "id": document.id,
                "accession_number": document.accession_number,
                "filename": document.filename
            })

            # Log upload action
            audit_service.log_action(
                user_id=current_user["user_id"],
                user_email=current_user["user_email"],
                action="CREATE",
                resource_type="DOCUMENT",
                resource_id=str(document.id),
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            errors.append({
                "filename": file.filename,
                "error": str(e)
            })

    logger.info(f"Bulk upload: {len(uploaded_docs)} queued, {len(errors)} failed")

    return {
        "status": "queued",
        "total_files": len(files),
        "queued_count": len(uploaded_docs),
        "error_count": len(errors),
        "documents": uploaded_docs,
        "errors": errors,
        "message": f"{len(uploaded_docs)} documents queued for AI extraction"
    }


@router.get("/upload-status/{job_id}")
async def get_upload_status(job_id: str):
    """Get the status of a bulk upload job."""
    job_status = BackgroundTaskManager.get_job_status(job_id)

    if job_status.get('status') == 'not_found':
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    return job_status


@router.get("/all-jobs")
async def get_all_jobs():
    """Get all background jobs."""
    jobs = BackgroundTaskManager.get_all_jobs()
    return jobs


@router.post("/cancel-job/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running or queued job."""
    result = BackgroundTaskManager.cancel_job(job_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found or cannot be cancelled"
        )

    return {"status": "cancelled", "job_id": job_id}


@router.post("/retry-job/{job_id}")
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Retry a failed job."""
    job_data = BackgroundTaskManager.get_job_for_retry(job_id)

    if not job_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found or cannot be retried"
        )

    # Generate new job ID for retry
    new_job_id = str(uuid.uuid4())

    # Get database URL for background task
    db_url = settings.DATABASE_URL

    # Queue background task with failed files
    background_tasks.add_task(
        process_bulk_upload,
        job_id=new_job_id,
        files_data=job_data['failed_files'],
        source=job_data.get('source', 'upload'),
        uploaded_by=job_data.get('uploaded_by', 'current_user'),
        db_url=db_url
    )

    logger.info(f"Queued retry job {new_job_id} for original job {job_id}")

    return {
        "status": "queued",
        "new_job_id": new_job_id,
        "original_job_id": job_id
    }


@router.delete("/delete-job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job from the system."""
    result = BackgroundTaskManager.delete_job(job_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )

    return {"status": "deleted", "job_id": job_id}


@router.get("/", response_model=DocumentListResponse)
async def get_all_documents(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    scan_station_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get all documents with optional status and scan station filters."""
    import json
    from app.services.encryption_service import EncryptionService

    doc_service = DocumentService(db)
    documents = doc_service.get_all_documents(skip=skip, limit=limit, status_filter=status, scan_station_id=scan_station_id)
    total = doc_service.count_all_documents(status_filter=status, scan_station_id=scan_station_id)

    encryption_service = EncryptionService()

    # Convert SQLAlchemy models to Pydantic schemas
    document_items = []
    for doc in documents:
        # Extract facility info from extracted_data
        facility_name = None
        facility_id = None
        if doc.extracted_data:
            try:
                encrypted_data = json.loads(doc.extracted_data)
                decrypted_data = encryption_service.decrypt_phi_fields(encrypted_data)

                # Check for nested facility structure
                if "facility" in decrypted_data and isinstance(decrypted_data["facility"], dict):
                    facility_name = decrypted_data["facility"].get("name")
                    facility_id = decrypted_data["facility"].get("facility_id")
                # Fallback to legacy flat structure
                elif "facility_name" in decrypted_data:
                    facility_name = decrypted_data.get("facility_name")
                    facility_id = decrypted_data.get("facility_id")
            except Exception as e:
                logger.error(f"Error extracting facility info: {e}")

        # Fallback to matched_facility relationship if no facility in extracted_data
        if not facility_name and doc.matched_facility:
            facility_name = doc.matched_facility.facility_name
            facility_id = doc.matched_facility.facility_id

        document_items.append(DocumentListItem(
            id=doc.id,
            accession_number=doc.accession_number,
            filename=doc.filename,
            upload_date=doc.upload_date,
            confidence_score=float(doc.confidence_score) if doc.confidence_score else None,
            status=doc.status,
            processing_status=doc.processing_status,
            facility_name=facility_name,
            facility_id=facility_id,
            how_received=doc.source,
            last_extraction_error=doc.last_extraction_error
        ))

    return DocumentListResponse(
        total=total,
        documents=document_items
    )


@router.get("/pending", response_model=DocumentListResponse)
async def get_pending_documents(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get all pending documents for review."""
    import json
    from app.services.encryption_service import EncryptionService

    doc_service = DocumentService(db)
    documents = doc_service.get_pending_documents(skip=skip, limit=limit)
    total = doc_service.count_pending_documents()

    encryption_service = EncryptionService()

    # Convert SQLAlchemy models to Pydantic schemas
    document_items = []
    for doc in documents:
        # Extract facility info from extracted_data
        facility_name = None
        facility_id = None
        if doc.extracted_data:
            try:
                encrypted_data = json.loads(doc.extracted_data)
                decrypted_data = encryption_service.decrypt_phi_fields(encrypted_data)

                # Check for nested facility structure
                if "facility" in decrypted_data and isinstance(decrypted_data["facility"], dict):
                    facility_name = decrypted_data["facility"].get("name")
                    facility_id = decrypted_data["facility"].get("facility_id")
                # Fallback to legacy flat structure
                elif "facility_name" in decrypted_data:
                    facility_name = decrypted_data.get("facility_name")
                    facility_id = decrypted_data.get("facility_id")
            except Exception as e:
                logger.error(f"Error extracting facility info: {e}")

        # Fallback to matched_facility relationship if no facility in extracted_data
        if not facility_name and doc.matched_facility:
            facility_name = doc.matched_facility.facility_name
            facility_id = doc.matched_facility.facility_id

        document_items.append(DocumentListItem(
            id=doc.id,
            accession_number=doc.accession_number,
            filename=doc.filename,
            upload_date=doc.upload_date,
            confidence_score=float(doc.confidence_score) if doc.confidence_score else None,
            status=doc.status,
            processing_status=doc.processing_status,
            facility_name=facility_name,
            facility_id=facility_id,
            how_received=doc.source,
            last_extraction_error=doc.last_extraction_error
        ))

    return DocumentListResponse(
        total=total,
        documents=document_items
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(request: Request, document_id: int, db: Session = Depends(get_db)):
    """Get a specific document with all details."""
    doc_service = DocumentService(db)
    audit_service = AuditService(db)
    current_user = get_current_user_from_request(request, db)

    document = doc_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # Generate time-limited URL for document (if blob exists)
    document_url = None
    expires = None
    if document.blob_name:
        document_url, expires = doc_service.generate_sas_url(document.blob_name)
        # For local development with mock storage, use API endpoint instead
        if document_url and document_url.startswith("file://"):
            document_url = f"/api/documents/{document_id}/file?token={{token}}"

    # Decrypt and parse extracted data
    import json
    from app.services.encryption_service import EncryptionService

    extracted_data_dict = None
    if document.extracted_data:
        try:
            # Check if already a dict (SQLAlchemy may auto-deserialize) or JSON string
            if isinstance(document.extracted_data, dict):
                encrypted_data = document.extracted_data
                logger.info(f"Extracted data is already a dict")
            elif isinstance(document.extracted_data, str):
                encrypted_data = json.loads(document.extracted_data)
                logger.info(f"Parsed extracted_data JSON string successfully")
            else:
                logger.error(f"Unexpected extracted_data type: {type(document.extracted_data)}")
                encrypted_data = {}

            # Decrypt PHI fields
            encryption_service = EncryptionService()
            extracted_data_dict = encryption_service.decrypt_phi_fields(encrypted_data)
            logger.info(f"Decrypted data successfully, keys: {list(extracted_data_dict.keys())}")
        except Exception as e:
            logger.error(f"Error decrypting extracted data for document {document_id}: {e}", exc_info=True)
            # Try to return the original data as fallback
            if isinstance(document.extracted_data, dict):
                extracted_data_dict = document.extracted_data
                logger.warning(f"Returning original dict data as fallback for document {document_id}")
            else:
                extracted_data_dict = None

    # Log PHI access
    audit_service.log_action(
        user_id=current_user["user_id"],
        user_email=current_user["user_email"],
        action="VIEW",
        resource_type="DOCUMENT",
        resource_id=str(document_id),
        phi_accessed=["patient_name", "date_of_birth"],
        success=True
    )

    return DocumentResponse(
        id=document.id,
        accession_number=document.accession_number,
        filename=document.filename,
        upload_date=document.upload_date,
        uploaded_by=document.uploaded_by,
        confidence_score=float(document.confidence_score) if document.confidence_score else None,
        status=document.status,
        extracted_data=extracted_data_dict,
        document_url=document_url,
        document_url_expires=expires
    )


@router.post("/{document_id}/review", response_model=ReviewResponse)
async def review_document(
    http_request: Request,
    document_id: int,
    request: ReviewRequest,
    db: Session = Depends(get_db)
):
    """Review and approve a document."""
    doc_service = DocumentService(db)
    lab_service = LabIntegrationService()
    audit_service = AuditService(db)
    current_user = get_current_user_from_request(http_request, db)

    document = doc_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    # Update document with corrections
    doc_service.update_document_review(
        document_id=document_id,
        corrected_data=request.corrected_data.model_dump(),
        reviewer_notes=request.reviewer_notes,
        approved=request.approved,
        reviewed_by=current_user["user_email"]
    )

    # Submit to lab if approved
    lab_result = None
    if request.approved:
        lab_result = await lab_service.submit_to_lab(document_id, request.corrected_data.model_dump())

    # Log review action
    audit_service.log_action(
        user_id=current_user["user_id"],
        user_email=current_user["user_email"],
        action="UPDATE",
        resource_type="DOCUMENT",
        resource_id=str(document_id),
        phi_accessed=list(request.corrected_data.model_dump().keys()),
        success=True
    )

    return ReviewResponse(
        status="success",
        document_status="approved" if request.approved else "reviewed",
        lab_result=lab_result
    )


@router.post("/{document_id}/reject")
async def reject_document(
    http_request: Request,
    document_id: int,
    request: RejectRequest,
    db: Session = Depends(get_db)
):
    """Reject a document."""
    doc_service = DocumentService(db)
    audit_service = AuditService(db)
    current_user = get_current_user_from_request(http_request, db)

    document = doc_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    doc_service.reject_document(document_id, request.reason, current_user["user_email"])

    # Log rejection
    audit_service.log_action(
        user_id=current_user["user_id"],
        user_email=current_user["user_email"],
        action="UPDATE",
        resource_type="DOCUMENT",
        resource_id=str(document_id),
        success=True
    )

    return {"status": "success", "document_status": "rejected"}


@router.post("/manual", response_model=DocumentUploadResponse)
async def create_manual_order(
    http_request: Request,
    order_data: ManualOrderCreate,
    db: Session = Depends(get_db)
):
    """Create a new order manually without document upload."""
    doc_service = DocumentService(db)
    audit_service = AuditService(db)
    current_user = get_current_user_from_request(http_request, db)

    try:
        # Convert Pydantic model to dict for extracted_data
        extracted_data = order_data.model_dump()

        # Create document record with manual source and high confidence
        # (since it's manually entered by a human)
        document = doc_service.create_document(
            filename=f"Manual_Order_Temp.json",  # Temporary filename
            blob_name=None,  # No blob for manual entries
            extracted_data=extracted_data,
            confidence_score=1.0,  # Manual entry = 100% confidence
            source="manual",
            uploaded_by=current_user["user_email"]
        )

        # Update filename to use accession number now that ID is assigned
        from app.models.document import Document as DocumentModel
        document_from_db = db.query(DocumentModel).filter(DocumentModel.id == document.id).first()
        if document_from_db:
            document_from_db.filename = f"{document.accession_number}.json"
            db.commit()
            db.refresh(document_from_db)
            document = document_from_db

        # Log manual creation
        audit_service.log_action(
            user_id=current_user["user_id"],
            user_email=current_user["user_email"],
            action="CREATE",
            resource_type="DOCUMENT",
            resource_id=str(document.id),
            success=True
        )

        return DocumentUploadResponse(
            id=document.id,
            accession_number=document.accession_number,
            filename=document.filename,
            status=document.status,
            confidence_score=1.0,
            extracted_data=extracted_data
        )

    except Exception as e:
        logger.error(f"Manual order creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create manual order: {str(e)}"
        )


@router.post("/{document_id}/re-extract")
async def re_extract_document(
    http_request: Request,
    document_id: int,
    db: Session = Depends(get_db)
):
    """Queue document for AI re-extraction.

    This queues the document for background processing to avoid HTTP timeouts.
    The document will be processed by the extraction worker.
    """
    from app.models.document import Document
    from app.utils.timezone import now_eastern

    audit_service = AuditService(db)
    current_user = get_current_user_from_request(http_request, db)

    # Get the document directly to modify it
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if not document.blob_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot re-extract manually created orders"
        )

    try:
        # Queue the document for re-extraction by setting processing_status to 'queued'
        document.processing_status = Document.PROC_STATUS_QUEUED
        document.queued_at = now_eastern()
        document.extraction_error = None  # Clear any previous error

        # Reset confidence to indicate re-extraction is pending
        # Keep the old extracted_data until new extraction completes

        db.commit()

        logger.info(f"Document {document_id} queued for re-extraction")

        # Log re-extraction action
        audit_service.log_action(
            user_id=current_user["user_id"],
            user_email=current_user["user_email"],
            action="QUEUE_REEXTRACT",
            resource_type="DOCUMENT",
            resource_id=str(document_id),
            success=True
        )

        return {
            "status": "queued",
            "message": "Document queued for re-extraction. Processing will complete in the background.",
            "document_id": document_id,
            "processing_status": "queued"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Re-extraction queue error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue re-extraction: {str(e)}"
        )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: int,
    token: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Serve the document file - redirects to SAS URL in production."""
    from app.config import settings
    from fastapi.responses import RedirectResponse

    # Verify token if provided
    if token:
        try:
            import jwt
            jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token"
            )

    doc_service = DocumentService(db)

    document = doc_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if not document.blob_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No file associated with this document"
        )

    # In production (Azure), redirect to SAS URL
    if settings.AZURE_STORAGE_CONNECTION_STRING:
        sas_url, expires = doc_service.generate_sas_url(document.blob_name)
        if sas_url:
            return RedirectResponse(url=sas_url, status_code=302)
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate document URL"
            )

    # For local development, serve from uploads folder
    file_path = os.path.join("uploads", document.blob_name)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file not found"
        )

    # Determine media type
    ext = document.filename.lower().split(".")[-1]
    media_types = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "tiff": "image/tiff",
        "tif": "image/tiff"
    }
    media_type = media_types.get(ext, "application/octet-stream")

    # Return file with inline disposition to display in browser
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename={document.filename}"
        }
    )
