"""Background task processing for long-running operations."""

import logging
import asyncio
from typing import Dict, List
from datetime import datetime
from sqlalchemy.orm import Session
import threading
import json
from pathlib import Path

from app.services.document_service import DocumentService
from app.services.extraction_factory import get_extraction_service
from app.services.audit_service import AuditService
from app.services.config_service import ConfigService
from app.services.training_service import TrainingService
from app.models.training_data import DocumentType

logger = logging.getLogger(__name__)

# Thread-safe in-memory store for job status with file persistence
_job_store_lock = threading.Lock()
_job_store_file = Path("jobs_store.json")
job_status_store: Dict[str, dict] = {}

# Load existing jobs from file on startup
def _load_jobs_from_file():
    """Load jobs from persistent storage."""
    global job_status_store
    if _job_store_file.exists():
        try:
            with open(_job_store_file, 'r') as f:
                job_status_store = json.load(f)
            logger.info(f"Loaded {len(job_status_store)} jobs from persistent storage")
        except Exception as e:
            logger.error(f"Failed to load jobs from file: {e}")
            job_status_store = {}
    else:
        job_status_store = {}

def _save_jobs_to_file():
    """Save jobs to persistent storage."""
    try:
        with open(_job_store_file, 'w') as f:
            json.dump(job_status_store, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save jobs to file: {e}")

# Initialize job store on module load
_load_jobs_from_file()


class BackgroundTaskManager:
    """Manages background task execution and status tracking."""

    @staticmethod
    def create_job(job_id: str, total_files: int) -> None:
        """Create a new job in the status store."""
        with _job_store_lock:
            job_status_store[job_id] = {
                'job_id': job_id,
                'status': 'processing',
                'total_files': total_files,
                'processed_files': 0,
                'successful_files': 0,
                'failed_files': 0,
                'results': [],
                'started_at': datetime.now().isoformat(),
                'completed_at': None,
                'error': None,
                'cancelled': False
            }
            _save_jobs_to_file()

    @staticmethod
    def get_job_status(job_id: str) -> dict:
        """Get the current status of a job."""
        with _job_store_lock:
            return job_status_store.get(job_id, {'status': 'not_found'})

    @staticmethod
    def get_all_jobs() -> List[dict]:
        """Get all jobs."""
        with _job_store_lock:
            return list(job_status_store.values())

    @staticmethod
    def update_job_progress(job_id: str, processed: int, successful: int, failed: int) -> None:
        """Update job progress."""
        with _job_store_lock:
            if job_id in job_status_store:
                job_status_store[job_id]['processed_files'] = processed
                job_status_store[job_id]['successful_files'] = successful
                job_status_store[job_id]['failed_files'] = failed
                _save_jobs_to_file()

    @staticmethod
    def complete_job(job_id: str) -> None:
        """Mark job as completed."""
        with _job_store_lock:
            if job_id in job_status_store:
                job_status_store[job_id]['status'] = 'completed'
                job_status_store[job_id]['completed_at'] = datetime.now().isoformat()
                _save_jobs_to_file()

    @staticmethod
    def fail_job(job_id: str, error: str) -> None:
        """Mark job as failed."""
        with _job_store_lock:
            if job_id in job_status_store:
                job_status_store[job_id]['status'] = 'failed'
                job_status_store[job_id]['error'] = error
                job_status_store[job_id]['completed_at'] = datetime.now().isoformat()
                _save_jobs_to_file()

    @staticmethod
    def cancel_job(job_id: str) -> bool:
        """Cancel a job."""
        with _job_store_lock:
            if job_id in job_status_store:
                job = job_status_store[job_id]
                if job['status'] in ['processing', 'queued']:
                    job_status_store[job_id]['status'] = 'cancelled'
                    job_status_store[job_id]['cancelled'] = True
                    job_status_store[job_id]['completed_at'] = datetime.now().isoformat()
                    _save_jobs_to_file()
                    return True
            return False

    @staticmethod
    def delete_job(job_id: str) -> bool:
        """Delete a job from the store."""
        with _job_store_lock:
            if job_id in job_status_store:
                del job_status_store[job_id]
                _save_jobs_to_file()
                return True
            return False

    @staticmethod
    def get_job_for_retry(job_id: str) -> dict:
        """Get job data for retry (only failed files)."""
        with _job_store_lock:
            if job_id not in job_status_store:
                return None

            job = job_status_store[job_id]
            if job['status'] not in ['failed', 'cancelled']:
                return None

            # Extract failed files from results
            failed_files = []
            for result in job.get('results', []):
                if result.get('status') == 'failed':
                    # Note: We don't have the original file content stored
                    # This is a limitation of the in-memory approach
                    # In production, you'd want to store files temporarily or use a queue system
                    failed_files.append({
                        'filename': result['filename'],
                        'content': b'',  # Placeholder - needs actual file content
                        'content_type': 'application/pdf'
                    })

            return {
                'failed_files': failed_files,
                'source': job.get('source', 'upload'),
                'uploaded_by': job.get('uploaded_by', 'current_user')
            }

    @staticmethod
    def add_result(job_id: str, result: dict) -> None:
        """Add a file processing result to the job."""
        with _job_store_lock:
            if job_id in job_status_store:
                job_status_store[job_id]['results'].append(result)
                _save_jobs_to_file()


# Default concurrency for parallel file processing
DEFAULT_CONCURRENT_UPLOADS = 3


async def process_bulk_upload(
    job_id: str,
    files_data: List[dict],
    source: str,
    uploaded_by: str,
    db_url: str
) -> None:
    """
    Process multiple files in the background with concurrent processing.

    Args:
        job_id: Unique identifier for this job
        files_data: List of dicts containing file data (filename, content, content_type)
        source: Upload source (upload, email, fax, etc.)
        uploaded_by: User ID
        db_url: Database connection URL
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    logger.info(f"Starting background job {job_id} with {len(files_data)} files (concurrent processing)")

    BackgroundTaskManager.create_job(job_id, len(files_data))

    # Shared counters with lock for thread safety
    progress_lock = threading.Lock()
    progress = {'processed': 0, 'successful': 0, 'failed': 0}

    try:
        # Create new database session for background task
        engine = create_engine(db_url)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        # Get concurrency limit from config (default 3)
        db = SessionLocal()
        config_service = ConfigService(db)
        concurrent_limit = config_service.get_int("CONCURRENT_UPLOAD_LIMIT", DEFAULT_CONCURRENT_UPLOADS)
        db.close()

        # Semaphore to limit concurrent Azure OpenAI calls
        semaphore = asyncio.Semaphore(concurrent_limit)

        async def process_single_file(file_data: dict, index: int) -> None:
            """Process a single file with semaphore limiting."""
            # Check if job was cancelled before starting
            with _job_store_lock:
                cancelled = job_status_store.get(job_id, {}).get('cancelled', False)
            if cancelled:
                return

            async with semaphore:
                # Check again after acquiring semaphore
                with _job_store_lock:
                    cancelled = job_status_store.get(job_id, {}).get('cancelled', False)
                if cancelled:
                    return

                # Each task gets its own DB session
                db = SessionLocal()
                try:
                    doc_service = DocumentService(db)
                    extraction_service = get_extraction_service()
                    audit_service = AuditService(db)
                    training_service = TrainingService(db)

                    filename = file_data['filename']
                    content = file_data['content']
                    content_type = file_data['content_type']

                    logger.info(f"Processing file {index + 1}/{len(files_data)}: {filename}")

                    # Create mock upload file object
                    from io import BytesIO
                    from fastapi import UploadFile
                    from starlette.datastructures import Headers

                    headers = Headers({'content-type': content_type})
                    file_obj = UploadFile(
                        filename=filename,
                        file=BytesIO(content),
                        size=len(content),
                        headers=headers
                    )

                    # Validate file
                    doc_service.validate_file(file_obj)

                    # Upload to blob storage
                    file_obj.file.seek(0)
                    blob_name = await doc_service.upload_to_blob(file_obj, user_email=uploaded_by)

                    # Extract data using Azure OpenAI
                    file_obj.file.seek(0)
                    extracted_data, confidence_score = await extraction_service.extract_data(file_obj)

                    # Save document record
                    document = doc_service.create_document(
                        filename=filename,
                        blob_name=blob_name,
                        extracted_data=extracted_data,
                        confidence_score=confidence_score,
                        source=source,
                        uploaded_by=uploaded_by
                    )

                    # Log upload action
                    audit_service.log_action(
                        user_id=uploaded_by,
                        user_email="background@system.local",
                        action="CREATE",
                        resource_type="DOCUMENT",
                        resource_id=str(document.id),
                        success=True
                    )

                    # Run training analysis (check per-type training_enabled)
                    if training_service and training_service.is_configured:
                        try:
                            should_train = True
                            if document.document_type:
                                doc_type = db.query(DocumentType).filter(
                                    DocumentType.name == document.document_type,
                                    DocumentType.is_active == True
                                ).first()
                                if doc_type and not doc_type.training_enabled:
                                    should_train = False
                                    logger.debug(f"Training disabled for type: {document.document_type}")

                            if should_train:
                                logger.info(f"Running training analysis for document {document.id}")
                                await training_service.analyze_document(
                                    image_bytes=content,
                                    document_id=document.id,
                                    blob_name=blob_name,
                                    user_email=uploaded_by
                                )
                        except Exception as train_error:
                            logger.warning(f"Training analysis failed for document {document.id}: {train_error}")

                    # Update progress
                    with progress_lock:
                        progress['processed'] += 1
                        progress['successful'] += 1
                        BackgroundTaskManager.update_job_progress(
                            job_id, progress['processed'], progress['successful'], progress['failed']
                        )

                    BackgroundTaskManager.add_result(job_id, {
                        'filename': filename,
                        'status': 'success',
                        'document_id': document.id,
                        'accession_number': document.accession_number,
                        'confidence_score': float(confidence_score) if confidence_score else None
                    })

                except Exception as e:
                    logger.error(f"Failed to process file {file_data['filename']}: {e}")
                    with progress_lock:
                        progress['processed'] += 1
                        progress['failed'] += 1
                        BackgroundTaskManager.update_job_progress(
                            job_id, progress['processed'], progress['successful'], progress['failed']
                        )

                    BackgroundTaskManager.add_result(job_id, {
                        'filename': file_data['filename'],
                        'status': 'failed',
                        'error': str(e)
                })

            processed += 1
            BackgroundTaskManager.update_job_progress(job_id, processed, successful, failed)

            # Small delay between files to keep server responsive
            if processed < len(files_data):
                await asyncio.sleep(0.1)

        BackgroundTaskManager.complete_job(job_id)
        db.close()

        logger.info(f"Job {job_id} completed: {successful} successful, {failed} failed")

    except Exception as e:
        logger.error(f"Job {job_id} failed with error: {e}")
        BackgroundTaskManager.fail_job(job_id, str(e))
