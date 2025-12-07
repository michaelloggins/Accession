"""
SAML 2.0 Authentication Service for Entra ID.

Handles SAML SSO authentication flow with Microsoft Entra ID.
"""

import logging
import base64
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode

from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from onelogin.saml2.utils import OneLogin_Saml2_Utils

from app.config import settings

logger = logging.getLogger(__name__)


class SAMLService:
    """SAML 2.0 authentication service for Entra ID SSO."""

    def __init__(self):
        self._settings = None

    @property
    def is_configured(self) -> bool:
        """Check if SAML is properly configured."""
        return bool(
            settings.AZURE_AD_TENANT_ID and
            settings.AZURE_AD_CLIENT_ID and
            (settings.SAML_IDP_SSO_URL or settings.AZURE_AD_TENANT_ID)
        )

    def _get_saml_settings(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build SAML settings dictionary for python3-saml.

        Args:
            request_data: Request information (https, host, etc.)

        Returns:
            SAML settings dictionary
        """
        # Build URLs
        base_url = f"https://{request_data.get('http_host', 'localhost')}"

        # Entity ID (use app URL or configured value)
        entity_id = settings.SAML_ENTITY_ID or base_url

        # ACS URL (where IdP sends the SAML response)
        acs_url = settings.SAML_ACS_URL or f"{base_url}/api/auth/saml/acs"

        # SLO URL
        slo_url = settings.SAML_SLO_URL or f"{base_url}/api/auth/saml/slo"

        # IdP settings - use Entra ID defaults if not explicitly configured
        tenant_id = settings.AZURE_AD_TENANT_ID

        idp_entity_id = settings.SAML_IDP_ENTITY_ID or f"https://sts.windows.net/{tenant_id}/"
        idp_sso_url = settings.SAML_IDP_SSO_URL or f"https://login.microsoftonline.com/{tenant_id}/saml2"
        idp_slo_url = settings.SAML_IDP_SLO_URL or f"https://login.microsoftonline.com/{tenant_id}/saml2"

        saml_settings = {
            "strict": True,   # Enforce all SAML security validations
            "debug": False,   # No verbose errors in production
            "sp": {
                "entityId": entity_id,
                "assertionConsumerService": {
                    "url": acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                },
                "singleLogoutService": {
                    "url": slo_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
            },
            "idp": {
                "entityId": idp_entity_id,
                "singleSignOnService": {
                    "url": idp_sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                },
                "singleLogoutService": {
                    "url": idp_slo_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                }
            },
            "security": {
                "nameIdEncrypted": False,
                "authnRequestsSigned": settings.SAML_SIGN_REQUESTS,
                "logoutRequestSigned": settings.SAML_SIGN_REQUESTS,
                "logoutResponseSigned": settings.SAML_SIGN_REQUESTS,
                "signMetadata": False,
                "wantMessagesSigned": settings.SAML_WANT_RESPONSE_SIGNED,
                "wantAssertionsSigned": settings.SAML_WANT_ASSERTIONS_SIGNED,
                "wantNameId": True,
                "wantNameIdEncrypted": False,
                "wantAssertionsEncrypted": False,
                "allowSingleLabelDomains": False,
                "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
                "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
                # Don't request specific authentication context - allow any method (MFA, FIDO, etc.)
                "requestedAuthnContext": False
            }
        }

        # Add IdP certificate if configured
        if settings.SAML_IDP_CERT:
            saml_settings["idp"]["x509cert"] = settings.SAML_IDP_CERT

        # Add SP certificate and key if configured
        if settings.SAML_SP_CERT:
            saml_settings["sp"]["x509cert"] = settings.SAML_SP_CERT
        if settings.SAML_SP_KEY:
            saml_settings["sp"]["privateKey"] = settings.SAML_SP_KEY

        return saml_settings

    def _prepare_request_data(self, request) -> Dict[str, Any]:
        """
        Prepare request data for SAML library.

        Args:
            request: FastAPI/Starlette request object

        Returns:
            Dictionary with request information
        """
        # Determine if HTTPS
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        https = forwarded_proto == "https" or request.url.scheme == "https"

        # Get host
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or str(request.url.netloc)

        return {
            "https": "on" if https else "off",
            "http_host": host,
            "server_port": request.url.port or (443 if https else 80),
            "script_name": request.url.path,
            "get_data": dict(request.query_params),
            "post_data": {}  # Will be populated for POST requests
        }

    def get_auth_request_url(self, request, relay_state: str = None) -> str:
        """
        Generate SAML authentication request URL.

        Args:
            request: FastAPI request object
            relay_state: Optional state to pass through (e.g., return URL)

        Returns:
            URL to redirect user to for authentication
        """
        request_data = self._prepare_request_data(request)
        saml_settings = self._get_saml_settings(request_data)

        auth = OneLogin_Saml2_Auth(request_data, saml_settings)

        return auth.login(return_to=relay_state)

    async def process_saml_response(
        self,
        request,
        saml_response: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Process SAML response from IdP.

        Args:
            request: FastAPI request object
            saml_response: Base64 encoded SAML response

        Returns:
            Tuple of (user_info dict, error message)
        """
        request_data = self._prepare_request_data(request)
        request_data["post_data"] = {"SAMLResponse": saml_response}

        saml_settings = self._get_saml_settings(request_data)

        try:
            auth = OneLogin_Saml2_Auth(request_data, saml_settings)
            auth.process_response()

            errors = auth.get_errors()
            if errors:
                error_msg = ", ".join(errors)
                last_reason = auth.get_last_error_reason() or "unknown"
                logger.error(f"SAML response errors: {error_msg}")
                logger.error(f"SAML last error reason: {last_reason}")
                # Include last error reason in returned error for debugging
                return None, f"{error_msg} ({last_reason})"

            if not auth.is_authenticated():
                logger.warning("SAML: User not authenticated")
                return None, "User not authenticated"

            # Extract user attributes
            attributes = auth.get_attributes()
            name_id = auth.get_nameid()
            name_id_format = auth.get_nameid_format()
            session_index = auth.get_session_index()

            logger.info(f"SAML: Authenticated user: {name_id}")
            logger.debug(f"SAML: Attributes: {attributes}")

            # Map SAML attributes to user info
            # Entra ID typically sends these attributes
            user_info = {
                "id": attributes.get("http://schemas.microsoft.com/identity/claims/objectidentifier", [name_id])[0],
                "email": name_id if "@" in name_id else attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress", [None])[0],
                "upn": attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name", [name_id])[0],
                "display_name": attributes.get("http://schemas.microsoft.com/identity/claims/displayname", [None])[0],
                "given_name": attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname", [None])[0],
                "surname": attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname", [None])[0],
                "groups": attributes.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/groups", []),
                "session_index": session_index,
                "name_id": name_id,
                "name_id_format": name_id_format,
                "raw_attributes": attributes
            }

            # Build display name if not provided
            if not user_info["display_name"]:
                given = user_info.get("given_name", "")
                surname = user_info.get("surname", "")
                user_info["display_name"] = f"{given} {surname}".strip() or user_info["email"]

            return user_info, None

        except Exception as e:
            logger.error(f"SAML response processing error: {e}", exc_info=True)
            return None, str(e)

    def get_logout_url(self, request, name_id: str = None, session_index: str = None) -> str:
        """
        Generate SAML logout URL.

        Args:
            request: FastAPI request object
            name_id: User's name ID from authentication
            session_index: Session index from authentication

        Returns:
            URL to redirect user to for logout
        """
        request_data = self._prepare_request_data(request)
        saml_settings = self._get_saml_settings(request_data)

        auth = OneLogin_Saml2_Auth(request_data, saml_settings)

        return auth.logout(
            name_id=name_id,
            session_index=session_index
        )

    def get_metadata(self, request) -> str:
        """
        Generate SP metadata XML.

        Args:
            request: FastAPI request object

        Returns:
            XML metadata string
        """
        request_data = self._prepare_request_data(request)
        saml_settings = self._get_saml_settings(request_data)

        settings_obj = OneLogin_Saml2_Settings(saml_settings, sp_validation_only=True)
        metadata = settings_obj.get_sp_metadata()

        errors = settings_obj.validate_metadata(metadata)
        if errors:
            logger.warning(f"SAML metadata validation errors: {errors}")

        return metadata

    def map_groups_to_role(self, group_ids: list) -> Optional[str]:
        """
        Map Entra ID group memberships to application role.

        Args:
            group_ids: List of group object IDs

        Returns:
            Role string (admin, reviewer, or read_only), or None if no match and group membership is required
        """
        # Check admin group first
        if settings.AZURE_AD_ADMIN_GROUP_ID and settings.AZURE_AD_ADMIN_GROUP_ID in group_ids:
            return "admin"

        # Check reviewer group
        if settings.AZURE_AD_REVIEWER_GROUP_ID and settings.AZURE_AD_REVIEWER_GROUP_ID in group_ids:
            return "reviewer"

        # Check read-only group
        if settings.AZURE_AD_READONLY_GROUP_ID and settings.AZURE_AD_READONLY_GROUP_ID in group_ids:
            return "read_only"

        # If group membership is required and user is not in any mapped group, deny access
        if settings.SSO_REQUIRE_GROUP_MEMBERSHIP:
            logger.warning(f"User not in any mapped group and group membership is required. Groups: {group_ids}")
            return None

        # Default role (only used if group membership is not required)
        return settings.SSO_DEFAULT_ROLE


# Singleton instance
_saml_service = None


def get_saml_service() -> SAMLService:
    """Get SAML service singleton."""
    global _saml_service
    if _saml_service is None:
        _saml_service = SAMLService()
    return _saml_service
