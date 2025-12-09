"""
Application Configuration Settings
HIPAA-Compliant Lab Document Intelligence System
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Application
    APP_NAME: str = "Lab Document Intelligence System"
    APP_VERSION: str = "1.0.0"
    SECRET_KEY: str = "change-this-in-production"

    # Database
    DATABASE_URL: str = "mssql+pyodbc://user:password@server/database?driver=ODBC+Driver+17+for+SQL+Server"

    # Azure Blob Storage
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_STORAGE_CONTAINER: str = "documents"
    BLOB_SAS_EXPIRY_HOURS: int = 1

    # Azure Key Vault
    AZURE_KEY_VAULT_URL: str = ""
    ENCRYPTION_KEY_NAME: str = "phi-encryption-key"
    PHI_ENCRYPTION_KEY: str = ""  # Direct encryption key (fallback if Key Vault unavailable)

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-4-vision"
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"

    # Azure Document Intelligence (Form Recognizer)
    AZURE_DOC_INTELLIGENCE_ENDPOINT: str = ""
    AZURE_DOC_INTELLIGENCE_KEY: str = ""
    AZURE_DOC_INTELLIGENCE_CLASSIFIER_ID: str = ""  # Custom classifier model ID

    # Microsoft Universal Print (via Graph API)
    UNIVERSAL_PRINT_ENABLED: bool = False
    # Uses existing Azure AD credentials for Graph API authentication
    # Required Graph API permissions: PrintJob.Create, Printer.Read.All

    # Authentication
    JWT_SECRET_KEY: str = "change-this-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    SESSION_TIMEOUT_MINUTES: int = 15

    # Azure AD / Entra ID - OIDC Authentication
    AZURE_AD_TENANT_ID: str = ""
    AZURE_AD_CLIENT_ID: str = ""
    AZURE_AD_CLIENT_SECRET: str = ""
    AZURE_AD_REDIRECT_URI: str = ""  # e.g., https://your-app.azurewebsites.net/api/auth/callback

    # Entra ID Group-to-Role Mapping (Object IDs of Azure AD Security Groups)
    AZURE_AD_ADMIN_GROUP_ID: str = ""      # "Accession - Admin" -> admin role
    AZURE_AD_REVIEWER_GROUP_ID: str = ""   # "Accession - PowerUser" -> reviewer role
    AZURE_AD_LAB_STAFF_GROUP_ID: str = ""  # "Accession - LabStaff" -> lab_staff role
    AZURE_AD_READONLY_GROUP_ID: str = ""   # "Accession - User" -> read_only role

    # SSO Configuration
    SSO_ENABLED: bool = True  # Enable/disable Entra ID SSO
    SSO_DEFAULT_ROLE: str = "read_only"  # Default role if user not in any mapped group
    SSO_REQUIRE_GROUP_MEMBERSHIP: bool = True  # Deny access if user is not in any mapped group
    SSO_METHOD: str = "saml"  # "saml" or "oidc" - authentication method

    # SAML Configuration
    SAML_ENTITY_ID: str = ""  # Application entity ID (usually app URL)
    SAML_ACS_URL: str = ""  # Assertion Consumer Service URL
    SAML_SLO_URL: str = ""  # Single Logout URL
    SAML_METADATA_URL: str = ""  # IdP metadata URL for auto-configuration
    SAML_IDP_ENTITY_ID: str = ""  # Identity Provider entity ID
    SAML_IDP_SSO_URL: str = ""  # IdP Single Sign-On URL
    SAML_IDP_SLO_URL: str = ""  # IdP Single Logout URL
    SAML_IDP_CERT: str = ""  # IdP X.509 certificate (base64 encoded)
    SAML_SP_CERT: str = ""  # Service Provider certificate (optional)
    SAML_SP_KEY: str = ""  # Service Provider private key (optional)
    SAML_SIGN_REQUESTS: bool = False  # Sign authentication requests
    SAML_WANT_ASSERTIONS_SIGNED: bool = True  # Require signed assertions
    SAML_WANT_RESPONSE_SIGNED: bool = True  # Require signed responses

    # SCIM Provisioning
    SCIM_BEARER_TOKEN: str = ""  # Secret token for SCIM endpoint authentication

    # Security
    ALLOWED_ORIGINS: List[str] = ["http://localhost:8000"]
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 30
    PASSWORD_MIN_LENGTH: int = 12

    # Document Processing
    MAX_FILE_SIZE_MB: int = 25
    SUPPORTED_FILE_TYPES: List[str] = [".pdf", ".tiff", ".tif", ".png", ".jpg", ".jpeg"]
    AUTO_APPROVE_THRESHOLD: float = 0.90
    URGENT_REVIEW_THRESHOLD: float = 0.70

    # Lab Integration
    LAB_SYSTEM_API_URL: str = ""
    LAB_SYSTEM_API_KEY: str = ""
    LAB_SUBMISSION_RETRIES: int = 3
    LAB_RETRY_BACKOFF_SECONDS: List[int] = [1, 2, 4]

    # Compliance
    AUDIT_LOG_RETENTION_DAYS: int = 2555  # 7 years
    DOCUMENT_RETENTION_DAYS: int = 2555  # 7 years
    PHI_ACCESS_ALERT_THRESHOLD: int = 50

    # Email Alerts
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    ADMIN_EMAIL: str = ""

    # Google Places API
    GOOGLE_PLACES_API_KEY: str = ""

    # FedEx Address Validation API
    FEDEX_API_KEY: str = ""
    FEDEX_API_SECRET: str = ""
    FEDEX_ACCOUNT_NUMBER: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

PHI_FIELDS = [
    "patient_name",
    "date_of_birth",
    "ssn",
    "address",
    "patient_address",
    "phone",
    "patient_phone",
    "email",
    "patient_email",
    "policy_number",
    "medical_record_number"
]

ROLES = {
    "admin": {
        "name": "Administrator",
        "permissions": ["upload", "view", "edit", "approve", "reject", "submit", "audit", "reports", "users", "config"]
    },
    "reviewer": {
        "name": "Reviewer",
        "permissions": ["upload", "view", "edit", "approve", "reject", "submit", "audit_own"]
    },
    "lab_staff": {
        "name": "Lab Staff",
        "permissions": ["upload", "view", "scan"]
    },
    "read_only": {
        "name": "Read-Only Auditor",
        "permissions": ["view", "audit", "reports"]
    }
}
