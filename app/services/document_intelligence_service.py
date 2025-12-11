"""
Azure Document Intelligence Service - Document Classification and Separation.

This service handles:
- Document classification using custom classifier models
- Document separation (splitting multi-page scans into individual documents)
- Page analysis and boundary detection
- Custom classifier training from learned document types

The extracted/separated documents are then passed to Azure OpenAI for data extraction.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class DocumentIntelligenceService:
    """Service for document classification and separation using Azure Document Intelligence."""

    def __init__(self):
        self.endpoint = settings.AZURE_DOC_INTELLIGENCE_ENDPOINT
        self.api_key = settings.AZURE_DOC_INTELLIGENCE_KEY
        self.classifier_id = settings.AZURE_DOC_INTELLIGENCE_CLASSIFIER_ID
        self.api_version = "2024-02-29-preview"
        self._classification_concurrent_limit = 5  # Default, configurable via CLASSIFICATION_CONCURRENT_LIMIT

    def set_concurrent_limit(self, limit: int) -> None:
        """Set the concurrent classification limit (called from routers with config value)."""
        self._classification_concurrent_limit = max(1, min(limit, 20))  # Clamp 1-20

    @property
    def is_configured(self) -> bool:
        """Check if Document Intelligence is properly configured."""
        return bool(self.endpoint and self.api_key)

    @property
    def has_classifier(self) -> bool:
        """Check if a custom classifier is configured."""
        return bool(self.classifier_id)

    async def classify_and_split(
        self,
        pages: List[bytes],
        split_mode: str = "auto"
    ) -> List[Dict]:
        """
        Classify and split a batch of scanned pages into individual documents.

        Args:
            pages: List of page images as bytes (PNG/JPEG)
            split_mode: "auto" (AI determines boundaries), "perPage" (each page is a document),
                       "none" (all pages are one document)

        Returns:
            List of document groups, each containing:
            - document_type: Classified document type
            - pages: List of page indices belonging to this document
            - confidence: Classification confidence score
        """
        if not self.is_configured:
            logger.warning("Document Intelligence not configured, falling back to per-page splitting")
            return self._fallback_per_page(pages)

        if not self.has_classifier:
            logger.warning("No classifier configured, using layout analysis for splitting")
            return await self._split_by_layout(pages)

        try:
            # Use custom classifier with split mode
            return await self._classify_with_split(pages, split_mode)
        except Exception as e:
            logger.error(f"Classification failed: {e}, falling back to per-page")
            return self._fallback_per_page(pages)

    async def _classify_with_split(
        self,
        pages: List[bytes],
        split_mode: str
    ) -> List[Dict]:
        """
        Use the custom classifier to classify and split documents.
        """
        # Create a multi-page document for classification
        # Document Intelligence can accept base64 encoded content

        url = f"{self.endpoint}/documentintelligence/documentClassifiers/{self.classifier_id}:analyze"
        params = {
            "api-version": self.api_version,
            "splitMode": split_mode  # auto, perPage, or none
        }

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json"
        }

        # For multiple pages, we need to combine them or send as separate requests
        # Using the first page for now - full implementation would combine into PDF
        if len(pages) == 1:
            body = {
                "base64Source": base64.b64encode(pages[0]).decode("utf-8")
            }
        else:
            # For multiple pages, we'll analyze each and group by detected type
            return await self._classify_multiple_pages(pages, split_mode)

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Start the analysis
            response = await client.post(url, params=params, headers=headers, json=body)

            if response.status_code == 202:
                # Get the operation location for polling
                operation_url = response.headers.get("Operation-Location")
                if operation_url:
                    result = await self._poll_operation(operation_url)
                    return self._parse_classification_result(result, len(pages))
            elif response.status_code == 200:
                result = response.json()
                return self._parse_classification_result(result, len(pages))
            else:
                logger.error(f"Classification request failed: {response.status_code} - {response.text}")
                return self._fallback_per_page(pages)

    async def _classify_multiple_pages(
        self,
        pages: List[bytes],
        split_mode: str
    ) -> List[Dict]:
        """
        Classify multiple pages and determine document boundaries.
        Now classifies pages in parallel for better performance.
        """
        # Get concurrency limit (default 5 for classification)
        concurrent_limit = getattr(self, '_classification_concurrent_limit', 5)

        # Semaphore to limit concurrent classification calls
        semaphore = asyncio.Semaphore(concurrent_limit)

        async def classify_with_semaphore(page: bytes) -> Dict:
            async with semaphore:
                return await self._classify_single_page(page)

        # Classify all pages in parallel (respecting concurrency limit)
        logger.info(f"Classifying {len(pages)} pages with concurrency limit {concurrent_limit}")
        classifications = await asyncio.gather(*[classify_with_semaphore(page) for page in pages])

        # Process classifications sequentially for boundary detection
        documents = []
        current_doc = None

        for idx, classification in enumerate(classifications):
            if current_doc is None:
                # Start new document
                current_doc = {
                    "document_type": classification.get("document_type", "unknown"),
                    "pages": [idx],
                    "confidence": classification.get("confidence", 0.0),
                    "page_confidences": [classification.get("confidence", 0.0)]
                }
            elif split_mode == "perPage":
                # Each page is its own document
                documents.append(current_doc)
                current_doc = {
                    "document_type": classification.get("document_type", "unknown"),
                    "pages": [idx],
                    "confidence": classification.get("confidence", 0.0),
                    "page_confidences": [classification.get("confidence", 0.0)]
                }
            elif self._is_new_document(current_doc, classification):
                # New document detected based on classification change
                documents.append(current_doc)
                current_doc = {
                    "document_type": classification.get("document_type", "unknown"),
                    "pages": [idx],
                    "confidence": classification.get("confidence", 0.0),
                    "page_confidences": [classification.get("confidence", 0.0)]
                }
            else:
                # Continue current document
                current_doc["pages"].append(idx)
                current_doc["page_confidences"].append(classification.get("confidence", 0.0))

        # Don't forget the last document
        if current_doc:
            # Calculate average confidence
            if current_doc["page_confidences"]:
                current_doc["confidence"] = sum(current_doc["page_confidences"]) / len(current_doc["page_confidences"])
            documents.append(current_doc)

        return documents

    async def _classify_single_page(self, page: bytes) -> Dict:
        """Classify a single page image."""
        if not self.has_classifier:
            return {"document_type": "unknown", "confidence": 0.5}

        url = f"{self.endpoint}/documentintelligence/documentClassifiers/{self.classifier_id}:analyze"
        params = {"api-version": self.api_version}

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json"
        }

        body = {
            "base64Source": base64.b64encode(page).decode("utf-8")
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, params=params, headers=headers, json=body)

                if response.status_code == 202:
                    operation_url = response.headers.get("Operation-Location")
                    if operation_url:
                        result = await self._poll_operation(operation_url)
                        return self._extract_classification(result)
                elif response.status_code == 200:
                    return self._extract_classification(response.json())

        except Exception as e:
            logger.error(f"Single page classification failed: {e}")

        return {"document_type": "unknown", "confidence": 0.0}

    def _extract_classification(self, result: Dict) -> Dict:
        """Extract classification info from API result."""
        try:
            documents = result.get("analyzeResult", {}).get("documents", [])
            if documents:
                doc = documents[0]
                return {
                    "document_type": doc.get("docType", "unknown"),
                    "confidence": doc.get("confidence", 0.0)
                }
        except Exception as e:
            logger.error(f"Error extracting classification: {e}")

        return {"document_type": "unknown", "confidence": 0.0}

    def _is_new_document(self, current_doc: Dict, new_classification: Dict) -> bool:
        """
        Determine if a new classification indicates a new document.

        Heuristics:
        - Different document type = new document
        - High confidence on new type = new document
        - Same type with very high confidence = might be continuation
        """
        current_type = current_doc.get("document_type", "unknown")
        new_type = new_classification.get("document_type", "unknown")
        new_confidence = new_classification.get("confidence", 0.0)

        # Different type with reasonable confidence = new document
        if current_type != new_type and new_confidence > 0.6:
            return True

        # Same type - could be continuation or new document
        # If it's a form type with high confidence, likely a new form
        if new_confidence > 0.85 and new_type != "unknown":
            return True

        return False

    async def _poll_operation(self, operation_url: str, max_attempts: int = 30) -> Dict:
        """Poll an async operation until complete."""
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(max_attempts):
                response = await client.get(operation_url, headers=headers)
                result = response.json()

                status = result.get("status", "").lower()
                if status == "succeeded":
                    return result
                elif status == "failed":
                    error = result.get("error", {})
                    raise Exception(f"Operation failed: {error.get('message', 'Unknown error')}")

                # Still running, wait and retry
                await asyncio.sleep(1)

        raise Exception("Operation timed out")

    async def _split_by_layout(self, pages: List[bytes]) -> List[Dict]:
        """
        Use layout analysis to detect document boundaries.
        Looks for common patterns like headers, form titles, etc.
        """
        # TODO: Implement layout-based splitting using prebuilt-layout model
        # For now, fall back to per-page
        logger.info("Layout-based splitting not yet implemented, using per-page")
        return self._fallback_per_page(pages)

    def _fallback_per_page(self, pages: List[bytes]) -> List[Dict]:
        """
        Fallback: treat each page as a separate document.
        """
        return [
            {
                "document_type": "unknown",
                "pages": [i],
                "confidence": 1.0,
                "note": "fallback_per_page"
            }
            for i in range(len(pages))
        ]

    def _parse_classification_result(self, result: Dict, total_pages: int) -> List[Dict]:
        """Parse the classification API result into document groups."""
        try:
            analyze_result = result.get("analyzeResult", {})
            documents = analyze_result.get("documents", [])

            if not documents:
                return self._fallback_per_page([None] * total_pages)

            parsed = []
            for doc in documents:
                parsed.append({
                    "document_type": doc.get("docType", "unknown"),
                    "pages": doc.get("boundingRegions", [{}])[0].get("pageNumber", [1]),
                    "confidence": doc.get("confidence", 0.0),
                    "spans": doc.get("spans", [])
                })

            return parsed if parsed else self._fallback_per_page([None] * total_pages)

        except Exception as e:
            logger.error(f"Error parsing classification result: {e}")
            return self._fallback_per_page([None] * total_pages)

    async def analyze_layout(self, page: bytes) -> Dict:
        """
        Analyze page layout to extract structure information.
        Useful for understanding document structure.
        """
        url = f"{self.endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze"
        params = {"api-version": self.api_version}

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json"
        }

        body = {
            "base64Source": base64.b64encode(page).decode("utf-8")
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, params=params, headers=headers, json=body)

                if response.status_code == 202:
                    operation_url = response.headers.get("Operation-Location")
                    if operation_url:
                        return await self._poll_operation(operation_url)
                elif response.status_code == 200:
                    return response.json()

        except Exception as e:
            logger.error(f"Layout analysis failed: {e}")

        return {}

    async def build_classifier(
        self,
        classifier_id: str,
        document_types: List[Dict],
        blob_container_url: str
    ) -> Dict:
        """
        Build a custom classifier from training data.

        Args:
            classifier_id: Unique ID for the new classifier
            document_types: List of document types with their training samples
                Each type should have: name, samples (list of blob_names)
            blob_container_url: SAS URL to the blob container with training documents

        Returns:
            Dict with classifier_id, status, and any errors
        """
        if not self.is_configured:
            return {"error": "Document Intelligence not configured"}

        url = f"{self.endpoint}/documentintelligence/documentClassifiers/{classifier_id}"
        params = {"api-version": self.api_version}

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json"
        }

        # Build the docTypes structure for the API
        doc_types = {}
        for dt in document_types:
            type_name = dt["name"].replace(" ", "_").lower()
            samples = dt.get("samples", [])

            if samples:
                # Each document type needs azureBlobSource with file list
                doc_types[type_name] = {
                    "azureBlobSource": {
                        "containerUrl": blob_container_url,
                        "prefix": ""  # Training samples are in root
                    },
                    "azureBlobFileListSource": {
                        "containerUrl": blob_container_url,
                        "fileList": f"{type_name}_files.jsonl"
                    }
                }

        if not doc_types:
            return {"error": "No document types with samples to train"}

        body = {
            "classifierId": classifier_id,
            "description": f"Auto-trained classifier from learning mode - {datetime.utcnow().isoformat()}",
            "docTypes": doc_types
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.put(url, params=params, headers=headers, json=body)

                if response.status_code == 201:
                    # Classifier creation started
                    operation_url = response.headers.get("Operation-Location")
                    logger.info(f"Classifier build started: {classifier_id}")

                    if operation_url:
                        # Poll for completion
                        result = await self._poll_classifier_build(operation_url)
                        return result
                    return {"success": True, "classifier_id": classifier_id, "status": "building"}

                elif response.status_code == 200:
                    return {"success": True, "classifier_id": classifier_id, "status": "exists"}

                else:
                    error_text = response.text
                    logger.error(f"Classifier build failed: {response.status_code} - {error_text}")
                    return {"error": f"API error {response.status_code}: {error_text}"}

        except Exception as e:
            logger.error(f"Classifier build error: {e}")
            return {"error": str(e)}

    async def build_classifier_simple(
        self,
        classifier_id: str,
        training_data: Dict
    ) -> Dict:
        """
        Build a classifier using inline training data (base64 encoded samples).

        This is simpler than blob-based training but limited to smaller datasets.

        Args:
            classifier_id: Unique ID for the classifier
            training_data: Dict with document_types, each containing base64 samples

        Returns:
            Dict with result status
        """
        if not self.is_configured:
            return {"error": "Document Intelligence not configured"}

        # For simple training, we use the prebuilt model as base
        # and provide labeled examples
        url = f"{self.endpoint}/documentintelligence/documentClassifiers/{classifier_id}"
        params = {"api-version": self.api_version}

        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json"
        }

        body = {
            "classifierId": classifier_id,
            "description": f"Learned classifier - {datetime.utcnow().isoformat()}",
            "docTypes": training_data.get("docTypes", {})
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.put(url, params=params, headers=headers, json=body)

                if response.status_code in [200, 201]:
                    operation_url = response.headers.get("Operation-Location")
                    if operation_url:
                        result = await self._poll_classifier_build(operation_url)
                        return result
                    return {"success": True, "classifier_id": classifier_id}
                else:
                    return {"error": f"API error: {response.status_code} - {response.text}"}

        except Exception as e:
            logger.error(f"Simple classifier build error: {e}")
            return {"error": str(e)}

    async def _poll_classifier_build(self, operation_url: str, max_attempts: int = 120) -> Dict:
        """Poll classifier build operation until complete (can take several minutes)."""
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.get(operation_url, headers=headers)
                    result = response.json()

                    status = result.get("status", "").lower()
                    logger.info(f"Classifier build status: {status} (attempt {attempt + 1})")

                    if status == "succeeded":
                        return {
                            "success": True,
                            "classifier_id": result.get("result", {}).get("classifierId"),
                            "status": "succeeded",
                            "doc_types": list(result.get("result", {}).get("docTypes", {}).keys())
                        }
                    elif status == "failed":
                        error = result.get("error", {})
                        return {
                            "success": False,
                            "error": error.get("message", "Build failed"),
                            "status": "failed"
                        }

                    # Still running, wait and retry
                    await asyncio.sleep(5)  # Classifier builds take longer

                except Exception as e:
                    logger.warning(f"Poll attempt {attempt + 1} failed: {e}")
                    await asyncio.sleep(5)

        return {"success": False, "error": "Build timed out", "status": "timeout"}

    async def delete_classifier(self, classifier_id: str) -> Dict:
        """Delete an existing classifier."""
        if not self.is_configured:
            return {"error": "Document Intelligence not configured"}

        url = f"{self.endpoint}/documentintelligence/documentClassifiers/{classifier_id}"
        params = {"api-version": self.api_version}

        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(url, params=params, headers=headers)

                if response.status_code == 204:
                    return {"success": True, "message": f"Classifier {classifier_id} deleted"}
                else:
                    return {"error": f"Delete failed: {response.status_code}"}

        except Exception as e:
            return {"error": str(e)}

    async def list_classifiers(self) -> List[Dict]:
        """List all available classifiers."""
        if not self.is_configured:
            return []

        url = f"{self.endpoint}/documentintelligence/documentClassifiers"
        params = {"api-version": self.api_version}

        headers = {"Ocp-Apim-Subscription-Key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    result = response.json()
                    return result.get("value", [])

        except Exception as e:
            logger.error(f"List classifiers error: {e}")

        return []


# Singleton instance
_doc_intelligence_service: Optional[DocumentIntelligenceService] = None


def get_document_intelligence_service() -> DocumentIntelligenceService:
    """Get or create the Document Intelligence service instance."""
    global _doc_intelligence_service
    if _doc_intelligence_service is None:
        _doc_intelligence_service = DocumentIntelligenceService()
    return _doc_intelligence_service
