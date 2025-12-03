"""Blob container watcher service for detecting new documents."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import and_
from azure.storage.blob import BlobServiceClient, BlobProperties

from app.database import SessionLocal
from app.config import settings
from app.models.document import Document
from app.services.config_service import ConfigService
from app.services.document_service import DocumentService
from app.services.blob_lifecycle_service import BlobLifecycleService

# Regex to detect if blob is already in YYYY/MM/ structure
import re
ORGANIZED_PATH_PATTERN = re.compile(r'^\d{4}/\d{2}/')

logger = logging.getLogger(__name__)


class BlobWatcher:
    """Service that monitors Azure Blob Storage for new documents."""

    def __init__(self):
        self.running = False
        self._blob_service_client = None
        self._known_blobs: Set[str] = set()  # Cache of known blob names
        self._last_full_scan: Optional[datetime] = None

    @property
    def blob_service_client(self) -> Optional[BlobServiceClient]:
        """Lazy initialization of blob service client."""
        if self._blob_service_client is None and settings.AZURE_STORAGE_CONNECTION_STRING:
            try:
                self._blob_service_client = BlobServiceClient.from_connection_string(
                    settings.AZURE_STORAGE_CONNECTION_STRING
                )
            except Exception as e:
                logger.error(f"Failed to initialize blob service client: {e}")
        return self._blob_service_client

    async def start(self):
        """Start the blob watcher service."""
        if self.running:
            logger.warning("Blob watcher already running")
            return

        if not self.blob_service_client:
            logger.error("Blob watcher cannot start - storage not configured")
            return

        self.running = True
        logger.info("Blob watcher started")

        # Initial full scan to build known blobs cache
        try:
            await self._full_scan()
        except Exception as e:
            logger.error(f"Initial blob scan failed: {e}", exc_info=True)

        while self.running:
            try:
                await self._poll_for_new_blobs()
            except Exception as e:
                logger.error(f"Blob watcher error: {e}", exc_info=True)

            # Get poll interval from config
            poll_interval = 30  # Default
            try:
                db = SessionLocal()
                try:
                    config_service = ConfigService(db)
                    poll_interval = config_service.get_int("BLOB_WATCH_POLL_INTERVAL", 30)
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Could not get poll interval from config: {e}")

            await asyncio.sleep(poll_interval)

    def stop(self):
        """Stop the blob watcher service."""
        self.running = False
        logger.info("Blob watcher stopped")

    async def _full_scan(self):
        """Perform a full scan of the container to build the known blobs cache."""
        logger.info("Performing full blob container scan...")

        db = SessionLocal()
        try:
            # Get all existing blob names from database
            existing_docs = db.query(Document.blob_name).filter(
                Document.blob_name.isnot(None)
            ).all()
            self._known_blobs = {doc.blob_name for doc in existing_docs if doc.blob_name}

            logger.info(f"Loaded {len(self._known_blobs)} known blobs from database")
            self._last_full_scan = datetime.utcnow()

        except Exception as e:
            logger.error(f"Full scan failed: {e}")
        finally:
            db.close()

    async def _poll_for_new_blobs(self) -> dict:
        """Poll the blob container for new files.

        Returns:
            dict with scan statistics
        """
        result = {
            "total_blobs": 0,
            "new_blobs": 0,
            "skipped_unsupported": 0,
            "already_known": 0,
            "processed": []
        }

        if not self.blob_service_client:
            logger.warning("Blob watcher poll skipped - no blob_service_client")
            result["error"] = "No blob service client configured"
            return result

        try:
            container_name = settings.AZURE_STORAGE_CONTAINER
            logger.info(f"Polling container '{container_name}' for new blobs...")

            container_client = self.blob_service_client.get_container_client(container_name)

            # List all blobs in the container
            blobs_to_process = []

            for blob in container_client.list_blobs():
                result["total_blobs"] += 1
                blob_name = blob.name
                logger.debug(f"Checking blob: {blob_name}")

                # TESTING: Skip the in-memory cache check to force re-evaluation
                # Uncomment this block to restore normal behavior:
                # if blob_name in self._known_blobs:
                #     logger.debug(f"Blob already known: {blob_name}")
                #     result["already_known"] += 1
                #     continue

                # Check if it's a supported file type
                if not self._is_supported_file(blob_name):
                    logger.info(f"Skipping unsupported file type: {blob_name}")
                    self._known_blobs.add(blob_name)  # Add to known so we don't check again
                    result["skipped_unsupported"] += 1
                    continue

                # Check if blob already exists in database (authoritative check)
                if await self._blob_exists_in_db(blob_name):
                    logger.info(f"Blob already in database: {blob_name}")
                    self._known_blobs.add(blob_name)
                    result["already_known"] += 1
                    continue

                logger.info(f"New blob to process: {blob_name}")
                blobs_to_process.append(blob)
                result["new_blobs"] += 1
                result["processed"].append(blob_name)

            logger.info(f"Poll complete: {result['total_blobs']} total, {result['new_blobs']} new, {len(self._known_blobs)} known")

            # Process new blobs
            if blobs_to_process:
                logger.info(f"Processing {result['new_blobs']} new blobs...")
                await self._create_documents_for_blobs(blobs_to_process)
            else:
                logger.info("No new blobs to process")

            return result

        except Exception as e:
            logger.error(f"Error polling for new blobs: {e}", exc_info=True)
            result["error"] = str(e)
            return result

    def _is_supported_file(self, blob_name: str) -> bool:
        """Check if the file type is supported for processing."""
        supported_extensions = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}
        lower_name = blob_name.lower()
        return any(lower_name.endswith(ext) for ext in supported_extensions)

    async def _blob_exists_in_db(self, blob_name: str) -> bool:
        """Check if a blob already has a database record."""
        db = SessionLocal()
        try:
            exists = db.query(Document).filter(Document.blob_name == blob_name).first() is not None
            return exists
        finally:
            db.close()

    async def _create_documents_for_blobs(self, blobs: list):
        """Create document records for new blobs."""
        db = SessionLocal()
        try:
            config_service = ConfigService(db)

            # Check if auto-extraction is enabled
            auto_extract = config_service.get_bool("AUTO_EXTRACT_ENABLED", default=True)

            for blob in blobs:
                try:
                    # Extract filename from blob path
                    # Blob names are like: 2024/11/26/{uuid}/filename.pdf
                    blob_name = blob.name
                    filename = blob_name.split('/')[-1] if '/' in blob_name else blob_name

                    # Determine source based on blob path or metadata
                    source = self._determine_source(blob)

                    # Set status based on auto-extract setting
                    if auto_extract:
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
                        source=source,
                        uploaded_by="blob_watcher",  # System user
                        processing_status=processing_status,
                        status=doc_status,
                        queued_at=queued_at,
                        extraction_attempts=0
                    )

                    db.add(document)
                    db.commit()
                    db.refresh(document)

                    # Set blob metadata with document info, lifecycle dates, and retention info
                    # This includes calculated tier transition and expiry dates
                    # Full metadata (facility, patient, etc.) will be added after extraction
                    try:
                        lifecycle_service = BlobLifecycleService(db)
                        lifecycle_service.set_blob_metadata_full(
                            blob_name=blob_name,
                            document_id=document.id,
                            accession_number=document.accession_number,
                            import_date=document.upload_date,
                            extracted_data=None,  # Not extracted yet
                            source=source
                        )
                    except Exception as meta_err:
                        logger.warning(f"Failed to set blob metadata for {blob_name}: {meta_err}")

                    # Add to known blobs cache
                    self._known_blobs.add(blob_name)

                    logger.info(f"Created document {document.id} (accession: {document.accession_number}) for blob: {blob_name}")

                except Exception as e:
                    logger.error(f"Failed to create document for blob {blob.name}: {e}")
                    db.rollback()

        finally:
            db.close()

    def _determine_source(self, blob: BlobProperties) -> str:
        """Determine the source of the document based on blob metadata or path."""
        blob_name = blob.name.lower()

        # Check path prefixes for source hints
        if '/email/' in blob_name or blob_name.startswith('email/'):
            return 'email'
        elif '/fax/' in blob_name or blob_name.startswith('fax/'):
            return 'fax'
        elif '/scan/' in blob_name or blob_name.startswith('scan/'):
            return 'scanner'
        elif '/api/' in blob_name or blob_name.startswith('api/'):
            return 'api'

        # Check blob metadata if available
        if hasattr(blob, 'metadata') and blob.metadata:
            source = blob.metadata.get('source')
            if source:
                return source

        # Default source
        return 'blob_upload'

    def _is_blob_in_organized_path(self, blob_name: str) -> bool:
        """Check if blob is already in YYYY/MM/ organized path structure."""
        return bool(ORGANIZED_PATH_PATTERN.match(blob_name))


# Global watcher instance
_watcher_instance: Optional[BlobWatcher] = None
_watcher_task: Optional[asyncio.Task] = None


async def start_blob_watcher():
    """Start the global blob watcher."""
    global _watcher_instance, _watcher_task

    if _watcher_instance is None:
        _watcher_instance = BlobWatcher()

    if _watcher_task is None or _watcher_task.done():
        _watcher_task = asyncio.create_task(_watcher_instance.start())
        logger.info("Blob watcher task started")


def stop_blob_watcher():
    """Stop the global blob watcher."""
    global _watcher_instance, _watcher_task

    if _watcher_instance:
        _watcher_instance.stop()

    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()

    logger.info("Blob watcher task stopped")


def get_blob_watcher_instance() -> Optional[BlobWatcher]:
    """Get the current blob watcher instance."""
    global _watcher_instance
    return _watcher_instance


def get_blob_watcher_status() -> dict:
    """Get the status of the blob watcher."""
    global _watcher_instance

    if _watcher_instance is None:
        return {
            "running": False,
            "status": "not_started",
            "known_blobs": 0,
            "last_full_scan": None
        }

    return {
        "running": _watcher_instance.running,
        "status": "running" if _watcher_instance.running else "stopped",
        "known_blobs": len(_watcher_instance._known_blobs),
        "last_full_scan": _watcher_instance._last_full_scan.isoformat() if _watcher_instance._last_full_scan else None
    }
