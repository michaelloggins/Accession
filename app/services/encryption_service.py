"""PHI encryption service using Fernet symmetric encryption."""

from cryptography.fernet import Fernet
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
import logging
import json

from app.config import settings, PHI_FIELDS

logger = logging.getLogger(__name__)


class EncryptionService:
    """Service for encrypting and decrypting PHI data."""

    def __init__(self):
        self._key = None
        self._fernet = None

    @property
    def fernet(self):
        """Lazy load encryption key and create Fernet instance."""
        if self._fernet is None:
            self._key = self._get_encryption_key()
            self._fernet = Fernet(self._key)
        return self._fernet

    def _get_encryption_key(self) -> bytes:
        """Get encryption key from environment, Azure Key Vault, or generate for development."""
        # Priority 1: Direct environment variable (PHI_ENCRYPTION_KEY)
        if settings.PHI_ENCRYPTION_KEY:
            logger.info("Using PHI encryption key from environment variable")
            return settings.PHI_ENCRYPTION_KEY.encode()

        # Priority 2: Development mode - derive from SECRET_KEY
        if settings.ENVIRONMENT == "development":
            # Derive a consistent key from SECRET_KEY for development
            logger.warning("Using development encryption key - not for production!")
            import base64
            import hashlib
            # Derive Fernet-compatible key from SECRET_KEY
            key_material = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
            return base64.urlsafe_b64encode(key_material)

        # Priority 3: Azure Key Vault
        if settings.AZURE_KEY_VAULT_URL:
            try:
                # Get key from Azure Key Vault
                credential = DefaultAzureCredential()
                client = SecretClient(
                    vault_url=settings.AZURE_KEY_VAULT_URL,
                    credential=credential
                )
                secret = client.get_secret(settings.ENCRYPTION_KEY_NAME)
                logger.info("Using PHI encryption key from Azure Key Vault")
                return secret.value.encode()
            except Exception as e:
                logger.error(f"Failed to get encryption key from Key Vault: {e}")
                raise

        # No encryption key available
        raise ValueError(
            "No PHI encryption key configured. Set PHI_ENCRYPTION_KEY environment variable "
            "or configure AZURE_KEY_VAULT_URL with phi-encryption-key secret."
        )

    def encrypt_phi_fields(self, data: dict) -> dict:
        """Encrypt PHI fields in a dictionary (supports both flat and nested formats)."""
        encrypted_data = data.copy()

        # Define which nested fields contain PHI
        phi_nested_fields = {
            'facility': ['facility_name', 'phone', 'fax', 'email', 'address', 'laboratory_contact'],
            'patient': ['owner_first_name', 'owner_last_name', 'owner_middle_name', 'pet_name',
                       'date_of_birth', 'phone', 'email', 'address', 'medical_record_number', 'patient_id'],
            'order': ['ordering_veterinarian', 'special_instructions']
        }

        # Encrypt flat fields at root level
        for field in PHI_FIELDS:
            if field in encrypted_data and encrypted_data[field] is not None:
                value = encrypted_data[field]
                if isinstance(value, str):
                    encrypted_value = self.encrypt_string(value)
                    encrypted_data[field] = encrypted_value

        # Encrypt nested structures (facility, patient, order) - only specific PHI fields
        for section, phi_fields in phi_nested_fields.items():
            if section in encrypted_data and isinstance(encrypted_data[section], dict):
                for field in phi_fields:
                    if field in encrypted_data[section]:
                        value = encrypted_data[section][field]
                        if value is not None and isinstance(value, str) and len(value) > 0:
                            encrypted_data[section][field] = self.encrypt_string(value)
                            logger.debug(f"Encrypted {section}.{field}")

        return encrypted_data

    def decrypt_phi_fields(self, data: dict) -> dict:
        """Decrypt PHI fields in a dictionary (supports both flat and nested formats)."""
        import copy
        decrypted_data = copy.deepcopy(data)  # Use deepcopy to avoid modifying nested dicts

        # Decrypt flat fields at root level
        for field in PHI_FIELDS:
            if field in decrypted_data and decrypted_data[field] is not None:
                value = decrypted_data[field]
                logger.debug(f"Checking field {field}: type={type(value)}, value={value[:50] if isinstance(value, str) else value}")
                if isinstance(value, str) and self._is_encrypted(value):
                    logger.info(f"Decrypting field: {field}")
                    try:
                        decrypted_value = self.decrypt_string(value)
                        decrypted_data[field] = decrypted_value
                        logger.debug(f"Decrypted {field}: {decrypted_value}")
                    except Exception as e:
                        logger.error(f"Failed to decrypt field {field}: {e}")
                        # Keep encrypted value if decryption fails

        # Decrypt nested structures (facility, patient, order)
        for section in ['facility', 'patient', 'order']:
            if section in decrypted_data and isinstance(decrypted_data[section], dict):
                for field, value in list(decrypted_data[section].items()):
                    if value is not None and isinstance(value, str) and self._is_encrypted(value):
                        logger.info(f"Decrypting nested field: {section}.{field}")
                        try:
                            decrypted_data[section][field] = self.decrypt_string(value)
                            logger.debug(f"Decrypted {section}.{field}")
                        except Exception as e:
                            logger.error(f"Failed to decrypt {section}.{field}: {e}")
                            # Keep encrypted value if decryption fails

        return decrypted_data

    def encrypt_string(self, plaintext: str) -> str:
        """Encrypt a string value."""
        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode())
            return encrypted_bytes.decode()
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            raise

    def decrypt_string(self, ciphertext: str) -> str:
        """Decrypt a string value."""
        try:
            decrypted_bytes = self.fernet.decrypt(ciphertext.encode())
            return decrypted_bytes.decode()
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            raise

    def _is_encrypted(self, value: str) -> bool:
        """Check if a value appears to be encrypted (Fernet format)."""
        # Fernet tokens start with 'gAAAAA' and are typically 100+ characters
        return value.startswith("gAAAAA") and len(value) >= 100
