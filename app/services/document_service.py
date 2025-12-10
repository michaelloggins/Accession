"""Document management service."""

from datetime import datetime, timedelta
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from azure.storage.blob import BlobServiceClient, generate_blob_sas, generate_container_sas, BlobSasPermissions, ContainerSasPermissions, ContentSettings
import json
import uuid
import logging
import os
import shutil
import re

from app.config import settings
from app.models.document import Document
from app.services.encryption_service import EncryptionService

logger = logging.getLogger(__name__)


def generate_standardized_filename(username: str, original_filename: str) -> str:
    """Generate standardized filename in format: User_YYYYMMDDhhmmss_filename.ext

    Args:
        username: The user's email or username
        original_filename: The original filename with extension

    Returns:
        Standardized filename string
    """
    # Extract just the username part (before @ if email)
    if "@" in username:
        user_part = username.split("@")[0]
    else:
        user_part = username

    # Sanitize username - keep alphanumeric and underscores only
    user_part = re.sub(r'[^a-zA-Z0-9_]', '_', user_part)

    # Generate timestamp in YYYYMMDDhhmmss format
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')

    # Sanitize original filename - replace spaces and special chars
    safe_original = re.sub(r'[^\w\-_.]', '_', original_filename)

    return f"{user_part}_{timestamp}_{safe_original}"


