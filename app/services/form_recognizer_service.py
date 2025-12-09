"""
Form Recognizer Custom Model Service - Extraction using trained models.

This service handles:
- Document extraction using custom Form Recognizer models
- Training custom models from labeled data
- Managing model lifecycle (build, train, delete)

Works alongside Document Intelligence (classification) and Azure OpenAI (fallback extraction).
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class FormRecognizerService:
    """Service for document extraction using Azure Form Recognizer custom models."""

    def __init__(self):
        self.endpoint = settings.AZURE_DOC_INTELLIGENCE_ENDPOINT
        self.api_key = settings.AZURE_DOC_INTELLIGENCE_KEY
        self.api_version = "2024-02-29-preview"

    @property
    def is_configured(self) -> bool:
        """Check if Form Recognizer is properly configured."""
        return bool(self.endpoint and self.api_key)

    async def extract_with_model(
        self,
        model_id: str,
        document_bytes: bytes,
        filename: str = "document.pdf"
    ) -> Tuple[Optional[Dict], float, Optional[str]]:
        """
        Extract data from a document using a custom Form Recognizer model.

        Args:
            model_id: The custom model ID to use for extraction
            document_bytes: The document content as bytes
            filename: Original filename for content type detection

        Returns:
            Tuple of (extracted_data, confidence_score, error_message)
        """
        if not self.is_configured:
            return None, 0.0, "Form Recognizer not configured"

        try:
            # Determine content type
            content_type = self._get_content_type(filename)

            url = f"{self.endpoint}/documentintelligence/documentModels/{model_id}:analyze"
            params = {"api-version": self.api_version}

            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/json"
            }

            # Send as base64
            body = {
                "base64Source": base64.b64encode(document_bytes).decode("utf-8")
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, params=params, headers=headers, json=body)

                if response.status_code == 202:
                    # Async operation - poll for result
                    operation_url = response.headers.get("Operation-Location")
                    if operation_url:
                        result = await self._poll_operation(operation_url)
                        return self._parse_extraction_result(result)
                    return None, 0.0, "No operation location returned"

                elif response.status_code == 200:
                    result = response.json()
                    return self._parse_extraction_result(result)

                else:
                    error_msg = f"Form Recognizer error: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return None, 0.0, error_msg

        except Exception as e:
            logger.error(f"Form Recognizer extraction error: {e}")
            return None, 0.0, str(e)

    def _parse_extraction_result(self, result: Dict) -> Tuple[Optional[Dict], float, Optional[str]]:
        """Parse Form Recognizer extraction result into standardized format."""
        try:
            analyze_result = result.get("analyzeResult", {})
            documents = analyze_result.get("documents", [])

            if not documents:
                return None, 0.0, "No documents found in result"

            # Get the first document
            doc = documents[0]
            confidence = doc.get("confidence", 0.0)
            fields = doc.get("fields", {})

            # Convert to our standard extraction format
            extracted_data = self._map_fields_to_standard(fields)

            return extracted_data, confidence, None

        except Exception as e:
            logger.error(f"Error parsing extraction result: {e}")
            return None, 0.0, str(e)

    def _map_fields_to_standard(self, fields: Dict) -> Dict:
        """Map Form Recognizer fields to our standard extraction schema."""
        # Standard field mappings - Form Recognizer field names to our schema
        field_mappings = {
            "PatientName": "patient_name",
            "patient_name": "patient_name",
            "DateOfBirth": "date_of_birth",
            "date_of_birth": "date_of_birth",
            "DOB": "date_of_birth",
            "OrderingPhysician": "ordering_physician",
            "ordering_physician": "ordering_physician",
            "Physician": "ordering_physician",
            "FacilityName": "facility_name",
            "facility_name": "facility_name",
            "Facility": "facility_name",
            "TestsRequested": "tests_requested",
            "tests_requested": "tests_requested",
            "Tests": "tests_requested",
            "SpecimenType": "specimen_type",
            "specimen_type": "specimen_type",
            "Specimen": "specimen_type",
            "CollectionDate": "collection_date",
            "collection_date": "collection_date",
            "SpecialInstructions": "special_instructions",
            "special_instructions": "special_instructions",
            "Notes": "special_instructions",
        }

        extracted = {}

        for fr_field, value_obj in fields.items():
            # Get the standardized field name
            std_field = field_mappings.get(fr_field, fr_field.lower().replace(" ", "_"))

            # Extract the value
            if isinstance(value_obj, dict):
                value = value_obj.get("valueString") or value_obj.get("content") or value_obj.get("value")

                # Handle array fields (like tests)
                if value_obj.get("type") == "array":
                    items = value_obj.get("valueArray", [])
                    value = [item.get("valueString", item.get("content", "")) for item in items]
            else:
                value = value_obj

            if value:
                extracted[std_field] = value

        return extracted

    async def _poll_operation(self, operation_url: str, max_attempts: int = 60) -> Dict:
        """Poll an async operation until complete."""
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.get(operation_url, headers=headers)
                    result = response.json()

                    status = result.get("status", "").lower()
                    if status == "succeeded":
                        return result
                    elif status == "failed":
                        error = result.get("error", {})
                        raise Exception(f"Operation failed: {error.get('message', 'Unknown error')}")

                    # Still running, wait and retry
                    await asyncio.sleep(2)

                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    logger.warning(f"Poll attempt {attempt + 1} error: {e}")
                    await asyncio.sleep(2)

        raise Exception("Operation timed out")

    def _get_content_type(self, filename: str) -> str:
        """Get content type from filename."""
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        content_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "tif": "image/tiff"
        }
        return content_types.get(ext, "application/octet-stream")

    async def list_models(self) -> List[Dict]:
        """List all custom models."""
        if not self.is_configured:
            return []

        try:
            url = f"{self.endpoint}/documentintelligence/documentModels"
            params = {"api-version": self.api_version}
            headers = {"Ocp-Apim-Subscription-Key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    result = response.json()
                    # Filter to only custom models (not prebuilt)
                    models = result.get("value", [])
                    custom_models = [
                        m for m in models
                        if not m.get("modelId", "").startswith("prebuilt-")
                    ]
                    return custom_models

        except Exception as e:
            logger.error(f"Error listing models: {e}")

        return []

    async def get_model_info(self, model_id: str) -> Optional[Dict]:
        """Get information about a specific model."""
        if not self.is_configured:
            return None

        try:
            url = f"{self.endpoint}/documentintelligence/documentModels/{model_id}"
            params = {"api-version": self.api_version}
            headers = {"Ocp-Apim-Subscription-Key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    return response.json()

        except Exception as e:
            logger.error(f"Error getting model info: {e}")

        return None

    async def build_model(
        self,
        model_id: str,
        description: str,
        blob_container_url: str,
        build_mode: str = "template"  # "template" or "neural"
    ) -> Dict:
        """
        Build a custom extraction model from labeled training data.

        Args:
            model_id: Unique ID for the new model
            description: Description of the model
            blob_container_url: SAS URL to blob container with labeled training data
            build_mode: "template" for forms with fixed layout, "neural" for variable layouts

        Returns:
            Dict with model_id, status, and any errors
        """
        if not self.is_configured:
            return {"error": "Form Recognizer not configured"}

        try:
            url = f"{self.endpoint}/documentintelligence/documentModels/{model_id}"
            params = {"api-version": self.api_version}

            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/json"
            }

            body = {
                "modelId": model_id,
                "description": description,
                "buildMode": build_mode,
                "azureBlobSource": {
                    "containerUrl": blob_container_url
                }
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.put(url, params=params, headers=headers, json=body)

                if response.status_code in [200, 201, 202]:
                    operation_url = response.headers.get("Operation-Location")
                    logger.info(f"Model build started: {model_id}")

                    if operation_url:
                        # Poll for completion
                        result = await self._poll_model_build(operation_url)
                        return result

                    return {"success": True, "model_id": model_id, "status": "building"}
                else:
                    error_text = response.text
                    logger.error(f"Model build failed: {response.status_code} - {error_text}")
                    return {"error": f"API error {response.status_code}: {error_text}"}

        except Exception as e:
            logger.error(f"Model build error: {e}")
            return {"error": str(e)}

    async def _poll_model_build(self, operation_url: str, max_attempts: int = 180) -> Dict:
        """Poll model build operation until complete (can take several minutes)."""
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.get(operation_url, headers=headers)
                    result = response.json()

                    status = result.get("status", "").lower()
                    logger.info(f"Model build status: {status} (attempt {attempt + 1})")

                    if status == "succeeded":
                        return {
                            "success": True,
                            "model_id": result.get("result", {}).get("modelId"),
                            "status": "succeeded"
                        }
                    elif status == "failed":
                        error = result.get("error", {})
                        return {
                            "success": False,
                            "error": error.get("message", "Build failed"),
                            "status": "failed"
                        }

                    # Still running, wait and retry
                    await asyncio.sleep(5)

                except Exception as e:
                    logger.warning(f"Poll attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(5)

        return {"success": False, "error": "Build timed out", "status": "timeout"}

    async def delete_model(self, model_id: str) -> Dict:
        """Delete a custom model."""
        if not self.is_configured:
            return {"error": "Form Recognizer not configured"}

        try:
            url = f"{self.endpoint}/documentintelligence/documentModels/{model_id}"
            params = {"api-version": self.api_version}
            headers = {"Ocp-Apim-Subscription-Key": self.api_key}

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(url, params=params, headers=headers)

                if response.status_code == 204:
                    return {"success": True, "message": f"Model {model_id} deleted"}
                else:
                    return {"error": f"Delete failed: {response.status_code}"}

        except Exception as e:
            return {"error": str(e)}

    async def compose_model(
        self,
        composed_model_id: str,
        component_model_ids: List[str],
        description: str = ""
    ) -> Dict:
        """
        Compose multiple models into a single model.
        Useful for handling multiple document types with one model.

        Args:
            composed_model_id: ID for the new composed model
            component_model_ids: List of model IDs to compose
            description: Description for the composed model

        Returns:
            Dict with result status
        """
        if not self.is_configured:
            return {"error": "Form Recognizer not configured"}

        try:
            url = f"{self.endpoint}/documentintelligence/documentModels/{composed_model_id}:compose"
            params = {"api-version": self.api_version}

            headers = {
                "Ocp-Apim-Subscription-Key": self.api_key,
                "Content-Type": "application/json"
            }

            body = {
                "modelId": composed_model_id,
                "description": description or f"Composed model from {len(component_model_ids)} models",
                "componentModels": [{"modelId": mid} for mid in component_model_ids]
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, params=params, headers=headers, json=body)

                if response.status_code in [200, 201, 202]:
                    operation_url = response.headers.get("Operation-Location")
                    if operation_url:
                        result = await self._poll_model_build(operation_url)
                        return result
                    return {"success": True, "model_id": composed_model_id}
                else:
                    return {"error": f"Compose failed: {response.status_code} - {response.text}"}

        except Exception as e:
            return {"error": str(e)}


# Singleton instance
_form_recognizer_service: Optional[FormRecognizerService] = None


def get_form_recognizer_service() -> FormRecognizerService:
    """Get or create the Form Recognizer service instance."""
    global _form_recognizer_service
    if _form_recognizer_service is None:
        _form_recognizer_service = FormRecognizerService()
    return _form_recognizer_service
