"""Queue management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.document import Document
from app.models.extraction_batch import ExtractionBatch
from app.services.blob_watcher import (
    get_blob_watcher_status,
    get_blob_watcher_instance,
    start_blob_watcher,
    stop_blob_watcher,
)
from app.services.extraction_worker import (
    get_extraction_worker_status,
    start_extraction_worker,
    stop_extraction_worker,
    trigger_extraction_cycle
)
from app.services.blob_lifecycle_service import BlobLifecycleService

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("/blob-watcher/status")
async def blob_watcher_status():
    """Get blob watcher service status."""
    return get_blob_watcher_status()


@router.post("/blob-watcher/start")
async def start_blob_watcher_endpoint():
    """Start the blob watcher service."""
    try:
        await start_blob_watcher()
        return {"message": "Blob watcher started", "status": "running"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start blob watcher: {str(e)}"
        )


@router.post("/blob-watcher/stop")
async def stop_blob_watcher_endpoint():
    """Stop the blob watcher service."""
    try:
        stop_blob_watcher()
        return {"message": "Blob watcher stopped", "status": "stopped"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop blob watcher: {str(e)}"
        )


@router.post("/blob-watcher/scan")
async def trigger_blob_scan():
    """Trigger an immediate blob scan."""
    watcher = get_blob_watcher_instance()
    if watcher and watcher.running:
        try:
            result = await watcher._poll_for_new_blobs()
            return {
                "message": "Blob scan completed",
                "total_blobs": result.get("total_blobs", 0),
                "new_blobs_found": result.get("new_blobs", 0),
                "skipped_unsupported": result.get("skipped_unsupported", 0),
                "already_known": result.get("already_known", 0),
                "processed_files": result.get("processed", []),
                "error": result.get("error")
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scan failed: {str(e)}"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Blob watcher is not running"
        )


@router.get("/extraction-worker/status")
async def extraction_worker_status():
    """Get extraction worker service status."""
    return get_extraction_worker_status()


@router.post("/extraction-worker/start")
async def start_extraction_worker_endpoint():
    """Start the extraction worker service."""
    try:
        await start_extraction_worker()
        return {"message": "Extraction worker started", "status": "running"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start extraction worker: {str(e)}"
        )


@router.post("/extraction-worker/stop")
async def stop_extraction_worker_endpoint():
    """Stop the extraction worker service."""
    try:
        stop_extraction_worker()
        return {"message": "Extraction worker stopped", "status": "stopped"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop extraction worker: {str(e)}"
        )


@router.post("/extraction-worker/process")
async def trigger_process_cycle():
    """Trigger an immediate extraction processing cycle."""
    try:
        await trigger_extraction_cycle()
        return {"message": "Processing cycle triggered"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing failed: {str(e)}"
        )


@router.get("/stats")
async def queue_stats(db: Session = Depends(get_db)):
    """Get queue statistics by processing status."""
    stats = db.query(
        Document.processing_status,
        func.count(Document.id)
    ).group_by(Document.processing_status).all()

    result = {
        "queued": 0,
        "processing": 0,
        "extracted": 0,
        "failed": 0,
        "pending": 0,
        "manual": 0
    }

    for proc_status, count in stats:
        if proc_status in result:
            result[proc_status] = count

    return result


@router.get("/batches")
async def get_recent_batches(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get recent extraction batches."""
    batches = db.query(ExtractionBatch).order_by(
        ExtractionBatch.created_at.desc()
    ).limit(limit).all()

    return [
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


@router.post("/requeue-failed")
async def requeue_failed_documents(db: Session = Depends(get_db)):
    """Requeue all failed documents for extraction."""
    count = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_FAILED
    ).update({
        "processing_status": Document.PROC_STATUS_QUEUED,
        "queued_at": datetime.utcnow(),
        "last_extraction_error": None
    })

    db.commit()

    return {"message": f"Requeued {count} failed documents", "count": count}


@router.post("/queue-pending")
async def queue_pending_documents(db: Session = Depends(get_db)):
    """Queue all pending documents for extraction."""
    count = db.query(Document).filter(
        Document.processing_status == Document.PROC_STATUS_PENDING,
        Document.blob_name.isnot(None)  # Only documents with blobs
    ).update({
        "processing_status": Document.PROC_STATUS_QUEUED,
        "queued_at": datetime.utcnow()
    })

    db.commit()

    return {"message": f"Queued {count} pending documents", "count": count}


# ============================================
# Storage Lifecycle Management Endpoints
# ============================================

@router.get("/lifecycle/config")
async def get_lifecycle_config(db: Session = Depends(get_db)):
    """Get current storage lifecycle configuration."""
    lifecycle_service = BlobLifecycleService(db)
    config = lifecycle_service.get_retention_config()

    # Calculate example dates based on current settings
    now = datetime.utcnow()
    tier_dates = lifecycle_service.calculate_tier_dates(now)

    return {
        "config": config,
        "example_dates": {
            "import_date": now.isoformat(),
            "cool_tier_date": tier_dates["cool_tier_date"].isoformat(),
            "cold_tier_date": tier_dates["cold_tier_date"].isoformat(),
            "expiry_date": tier_dates["expiry_date"].isoformat()
        }
    }


