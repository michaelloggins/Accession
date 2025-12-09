"""Background worker for processing document extraction queue.

Extraction Flow:
1. If document type has Form Recognizer model configured and use_form_recognizer=True:
   - Try Form Recognizer extraction first
   - If confidence < threshold, fallback to Azure OpenAI
2. Otherwise, use Azure OpenAI directly

Training Flow (when learning_mode=True):
- After extraction, analyze document with GPT-4 Vision to learn patterns
- Store training data for future Form Recognizer model training
"""

import asyncio
import logging
import uuid
import json
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from azure.storage.blob import BlobServiceClient

from app.database import SessionLocal
from app.config import settings
from app.models.document import Document
from app.models.extraction_batch import ExtractionBatch
from app.models.training_data import DocumentType
from app.services.config_service import ConfigService
from app.services.azure_openai_service import AzureOpenAIExtractionService
from app.services.form_recognizer_service import get_form_recognizer_service
from app.services.encryption_service import EncryptionService
from app.services.blob_lifecycle_service import BlobLifecycleService

logger = logging.getLogger(__name__)


class ExtractionWorker:
    """Background worker that processes the document extraction queue."""

    def __init__(self):
        self.running = False
        self.extraction_service = None  # Azure OpenAI service
        self.form_recognizer_service = None  # Form Recognizer service
        self.encryption_service = EncryptionService()
        self._blob_service_client = None

    @property
    def blob_service_client(self):
        """Lazy initialization of blob service client."""
        if self._blob_service_client is None and settings.AZURE_STORAGE_CONNECTION_STRING:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
        return self._blob_service_client

    async def start(self):
        """Start the background worker."""
        if self.running:
            logger.warning("Extraction worker already running")
            return

        self.running = True
        logger.info("Extraction worker started")

        while self.running:
            try:
                await self._process_cycle()
            except Exception as e:
                logger.error(f"Extraction worker error: {e}", exc_info=True)

            # Get poll interval from config
            poll_interval = 10  # Default
            try:
                db = SessionLocal()
                try:
                    config_service = ConfigService(db)
                    poll_interval = config_service.get_int("EXTRACTION_POLL_INTERVAL", 10)
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Could not get poll interval from config: {e}")

            await asyncio.sleep(poll_interval)

    def stop(self):
        """Stop the background worker."""
        self.running = False
        logger.info("Extraction worker stopped")

    async def _process_cycle(self):
        """Process one cycle of the extraction queue."""
        db = SessionLocal()
        try:
            config_service = ConfigService(db)

            # Get configuration
            batch_size = config_service.get_int("EXTRACTION_BATCH_SIZE", 5)
            max_retries = config_service.get_int("EXTRACTION_MAX_RETRIES", 3)
            auto_approve_threshold = config_service.get_float("AUTO_APPROVE_THRESHOLD", 0.90)

            # Get Azure OpenAI config and create/update extraction service
            temperature = config_service.get_float("AZURE_OPENAI_TEMPERATURE", 0.1)
            max_tokens = config_service.get_int("AZURE_OPENAI_MAX_TOKENS", 2000)
            max_tokens_batch = config_service.get_int("AZURE_OPENAI_MAX_TOKENS_BATCH", 4000)
            default_confidence = config_service.get_float("DEFAULT_CONFIDENCE_SCORE", 0.85)

            self.extraction_service = AzureOpenAIExtractionService(
                temperature=temperature,
                max_tokens=max_tokens,
                max_tokens_batch=max_tokens_batch,
                default_confidence=default_confidence
            )

            # Initialize Form Recognizer service
            self.form_recognizer_service = get_form_recognizer_service()

            # Get AI service config for learning mode
            ai_config = self._get_ai_service_config(config_service)
            learning_mode = ai_config.get("learning_mode", False)

            # Query for queued documents
            queued_docs = (
                db.query(Document)
                .filter(
                    and_(
                        Document.processing_status == Document.PROC_STATUS_QUEUED,
                        Document.extraction_attempts < max_retries
                    )
                )
                .order_by(Document.queued_at.asc())
                .limit(batch_size)
                .all()
            )

            if not queued_docs:
                return  # Nothing to process

            logger.info(f"Processing {len(queued_docs)} queued documents")

            # Create batch record
            batch_id = str(uuid.uuid4())
            batch = ExtractionBatch(
                id=batch_id,
                status=ExtractionBatch.STATUS_PROCESSING,
                document_count=len(queued_docs),
                created_at=datetime.utcnow(),
                started_at=datetime.utcnow()
            )
            db.add(batch)

            # Update documents to processing status
            for doc in queued_docs:
                doc.processing_status = Document.PROC_STATUS_PROCESSING
                doc.batch_id = batch_id
                doc.extraction_started_at = datetime.utcnow()
                doc.extraction_attempts += 1

            db.commit()

            # Download document content from blob storage
            documents_data = []
            for doc in queued_docs:
                try:
                    content = await self._download_blob(doc.blob_name)
                    documents_data.append({
                        'id': doc.id,
                        'content': content,
                        'filename': doc.filename
                    })
                except Exception as e:
                    logger.error(f"Failed to download blob for document {doc.id}: {e}")
                    doc.processing_status = Document.PROC_STATUS_FAILED
                    doc.last_extraction_error = f"Blob download failed: {str(e)}"
                    batch.failed_count += 1

            db.commit()

            if not documents_data:
                batch.status = ExtractionBatch.STATUS_FAILED
                batch.error_message = "No documents could be downloaded from blob storage"
                batch.completed_at = datetime.utcnow()
                db.commit()
                return

            # Perform extraction with Form Recognizer -> OpenAI fallback
            try:
                results = await self._extract_with_fallback(
                    db, documents_data, queued_docs, learning_mode
                )

                # Process results
                successful = 0
                failed = 0

                for result in results:
                    doc = db.query(Document).filter(Document.id == result['document_id']).first()
                    if not doc:
                        continue

                    if result['error']:
                        doc.processing_status = Document.PROC_STATUS_FAILED
                        doc.last_extraction_error = result['error']
                        failed += 1
                    else:
                        # Encrypt PHI fields
                        encrypted_data = self.encryption_service.encrypt_phi_fields(
                            result['extracted_data']
                        )

                        doc.extracted_data = json.dumps(encrypted_data)
                        doc.confidence_score = result['confidence_score']
                        doc.processing_status = Document.PROC_STATUS_EXTRACTED
                        doc.extraction_completed_at = datetime.utcnow()
                        doc.last_extraction_error = None
                        doc.extraction_method = result.get('extraction_method', 'openai')

                        # Set review status based on confidence
                        if result['confidence_score'] >= auto_approve_threshold:
                            doc.status = "auto_approved"
                        else:
                            doc.status = "pending"

                        successful += 1

                        # Update document type statistics if available
                        if result.get('document_type_id'):
                            self._update_document_type_stats(
                                db,
                                result['document_type_id'],
                                result.get('extraction_method', 'openai'),
                                result.get('was_fallback', False)
                            )

                        # Update blob: rename to standard format, set metadata, and apply immutability
                        if doc.blob_name:
                            try:
                                lifecycle_service = BlobLifecycleService(db)

                                # Generate standardized blob name: YYYY-MM-DD_ACCESSION.ext
                                new_blob_name = lifecycle_service.generate_standard_blob_name(
                                    accession_number=doc.accession_number,
                                    upload_date=doc.upload_date,
                                    original_filename=doc.filename
                                )

                                # Rename blob if name is different
                                current_blob_name = doc.blob_name
                                if new_blob_name != current_blob_name:
                                    rename_result = lifecycle_service.rename_blob(
                                        old_blob_name=current_blob_name,
                                        new_blob_name=new_blob_name,
                                        delete_original=True
                                    )

                                    if rename_result["success"]:
                                        # Update document with new blob name
                                        doc.blob_name = new_blob_name
                                        logger.info(
                                            f"Renamed blob for document {doc.id}: "
                                            f"{current_blob_name} -> {new_blob_name}"
                                        )
                                    else:
                                        logger.warning(
                                            f"Could not rename blob for document {doc.id}: "
                                            f"{rename_result.get('error')}"
                                        )
                                        # Continue with original blob name
                                        new_blob_name = current_blob_name

                                # Set comprehensive metadata including all extracted fields
                                lifecycle_service.set_blob_metadata_full(
                                    blob_name=doc.blob_name,
                                    document_id=doc.id,
                                    accession_number=doc.accession_number,
                                    import_date=doc.upload_date,
                                    extracted_data=result['extracted_data'],  # Use unencrypted for metadata
                                    source=doc.source
                                )

                                # Set immutability policy after metadata is set
                                lifecycle_service.set_blob_immutability(doc.blob_name)

                                logger.info(f"Set blob lifecycle for document {doc.id}")
                            except Exception as lifecycle_error:
                                logger.warning(
                                    f"Failed to set blob lifecycle for document {doc.id}: {lifecycle_error}"
                                )

                batch.successful_count = successful
                batch.failed_count = failed
                batch.status = ExtractionBatch.STATUS_COMPLETED if failed == 0 else ExtractionBatch.STATUS_FAILED
                batch.completed_at = datetime.utcnow()

                db.commit()

                logger.info(f"Batch {batch_id} completed: {successful} successful, {failed} failed")

                # If batch failed and has retries remaining, check if we should split
                if failed > 0 and len(queued_docs) > 1:
                    await self._handle_batch_failure(db, batch, config_service)

            except Exception as e:
                logger.error(f"Batch extraction failed: {e}")
                batch.status = ExtractionBatch.STATUS_FAILED
                batch.error_message = str(e)
                batch.completed_at = datetime.utcnow()

                # Mark all documents in batch as failed
                for doc in queued_docs:
                    if doc.processing_status == Document.PROC_STATUS_PROCESSING:
                        doc.processing_status = Document.PROC_STATUS_FAILED
                        doc.last_extraction_error = f"Batch extraction failed: {str(e)}"

                db.commit()

                # Handle batch failure (retry/split)
                await self._handle_batch_failure(db, batch, config_service)

        finally:
            db.close()

    async def _download_blob(self, blob_name: str) -> bytes:
        """Download document content from Azure Blob Storage."""
        if not self.blob_service_client:
            raise Exception("Blob storage not configured")

        container_client = self.blob_service_client.get_container_client(
            settings.AZURE_STORAGE_CONTAINER
        )
        blob_client = container_client.get_blob_client(blob_name)

        download = blob_client.download_blob()
        return download.readall()

    async def _handle_batch_failure(self, db: Session, batch: ExtractionBatch, config_service: ConfigService):
        """Handle a failed batch - split into individual documents if max retries exceeded."""
        max_retries = config_service.get_int("EXTRACTION_MAX_RETRIES", 3)

        # Get failed documents from this batch
        failed_docs = (
            db.query(Document)
            .filter(
                and_(
                    Document.batch_id == batch.id,
                    Document.processing_status == Document.PROC_STATUS_FAILED
                )
            )
            .all()
        )

        if not failed_docs:
            return

        # Check if any documents still have retries remaining
        docs_with_retries = [d for d in failed_docs if d.extraction_attempts < max_retries]

        if docs_with_retries:
            # Re-queue documents for retry
            for doc in docs_with_retries:
                doc.processing_status = Document.PROC_STATUS_QUEUED
                doc.batch_id = None  # Will be assigned to new batch
                logger.info(f"Re-queued document {doc.id} for retry (attempt {doc.extraction_attempts + 1})")
        else:
            # Max retries exceeded - split batch into individual documents
            if batch.document_count > 1:
                logger.info(f"Splitting batch {batch.id} into individual documents")
                batch.status = ExtractionBatch.STATUS_SPLIT

                for doc in failed_docs:
                    # Reset attempts and re-queue as individual
                    doc.extraction_attempts = 0
                    doc.processing_status = Document.PROC_STATUS_QUEUED
                    doc.batch_id = None
                    doc.last_extraction_error = f"Split from failed batch {batch.id}"
                    logger.info(f"Document {doc.id} split from batch, will process individually")

        db.commit()

    async def _extract_with_fallback(
        self,
        db: Session,
        documents_data: List[Dict],
        queued_docs: List[Document],
        learning_mode: bool
    ) -> List[Dict]:
        """
        Extract documents using Form Recognizer with OpenAI fallback.

        Flow:
        1. Check if document has a known type with Form Recognizer model
        2. If yes and FR enabled for that type: try FR first
        3. If FR confidence < threshold or FR fails: fallback to OpenAI
        4. If learning mode: also run training analysis
        """
        results = []

        # Build a map of document IDs to their data
        doc_data_map = {d['id']: d for d in documents_data}

        # Get document types that have FR models configured
        doc_types_with_fr = self._get_document_types_with_fr(db)

        # Process each document
        for doc in queued_docs:
            doc_data = doc_data_map.get(doc.id)
            if not doc_data:
                results.append({
                    'document_id': doc.id,
                    'extracted_data': None,
                    'confidence_score': None,
                    'error': 'Document data not found'
                })
                continue

            try:
                result = await self._extract_single_document(
                    db, doc, doc_data, doc_types_with_fr, learning_mode
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Extraction error for document {doc.id}: {e}")
                results.append({
                    'document_id': doc.id,
                    'extracted_data': None,
                    'confidence_score': None,
                    'error': str(e)
                })

        return results

    async def _extract_single_document(
        self,
        db: Session,
        doc: Document,
        doc_data: Dict,
        doc_types_with_fr: Dict[str, DocumentType],
        learning_mode: bool
    ) -> Dict:
        """Extract a single document with FR -> OpenAI fallback logic."""
        document_id = doc.id
        content = doc_data['content']
        filename = doc_data['filename']

        extraction_method = 'openai'
        was_fallback = False
        document_type_id = None

        # Check if document has a known type with FR model
        doc_type = None
        if doc.document_type and doc.document_type in doc_types_with_fr:
            doc_type = doc_types_with_fr[doc.document_type]
            document_type_id = doc_type.id

        # Determine extraction strategy
        use_fr_first = (
            doc_type is not None and
            doc_type.use_form_recognizer and
            doc_type.form_recognizer_model_id and
            self.form_recognizer_service and
            self.form_recognizer_service.is_configured
        )

        extracted_data = None
        confidence_score = 0.0
        error = None

        if use_fr_first:
            # Try Form Recognizer first
            logger.info(f"Document {document_id}: Trying Form Recognizer model {doc_type.form_recognizer_model_id}")
            extraction_method = 'form_recognizer'

            fr_data, fr_confidence, fr_error = await self.form_recognizer_service.extract_with_model(
                model_id=doc_type.form_recognizer_model_id,
                document_bytes=content,
                filename=filename
            )

            if fr_error:
                logger.warning(f"Document {document_id}: Form Recognizer error: {fr_error}")
                # Fall back to OpenAI
                was_fallback = True
            elif fr_confidence < doc_type.fr_confidence_threshold:
                logger.info(
                    f"Document {document_id}: FR confidence {fr_confidence:.2f} < "
                    f"threshold {doc_type.fr_confidence_threshold:.2f}, falling back to OpenAI"
                )
                was_fallback = True
            else:
                # FR succeeded with good confidence
                extracted_data = fr_data
                confidence_score = fr_confidence
                logger.info(f"Document {document_id}: Form Recognizer extraction succeeded (confidence: {fr_confidence:.2f})")

        # Use OpenAI if FR not configured, failed, or confidence too low
        if extracted_data is None:
            if was_fallback:
                extraction_method = 'openai_fallback'
            else:
                extraction_method = 'openai'

            logger.info(f"Document {document_id}: Using Azure OpenAI extraction")

            try:
                # Use the batch extraction for single document
                openai_results = await self.extraction_service.extract_batch([doc_data])
                if openai_results and len(openai_results) > 0:
                    openai_result = openai_results[0]
                    if openai_result.get('error'):
                        error = openai_result['error']
                    else:
                        extracted_data = openai_result['extracted_data']
                        confidence_score = openai_result['confidence_score']
                else:
                    error = "OpenAI extraction returned no results"
            except Exception as e:
                error = f"OpenAI extraction failed: {str(e)}"

        # If learning mode is enabled and we have data, run training analysis
        if learning_mode and extracted_data and not error:
            await self._run_training_analysis(db, doc, content, extracted_data)

        return {
            'document_id': document_id,
            'extracted_data': extracted_data,
            'confidence_score': confidence_score,
            'error': error,
            'extraction_method': extraction_method,
            'was_fallback': was_fallback,
            'document_type_id': document_type_id
        }

    def _get_document_types_with_fr(self, db: Session) -> Dict[str, DocumentType]:
        """Get document types that have Form Recognizer models configured."""
        try:
            doc_types = db.query(DocumentType).filter(
                DocumentType.is_active == True,
                DocumentType.use_form_recognizer == True,
                DocumentType.form_recognizer_model_id != None
            ).all()

            return {dt.name: dt for dt in doc_types}
        except Exception as e:
            logger.warning(f"Error loading document types: {e}")
            return {}

    def _get_ai_service_config(self, config_service: ConfigService) -> Dict:
        """Get AI service configuration."""
        try:
            config_str = config_service.get("AI_SERVICE_CONFIG", "{}")
            if isinstance(config_str, str):
                return json.loads(config_str)
            return config_str or {}
        except Exception as e:
            logger.warning(f"Error loading AI service config: {e}")
            return {}

    def _update_document_type_stats(
        self,
        db: Session,
        document_type_id: int,
        extraction_method: str,
        was_fallback: bool
    ):
        """Update extraction statistics for a document type."""
        try:
            doc_type = db.query(DocumentType).filter(DocumentType.id == document_type_id).first()
            if doc_type:
                if extraction_method == 'form_recognizer':
                    doc_type.fr_extraction_count = (doc_type.fr_extraction_count or 0) + 1
                elif extraction_method in ('openai', 'openai_fallback'):
                    doc_type.openai_extraction_count = (doc_type.openai_extraction_count or 0) + 1
                    if was_fallback:
                        doc_type.openai_fallback_count = (doc_type.openai_fallback_count or 0) + 1
        except Exception as e:
            logger.warning(f"Error updating document type stats: {e}")

    async def _run_training_analysis(
        self,
        db: Session,
        doc: Document,
        content: bytes,
        extracted_data: Dict
    ):
        """Run training analysis on a document when learning mode is enabled."""
        try:
            from app.services.training_service import TrainingService

            training_service = TrainingService(db)
            if training_service.is_configured:
                # Check if this document type has training enabled
                if doc.document_type:
                    doc_type = db.query(DocumentType).filter(
                        DocumentType.name == doc.document_type,
                        DocumentType.is_active == True
                    ).first()

                    # Skip if training is disabled for this type
                    if doc_type and not doc_type.training_enabled:
                        logger.debug(f"Training disabled for document type: {doc.document_type}")
                        return

                logger.info(f"Running training analysis for document {doc.id}")
                await training_service.analyze_document(
                    image_bytes=content,
                    document_id=doc.id,
                    blob_name=doc.blob_name,
                    user_email="system"
                )
        except Exception as e:
            logger.warning(f"Training analysis failed for document {doc.id}: {e}")


# Global worker instance
_worker_instance: Optional[ExtractionWorker] = None
_worker_task: Optional[asyncio.Task] = None


async def start_extraction_worker():
    """Start the global extraction worker."""
    global _worker_instance, _worker_task

    if _worker_instance is None:
        _worker_instance = ExtractionWorker()

    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_instance.start())
        logger.info("Extraction worker task started")


