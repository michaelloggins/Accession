"""
Training Service - Uses GPT-4 Vision to learn document types and extraction patterns.

When learning mode is enabled:
1. Analyzes scanned documents with GPT-4 Vision
2. Identifies document type and distinguishing features
3. Stores training samples for Document Intelligence classifier
4. Learns extraction patterns for each document type
"""

import base64
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
import httpx

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.models.training_data import DocumentType, TrainingSample, ExtractionRule

logger = logging.getLogger(__name__)


# Prompt for document type discovery
DOCUMENT_ANALYSIS_PROMPT = """Analyze this scanned document image and provide a detailed classification.

Return a JSON response with the following structure:
{
    "document_type": {
        "name": "Short name for this document type (e.g., 'Lab Requisition', 'Patient Consent Form')",
        "description": "Brief description of what this document is used for"
    },
    "confidence": 0.0 to 1.0,
    "reasoning": "Explain why you classified it this way",
    "visual_features": {
        "has_logo": true/false,
        "logo_description": "Description of logo if present",
        "header_text": "Main header or title text",
        "layout_type": "form/letter/report/table/other",
        "has_checkboxes": true/false,
        "has_tables": true/false,
        "color_scheme": "Description of colors used"
    },
    "text_patterns": {
        "key_phrases": ["List of distinctive phrases that identify this document type"],
        "field_labels": ["List of field labels like 'Patient Name:', 'Date of Birth:'"],
        "section_headers": ["List of section headers"]
    },
    "extractable_fields": [
        {
            "field_name": "patient_name",
            "field_type": "text",
            "location_hint": "Where this field appears (e.g., 'top left, after Patient Name label')",
            "sample_value": "The value if visible in this document"
        }
    ]
}

Be thorough in identifying distinguishing features that would help classify similar documents in the future."""