class DocumentService:
    """Service for document management operations."""

    def __init__(self, db: Session):
        self.db = db
        self.encryption_service = EncryptionService()
        self._mock_storage = None

    def _get_mock_storage(self):
        """Get mock storage service for local development."""
        if self._mock_storage is None:
            from app.services.mock_storage_service import MockStorageService
            self._mock_storage = MockStorageService()
        return self._mock_storage

    def copy_to_unc_path(self, content: bytes, filename: str, unc_path: str) -> bool:
        """Copy file content to a UNC network path.

        Args:
            content: The file content as bytes
            filename: The filename to use (should be standardized format)
            unc_path: The UNC path to copy to (e.g., \server\shareolder)

        Returns:
            True if copy was successful, False otherwise
        """
        if not unc_path:
            logger.warning("UNC path not configured, skipping UNC export")
            return False

        try:
            # Ensure the UNC path exists
            if not os.path.exists(unc_path):
                logger.error(f"UNC path does not exist or is not accessible: {unc_path}")
                return False

            # Build the full destination path
            dest_path = os.path.join(unc_path, filename)

            # Write the file
            with open(dest_path, 'wb') as f:
                f.write(content)

            logger.info(f"File copied to UNC path: {dest_path}")
            return True

        except PermissionError as e:
            logger.error(f"Permission denied writing to UNC path {unc_path}: {e}")
            return False
        except OSError as e:
            logger.error(f"OS error writing to UNC path {unc_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error copying to UNC path {unc_path}: {e}")
            return False

    def validate_file(self, file: UploadFile):
        """Validate uploaded file."""
        # Check file extension
        file_ext = "." + file.filename.split(".")[-1].lower()
        if file_ext not in settings.SUPPORTED_FILE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type. Supported: {settings.SUPPORTED_FILE_TYPES}"
            )

        # Check file size (approximate)
        # Note: In production, read file content to get exact size
        max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        # file.file.seek(0, 2)
        # size = file.file.tell()
        # file.file.seek(0)
        # if size > max_size_bytes:
        #     raise HTTPException(
        #         status_code=status.HTTP_400_BAD_REQUEST,
        #         detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE_MB}MB"
        #     )

    async def upload_to_blob(self, file: UploadFile, accession_number: str = None) -> str:
        """Upload file to Azure Blob Storage or local mock storage.

        Args:
            file: The file to upload
            accession_number: Optional accession number to add as blob metadata
        """
        # Use mock storage if Azure not configured
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            logger.info("Using mock storage (Azure not configured)")
            return await self._get_mock_storage().upload_file(file)

        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
            container_client = blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )

            # Generate blob name with date-based organization (YYYY/MM/filename)
            # Add timestamp prefix to filename to avoid collisions
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            safe_filename = f"{timestamp}_{file.filename}"
            blob_name = f"{datetime.utcnow().strftime('%Y/%m')}/{safe_filename}"

            # Upload file with metadata
            blob_client = container_client.get_blob_client(blob_name)
            content = await file.read()

            # Prepare metadata for the blob
            metadata = {
                "import_date": datetime.utcnow().isoformat(),
                "source": "upload"
            }
            if accession_number:
                metadata["accession_number"] = accession_number

            blob_client.upload_blob(content, overwrite=True, metadata=metadata)

            logger.info(f"File uploaded to blob: {blob_name} with metadata: {metadata}")
            return blob_name

        except Exception as e:
            logger.error(f"Blob upload error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload file to storage"
            )

    async def upload_bytes_to_blob(
        self,
        content: bytes,
        filename: str,
        source: str = "scanner",
        metadata: dict = None
    ) -> str:
        """Upload raw bytes to Azure Blob Storage.

        Args:
            content: The file content as bytes
            filename: The filename to use
            source: The source of the upload (default: scanner)
            metadata: Additional metadata to store with the blob

        Returns:
            The blob name/path
        """
        # Use mock storage if Azure not configured
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            logger.info("Using mock storage (Azure not configured)")
            mock_storage = self._get_mock_storage()
            # Create a simple mock upload for bytes
            blob_name = f"{datetime.utcnow().strftime('%Y/%m')}/{filename}"
            return blob_name

        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
            container_client = blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )

            # Generate blob name with date-based organization
            blob_name = f"{datetime.utcnow().strftime('%Y/%m')}/{filename}"

            # Build metadata - start with base metadata
            blob_metadata = {
                "import_date": datetime.utcnow().isoformat(),
                "source": source
            }

            # Add any additional metadata (filter out None/empty values)
            if metadata:
                for key, value in metadata.items():
                    if value is not None and value != "":
                        # Azure blob metadata keys must be valid C# identifiers
                        safe_key = key.replace("-", "_").replace(" ", "_")
                        blob_metadata[safe_key] = str(value)

            # Upload with metadata
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(content, overwrite=True, metadata=blob_metadata)

            logger.info(f"Bytes uploaded to blob: {blob_name} with metadata: {list(blob_metadata.keys())}")
            return blob_name

        except Exception as e:
            logger.error(f"Blob upload error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload file to storage"
            )

    def set_blob_metadata(self, blob_name: str, accession_number: str, import_date: datetime = None) -> bool:
        """Set metadata on an existing blob (e.g., after document creation from blob watcher).

        Args:
            blob_name: The blob name/path
            accession_number: The accession number to set
            import_date: The import date (defaults to now)

        Returns:
            True if metadata was set successfully
        """
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            logger.info("Skipping blob metadata (Azure not configured)")
            return False

        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )
            container_client = blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )
            blob_client = container_client.get_blob_client(blob_name)

            # Get existing metadata
            properties = blob_client.get_blob_properties()
            existing_metadata = properties.metadata or {}

            # Update metadata
            existing_metadata["accession_number"] = accession_number
            existing_metadata["import_date"] = (import_date or datetime.utcnow()).isoformat()

            blob_client.set_blob_metadata(existing_metadata)

            logger.info(f"Set metadata on blob {blob_name}: accession_number={accession_number}")
            return True

        except Exception as e:
            logger.error(f"Failed to set blob metadata for {blob_name}: {e}")
            return False

    def create_document(
        self,
        filename: str,
        blob_name: str,
        extracted_data: dict,
        confidence_score: float,
        source: str,
        uploaded_by: str
    ) -> Document:
        """Create a new document record."""
        # Encrypt PHI fields
        encrypted_data = self.encryption_service.encrypt_phi_fields(extracted_data)

        document = Document(
            filename=filename,
            blob_name=blob_name,
            extracted_data=json.dumps(encrypted_data),
            confidence_score=confidence_score,
            source=source,
            uploaded_by=uploaded_by,
            status="pending"
        )

        # Auto-approve if confidence is high enough
        if confidence_score >= settings.AUTO_APPROVE_THRESHOLD:
            document.status = "auto_approved"
            logger.info(f"Document {filename} auto-approved with confidence {confidence_score}")

        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        return document

    def get_document(self, document_id: int) -> Document:
        """Get a document by ID."""
        document = self.db.query(Document).filter(Document.id == document_id).first()
        if document:
            # Detach from session to prevent accidental updates
            self.db.expunge(document)

            # Decrypt PHI fields
            if document.extracted_data:
                encrypted_data = json.loads(document.extracted_data)
                document.extracted_data = self.encryption_service.decrypt_phi_fields(encrypted_data)
            if document.corrected_data:
                encrypted_corrected = json.loads(document.corrected_data)
                document.corrected_data = self.encryption_service.decrypt_phi_fields(encrypted_corrected)
        return document

    def get_pending_documents(self, skip: int = 0, limit: int = 50):
        """Get all pending documents ordered by confidence (lowest first)."""
        documents = (
            self.db.query(Document)
            .filter(Document.status == "pending")
            .order_by(Document.confidence_score.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return documents

    def count_pending_documents(self) -> int:
        """Count total pending documents."""
        return self.db.query(Document).filter(Document.status == "pending").count()

    def get_all_documents(self, skip: int = 0, limit: int = 50, status_filter: str = None, scan_station_id: int = None):
        """Get all documents with optional status and scan station filters, ordered by upload date (newest first)."""
        query = self.db.query(Document)

        if status_filter:
            query = query.filter(Document.status == status_filter)

        if scan_station_id:
            query = query.filter(Document.scan_station_id == scan_station_id)

        documents = (
            query
            .order_by(Document.upload_date.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return documents

    def count_all_documents(self, status_filter: str = None, scan_station_id: int = None) -> int:
        """Count all documents with optional status and scan station filters."""
        query = self.db.query(Document)

        if status_filter:
            query = query.filter(Document.status == status_filter)

        if scan_station_id:
            query = query.filter(Document.scan_station_id == scan_station_id)

        return query.count()

    def update_document_review(
        self,
        document_id: int,
        corrected_data: dict,
        reviewer_notes: str,
        approved: bool,
        reviewed_by: str
    ):
        """Update document with review corrections."""
        document = self.db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Encrypt corrected PHI fields
        encrypted_corrected = self.encryption_service.encrypt_phi_fields(corrected_data)

        document.corrected_data = json.dumps(encrypted_corrected)
        document.reviewer_notes = reviewer_notes
        document.reviewed_by = reviewed_by
        document.reviewed_at = datetime.utcnow()
        document.status = "approved" if approved else "reviewed"

        self.db.commit()

    def reject_document(self, document_id: int, reason: str, rejected_by: str):
        """Reject a document."""
        document = self.db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        document.status = "rejected"
        document.reviewer_notes = reason
        document.reviewed_by = rejected_by
        document.reviewed_at = datetime.utcnow()

        self.db.commit()

    def update_extraction(
        self,
        document_id: int,
        extracted_data: dict,
        confidence_score: float
    ):
        """Update document with new AI extraction results."""
        document = self.db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )

        # Encrypt PHI fields
        encrypted_data = self.encryption_service.encrypt_phi_fields(extracted_data)

        document.extracted_data = json.dumps(encrypted_data)
        document.confidence_score = confidence_score

        # Reset status to pending if it was previously reviewed/approved
        # This forces human review of the new extraction
        if document.status in ["reviewed", "approved", "auto_approved"]:
            document.status = "pending"
            # Clear previous review data since extraction has changed
            document.corrected_data = None
            document.reviewer_notes = None
            document.reviewed_by = None
            document.reviewed_at = None

        self.db.commit()

    def generate_sas_url(self, blob_name: str, inline: bool = True) -> tuple:
        """Generate time-limited SAS URL for document access.

        Args:
            blob_name: Name of the blob in storage
            inline: If True, sets Content-Disposition to inline for browser preview
        """
        # Use mock storage if Azure not configured
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            return self._get_mock_storage().generate_url(blob_name)

        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )

            expiry = datetime.utcnow() + timedelta(hours=settings.BLOB_SAS_EXPIRY_HOURS)

            # Determine content type from file extension
            ext = blob_name.lower().split('.')[-1] if '.' in blob_name else ''
            content_types = {
                'pdf': 'application/pdf',
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'tiff': 'image/tiff',
                'tif': 'image/tiff'
            }
            content_type = content_types.get(ext, 'application/octet-stream')

            # Set content disposition for inline display (prevents download)
            content_disposition = 'inline' if inline else 'attachment'

            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=settings.AZURE_STORAGE_CONTAINER,
                blob_name=blob_name,
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
                content_disposition=content_disposition,
                content_type=content_type
            )

            url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{settings.AZURE_STORAGE_CONTAINER}/{blob_name}?{sas_token}"

            return url, expiry

        except Exception as e:
            logger.error(f"SAS URL generation error: {e}")
            return None, None

    def get_training_container_sas_url(self) -> str:
        """
        Generate a SAS URL for the blob container for Document Intelligence training.

        Returns:
            Container URL with SAS token, or None if not configured
        """
        if not settings.AZURE_STORAGE_CONNECTION_STRING:
            logger.warning("Azure Storage not configured, cannot generate training SAS URL")
            return None

        try:
            blob_service_client = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )

            # Generate container SAS with read and list permissions
            # Training requires longer expiry (classifier build can take time)
            expiry = datetime.utcnow() + timedelta(hours=24)

            sas_token = generate_container_sas(
                account_name=blob_service_client.account_name,
                container_name=settings.AZURE_STORAGE_CONTAINER,
                account_key=blob_service_client.credential.account_key,
                permission=ContainerSasPermissions(read=True, list=True),
                expiry=expiry
            )

            url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{settings.AZURE_STORAGE_CONTAINER}?{sas_token}"

            logger.info(f"Generated training container SAS URL, expires: {expiry}")
            return url

        except Exception as e:
            logger.error(f"Training container SAS URL generation error: {e}")
            return None