def stop_extraction_worker():
    """Stop the global extraction worker."""
    global _worker_instance, _worker_task

    if _worker_instance:
        _worker_instance.stop()

    if _worker_task and not _worker_task.done():
        _worker_task.cancel()

    logger.info("Extraction worker task stopped")


def get_worker_status() -> dict:
    """Get the status of the extraction worker."""
    global _worker_instance

    if _worker_instance is None:
        return {"running": False, "status": "not_started"}

    return {
        "running": _worker_instance.running,
        "status": "running" if _worker_instance.running else "stopped"
    }


def get_extraction_worker_status() -> dict:
    """Get detailed status of the extraction worker."""
    global _worker_instance

    if _worker_instance is None:
        return {
            "running": False,
            "status": "not_started",
            "current_batch_id": None,
            "last_cycle": None
        }

    return {
        "running": _worker_instance.running,
        "status": "running" if _worker_instance.running else "stopped",
        "current_batch_id": getattr(_worker_instance, '_current_batch_id', None),
        "last_cycle": getattr(_worker_instance, '_last_cycle', None)
    }


async def trigger_extraction_cycle():
    """Trigger an immediate extraction processing cycle."""
    global _worker_instance

    if _worker_instance is None or not _worker_instance.running:
        raise Exception("Extraction worker is not running")

    # Call the process cycle method directly
    await _worker_instance._process_cycle()
