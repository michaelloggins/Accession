"""Lab system integration service."""

import httpx
import asyncio
import logging
from datetime import datetime

from app.config import settings
from app.schemas.document import LabSubmissionResult

logger = logging.getLogger(__name__)


class LabIntegrationService:
    """Service for integrating with lab information systems."""

    def __init__(self):
        self.api_url = settings.LAB_SYSTEM_API_URL
        self.api_key = settings.LAB_SYSTEM_API_KEY

    async def submit_to_lab(self, document_id: int, data: dict) -> LabSubmissionResult:
        """Submit approved document data to lab system."""
        # Transform data to lab system format
        lab_data = self._transform_to_lab_format(data)

        # Submit with retry logic
        for attempt in range(settings.LAB_SUBMISSION_RETRIES):
            try:
                result = await self._send_to_lab(lab_data)

                logger.info(
                    f"Document {document_id} submitted to lab successfully. "
                    f"Confirmation: {result['confirmation_id']}"
                )

                return LabSubmissionResult(
                    submitted=True,
                    confirmation_id=result["confirmation_id"]
                )

            except Exception as e:
                if attempt < settings.LAB_SUBMISSION_RETRIES - 1:
                    delay = settings.LAB_RETRY_BACKOFF_SECONDS[attempt]
                    logger.warning(
                        f"Lab submission failed (attempt {attempt + 1}), "
                        f"retrying in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Lab submission failed after all retries: {e}")
                    return LabSubmissionResult(submitted=False, confirmation_id=None)

    async def _send_to_lab(self, data: dict) -> dict:
        """Send data to lab system API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            response = await client.post(
                f"{self.api_url}/requisitions",
                json=data,
                headers=headers
            )

            response.raise_for_status()

            return response.json()

    def _transform_to_lab_format(self, data: dict) -> dict:
        """Transform extracted data to lab system's required format."""
        # Map our field names to lab system's field names
        lab_format = {
            "patient": {
                "name": data.get("patient_name"),
                "dob": self._format_date(data.get("date_of_birth")),
                "address": data.get("patient_address"),
                "phone": data.get("patient_phone"),
                "email": data.get("patient_email"),
                "mrn": data.get("medical_record_number")
            },
            "ordering_provider": data.get("ordering_physician"),
            "orders": data.get("tests_requested", []),
            "specimen": {
                "type": data.get("specimen_type"),
                "collection_date": self._format_date(data.get("collection_date"))
            },
            "insurance": {
                "provider": data.get("insurance_provider"),
                "policy_number": data.get("policy_number")
            },
            "diagnosis_codes": data.get("icd10_codes", []),
            "priority": data.get("priority", "Routine"),
            "special_instructions": data.get("special_instructions"),
            "submitted_at": datetime.utcnow().isoformat()
        }

        return lab_format

    def _format_date(self, date_str: str) -> str:
        """Format date string to lab system's required format."""
        if not date_str:
            return None

        # Assuming input is YYYY-MM-DD, convert to lab system format if needed
        try:
            # Parse and reformat if necessary
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return date_str

    async def check_submission_status(self, confirmation_id: str) -> dict:
        """Check the status of a lab submission."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }

            response = await client.get(
                f"{self.api_url}/requisitions/{confirmation_id}",
                headers=headers
            )

            response.raise_for_status()

            return response.json()

    async def batch_submit(self, documents: list) -> list:
        """Submit multiple documents in batch."""
        results = []

        for doc in documents:
            result = await self.submit_to_lab(doc["id"], doc["data"])
            results.append({
                "document_id": doc["id"],
                "result": result
            })

        return results
