"""Mock storage service for local development without Azure."""

import os
import uuid
from datetime import datetime, timedelta
from fastapi import UploadFile
import logging

logger = logging.getLogger(__name__)

# Local storage directory
LOCAL_STORAGE_DIR = "uploads"


class MockStorageService:
    """Mock Azure Blob Storage for local development."""

    def __init__(self):
        # Create local uploads directory
        if not os.path.exists(LOCAL_STORAGE_DIR):
            os.makedirs(LOCAL_STORAGE_DIR)
            logger.info(f"Created local storage directory: {LOCAL_STORAGE_DIR}")

    async def upload_file(self, file: UploadFile) -> str:
        """Save file locally instead of Azure Blob Storage."""
        # Generate unique path
        date_path = datetime.utcnow().strftime('%Y/%m/%d')
        unique_id = str(uuid.uuid4())
        blob_name = f"{date_path}/{unique_id}/{file.filename}"

        # Create directory structure
        full_dir = os.path.join(LOCAL_STORAGE_DIR, date_path, unique_id)
        os.makedirs(full_dir, exist_ok=True)

        # Save file
        file_path = os.path.join(full_dir, file.filename)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        # Reset file pointer for extraction service
        await file.seek(0)

        logger.info(f"File saved locally: {file_path}")
        return blob_name

    def generate_url(self, blob_name: str) -> tuple:
        """Generate local file URL."""
        # For local dev, just return path to static file
        file_path = os.path.join(LOCAL_STORAGE_DIR, blob_name)

        # Return as file:// URL for local viewing
        abs_path = os.path.abspath(file_path)
        url = f"file:///{abs_path.replace(os.sep, '/')}"

        # Expiry time (not enforced locally)
        expires = datetime.utcnow() + timedelta(hours=1)

        return url, expires
