"""AI extraction service using Azure OpenAI GPT-4 Vision."""

import base64
import json
import logging
import io
import os
from pathlib import Path
from typing import Optional
from openai import AzureOpenAI
from fastapi import UploadFile, HTTPException, status

from app.config import settings
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

# Default values from SystemConfig.DEFAULTS (used when db not available)
DEFAULT_TEMPERATURE = float(SystemConfig.DEFAULTS.get("AZURE_OPENAI_TEMPERATURE", {}).get("value", "0.1"))
DEFAULT_MAX_TOKENS = int(SystemConfig.DEFAULTS.get("AZURE_OPENAI_MAX_TOKENS", {}).get("value", "2000"))
DEFAULT_MAX_TOKENS_BATCH = int(SystemConfig.DEFAULTS.get("AZURE_OPENAI_MAX_TOKENS_BATCH", {}).get("value", "4000"))
DEFAULT_CONFIDENCE = float(SystemConfig.DEFAULTS.get("DEFAULT_CONFIDENCE_SCORE", {}).get("value", "0.85"))


def load_prompt_file(filename: str) -> str:
    """Load prompt from file."""
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / filename
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found at: {prompt_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading prompt: {e}")
        raise


class AzureOpenAIExtractionService:
    """Service for extracting data from documents using Azure OpenAI GPT-4 Vision."""

    def __init__(
        self,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_tokens_batch: Optional[int] = None,
        default_confidence: Optional[float] = None
    ):
        self.client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
        )
        self.deployment_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME

        # Config values (use passed values or module defaults)
        self.temperature = temperature if temperature is not None else DEFAULT_TEMPERATURE
        self.max_tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        self.max_tokens_batch = max_tokens_batch if max_tokens_batch is not None else DEFAULT_MAX_TOKENS_BATCH
        self.default_confidence = default_confidence if default_confidence is not None else DEFAULT_CONFIDENCE

    async def extract_data(self, file: UploadFile) -> tuple:
        """Extract data from uploaded document using Azure OpenAI GPT-4 Vision."""
        try:
            # Read file content
            content = await file.read()
            await file.seek(0)

            # Check if PDF and convert to PNG if needed
            filename_lower = file.filename.lower()
            if filename_lower.endswith('.pdf'):
                logger.info("PDF detected, converting to PNG for vision API...")
                content = self._convert_pdf_to_png(content)
                media_type = "image/png"
            else:
                media_type = self._get_media_type(file.filename)

            # Encode to base64
            base64_data = base64.standard_b64encode(content).decode("utf-8")

            # Call Azure OpenAI with retry
            response = await self._call_azure_openai_with_retry(base64_data, media_type)

            # Parse response
            extracted_data = self._parse_response(response)

            # Extract confidence from metadata (new format) or root level (legacy)
            confidence_score = self.default_confidence
            if "metadata" in extracted_data and isinstance(extracted_data["metadata"], dict):
                confidence_score = extracted_data["metadata"].get("confidence_score", self.default_confidence)
            else:
                # Legacy format - pop from root
                confidence_score = extracted_data.pop("confidence_score", self.default_confidence)

            logger.info(f"Azure OpenAI extraction completed with confidence: {confidence_score}")
            return extracted_data, confidence_score

        except Exception as e:
            logger.error(f"Azure OpenAI extraction error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Document extraction failed: {str(e)}"
            )

    async def _call_azure_openai_with_retry(self, base64_data: str, media_type: str) -> str:
        """Call Azure OpenAI API with retry logic."""
        import asyncio
        retry_delays = settings.LAB_RETRY_BACKOFF_SECONDS

        for attempt in range(settings.LAB_SUBMISSION_RETRIES):
            try:
                # Load prompts fresh on each request (allows updates without restart)
                system_prompt = load_prompt_file("system_prompt.txt")
                user_prompt = load_prompt_file("user_prompt.txt")

                # Prepare messages with system prompt and image
                messages = [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{base64_data}",
                                    "detail": "high"
                                }
                            },
                            {
                                "type": "text",
                                "text": user_prompt
                            }
                        ]
                    }
                ]

                response = self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature  # Low temperature for consistent extraction
                )

                return response.choices[0].message.content

            except Exception as e:
                if attempt < len(retry_delays) - 1:
                    logger.warning(f"Azure OpenAI API error, retrying: {e}")
                    await asyncio.sleep(retry_delays[attempt])
                else:
                    raise

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service temporarily unavailable"
        )

    def _get_media_type(self, filename: str) -> str:
        """Get media type from filename."""
        ext = filename.lower().split(".")[-1]
        media_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "tif": "image/tiff"
        }
        return media_types.get(ext, "application/octet-stream")

    def _parse_response(self, response_text: str) -> dict:
        """Parse Azure OpenAI response to extract JSON data."""
        try:
            # Try to parse as JSON directly
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            logger.error(f"Failed to parse Azure OpenAI response: {response_text}")
            return {
                "patient_name": None,
                "date_of_birth": None,
                "ordering_physician": None,
                "tests_requested": [],
                "specimen_type": None,
                "collection_date": None,
                "confidence_score": 0.50
            }

    def _convert_pdf_to_png(self, pdf_bytes: bytes) -> bytes:
        """Convert PDF to PNG image (first page only)."""
        try:
            import fitz  # PyMuPDF

            # Open PDF from bytes
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")

            # Get first page
            page = pdf_document[0]

            # Render page to image at high resolution (300 DPI for good OCR)
            zoom = 300 / 72  # 72 is default DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PNG bytes
            png_bytes = pix.tobytes("png")

            pdf_document.close()

            logger.info(f"PDF converted to PNG: {len(png_bytes)} bytes")
            return png_bytes

        except Exception as e:
            logger.error(f"PDF conversion error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to convert PDF to image: {str(e)}"
            )

    async def extract_batch(self, documents: list) -> list:
        """Extract data from multiple documents in a single API call.

        Args:
            documents: List of dicts with 'id', 'content' (bytes), and 'filename'

        Returns:
            List of dicts with 'document_id', 'extracted_data', 'confidence_score', 'error'
        """
        if not documents:
            return []

        if len(documents) == 1:
            # Single document - use regular extraction
            doc = documents[0]
            try:
                result = await self._extract_single_from_bytes(
                    doc['content'],
                    doc['filename']
                )
                return [{
                    'document_id': doc['id'],
                    'extracted_data': result[0],
                    'confidence_score': result[1],
                    'error': None
                }]
            except Exception as e:
                return [{
                    'document_id': doc['id'],
                    'extracted_data': None,
                    'confidence_score': None,
                    'error': str(e)
                }]

        # Multiple documents - batch extraction
        try:
            logger.info(f"Starting batch extraction for {len(documents)} documents")

            # Prepare images for batch
            image_contents = []
            for idx, doc in enumerate(documents):
                content = doc['content']
                filename = doc['filename']

                # Convert PDF to PNG if needed
                if filename.lower().endswith('.pdf'):
                    content = self._convert_pdf_to_png(content)
                    media_type = "image/png"
                else:
                    media_type = self._get_media_type(filename)

                base64_data = base64.standard_b64encode(content).decode("utf-8")
                image_contents.append({
                    'index': idx,
                    'document_id': doc['id'],
                    'base64': base64_data,
                    'media_type': media_type
                })

            # Call Azure OpenAI with batch
            response = await self._call_azure_openai_batch(image_contents)

            # Parse batch response
            results = self._parse_batch_response(response, documents)

            logger.info(f"Batch extraction completed: {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Batch extraction error: {e}")
            # Return error for all documents
            return [{
                'document_id': doc['id'],
                'extracted_data': None,
                'confidence_score': None,
                'error': str(e)
            } for doc in documents]

    async def _extract_single_from_bytes(self, content: bytes, filename: str) -> tuple:
        """Extract data from document bytes."""
        # Convert PDF to PNG if needed
        if filename.lower().endswith('.pdf'):
            content = self._convert_pdf_to_png(content)
            media_type = "image/png"
        else:
            media_type = self._get_media_type(filename)

        base64_data = base64.standard_b64encode(content).decode("utf-8")

        response = await self._call_azure_openai_with_retry(base64_data, media_type)
        extracted_data = self._parse_response(response)

        confidence_score = self.default_confidence
        if "metadata" in extracted_data and isinstance(extracted_data["metadata"], dict):
            confidence_score = extracted_data["metadata"].get("confidence_score", self.default_confidence)
        else:
            confidence_score = extracted_data.pop("confidence_score", self.default_confidence)

        return extracted_data, confidence_score

    async def _call_azure_openai_batch(self, image_contents: list) -> str:
        """Call Azure OpenAI API with multiple images in one request."""
        import asyncio
        retry_delays = settings.LAB_RETRY_BACKOFF_SECONDS

        for attempt in range(settings.LAB_SUBMISSION_RETRIES):
            try:
                # Load prompts
                system_prompt = load_prompt_file("system_prompt.txt")

                # Build batch user prompt
                batch_prompt = self._build_batch_prompt(len(image_contents))

                # Build content array with all images
                content_array = []

                # Add each image with its index label
                for img in image_contents:
                    content_array.append({
                        "type": "text",
                        "text": f"--- Document {img['index']} ---"
                    })
                    content_array.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['media_type']};base64,{img['base64']}",
                            "detail": "high"
                        }
                    })

                # Add the batch extraction prompt
                content_array.append({
                    "type": "text",
                    "text": batch_prompt
                })

                messages = [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": content_array
                    }
                ]

                # Increase max tokens for batch (more documents = more output)
                # Use configured max_tokens_batch as the ceiling
                max_tokens = min(self.max_tokens_batch, 1500 + (len(image_contents) * 500))

                response = self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self.temperature
                )

                return response.choices[0].message.content

            except Exception as e:
                if attempt < len(retry_delays) - 1:
                    logger.warning(f"Azure OpenAI batch API error, retrying: {e}")
                    await asyncio.sleep(retry_delays[attempt])
                else:
                    raise

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service temporarily unavailable"
        )

    def _build_batch_prompt(self, document_count: int) -> str:
        """Build the prompt for batch extraction."""
        return f"""
You are processing {document_count} lab requisition documents shown above.

Extract data from EACH document separately and return a JSON array.
Each element in the array corresponds to the document at that index (0 through {document_count - 1}).

Return ONLY valid JSON in this exact format:
[
  {{
    "document_index": 0,
    "confidence_score": 0.95,
    "data": {{
      "patient_name": "...",
      "date_of_birth": "YYYY-MM-DD",
      "ordering_physician": "...",
      "facility_name": "...",
      "tests_requested": ["test1", "test2"],
      "specimen_type": "...",
      "collection_date": "YYYY-MM-DD",
      "special_instructions": "..."
    }}
  }},
  {{
    "document_index": 1,
    "confidence_score": 0.87,
    "data": {{...}}
  }}
]

Important:
- Return one object per document in the array
- document_index must match the document number shown above
- confidence_score reflects how confident you are in the extraction (0.0-1.0)
- If a document is unreadable or not a lab requisition, set confidence_score to 0.0 and leave data fields as null
- Extract all visible patient information, tests, and facility details
"""

    def _parse_batch_response(self, response_text: str, documents: list) -> list:
        """Parse batch extraction response into individual results."""
        results = []

        try:
            # Try to parse as JSON array
            parsed = json.loads(response_text)

            if isinstance(parsed, list):
                # Map results to documents
                result_map = {r.get('document_index'): r for r in parsed}

                for idx, doc in enumerate(documents):
                    result = result_map.get(idx)
                    if result:
                        results.append({
                            'document_id': doc['id'],
                            'extracted_data': result.get('data', {}),
                            'confidence_score': result.get('confidence_score', self.default_confidence),
                            'error': None
                        })
                    else:
                        results.append({
                            'document_id': doc['id'],
                            'extracted_data': None,
                            'confidence_score': None,
                            'error': f'No result found for document index {idx}'
                        })
            else:
                raise ValueError("Response is not a JSON array")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse batch response: {e}")
            logger.error(f"Response was: {response_text[:500]}...")

            # Try to extract JSON array from response
            import re
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                try:
                    return self._parse_batch_response(json_match.group(), documents)
                except Exception:
                    pass

            # Return error for all documents
            for doc in documents:
                results.append({
                    'document_id': doc['id'],
                    'extracted_data': None,
                    'confidence_score': None,
                    'error': f'Failed to parse batch response: {str(e)}'
                })

        return results