class TrainingService:
    """Service for learning document types and extraction patterns using GPT-4 Vision."""

    def __init__(self, db: Session):
        self.db = db
        self.endpoint = settings.AZURE_OPENAI_ENDPOINT
        self.api_key = settings.AZURE_OPENAI_API_KEY
        self.deployment = settings.AZURE_OPENAI_DEPLOYMENT_NAME
        self.api_version = settings.AZURE_OPENAI_API_VERSION

    @property
    def is_configured(self) -> bool:
        """Check if Azure OpenAI is configured for training."""
        return bool(self.endpoint and self.api_key and self.deployment)

    async def analyze_document(
        self,
        image_bytes: bytes,
        document_id: Optional[int] = None,
        blob_name: Optional[str] = None,
        user_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze a document image with GPT-4 Vision to learn its type and features.

        Args:
            image_bytes: The document image as bytes
            document_id: Optional reference to source document
            blob_name: Optional blob storage path
            user_email: User who triggered the analysis

        Returns:
            Analysis results including document type, features, and extraction rules
        """
        if not self.is_configured:
            raise ValueError("Azure OpenAI not configured for training")

        try:
            # Encode image to base64
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")

            # Call GPT-4 Vision
            url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"

            payload = {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a document analysis expert. Analyze documents and return structured JSON responses."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": DOCUMENT_ANALYSIS_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 2000,
                "temperature": 0.1
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json"
                    },
                    json=payload
                )

                if response.status_code != 200:
                    logger.error(f"GPT-4 Vision analysis failed: {response.text}")
                    return {"error": f"API error: {response.status_code}"}

                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # Parse JSON from response
                try:
                    # Try to extract JSON from the response
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        json_str = content.split("```")[1].split("```")[0].strip()
                    else:
                        json_str = content.strip()

                    analysis = json.loads(json_str)
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse JSON from GPT response: {content[:500]}")
                    analysis = {
                        "document_type": {"name": "Unknown", "description": "Could not parse response"},
                        "confidence": 0.5,
                        "raw_response": content
                    }

                # Store the training sample
                sample = await self._store_training_sample(
                    analysis=analysis,
                    document_id=document_id,
                    blob_name=blob_name,
                    user_email=user_email
                )

                return {
                    "success": True,
                    "analysis": analysis,
                    "training_sample_id": sample.id if sample else None
                }

        except Exception as e:
            logger.error(f"Document analysis error: {e}")
            return {"error": str(e)}

    async def _store_training_sample(
        self,
        analysis: Dict[str, Any],
        document_id: Optional[int],
        blob_name: Optional[str],
        user_email: Optional[str]
    ) -> Optional[TrainingSample]:
        """Store the analysis result as a training sample."""
        try:
            doc_type_info = analysis.get("document_type", {})
            doc_type_name = doc_type_info.get("name", "Unknown")

            # Find or create document type
            doc_type = self.db.query(DocumentType).filter(
                DocumentType.name == doc_type_name
            ).first()

            if not doc_type:
                # Create new document type
                doc_type = DocumentType(
                    name=doc_type_name,
                    description=doc_type_info.get("description", ""),
                    visual_features=json.dumps(analysis.get("visual_features", {})),
                    text_patterns=json.dumps(analysis.get("text_patterns", {})),
                    extraction_fields=json.dumps(analysis.get("extractable_fields", [])),
                    sample_count=0,
                    created_by=user_email
                )
                self.db.add(doc_type)
                self.db.flush()
                logger.info(f"Created new document type: {doc_type_name}")
            else:
                # Update existing with new features (merge)
                self._merge_features(doc_type, analysis)

            # Create training sample
            sample = TrainingSample(
                document_type_id=doc_type.id,
                document_id=document_id,
                blob_name=blob_name,
                gpt_classification=doc_type_name,
                gpt_confidence=analysis.get("confidence", 0.0),
                gpt_reasoning=analysis.get("reasoning", ""),
                gpt_features=json.dumps({
                    "visual": analysis.get("visual_features", {}),
                    "text": analysis.get("text_patterns", {}),
                    "fields": analysis.get("extractable_fields", [])
                }),
                extracted_fields=json.dumps(analysis.get("extractable_fields", []))
            )

            self.db.add(sample)

            # Update document type stats
            doc_type.sample_count += 1
            doc_type.avg_confidence = (
                (doc_type.avg_confidence * (doc_type.sample_count - 1) + analysis.get("confidence", 0.0))
                / doc_type.sample_count
            )

            # Create/update extraction rules
            await self._update_extraction_rules(doc_type, analysis.get("extractable_fields", []))

            self.db.commit()

            return sample

        except Exception as e:
            logger.error(f"Error storing training sample: {e}")
            self.db.rollback()
            return None

    def _merge_features(self, doc_type: DocumentType, analysis: Dict[str, Any]):
        """Merge new features into existing document type."""
        try:
            # Merge visual features
            existing_visual = json.loads(doc_type.visual_features or "{}")
            new_visual = analysis.get("visual_features", {})
            merged_visual = {**existing_visual, **new_visual}
            doc_type.visual_features = json.dumps(merged_visual)

            # Merge text patterns (combine lists)
            existing_text = json.loads(doc_type.text_patterns or "{}")
            new_text = analysis.get("text_patterns", {})

            for key in ["key_phrases", "field_labels", "section_headers"]:
                existing_list = set(existing_text.get(key, []))
                new_list = set(new_text.get(key, []))
                existing_text[key] = list(existing_list | new_list)

            doc_type.text_patterns = json.dumps(existing_text)

        except Exception as e:
            logger.error(f"Error merging features: {e}")

    async def _update_extraction_rules(
        self,
        doc_type: DocumentType,
        extractable_fields: List[Dict]
    ):
        """Update extraction rules based on learned fields."""
        for field_info in extractable_fields:
            field_name = field_info.get("field_name", "").lower().replace(" ", "_")
            if not field_name:
                continue

            # Find or create rule
            rule = self.db.query(ExtractionRule).filter(
                ExtractionRule.document_type_id == doc_type.id,
                ExtractionRule.field_name == field_name
            ).first()

            if not rule:
                rule = ExtractionRule(
                    document_type_id=doc_type.id,
                    field_name=field_name,
                    field_type=field_info.get("field_type", "text"),
                    field_description=field_info.get("field_name", "").replace("_", " ").title(),
                    location_hints=json.dumps([field_info.get("location_hint", "")]),
                    sample_count=1
                )
                self.db.add(rule)
            else:
                # Update location hints
                existing_hints = json.loads(rule.location_hints or "[]")
                new_hint = field_info.get("location_hint", "")
                if new_hint and new_hint not in existing_hints:
                    existing_hints.append(new_hint)
                    rule.location_hints = json.dumps(existing_hints[-5:])  # Keep last 5
                rule.sample_count += 1

    def get_training_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        try:
            doc_type_count = self.db.query(DocumentType).filter(
                DocumentType.is_active == True
            ).count()

            sample_count = self.db.query(TrainingSample).count()

            feature_count = self.db.query(ExtractionRule).filter(
                ExtractionRule.is_active == True
            ).count()

            return {
                "document_types": doc_type_count,
                "total_samples": sample_count,
                "total_features": feature_count
            }
        except Exception as e:
            logger.error(f"Error getting training stats: {e}")
            return {"document_types": 0, "total_samples": 0, "total_features": 0}

    def get_learned_types(self) -> List[Dict[str, Any]]:
        """Get all learned document types."""
        try:
            types = self.db.query(DocumentType).filter(
                DocumentType.is_active == True
            ).order_by(DocumentType.sample_count.desc()).all()

            return [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "sample_count": t.sample_count,
                    "avg_confidence": round(t.avg_confidence, 2) if t.avg_confidence else 0,
                    "created_at": t.created_at.isoformat() if t.created_at else None
                }
                for t in types
            ]
        except Exception as e:
            logger.error(f"Error getting learned types: {e}")
            return []

    def export_training_data(self) -> Dict[str, Any]:
        """Export all training data for Document Intelligence."""
        try:
            types = self.db.query(DocumentType).filter(
                DocumentType.is_active == True
            ).all()

            export_data = {
                "export_date": datetime.utcnow().isoformat(),
                "document_types": [],
                "format_version": "1.0"
            }

            for doc_type in types:
                samples = self.db.query(TrainingSample).filter(
                    TrainingSample.document_type_id == doc_type.id
                ).all()

                rules = self.db.query(ExtractionRule).filter(
                    ExtractionRule.document_type_id == doc_type.id,
                    ExtractionRule.is_active == True
                ).all()

                type_data = {
                    "name": doc_type.name,
                    "description": doc_type.description,
                    "visual_features": json.loads(doc_type.visual_features or "{}"),
                    "text_patterns": json.loads(doc_type.text_patterns or "{}"),
                    "sample_count": doc_type.sample_count,
                    "samples": [
                        {
                            "blob_name": s.blob_name,
                            "confidence": s.gpt_confidence,
                            "features": json.loads(s.gpt_features or "{}")
                        }
                        for s in samples
                    ],
                    "extraction_rules": [
                        {
                            "field_name": r.field_name,
                            "field_type": r.field_type,
                            "location_hints": json.loads(r.location_hints or "[]"),
                            "sample_count": r.sample_count
                        }
                        for r in rules
                    ]
                }
                export_data["document_types"].append(type_data)

            return export_data

        except Exception as e:
            logger.error(f"Error exporting training data: {e}")
            return {"error": str(e)}

    def clear_training_data(self) -> bool:
        """Clear all training data."""
        try:
            self.db.query(TrainingSample).delete()
            self.db.query(ExtractionRule).delete()
            self.db.query(DocumentType).delete()
            self.db.commit()
            logger.info("Training data cleared")
            return True
        except Exception as e:
            logger.error(f"Error clearing training data: {e}")
            self.db.rollback()
            return False