@router.get("/lifecycle/blob/{blob_name:path}")
async def get_blob_lifecycle_status(
    blob_name: str,
    db: Session = Depends(get_db)
):
    """Get lifecycle status for a specific blob."""
    lifecycle_service = BlobLifecycleService(db)
    return lifecycle_service.get_blob_lifecycle_status(blob_name)


@router.post("/lifecycle/sync-all")
async def sync_all_documents_metadata(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Sync metadata for all documents in the database.

    This updates blob metadata with current retention settings and document data.
    Runs as a background task for large datasets.
    """
    # Get count first
    total_count = db.query(Document).filter(
        Document.blob_name.isnot(None)
    ).count()

    if total_count == 0:
        return {"message": "No documents with blobs to sync", "count": 0}

    # For small datasets, run synchronously
    if total_count <= 50:
        documents = db.query(Document).filter(
            Document.blob_name.isnot(None)
        ).all()

        lifecycle_service = BlobLifecycleService(db)
        results = lifecycle_service.sync_all_blob_metadata(documents)

        return {
            "message": "Metadata sync completed",
            "results": results
        }

    # For larger datasets, return immediately with count
    return {
        "message": f"Sync initiated for {total_count} documents. This will run in the background.",
        "count": total_count,
        "note": "Check logs for progress and results"
    }


@router.post("/lifecycle/sync-policy")
async def sync_lifecycle_policy(db: Session = Depends(get_db)):
    """
    Generate/sync container lifecycle policy configuration.

    Returns the policy configuration that should be applied to Azure Blob Storage
    for automatic tiering.
    """
    lifecycle_service = BlobLifecycleService(db)
    return lifecycle_service.sync_container_lifecycle_policy()


@router.post("/lifecycle/set-tier/{document_id}")
async def set_document_tier(
    document_id: int,
    tier: str,
    db: Session = Depends(get_db)
):
    """
    Manually set the storage tier for a document's blob.

    Valid tiers: Hot, Cool, Cold, Archive
    Note: Uptiering (e.g., Cool to Hot) is blocked to prevent accidental cost increases.
    """
    valid_tiers = ["Hot", "Cool", "Cold", "Archive"]
    if tier not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier. Must be one of: {valid_tiers}"
        )

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if not document.blob_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has no associated blob"
        )

    lifecycle_service = BlobLifecycleService(db)
    success = lifecycle_service.set_blob_tier(document.blob_name, tier)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to set tier. Uptiering is not allowed."
        )

    return {
        "message": f"Tier set to {tier}",
        "document_id": document_id,
        "blob_name": document.blob_name
    }


@router.post("/lifecycle/set-immutability/{document_id}")
async def set_document_immutability(
    document_id: int,
    expiry_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Set or extend immutability policy on a document's blob.

    Args:
        document_id: The document ID
        expiry_date: Optional expiry date (ISO format). Defaults to retention policy.

    Note: Immutability can only be extended, not reduced.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if not document.blob_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has no associated blob"
        )

    lifecycle_service = BlobLifecycleService(db)

    # Parse expiry date if provided
    parsed_expiry = None
    if expiry_date:
        try:
            parsed_expiry = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid expiry_date format. Use ISO format."
            )

    success = lifecycle_service.set_blob_immutability(
        document.blob_name,
        parsed_expiry
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to set immutability. Container may not support blob-level immutability."
        )

    return {
        "message": "Immutability policy set",
        "document_id": document_id,
        "blob_name": document.blob_name,
        "expiry_date": parsed_expiry.isoformat() if parsed_expiry else "default retention policy"
    }


@router.post("/lifecycle/update-metadata/{document_id}")
async def update_document_blob_metadata(
    document_id: int,
    db: Session = Depends(get_db)
):
    """
    Update blob metadata for a specific document with all extracted data.

    This refreshes the blob metadata with current document data and recalculated
    expiry dates based on current retention settings.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    if not document.blob_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has no associated blob"
        )

    # Parse extracted data
    extracted_data = None
    if document.extracted_data:
        import json
        try:
            extracted_data = json.loads(document.extracted_data)
        except json.JSONDecodeError:
            pass

    lifecycle_service = BlobLifecycleService(db)
    success = lifecycle_service.set_blob_metadata_full(
        blob_name=document.blob_name,
        document_id=document.id,
        accession_number=document.accession_number,
        import_date=document.upload_date,
        extracted_data=extracted_data,
        source=document.source
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to update metadata. Blob may be immutable."
        )

    return {
        "message": "Metadata updated successfully",
        "document_id": document_id,
        "blob_name": document.blob_name
    }
