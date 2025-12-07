"""
Entra ID (Azure AD) OpenID Connect Authentication Service.

Handles OIDC authentication flow with Microsoft Entra ID including:
- Authorization URL generation
- Token exchange
- User info retrieval from Microsoft Graph
- Group-to-role mapping
- Token validation
"""

import logging
import secrets
from datetime import datetime
from typing import Optional, Dict, Any, List

import httpx
import msal

from app.config import settings
from app.utils.timezone import now_eastern

logger = logging.getLogger(__name__)

# Microsoft Graph API base URL
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# OIDC scopes
SCOPES = ["User.Read", "GroupMember.Read.All"]


class EntraIDService:
    """Microsoft Entra ID OIDC authentication service."""

    def __init__(self):
        """Initialize the MSAL confidential client application."""
        self._msal_app = None
        self._authority = f"https://login.microsoftonline.com/{settings.AZURE_AD_TENANT_ID}"

    @property
    def msal_app(self) -> msal.ConfidentialClientApplication:
        """Lazy initialization of MSAL application."""
        if self._msal_app is None:
            if not settings.AZURE_AD_CLIENT_ID or not settings.AZURE_AD_CLIENT_SECRET:
                raise ValueError("Entra ID credentials not configured")

            self._msal_app = msal.ConfidentialClientApplication(
                client_id=settings.AZURE_AD_CLIENT_ID,
                client_credential=settings.AZURE_AD_CLIENT_SECRET,
                authority=self._authority
            )
        return self._msal_app

    @property
    def is_configured(self) -> bool:
        """Check if Entra ID is properly configured."""
        return bool(
            settings.AZURE_AD_TENANT_ID and
            settings.AZURE_AD_CLIENT_ID and
            settings.AZURE_AD_CLIENT_SECRET and
            settings.AZURE_AD_REDIRECT_URI
        )

    def generate_state(self) -> str:
        """Generate a secure random state parameter for CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_auth_url(self, state: str, redirect_uri: Optional[str] = None) -> str:
        """
        Generate the Entra ID authorization URL for OIDC flow.

        Args:
            state: CSRF protection state parameter
            redirect_uri: Optional override for redirect URI

        Returns:
            Authorization URL to redirect user to
        """
        if not self.is_configured:
            raise ValueError("Entra ID is not properly configured")

        redirect = redirect_uri or settings.AZURE_AD_REDIRECT_URI

        auth_url = self.msal_app.get_authorization_request_url(
            scopes=SCOPES,
            state=state,
            redirect_uri=redirect,
            response_type="code"
        )

        logger.info(f"Generated Entra ID auth URL for redirect to: {redirect}")
        return auth_url

    def exchange_code_for_token(self, code: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
        """
        Exchange authorization code for access and ID tokens.

        Args:
            code: Authorization code from Entra ID callback
            redirect_uri: Optional override for redirect URI

        Returns:
            Dictionary containing access_token, id_token, and token claims
        """
        if not self.is_configured:
            raise ValueError("Entra ID is not properly configured")

        redirect = redirect_uri or settings.AZURE_AD_REDIRECT_URI

        result = self.msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=SCOPES,
            redirect_uri=redirect
        )

        if "error" in result:
            error_desc = result.get("error_description", result.get("error"))
            logger.error(f"Token exchange failed: {error_desc}")
            raise ValueError(f"Token exchange failed: {error_desc}")

        logger.info("Successfully exchanged authorization code for tokens")
        return result

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get user profile and group memberships from Microsoft Graph API.

        Args:
            access_token: Access token from Entra ID

        Returns:
            Dictionary with user profile and group IDs
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get user profile
            profile_response = await client.get(
                f"{GRAPH_API_BASE}/me",
                headers=headers
            )

            if profile_response.status_code != 200:
                logger.error(f"Failed to get user profile: {profile_response.text}")
                raise ValueError(f"Failed to get user profile: {profile_response.status_code}")

            profile = profile_response.json()

            # Get group memberships
            groups_response = await client.get(
                f"{GRAPH_API_BASE}/me/memberOf",
                headers=headers
            )

            group_ids = []
            if groups_response.status_code == 200:
                groups_data = groups_response.json()
                group_ids = [
                    g.get("id") for g in groups_data.get("value", [])
                    if g.get("@odata.type") == "#microsoft.graph.group"
                ]
            else:
                logger.warning(f"Could not fetch group memberships: {groups_response.status_code}")

        user_info = {
            "id": profile.get("id"),  # Azure AD Object ID
            "email": profile.get("mail") or profile.get("userPrincipalName"),
            "upn": profile.get("userPrincipalName"),
            "display_name": profile.get("displayName"),
            "given_name": profile.get("givenName"),
            "surname": profile.get("surname"),
            "job_title": profile.get("jobTitle"),
            "department": profile.get("department"),
            "group_ids": group_ids
        }

        logger.info(f"Retrieved user info for: {user_info['email']} with {len(group_ids)} groups")
        return user_info

    def map_groups_to_role(self, group_ids: List[str]) -> Optional[str]:
        """
        Map Entra ID group memberships to application role.

        Priority: admin > reviewer > read_only > default

        Args:
            group_ids: List of Entra ID group Object IDs

        Returns:
            Application role string, or None if no match and group membership is required
        """
        # Check for admin group first (highest priority)
        if settings.AZURE_AD_ADMIN_GROUP_ID and settings.AZURE_AD_ADMIN_GROUP_ID in group_ids:
            logger.info("User is member of admin group")
            return "admin"

        # Check for reviewer group
        if settings.AZURE_AD_REVIEWER_GROUP_ID and settings.AZURE_AD_REVIEWER_GROUP_ID in group_ids:
            logger.info("User is member of reviewer group")
            return "reviewer"

        # Check for read-only group
        if settings.AZURE_AD_READONLY_GROUP_ID and settings.AZURE_AD_READONLY_GROUP_ID in group_ids:
            logger.info("User is member of read_only group")
            return "read_only"

        # If group membership is required and user is not in any mapped group, deny access
        if settings.SSO_REQUIRE_GROUP_MEMBERSHIP:
            logger.warning(f"User not in any mapped group and group membership is required. Groups: {group_ids}")
            return None

        # Default role if not in any mapped group (only used if group membership is not required)
        logger.info(f"User not in any mapped group, using default role: {settings.SSO_DEFAULT_ROLE}")
        return settings.SSO_DEFAULT_ROLE

    def get_id_token_claims(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract claims from the ID token.

        Args:
            result: Token response from MSAL

        Returns:
            Dictionary of ID token claims
        """
        id_token_claims = result.get("id_token_claims", {})

        return {
            "sub": id_token_claims.get("sub"),
            "oid": id_token_claims.get("oid"),  # Object ID
            "email": id_token_claims.get("email") or id_token_claims.get("preferred_username"),
            "name": id_token_claims.get("name"),
            "given_name": id_token_claims.get("given_name"),
            "family_name": id_token_claims.get("family_name"),
            "tid": id_token_claims.get("tid"),  # Tenant ID
            "iss": id_token_claims.get("iss"),
            "aud": id_token_claims.get("aud"),
            "exp": id_token_claims.get("exp"),
            "iat": id_token_claims.get("iat"),
        }

    def get_logout_url(self, post_logout_redirect_uri: Optional[str] = None) -> str:
        """
        Generate the Entra ID logout URL.

        Args:
            post_logout_redirect_uri: Where to redirect after logout

        Returns:
            Logout URL
        """
        base_url = f"{self._authority}/oauth2/v2.0/logout"

        if post_logout_redirect_uri:
            return f"{base_url}?post_logout_redirect_uri={post_logout_redirect_uri}"

        return base_url


# Global service instance
_entra_id_service: Optional[EntraIDService] = None


def get_entra_id_service() -> EntraIDService:
    """Get or create the Entra ID service instance."""
    global _entra_id_service
    if _entra_id_service is None:
        _entra_id_service = EntraIDService()
    return _entra_id_service
