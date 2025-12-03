"""Integration management service."""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from app.models.integration import Integration, ApiKey, IntegrationLog
from app.models.document import Document

logger = logging.getLogger(__name__)


class IntegrationService:
    """Service for managing external integrations."""

    # Integration type configurations
    # NOTE: These are configured to receive data via webhook/API.
    # For complex integrations (M365, Monday.com, etc.), use Azure Logic Apps
    # or Azure Functions to connect to the source, then push to our webhook endpoint.
    INTEGRATION_CONFIGS = {
        Integration.TYPE_REST_API: {
            "name": "REST API (Outbound)",
            "description": "Push processed documents to external REST APIs",
            "icon": "bi-cloud-arrow-up",
            "config_fields": [
                {"key": "url", "label": "API URL", "type": "url", "required": True},
                {"key": "method", "label": "HTTP Method", "type": "select", "options": ["POST", "PUT"], "default": "POST"},
                {"key": "auth_type", "label": "Authentication", "type": "select", "options": ["none", "api_key", "bearer", "basic"], "default": "api_key"},
                {"key": "auth_header", "label": "Auth Header Name", "type": "text", "default": "Authorization"},
                {"key": "auth_value", "label": "Auth Value/Token", "type": "password"},
                {"key": "trigger_on", "label": "Trigger On", "type": "select", "options": ["approved", "extracted", "all"], "default": "approved"},
            ],
            "mcp_available": False,
            "direction": "outbound",
        },
        Integration.TYPE_CSV_UPLOAD: {
            "name": "CSV Upload",
            "description": "Accept CSV file uploads for batch document import",
            "icon": "bi-file-earmark-spreadsheet",
            "config_fields": [
                {"key": "delimiter", "label": "Delimiter", "type": "select", "options": [",", ";", "|", "\\t"], "default": ","},
                {"key": "encoding", "label": "Encoding", "type": "select", "options": ["utf-8", "utf-16", "latin-1", "cp1252"], "default": "utf-8"},
                {"key": "has_header", "label": "Has Header Row", "type": "boolean", "default": True},
                {"key": "skip_rows", "label": "Skip Rows", "type": "number", "default": 0},
            ],
            "mcp_available": False,
            "direction": "inbound",
        },
        Integration.TYPE_CSV_PICKUP: {
            "name": "CSV Blob Pickup",
            "description": "Monitor blob container for CSV files (use Azure Function for other sources)",
            "icon": "bi-folder-symlink",
            "config_fields": [
                {"key": "container_path", "label": "Container/Folder Path", "type": "text", "required": True},
                {"key": "file_pattern", "label": "File Pattern", "type": "text", "default": "*.csv"},
                {"key": "archive_processed", "label": "Archive Processed Files", "type": "boolean", "default": True},
                {"key": "delimiter", "label": "Delimiter", "type": "select", "options": [",", ";", "|", "\\t"], "default": ","},
            ],
            "mcp_available": False,
            "direction": "inbound",
            "azure_recommendation": "Use Azure Function with Blob Trigger for SFTP/FTP sources",
        },
        Integration.TYPE_M365_EMAIL: {
            "name": "Microsoft 365 Email",
            "description": "Receive documents from shared mailbox via Logic App",
            "icon": "bi-envelope",
            "config_fields": [
                {"key": "mailbox", "label": "Mailbox Address (for reference)", "type": "email"},
                {"key": "folder", "label": "Folder Monitored", "type": "text", "default": "Inbox"},
            ],
            "mcp_available": False,
            "direction": "inbound",
            "azure_recommendation": "Use Azure Logic App with Office 365 connector to monitor mailbox and push attachments to this app's webhook",
            "logic_app_template": "m365_email_to_webhook",
        },
        Integration.TYPE_MONDAY_COM: {
            "name": "Monday.com",
            "description": "Sync with Monday.com boards via Logic App or MCP",
            "icon": "bi-kanban",
            "config_fields": [
                {"key": "board_id", "label": "Board ID (for reference)", "type": "text"},
                {"key": "sync_direction", "label": "Sync Direction", "type": "select", "options": ["inbound", "outbound", "bidirectional"], "default": "bidirectional"},
                {"key": "monday_token", "label": "Monday.com API Token (for MCP)", "type": "password"},
            ],
            "mcp_available": True,
            "mcp_server": "monday-api",
            "mcp_package": "@mondaydotcomorg/monday-api-mcp",
            "mcp_env_vars": ["monday_token"],
            "direction": "bidirectional",
            "azure_recommendation": "Use Azure Logic App with Monday.com connector for bidirectional sync, or enable MCP for direct AI-assisted access",
            "logic_app_template": "monday_sync",
        },
        Integration.TYPE_WEBHOOK_INBOUND: {
            "name": "Inbound Webhook",
            "description": "Receive data from Logic Apps, Azure Functions, or external systems",
            "icon": "bi-broadcast",
            "config_fields": [
                {"key": "secret", "label": "Webhook Secret (for verification)", "type": "password"},
                {"key": "verify_signature", "label": "Verify Signature", "type": "boolean", "default": False},
                {"key": "signature_header", "label": "Signature Header", "type": "text", "default": "X-Webhook-Signature"},
                {"key": "payload_format", "label": "Expected Payload Format", "type": "select", "options": ["json", "form", "multipart"], "default": "json"},
            ],
            "mcp_available": False,
            "direction": "inbound",
            "azure_recommendation": "This is the recommended endpoint for Logic Apps and Azure Functions to push data",
        },
        Integration.TYPE_LIMS: {
            "name": "LIMS (Laboratory Information Management System)",
            "description": "Connect to StarLIMS, LabWare, or other LIMS systems",
            "icon": "bi-clipboard2-pulse",
            "config_fields": [
                {"key": "lims_type", "label": "LIMS Type", "type": "select", "options": ["starlims", "labware", "epic_beaker", "sunquest", "cerner", "other"], "default": "starlims"},
                {"key": "api_url", "label": "LIMS API URL", "type": "url"},
                {"key": "api_version", "label": "API Version", "type": "text", "default": "1.0"},
                {"key": "auth_type", "label": "Authentication", "type": "select", "options": ["api_key", "oauth2", "basic", "certificate"], "default": "api_key"},
                {"key": "auth_value", "label": "Auth Credentials", "type": "password"},
            ],
            "mcp_available": False,  # No official StarLIMS MCP yet - would require custom development
            "mcp_note": "StarLIMS LPH 1.1 MCP not available - custom MCP development may be required",
            "direction": "bidirectional",
            "azure_recommendation": "Use Azure Function with LIMS-specific SDK or REST API to bridge to webhook",
        },
        Integration.TYPE_AZURE_SERVICES: {
            "name": "Azure Services",
            "description": "Direct integration with Azure resources (Storage, OpenAI, etc.)",
            "icon": "bi-cloud",
            "config_fields": [
                {"key": "service_type", "label": "Azure Service", "type": "select", "options": ["openai", "storage", "cosmos", "sql", "functions"], "default": "openai"},
                {"key": "resource_name", "label": "Resource Name", "type": "text"},
                {"key": "subscription_id", "label": "Subscription ID", "type": "text"},
                {"key": "resource_group", "label": "Resource Group", "type": "text"},
            ],
            "mcp_available": True,
            "mcp_server": "azure",
            "mcp_package": "@azure/mcp",
            "mcp_env_vars": [],  # Uses Azure CLI / DefaultAzureCredential
            "direction": "bidirectional",
            "azure_recommendation": "Uses Azure MCP Server for AI-assisted access to Azure resources",
        },
    }

    # Available MCP servers that can be installed
    AVAILABLE_MCPS = {
        "azure": {
            "name": "Azure MCP Server",
            "package": "@azure/mcp",
            "description": "AI-assisted access to Azure resources (Storage, OpenAI, SQL, etc.)",
            "icon": "bi-cloud",
            "command": "npx -y @azure/mcp@latest",
            "env_vars": [],
            "auth_method": "Azure CLI / DefaultAzureCredential",
            "docs_url": "https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/",
        },
        "monday-api": {
            "name": "Monday.com MCP",
            "package": "@mondaydotcomorg/monday-api-mcp",
            "description": "AI-assisted access to Monday.com boards and items",
            "icon": "bi-kanban",
            "command": "npx -y @mondaydotcomorg/monday-api-mcp",
            "env_vars": ["monday_token"],
            "auth_method": "Monday.com API Token",
            "docs_url": "https://github.com/mondaycom/monday-ai/tree/master/packages/monday-api-mcp",
        },
    }

    # Default field mapping template
    DEFAULT_FIELD_MAPPING = {
        "accession_number": None,
        "patient_name": None,
        "patient_dob": None,
        "medical_record_number": None,
        "ordering_physician": None,
        "facility_name": None,
        "facility_id": None,
        "collection_date": None,
        "specimen_type": None,
        "tests_requested": None,
        "special_instructions": None,
    }

    def __init__(self, db: Session):
        self.db = db

    def get_integration_types(self) -> List[Dict[str, Any]]:
        """Get all available integration types with their configurations."""
        return [
            {
                "type": int_type,
                **config
            }
            for int_type, config in self.INTEGRATION_CONFIGS.items()
        ]

    def get_available_mcps(self) -> List[Dict[str, Any]]:
        """Get all available MCP servers with their configurations."""
        return [
            {
                "server_name": server_name,
                **config
            }
            for server_name, config in self.AVAILABLE_MCPS.items()
        ]

    def get_mcp_status(self) -> Dict[str, Any]:
        """
        Get the status of all MCP servers.

        Returns info about which MCPs are installed, enabled, and their connection status.
        """
        import subprocess

        mcp_status = {}

        for server_name, config in self.AVAILABLE_MCPS.items():
            status = {
                "server_name": server_name,
                "name": config["name"],
                "package": config["package"],
                "description": config["description"],
                "icon": config["icon"],
                "installed": False,
                "enabled": True,  # Default to enabled if installed
                "connected": False,
                "auth_method": config["auth_method"],
                "env_vars": config["env_vars"],
                "docs_url": config["docs_url"],
            }

            # Check if MCP is installed by looking at claude mcp list
            try:
                result = subprocess.run(
                    ["claude", "mcp", "list"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if server_name in result.stdout:
                    status["installed"] = True
                    # Check if it shows as connected
                    if f"{server_name}:" in result.stdout and "Failed" not in result.stdout.split(server_name)[1].split("\n")[0]:
                        status["connected"] = True
            except Exception:
                pass

            mcp_status[server_name] = status

        return mcp_status

    def create_integration(
        self,
        name: str,
        integration_type: str,
        description: str = None,
        config: Dict[str, Any] = None,
        created_by: str = None
    ) -> Integration:
        """Create a new integration."""
        if integration_type not in Integration.VALID_TYPES:
            raise ValueError(f"Invalid integration type: {integration_type}")

        integration = Integration(
            name=name,
            description=description,
            integration_type=integration_type,
            status=Integration.STATUS_PENDING,  # Always start in pending
            config=config or {},
            field_mapping=self.DEFAULT_FIELD_MAPPING.copy(),
            created_by=created_by
        )

        # Check if MCP is available for this type
        type_config = self.INTEGRATION_CONFIGS.get(integration_type, {})
        if type_config.get("mcp_available"):
            integration.mcp_server_name = type_config.get("mcp_server")

        self.db.add(integration)
        self.db.commit()
        self.db.refresh(integration)

        logger.info(f"Created integration {integration.id}: {name} ({integration_type})")
        return integration

    def get_integration(self, integration_id: int) -> Optional[Integration]:
        """Get an integration by ID."""
        return self.db.query(Integration).filter(Integration.id == integration_id).first()

    def get_all_integrations(self) -> List[Integration]:
        """Get all integrations."""
        return self.db.query(Integration).order_by(Integration.created_at.desc()).all()

    def get_integrations_by_type(self, integration_type: str) -> List[Integration]:
        """Get all integrations of a specific type."""
        return self.db.query(Integration).filter(
            Integration.integration_type == integration_type
        ).all()

    def get_active_integrations(self) -> List[Integration]:
        """Get all active integrations."""
        return self.db.query(Integration).filter(
            Integration.status == Integration.STATUS_ACTIVE
        ).all()

    def update_integration(
        self,
        integration_id: int,
        updates: Dict[str, Any],
        updated_by: str = None
    ) -> Optional[Integration]:
        """Update an integration."""
        integration = self.get_integration(integration_id)
        if not integration:
            return None

        # Allowed fields to update
        allowed_fields = [
            "name", "description", "config", "field_mapping",
            "mcp_enabled", "mcp_server_name"
        ]

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(integration, field, value)

        integration.updated_by = updated_by
        self.db.commit()
        self.db.refresh(integration)

        logger.info(f"Updated integration {integration_id}")
        return integration

    def update_integration_status(
        self,
        integration_id: int,
        status: str,
        updated_by: str = None
    ) -> Optional[Integration]:
        """Update integration status."""
        if status not in Integration.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")

        integration = self.get_integration(integration_id)
        if not integration:
            return None

        old_status = integration.status
        integration.status = status
        integration.updated_by = updated_by
        self.db.commit()

        logger.info(f"Integration {integration_id} status changed: {old_status} -> {status}")
        return integration

    def delete_integration(self, integration_id: int) -> bool:
        """Delete an integration."""
        integration = self.get_integration(integration_id)
        if not integration:
            return False

        self.db.delete(integration)
        self.db.commit()

        logger.info(f"Deleted integration {integration_id}")
        return True

    def update_field_mapping(
        self,
        integration_id: int,
        field_mapping: Dict[str, Any],
        updated_by: str = None
    ) -> Optional[Integration]:
        """Update the field mapping for an integration."""
        integration = self.get_integration(integration_id)
        if not integration:
            return None

        integration.field_mapping = field_mapping
        integration.updated_by = updated_by
        self.db.commit()
        self.db.refresh(integration)

        return integration

    def test_integration_sample(
        self,
        integration_id: int,
        sample_data: str
    ) -> Dict[str, Any]:
        """
        Test an integration with sample data.

        This parses the sample and applies field mapping to show what the result would be.
        Data is NOT processed into the system.
        """
        integration = self.get_integration(integration_id)
        if not integration:
            return {"success": False, "error": "Integration not found"}

        try:
            # Store the sample
            integration.sample_payload = sample_data
            integration.last_sample_test = datetime.utcnow()

            # Parse based on integration type
            parsed_data = self._parse_sample(integration, sample_data)

            if not parsed_data.get("success"):
                integration.sample_result = {"error": parsed_data.get("error")}
                self.db.commit()
                return parsed_data

            # Apply field mapping
            mapped_data = self._apply_field_mapping(
                integration.field_mapping or {},
                parsed_data.get("data", {})
            )

            result = {
                "success": True,
                "raw_fields": list(parsed_data.get("data", {}).keys()),
                "mapped_data": mapped_data,
                "unmapped_fields": [
                    k for k, v in (integration.field_mapping or {}).items()
                    if v is None
                ],
                "sample_record_count": parsed_data.get("record_count", 1)
            }

            integration.sample_result = result
            self.db.commit()

            return result

        except Exception as e:
            logger.error(f"Sample test failed for integration {integration_id}: {e}")
            error_result = {"success": False, "error": str(e)}
            integration.sample_result = error_result
            self.db.commit()
            return error_result

    def _parse_sample(self, integration: Integration, sample_data: str) -> Dict[str, Any]:
        """Parse sample data based on integration type."""
        int_type = integration.integration_type

        if int_type in [Integration.TYPE_CSV_UPLOAD, Integration.TYPE_CSV_PICKUP]:
            return self._parse_csv_sample(integration, sample_data)
        elif int_type in [Integration.TYPE_REST_API, Integration.TYPE_WEBHOOK_INBOUND]:
            return self._parse_json_sample(sample_data)
        elif int_type == Integration.TYPE_M365_EMAIL:
            return self._parse_email_sample(sample_data)
        elif int_type == Integration.TYPE_MONDAY_COM:
            return self._parse_json_sample(sample_data)
        else:
            return {"success": False, "error": f"Unknown integration type: {int_type}"}

    def _parse_csv_sample(self, integration: Integration, sample_data: str) -> Dict[str, Any]:
        """Parse CSV sample data."""
        import csv
        from io import StringIO

        config = integration.config or {}
        delimiter = config.get("delimiter", ",")
        if delimiter == "\\t":
            delimiter = "\t"

        try:
            reader = csv.DictReader(StringIO(sample_data), delimiter=delimiter)
            rows = list(reader)

            if not rows:
                return {"success": False, "error": "No data rows found in CSV"}

            # Return first row as sample
            return {
                "success": True,
                "data": rows[0],
                "record_count": len(rows),
                "columns": list(rows[0].keys())
            }
        except Exception as e:
            return {"success": False, "error": f"CSV parsing error: {str(e)}"}

    def _parse_json_sample(self, sample_data: str) -> Dict[str, Any]:
        """Parse JSON sample data."""
        try:
            data = json.loads(sample_data)

            # Handle array of records
            if isinstance(data, list):
                if not data:
                    return {"success": False, "error": "Empty JSON array"}
                return {
                    "success": True,
                    "data": data[0],
                    "record_count": len(data)
                }

            return {
                "success": True,
                "data": data,
                "record_count": 1
            }
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON parsing error: {str(e)}"}

    def _parse_email_sample(self, sample_data: str) -> Dict[str, Any]:
        """Parse email sample (simplified)."""
        # For now, treat as JSON with email fields
        return self._parse_json_sample(sample_data)

    def _apply_field_mapping(
        self,
        field_mapping: Dict[str, Any],
        source_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply field mapping to source data."""
        result = {}

        for target_field, source_field in field_mapping.items():
            if source_field and source_field in source_data:
                result[target_field] = source_data[source_field]
            else:
                result[target_field] = None

        return result

    def log_integration_event(
        self,
        integration_id: int,
        event_type: str,
        success: bool = True,
        request_summary: str = None,
        response_summary: str = None,
        error_message: str = None,
        document_id: int = None,
        processing_time_ms: int = None
    ) -> IntegrationLog:
        """Log an integration event."""
        log = IntegrationLog(
            integration_id=integration_id,
            event_type=event_type,
            success=success,
            request_summary=request_summary,
            response_summary=response_summary,
            error_message=error_message,
            document_id=document_id,
            processing_time_ms=processing_time_ms
        )

        self.db.add(log)

        # Update integration statistics
        integration = self.get_integration(integration_id)
        if integration:
            integration.total_received += 1
            if success:
                integration.total_processed += 1
            else:
                integration.total_errors += 1
                integration.last_error = error_message
                integration.last_error_at = datetime.utcnow()
            integration.last_received_at = datetime.utcnow()

        self.db.commit()
        return log

    def get_integration_logs(
        self,
        integration_id: int,
        limit: int = 100
    ) -> List[IntegrationLog]:
        """Get logs for an integration."""
        return self.db.query(IntegrationLog).filter(
            IntegrationLog.integration_id == integration_id
        ).order_by(IntegrationLog.created_at.desc()).limit(limit).all()


class ApiKeyService:
    """Service for managing API keys."""

    def __init__(self, db: Session):
        self.db = db

    def create_api_key(
        self,
        name: str,
        description: str = None,
        integration_id: int = None,
        scopes: List[str] = None,
        expires_at: datetime = None,
        rate_limit_per_minute: int = 60,
        rate_limit_per_day: int = 10000,
        created_by: str = None
    ) -> tuple:
        """
        Create a new API key.

        Returns:
            Tuple of (ApiKey, full_key)
            The full_key is shown once and should be copied by the user.
        """
        # Generate the key
        full_key, prefix, key_hash = ApiKey.generate_key()

        api_key = ApiKey(
            name=name,
            description=description,
            key_prefix=prefix,
            key_hash=key_hash,
            integration_id=integration_id,
            scopes=scopes or [ApiKey.SCOPE_DOCUMENTS_CREATE, ApiKey.SCOPE_WEBHOOK_RECEIVE],
            expires_at=expires_at,
            rate_limit_per_minute=rate_limit_per_minute,
            rate_limit_per_day=rate_limit_per_day,
            created_by=created_by
        )

        self.db.add(api_key)
        self.db.commit()
        self.db.refresh(api_key)

        logger.info(f"Created API key {api_key.id} ({prefix}...) for {name}")
        return api_key, full_key

    def get_api_key(self, key_id: int) -> Optional[ApiKey]:
        """Get an API key by ID."""
        return self.db.query(ApiKey).filter(ApiKey.id == key_id).first()

    def get_api_key_by_prefix(self, prefix: str) -> Optional[ApiKey]:
        """Get an API key by its prefix."""
        return self.db.query(ApiKey).filter(ApiKey.key_prefix == prefix).first()

    def validate_api_key(self, key: str) -> Optional[ApiKey]:
        """
        Validate an API key and return it if valid.

        Also updates last_used_at and usage_count.
        """
        if not key or len(key) < 8:
            return None

        prefix = key[:8]
        api_key = self.get_api_key_by_prefix(prefix)

        if not api_key:
            return None

        if not api_key.verify_key(key):
            return None

        if not api_key.is_valid():
            return None

        # Update usage stats
        api_key.last_used_at = datetime.utcnow()
        api_key.usage_count += 1
        self.db.commit()

        return api_key

    def get_all_api_keys(self) -> List[ApiKey]:
        """Get all API keys."""
        return self.db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()

    def get_api_keys_for_integration(self, integration_id: int) -> List[ApiKey]:
        """Get all API keys for a specific integration."""
        return self.db.query(ApiKey).filter(
            ApiKey.integration_id == integration_id
        ).all()

    def revoke_api_key(self, key_id: int, revoked_by: str = None) -> bool:
        """Revoke an API key."""
        api_key = self.get_api_key(key_id)
        if not api_key:
            return False

        api_key.is_active = False
        api_key.revoked_at = datetime.utcnow()
        api_key.revoked_by = revoked_by
        self.db.commit()

        logger.info(f"Revoked API key {key_id}")
        return True

    def delete_api_key(self, key_id: int) -> bool:
        """Delete an API key."""
        api_key = self.get_api_key(key_id)
        if not api_key:
            return False

        self.db.delete(api_key)
        self.db.commit()

        logger.info(f"Deleted API key {key_id}")
        return True
