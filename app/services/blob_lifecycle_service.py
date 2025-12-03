"""
Blob Lifecycle Management Service

Handles:
- Document metadata on blobs (facility, patient, order, tests, expiry date)
- Storage tiering (Hot -> Cool -> Cold)
- Immutability policies (WORM compliance)
- Lifecycle policy synchronization with Azure Blob Storage
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from azure.storage.blob import (
    BlobServiceClient,
    BlobClient,
    ContainerClient,
    ImmutabilityPolicy
)
from azure.storage.blob._models import BlobImmutabilityPolicyMode
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

from app.config import settings
from app.services.config_service import ConfigService

logger = logging.getLogger(__name__)


class BlobLifecycleService:
    """Service for managing blob storage lifecycle, metadata, and compliance."""

    # Maximum metadata key length in Azure
    MAX_METADATA_KEY_LENGTH = 64
    # Maximum metadata value length in Azure (8KB per value, but we'll limit for safety)
    MAX_METADATA_VALUE_LENGTH = 1024

    def __init__(self, db: Session):
        self.db = db
        self.config_service = ConfigService(db)
        self._blob_service_client = None

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

    def get_retention_config(self) -> Dict[str, Any]:
        """Get current retention and lifecycle configuration."""
        return {
            "retention_years": self.config_service.get_int("DOCUMENT_RETENTION_YEARS", 7),
            "cool_tier_days": self.config_service.get_int("STORAGE_TIER_COOL_DAYS", 60),
            "cold_tier_days": self.config_service.get_int("STORAGE_TIER_COLD_DAYS", 365),
            "immutability_enabled": self.config_service.get_bool("BLOB_IMMUTABILITY_ENABLED", True),
            "auto_sync_enabled": self.config_service.get_bool("STORAGE_LIFECYCLE_AUTO_SYNC", True)
        }

    def calculate_expiry_date(self, import_date: datetime = None) -> datetime:
        """Calculate expiry date based on retention policy (retention_years + 1 day)."""
        config = self.get_retention_config()
        base_date = import_date or datetime.utcnow()
        # Add retention years + 1 day
        expiry = base_date + timedelta(days=(config["retention_years"] * 365) + 1)
        return expiry

    def calculate_tier_dates(self, import_date: datetime = None) -> Dict[str, datetime]:
        """Calculate dates for storage tier transitions."""
        config = self.get_retention_config()
        base_date = import_date or datetime.utcnow()

        return {
            "cool_tier_date": base_date + timedelta(days=config["cool_tier_days"]),
            "cold_tier_date": base_date + timedelta(days=config["cold_tier_days"]),
            "expiry_date": self.calculate_expiry_date(base_date)
        }

    def _sanitize_metadata_value(self, value: Any) -> str:
        """Sanitize and truncate metadata value for Azure compliance."""
        if value is None:
            return ""
        str_value = str(value).strip()
        # Remove any characters that might cause issues
        str_value = str_value.replace('\n', ' ').replace('\r', ' ')
        # Truncate if too long
        if len(str_value) > self.MAX_METADATA_VALUE_LENGTH:
            str_value = str_value[:self.MAX_METADATA_VALUE_LENGTH - 3] + "..."
        return str_value

    def _sanitize_metadata_key(self, key: str) -> str:
        """Sanitize metadata key for Azure compliance (alphanumeric and underscores only)."""
        # Replace spaces and special chars with underscores
        sanitized = ''.join(c if c.isalnum() or c == '_' else '_' for c in key)
        # Azure metadata keys must start with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = 'x_' + sanitized
        return sanitized[:self.MAX_METADATA_KEY_LENGTH]

    def build_document_metadata(
        self,
        document_id: int,
        accession_number: str,
        import_date: datetime,
        extracted_data: Dict[str, Any] = None,
        source: str = None
    ) -> Dict[str, str]:
        """
        Build comprehensive metadata dictionary for a document blob.

        Includes:
        - Document identifiers
        - Lifecycle dates (import, expiry, tier transitions)
        - Facility information
        - Patient information (non-PHI identifiers only)
        - Order information
        - Tests requested (number/specimen format)
        """
        config = self.get_retention_config()
        tier_dates = self.calculate_tier_dates(import_date)

        # Base metadata
        metadata = {
            "document_id": str(document_id),
            "accession_number": accession_number,
            "source": source or "unknown",
            "import_date": import_date.isoformat(),
            "expiry_date": tier_dates["expiry_date"].isoformat(),
            "cool_tier_date": tier_dates["cool_tier_date"].isoformat(),
            "cold_tier_date": tier_dates["cold_tier_date"].isoformat(),
            "retention_years": str(config["retention_years"]),
            "immutability_enabled": str(config["immutability_enabled"]).lower(),
            "metadata_version": "2"  # Version for future schema changes
        }

        # Add extracted data if available
        if extracted_data:
            # Facility information
            if extracted_data.get("facility_name"):
                metadata["facility_name"] = self._sanitize_metadata_value(
                    extracted_data.get("facility_name")
                )
            if extracted_data.get("facility_id"):
                metadata["facility_id"] = self._sanitize_metadata_value(
                    extracted_data.get("facility_id")
                )
            if extracted_data.get("facility_city"):
                metadata["facility_city"] = self._sanitize_metadata_value(
                    extracted_data.get("facility_city")
                )
            if extracted_data.get("facility_state"):
                metadata["facility_state"] = self._sanitize_metadata_value(
                    extracted_data.get("facility_state")
                )

            # Patient information (non-PHI only - use identifiers, not actual PHI)
            if extracted_data.get("medical_record_number"):
                metadata["patient_mrn"] = self._sanitize_metadata_value(
                    extracted_data.get("medical_record_number")
                )
            if extracted_data.get("patient_gender"):
                metadata["patient_gender"] = self._sanitize_metadata_value(
                    extracted_data.get("patient_gender")
                )
            if extracted_data.get("species"):
                metadata["patient_species"] = self._sanitize_metadata_value(
                    extracted_data.get("species")
                )
            if extracted_data.get("patient_type"):
                metadata["patient_type"] = self._sanitize_metadata_value(
                    extracted_data.get("patient_type")
                )

            # Order information
            if extracted_data.get("ordering_physician"):
                metadata["ordering_physician"] = self._sanitize_metadata_value(
                    extracted_data.get("ordering_physician")
                )
            if extracted_data.get("collection_date"):
                metadata["collection_date"] = self._sanitize_metadata_value(
                    extracted_data.get("collection_date")
                )

            # Tests requested - format as "TestNumber/Specimen"
            tests_requested = extracted_data.get("tests_requested", [])
            specimen_type = extracted_data.get("specimen_type", "")

            if tests_requested:
                if isinstance(tests_requested, list):
                    # Format each test as number/specimen
                    formatted_tests = []
                    for test in tests_requested[:10]:  # Limit to 10 tests for metadata size
                        if isinstance(test, dict):
                            test_num = test.get("test_number", test.get("test_name", ""))
                            spec = test.get("specimen_type", specimen_type)
                            formatted_tests.append(f"{test_num}/{spec}")
                        else:
                            formatted_tests.append(f"{test}/{specimen_type}")
                    metadata["tests_requested"] = self._sanitize_metadata_value(
                        "; ".join(formatted_tests)
                    )
                else:
                    metadata["tests_requested"] = self._sanitize_metadata_value(
                        f"{tests_requested}/{specimen_type}"
                    )

            # Special instructions (truncated)
            if extracted_data.get("special_instructions"):
                metadata["special_instructions"] = self._sanitize_metadata_value(
                    extracted_data.get("special_instructions")[:200]
                )

        return metadata

    def set_blob_metadata_full(
        self,
        blob_name: str,
        document_id: int,
        accession_number: str,
        import_date: datetime,
        extracted_data: Dict[str, Any] = None,
        source: str = None
    ) -> bool:
        """
        Set comprehensive metadata on a blob including all document fields.

        This should be called after document creation/extraction to add
        all relevant metadata before immutability is applied.
        """
        if not self.blob_service_client:
            logger.warning("Blob service not configured, skipping metadata")
            return False

        try:
            container_client = self.blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )
            blob_client = container_client.get_blob_client(blob_name)

            # Build metadata
            metadata = self.build_document_metadata(
                document_id=document_id,
                accession_number=accession_number,
                import_date=import_date,
                extracted_data=extracted_data,
                source=source
            )

            # Set metadata on blob
            blob_client.set_blob_metadata(metadata)

            logger.info(f"Set full metadata on blob {blob_name}: {len(metadata)} fields")
            return True

        except HttpResponseError as e:
            if "BlobImmutable" in str(e) or "immutab" in str(e).lower():
                logger.warning(f"Cannot update metadata on immutable blob {blob_name}")
                return False
            logger.error(f"Failed to set blob metadata for {blob_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to set blob metadata for {blob_name}: {e}")
            return False

    def set_blob_immutability(
        self,
        blob_name: str,
        expiry_date: datetime = None
    ) -> bool:
        """
        Set immutability policy on a blob (WORM compliance).

        Args:
            blob_name: The blob to make immutable
            expiry_date: When the immutability expires (defaults to retention policy)

        Note: This cannot be reversed once set with 'locked' policy.
        We use 'unlocked' policy which allows extension but not reduction.
        """
        config = self.get_retention_config()

        if not config["immutability_enabled"]:
            logger.info(f"Immutability disabled, skipping for {blob_name}")
            return False

        if not self.blob_service_client:
            logger.warning("Blob service not configured, skipping immutability")
            return False

        try:
            container_client = self.blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )
            blob_client = container_client.get_blob_client(blob_name)

            # Calculate expiry if not provided
            if expiry_date is None:
                expiry_date = self.calculate_expiry_date()

            # Create immutability policy (unlocked allows extension, not reduction)
            # Note: Container must have version-level immutability enabled
            immutability_policy = ImmutabilityPolicy(
                expiry_time=expiry_date,
                policy_mode=BlobImmutabilityPolicyMode.UNLOCKED
            )

            blob_client.set_immutability_policy(immutability_policy)

            logger.info(f"Set immutability on blob {blob_name} until {expiry_date.isoformat()}")
            return True

        except HttpResponseError as e:
            error_msg = str(e)
            if "FeatureVersionMismatch" in error_msg or "BlobImmutabilityNotSupported" in error_msg:
                logger.warning(
                    f"Immutability not supported on container. Enable version-level immutability on container."
                )
            elif "ImmutabilityPolicyAlreadyExists" in error_msg:
                logger.info(f"Blob {blob_name} already has immutability policy")
                return True
            else:
                logger.error(f"Failed to set immutability on {blob_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to set immutability on {blob_name}: {e}")
            return False

    def extend_blob_immutability(
        self,
        blob_name: str,
        new_expiry_date: datetime
    ) -> bool:
        """
        Extend (not reduce) the immutability period on a blob.

        Args:
            blob_name: The blob to extend
            new_expiry_date: New expiry date (must be later than current)

        Returns:
            True if extended, False otherwise
        """
        if not self.blob_service_client:
            return False

        try:
            container_client = self.blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )
            blob_client = container_client.get_blob_client(blob_name)

            # Get current properties
            properties = blob_client.get_blob_properties()

            if properties.immutability_policy:
                current_expiry = properties.immutability_policy.expiry_time
                if new_expiry_date <= current_expiry:
                    logger.warning(
                        f"Cannot reduce immutability period. Current: {current_expiry}, Requested: {new_expiry_date}"
                    )
                    return False

            # Set new policy
            immutability_policy = ImmutabilityPolicy(
                expiry_time=new_expiry_date,
                policy_mode=BlobImmutabilityPolicyMode.UNLOCKED
            )

            blob_client.set_immutability_policy(immutability_policy)

            logger.info(f"Extended immutability on {blob_name} to {new_expiry_date.isoformat()}")
            return True

        except Exception as e:
            logger.error(f"Failed to extend immutability on {blob_name}: {e}")
            return False

    def get_blob_lifecycle_status(self, blob_name: str) -> Dict[str, Any]:
        """Get current lifecycle status of a blob."""
        if not self.blob_service_client:
            return {"error": "Blob service not configured"}

        try:
            container_client = self.blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )
            blob_client = container_client.get_blob_client(blob_name)

            properties = blob_client.get_blob_properties()

            status = {
                "blob_name": blob_name,
                "access_tier": str(properties.blob_tier) if properties.blob_tier else "Unknown",
                "creation_time": properties.creation_time.isoformat() if properties.creation_time else None,
                "last_modified": properties.last_modified.isoformat() if properties.last_modified else None,
                "content_length": properties.size,
                "metadata": dict(properties.metadata) if properties.metadata else {},
                "immutability": None
            }

            # Check immutability
            if properties.immutability_policy:
                status["immutability"] = {
                    "expiry_time": properties.immutability_policy.expiry_time.isoformat()
                        if properties.immutability_policy.expiry_time else None,
                    "policy_mode": str(properties.immutability_policy.policy_mode)
                        if properties.immutability_policy.policy_mode else None
                }

            return status

        except ResourceNotFoundError:
            return {"error": "Blob not found", "blob_name": blob_name}
        except Exception as e:
            return {"error": str(e), "blob_name": blob_name}

    def set_blob_tier(self, blob_name: str, tier: str) -> bool:
        """
        Set the storage tier for a blob.

        Args:
            blob_name: The blob to change tier
            tier: One of 'Hot', 'Cool', 'Cold', 'Archive'

        Returns:
            True if successful
        """
        if not self.blob_service_client:
            return False

        try:
            container_client = self.blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )
            blob_client = container_client.get_blob_client(blob_name)

            # Get current tier to prevent downtiering
            properties = blob_client.get_blob_properties()
            current_tier = str(properties.blob_tier) if properties.blob_tier else "Hot"

            # Define tier order (lower = hotter)
            tier_order = {"Hot": 0, "Cool": 1, "Cold": 2, "Archive": 3}

            current_order = tier_order.get(current_tier, 0)
            new_order = tier_order.get(tier, 0)

            # Don't allow uptiering (moving to hotter tier) automatically
            if new_order < current_order:
                logger.warning(
                    f"Cannot uptier blob {blob_name} from {current_tier} to {tier}. "
                    f"Uptiering requires manual intervention."
                )
                return False

            blob_client.set_standard_blob_tier(tier)

            logger.info(f"Changed blob {blob_name} tier from {current_tier} to {tier}")
            return True

        except Exception as e:
            logger.error(f"Failed to set tier on {blob_name}: {e}")
            return False

    def rename_blob(
        self,
        old_blob_name: str,
        new_blob_name: str,
        delete_original: bool = True
    ) -> Dict[str, Any]:
        """
        Rename a blob by copying to new name and optionally deleting the original.

        Azure Blob Storage doesn't support direct rename, so we:
        1. Copy the blob to the new name
        2. Copy metadata to the new blob
        3. Delete the original (if delete_original=True)

        Args:
            old_blob_name: Current blob name
            new_blob_name: New blob name (e.g., "2025-12-01_A000000008.pdf")
            delete_original: Whether to delete the original blob after copy

        Returns:
            Dict with success status, old_name, new_name
        """
        if not self.blob_service_client:
            return {"success": False, "error": "Blob service not configured"}

        try:
            container_client = self.blob_service_client.get_container_client(
                settings.AZURE_STORAGE_CONTAINER
            )

            source_blob = container_client.get_blob_client(old_blob_name)
            dest_blob = container_client.get_blob_client(new_blob_name)

            # Check if source exists
            if not source_blob.exists():
                return {
                    "success": False,
                    "error": f"Source blob not found: {old_blob_name}"
                }

            # Check if destination already exists
            if dest_blob.exists():
                return {
                    "success": False,
                    "error": f"Destination blob already exists: {new_blob_name}"
                }

            # Get source properties including metadata
            source_properties = source_blob.get_blob_properties()
            source_metadata = dict(source_properties.metadata) if source_properties.metadata else {}

            # Start copy operation
            copy_source = source_blob.url
            dest_blob.start_copy_from_url(copy_source)

            # Wait for copy to complete (for small files this is usually instant)
            import time
            max_wait = 30  # seconds
            wait_time = 0
            while wait_time < max_wait:
                props = dest_blob.get_blob_properties()
                if props.copy.status == "success":
                    break
                elif props.copy.status == "failed":
                    return {
                        "success": False,
                        "error": f"Copy failed: {props.copy.status_description}"
                    }
                time.sleep(0.5)
                wait_time += 0.5

            # Restore metadata on the new blob
            if source_metadata:
                dest_blob.set_blob_metadata(source_metadata)

            # Delete original if requested
            if delete_original:
                try:
                    source_blob.delete_blob()
                    logger.info(f"Deleted original blob: {old_blob_name}")
                except Exception as del_err:
                    # Log but don't fail - the copy succeeded
                    logger.warning(f"Could not delete original blob {old_blob_name}: {del_err}")

            logger.info(f"Renamed blob from {old_blob_name} to {new_blob_name}")

            return {
                "success": True,
                "old_name": old_blob_name,
                "new_name": new_blob_name
            }

        except HttpResponseError as e:
            if "BlobImmutable" in str(e) or "immutab" in str(e).lower():
                return {
                    "success": False,
                    "error": "Cannot rename immutable blob. Wait until immutability expires."
                }
            logger.error(f"Failed to rename blob: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Failed to rename blob: {e}")
            return {"success": False, "error": str(e)}

    def generate_standard_blob_name(
        self,
        accession_number: str,
        upload_date: datetime,
        original_filename: str
    ) -> str:
        """
        Generate a standardized blob name in format: YYYY/MM/YYYY-MM-DD_ACCESSION.ext

        Args:
            accession_number: Document accession number (e.g., "A000000008")
            upload_date: Date the document was uploaded
            original_filename: Original filename to extract extension

        Returns:
            Standardized blob name with folder structure
            (e.g., "2025/12/2025-12-01_A000000008.pdf")
        """
        # Get file extension from original filename
        ext = ""
        if "." in original_filename:
            ext = "." + original_filename.rsplit(".", 1)[-1].lower()

        # Format date components
        year = upload_date.strftime("%Y")
        month = upload_date.strftime("%m")
        date_str = upload_date.strftime("%Y-%m-%d")

        # Clean accession number (remove any path characters)
        clean_accession = accession_number.replace("/", "_").replace("\\", "_")

        # Return with folder structure: YYYY/MM/filename
        return f"{year}/{month}/{date_str}_{clean_accession}{ext}"

    def sync_container_lifecycle_policy(self) -> Dict[str, Any]:
        """
        Sync the lifecycle management policy to Azure Blob Storage container.

        This creates/updates the management policy rules for automatic tiering.
        """
        config = self.get_retention_config()

        if not self.blob_service_client:
            return {"success": False, "error": "Blob service not configured"}

        try:
            # Get the management policy client
            # Note: This requires azure-mgmt-storage for management operations
            # For now, we'll document the required policy

            policy_rules = {
                "rules": [
                    {
                        "name": "TierToCool",
                        "enabled": True,
                        "type": "Lifecycle",
                        "definition": {
                            "filters": {
                                "blobTypes": ["blockBlob"],
                                "prefixMatch": [settings.AZURE_STORAGE_CONTAINER]
                            },
                            "actions": {
                                "baseBlob": {
                                    "tierToCool": {
                                        "daysAfterModificationGreaterThan": config["cool_tier_days"]
                                    }
                                }
                            }
                        }
                    },
                    {
                        "name": "TierToCold",
                        "enabled": True,
                        "type": "Lifecycle",
                        "definition": {
                            "filters": {
                                "blobTypes": ["blockBlob"],
                                "prefixMatch": [settings.AZURE_STORAGE_CONTAINER]
                            },
                            "actions": {
                                "baseBlob": {
                                    "tierToCold": {
                                        "daysAfterModificationGreaterThan": config["cold_tier_days"]
                                    }
                                }
                            }
                        }
                    }
                ]
            }

            # Log the policy that should be applied
            logger.info(f"Lifecycle policy configuration: {policy_rules}")

            return {
                "success": True,
                "message": "Lifecycle policy configuration generated. Apply via Azure Portal or ARM template.",
                "policy": policy_rules,
                "config": config
            }

        except Exception as e:
            logger.error(f"Failed to generate lifecycle policy: {e}")
            return {"success": False, "error": str(e)}

    def sync_all_blob_metadata(
        self,
        documents: List[Any],
        progress_callback: callable = None
    ) -> Dict[str, Any]:
        """
        Sync metadata and policies for all documents.

        This recalculates expiry dates based on current retention settings
        and updates blob metadata accordingly.

        Args:
            documents: List of Document objects
            progress_callback: Optional callback for progress updates

        Returns:
            Summary of sync results
        """
        results = {
            "total": len(documents),
            "updated": 0,
            "skipped_immutable": 0,
            "skipped_no_blob": 0,
            "failed": 0,
            "errors": []
        }

        for i, doc in enumerate(documents):
            if progress_callback:
                progress_callback(i + 1, len(documents), doc.accession_number)

            # Skip documents without blob
            if not doc.blob_name:
                results["skipped_no_blob"] += 1
                continue

            try:
                # Get extracted data if available
                extracted_data = None
                if doc.extracted_data:
                    import json
                    try:
                        extracted_data = json.loads(doc.extracted_data)
                        # If data is encrypted, we might need to decrypt it
                        # This would require the encryption service
                    except json.JSONDecodeError:
                        pass

                # Try to set metadata
                success = self.set_blob_metadata_full(
                    blob_name=doc.blob_name,
                    document_id=doc.id,
                    accession_number=doc.accession_number,
                    import_date=doc.upload_date,
                    extracted_data=extracted_data,
                    source=doc.source
                )

                if success:
                    results["updated"] += 1
                else:
                    results["skipped_immutable"] += 1

            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "accession_number": doc.accession_number,
                    "error": str(e)
                })

        return results


# Singleton instance
_lifecycle_service: Optional[BlobLifecycleService] = None


def get_lifecycle_service(db: Session) -> BlobLifecycleService:
    """Get or create lifecycle service instance."""
    return BlobLifecycleService(db)
