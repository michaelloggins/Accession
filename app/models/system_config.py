"""System configuration model."""

from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class SystemConfig(Base):
    """System configuration key-value store."""

    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    value_type = Column(String(20), default="string")  # int, float, bool, string, json
    description = Column(String(500), nullable=True)
    category = Column(String(50), nullable=True)  # extraction, security, integration, etc.
    display_order = Column(String(10), default="999")  # For UI ordering
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(100), nullable=True)

    # Default configuration values
    DEFAULTS = {
        # Extraction Settings
        "EXTRACTION_BATCH_SIZE": {
            "value": "5",
            "value_type": "int",
            "description": "Maximum documents to process in a single AI extraction batch",
            "category": "extraction",
            "display_order": "010"
        },
        "EXTRACTION_POLL_INTERVAL": {
            "value": "10",
            "value_type": "int",
            "description": "Seconds between background worker polling cycles",
            "category": "extraction",
            "display_order": "020"
        },
        "EXTRACTION_MAX_RETRIES": {
            "value": "3",
            "value_type": "int",
            "description": "Maximum retry attempts before splitting a failed batch",
            "category": "extraction",
            "display_order": "030"
        },
        "AUTO_APPROVE_THRESHOLD": {
            "value": "0.90",
            "value_type": "float",
            "description": "Confidence threshold for automatic document approval (0.0-1.0)",
            "category": "extraction",
            "display_order": "040"
        },
        "URGENT_REVIEW_THRESHOLD": {
            "value": "0.70",
            "value_type": "float",
            "description": "Confidence threshold below which documents are flagged for urgent review",
            "category": "extraction",
            "display_order": "050"
        },
        # Security Settings
        "SESSION_TIMEOUT_MINUTES": {
            "value": "15",
            "value_type": "int",
            "description": "User session timeout in minutes",
            "category": "security",
            "display_order": "010"
        },
        "MAX_LOGIN_ATTEMPTS": {
            "value": "5",
            "value_type": "int",
            "description": "Maximum failed login attempts before account lockout",
            "category": "security",
            "display_order": "020"
        },
        "ACCOUNT_LOCKOUT_MINUTES": {
            "value": "30",
            "value_type": "int",
            "description": "Account lockout duration in minutes",
            "category": "security",
            "display_order": "030"
        },
        # Document Settings
        "MAX_FILE_SIZE_MB": {
            "value": "25",
            "value_type": "int",
            "description": "Maximum file size for uploads in megabytes",
            "category": "documents",
            "display_order": "010"
        },
        "BULK_UPLOAD_THRESHOLD": {
            "value": "4",
            "value_type": "int",
            "description": "Number of files above which uploads use server-side background processing",
            "category": "documents",
            "display_order": "020"
        },
        # Compliance Settings
        "AUDIT_LOG_RETENTION_DAYS": {
            "value": "2555",
            "value_type": "int",
            "description": "Days to retain audit logs (7 years = 2555 days for HIPAA)",
            "category": "compliance",
            "display_order": "010"
        },
        "PHI_ACCESS_ALERT_THRESHOLD": {
            "value": "50",
            "value_type": "int",
            "description": "Alert when user accesses more than this many PHI records per hour",
            "category": "compliance",
            "display_order": "020"
        },
        "AUDIT_LOG_ENABLED": {
            "value": "true",
            "value_type": "bool",
            "description": "Enable audit logging for all user actions",
            "category": "compliance",
            "display_order": "005"
        },
        "AUDIT_LOG_PHI_ACCESS": {
            "value": "true",
            "value_type": "bool",
            "description": "Track which PHI fields are accessed (patient name, DOB, SSN, etc.)",
            "category": "compliance",
            "display_order": "015"
        },
        "AUDIT_LOG_REQUEST_BODY": {
            "value": "false",
            "value_type": "bool",
            "description": "Include sanitized request body in audit logs (increases storage)",
            "category": "compliance",
            "display_order": "025"
        },
        "AUDIT_LOG_FAILED_ONLY": {
            "value": "false",
            "value_type": "bool",
            "description": "Only log failed actions (reduces volume, not HIPAA compliant)",
            "category": "compliance",
            "display_order": "030"
        },
        "AUDIT_LOG_ACTIONS": {
            "value": "LOGIN,LOGOUT,CREATE,VIEW,UPDATE,DELETE,APPROVE,EXPORT,QUEUE_REEXTRACT",
            "value_type": "str",
            "description": "Comma-separated list of actions to audit (empty = all actions)",
            "category": "compliance",
            "display_order": "035"
        },
        "AUDIT_ALERT_EMAIL": {
            "value": "",
            "value_type": "str",
            "description": "Email address to notify when suspicious activity is detected",
            "category": "compliance",
            "display_order": "040"
        },
        "AUDIT_IP_TRACKING": {
            "value": "true",
            "value_type": "bool",
            "description": "Record IP addresses in audit logs",
            "category": "compliance",
            "display_order": "045"
        },
        "AUDIT_USER_AGENT_TRACKING": {
            "value": "true",
            "value_type": "bool",
            "description": "Record browser/user agent in audit logs",
            "category": "compliance",
            "display_order": "050"
        },
        # Azure Storage Settings
        "AZURE_STORAGE_CONTAINER": {
            "value": "documents",
            "value_type": "str",
            "description": "Name of the Azure Blob Storage container for document uploads. Note: Also update AZURE_STORAGE_CONTAINER in Azure App Settings for changes to take effect.",
            "category": "storage",
            "display_order": "005"
        },
        # Blob Watcher Settings
        "BLOB_WATCH_ENABLED": {
            "value": "true",
            "value_type": "bool",
            "description": "Enable automatic monitoring of blob storage for new documents",
            "category": "blob_watcher",
            "display_order": "010"
        },
        "BLOB_WATCH_POLL_INTERVAL": {
            "value": "30",
            "value_type": "int",
            "description": "Seconds between blob container polling cycles",
            "category": "blob_watcher",
            "display_order": "020"
        },
        # Processing Mode Settings
        "AUTO_EXTRACT_ENABLED": {
            "value": "true",
            "value_type": "bool",
            "description": "When enabled, new documents are automatically queued for AI extraction. When disabled, documents require manual 'Re-Extract with AI' action.",
            "category": "extraction",
            "display_order": "005"
        },
        # Azure OpenAI Settings
        "AZURE_OPENAI_TEMPERATURE": {
            "value": "0.1",
            "value_type": "float",
            "description": "Temperature for AI extraction (0.0-1.0). Lower values = more consistent/deterministic results.",
            "category": "azure_openai",
            "display_order": "010"
        },
        "AZURE_OPENAI_MAX_TOKENS": {
            "value": "2000",
            "value_type": "int",
            "description": "Maximum tokens for single document AI extraction response",
            "category": "azure_openai",
            "display_order": "020"
        },
        "AZURE_OPENAI_MAX_TOKENS_BATCH": {
            "value": "4000",
            "value_type": "int",
            "description": "Maximum tokens for batch document AI extraction response",
            "category": "azure_openai",
            "display_order": "030"
        },
        "DEFAULT_CONFIDENCE_SCORE": {
            "value": "0.85",
            "value_type": "float",
            "description": "Default confidence score when AI does not return one (0.0-1.0)",
            "category": "azure_openai",
            "display_order": "040"
        },
        # API & Integration Settings
        "HTTP_TIMEOUT_SECONDS": {
            "value": "30",
            "value_type": "int",
            "description": "Default timeout in seconds for external API calls (Lab system, FedEx, etc.)",
            "category": "integration",
            "display_order": "010"
        },
        "FEDEX_API_BASE_URL": {
            "value": "https://apis.fedex.com",
            "value_type": "string",
            "description": "FedEx API base URL (production: https://apis.fedex.com, sandbox: https://apis-sandbox.fedex.com)",
            "category": "integration",
            "display_order": "020"
        },
        "DEFAULT_PAGINATION_LIMIT": {
            "value": "50",
            "value_type": "int",
            "description": "Default number of records per page in document listings",
            "category": "documents",
            "display_order": "030"
        },
        # Storage Lifecycle & Retention Settings
        "DOCUMENT_RETENTION_YEARS": {
            "value": "7",
            "value_type": "int",
            "description": "Document retention period in years. Files become deletable after this period + 1 day.",
            "category": "storage_lifecycle",
            "display_order": "010"
        },
        "STORAGE_TIER_COOL_DAYS": {
            "value": "60",
            "value_type": "int",
            "description": "Days after upload before moving document to Cool storage tier (cost savings for infrequent access)",
            "category": "storage_lifecycle",
            "display_order": "020"
        },
        "STORAGE_TIER_COLD_DAYS": {
            "value": "365",
            "value_type": "int",
            "description": "Days after upload before moving document to Cold/Archive storage tier (lowest cost, rare access)",
            "category": "storage_lifecycle",
            "display_order": "030"
        },
        "BLOB_IMMUTABILITY_ENABLED": {
            "value": "true",
            "value_type": "bool",
            "description": "Enable WORM (Write Once Read Many) immutability on blobs for compliance",
            "category": "storage_lifecycle",
            "display_order": "040"
        },
        "STORAGE_LIFECYCLE_AUTO_SYNC": {
            "value": "true",
            "value_type": "bool",
            "description": "Automatically sync lifecycle policy changes to Azure Blob Storage",
            "category": "storage_lifecycle",
            "display_order": "050"
        },
        # AI Service Settings
        "AI_SERVICE_CONFIG": {
            "value": '{"doc_intel_classify": true, "openai_extract": true, "learning_mode": false}',
            "value_type": "string",
            "description": "AI service configuration: Document Intelligence classification, OpenAI extraction, and learning mode settings",
            "category": "integration",
            "display_order": "005"
        },
    }
