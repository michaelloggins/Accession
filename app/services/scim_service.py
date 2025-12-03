"""
SCIM 2.0 User Provisioning Service.

Implements SCIM 2.0 protocol for automatic user provisioning from Entra ID.
Reference: https://datatracker.ietf.org/doc/html/rfc7644
"""

import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.user import User
from app.utils.timezone import now_eastern

logger = logging.getLogger(__name__)

# SCIM Schema URIs
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE_USER_SCHEMA = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
SCIM_LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


class SCIMService:
    """SCIM 2.0 user provisioning service for Entra ID integration."""

    def __init__(self, db: Session):
        self.db = db

    def list_users(
        self,
        filter_str: Optional[str] = None,
        start_index: int = 1,
        count: int = 100
    ) -> Dict[str, Any]:
        """
        List users with SCIM filtering and pagination.

        Args:
            filter_str: SCIM filter expression (e.g., 'userName eq "john@example.com"')
            start_index: 1-based starting index for pagination
            count: Maximum number of results to return

        Returns:
            SCIM ListResponse
        """
        query = self.db.query(User)

        # Apply SCIM filter
        if filter_str:
            query = self._apply_filter(query, filter_str)

        # Get total count before pagination
        total_count = query.count()

        # Apply pagination (SCIM uses 1-based indexing)
        # MSSQL requires ORDER BY when using OFFSET/LIMIT
        offset = max(0, start_index - 1)
        users = query.order_by(User.id).offset(offset).limit(count).all()

        # Convert to SCIM format
        resources = [self.user_to_scim(user) for user in users]

        return {
            "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
            "totalResults": total_count,
            "startIndex": start_index,
            "itemsPerPage": len(resources),
            "Resources": resources
        }

    def _apply_filter(self, query, filter_str: str):
        """
        Apply SCIM filter expression to query.

        Supports:
        - userName eq "value"
        - externalId eq "value"
        - emails.value eq "value"
        - displayName eq "value"
        - active eq true/false
        """
        # Parse simple equality filters
        eq_pattern = r'(\w+(?:\.\w+)?)\s+eq\s+"([^"]*)"'
        eq_match = re.match(eq_pattern, filter_str, re.IGNORECASE)

        if eq_match:
            field, value = eq_match.groups()
            field_lower = field.lower()

            if field_lower == "username" or field_lower == "emails.value":
                return query.filter(User.email == value)
            elif field_lower == "externalid":
                return query.filter(User.entra_id == value)
            elif field_lower == "displayname":
                return query.filter(User.full_name == value)

        # Parse boolean filters
        bool_pattern = r'(\w+)\s+eq\s+(true|false)'
        bool_match = re.match(bool_pattern, filter_str, re.IGNORECASE)

        if bool_match:
            field, value = bool_match.groups()
            bool_value = value.lower() == "true"

            if field.lower() == "active":
                return query.filter(User.is_active == bool_value)

        logger.warning(f"Unsupported SCIM filter: {filter_str}")
        return query

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single user by ID in SCIM format.

        Args:
            user_id: User ID (can be internal ID or Entra ID)

        Returns:
            SCIM User resource or None
        """
        user = self._find_user(user_id)
        if not user:
            return None

        return self.user_to_scim(user)

    def create_user(self, scim_user: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """
        Create a new user from SCIM payload.

        Args:
            scim_user: SCIM User resource

        Returns:
            Tuple of (SCIM User resource, was_created)
        """
        # Extract user attributes from SCIM payload
        attrs = self.scim_to_user_attrs(scim_user)

        # Check if user already exists
        existing = None
        if attrs.get("entra_id"):
            existing = self.db.query(User).filter(User.entra_id == attrs["entra_id"]).first()
        if not existing and attrs.get("email"):
            existing = self.db.query(User).filter(User.email == attrs["email"]).first()

        if existing:
            # Update existing user
            logger.info(f"SCIM: User already exists, updating: {attrs.get('email')}")
            return self.update_user(existing.id, scim_user)

        # Create new user
        user = User(
            id=attrs.get("entra_id") or attrs.get("email"),  # Use entra_id as primary key
            email=attrs["email"],
            full_name=attrs.get("full_name", ""),
            first_name=attrs.get("first_name"),
            last_name=attrs.get("last_name"),
            role=attrs.get("role", "read_only"),
            is_active=attrs.get("is_active", True),
            entra_id=attrs.get("entra_id"),
            entra_upn=attrs.get("entra_upn"),
            auth_provider="entra_id",
            last_synced_at=now_eastern(),
            created_at=now_eastern(),
            created_by="SCIM"
        )

        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        logger.info(f"SCIM: Created user: {user.email} (ID: {user.id})")
        return self.user_to_scim(user), True

    def update_user(self, user_id: str, scim_user: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """
        Update user from SCIM payload (full replace).

        Args:
            user_id: User ID
            scim_user: SCIM User resource

        Returns:
            Tuple of (SCIM User resource, was_created)
        """
        user = self._find_user(user_id)
        if not user:
            # Create if doesn't exist
            return self.create_user(scim_user)

        # Extract and apply attributes
        attrs = self.scim_to_user_attrs(scim_user)

        if attrs.get("email"):
            user.email = attrs["email"]
        if attrs.get("full_name"):
            user.full_name = attrs["full_name"]
        if attrs.get("first_name"):
            user.first_name = attrs["first_name"]
        if attrs.get("last_name"):
            user.last_name = attrs["last_name"]
        if attrs.get("entra_id"):
            user.entra_id = attrs["entra_id"]
        if attrs.get("entra_upn"):
            user.entra_upn = attrs["entra_upn"]
        if "is_active" in attrs:
            user.is_active = attrs["is_active"]

        user.last_synced_at = now_eastern()
        user.updated_at = now_eastern()

        self.db.commit()
        self.db.refresh(user)

        logger.info(f"SCIM: Updated user: {user.email}")
        return self.user_to_scim(user), False

    def patch_user(self, user_id: str, operations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Apply SCIM PATCH operations to user.

        Args:
            user_id: User ID
            operations: List of SCIM PATCH operations

        Returns:
            Updated SCIM User resource or None
        """
        user = self._find_user(user_id)
        if not user:
            return None

        for op in operations:
            op_type = op.get("op", "").lower()
            path = op.get("path", "").lower()
            value = op.get("value")

            if op_type == "replace":
                if path == "active":
                    user.is_active = bool(value)
                elif path == "displayname" or path == "name.formatted":
                    user.full_name = str(value)
                elif path == "username" or path == "emails[type eq \"work\"].value":
                    user.email = str(value)
                elif path == "externalid":
                    user.entra_id = str(value)

            elif op_type == "add":
                # Handle add operations similarly
                if path == "emails":
                    if isinstance(value, list) and value:
                        user.email = value[0].get("value", user.email)

            elif op_type == "remove":
                # Handle remove operations
                logger.info(f"SCIM: Remove operation for {path} (not implemented)")

        user.last_synced_at = now_eastern()
        user.updated_at = now_eastern()

        self.db.commit()
        self.db.refresh(user)

        logger.info(f"SCIM: Patched user: {user.email}")
        return self.user_to_scim(user)

    def delete_user(self, user_id: str) -> bool:
        """
        Soft-delete (deactivate) user.

        SCIM DELETE typically means deactivate, not hard delete.

        Args:
            user_id: User ID

        Returns:
            True if user was found and deactivated
        """
        user = self._find_user(user_id)
        if not user:
            return False

        user.is_active = False
        user.deactivated_at = now_eastern()
        user.deactivated_by = "SCIM"
        user.last_synced_at = now_eastern()

        self.db.commit()

        logger.info(f"SCIM: Deactivated user: {user.email}")
        return True

    def _find_user(self, user_id: str) -> Optional[User]:
        """
        Find user by ID (tries internal ID, then Entra ID).

        Args:
            user_id: User identifier

        Returns:
            User or None
        """
        # Try by primary key first
        user = self.db.query(User).filter(User.id == user_id).first()
        if user:
            return user

        # Try by Entra ID
        user = self.db.query(User).filter(User.entra_id == user_id).first()
        return user

    def user_to_scim(self, user: User) -> Dict[str, Any]:
        """
        Convert User model to SCIM 2.0 User resource.

        Args:
            user: User model instance

        Returns:
            SCIM User resource dictionary
        """
        # Use stored first_name/last_name if available, otherwise parse from full_name
        given_name = user.first_name or ""
        family_name = user.last_name or ""
        if not given_name and not family_name and user.full_name:
            name_parts = user.full_name.split(" ", 1)
            given_name = name_parts[0] if name_parts else ""
            family_name = name_parts[1] if len(name_parts) > 1 else ""

        scim_user = {
            "schemas": [SCIM_USER_SCHEMA],
            "id": user.id,
            "externalId": user.entra_id,
            "userName": user.email,
            "name": {
                "formatted": user.full_name,
                "givenName": given_name,
                "familyName": family_name
            },
            "displayName": user.full_name,
            "emails": [
                {
                    "value": user.email,
                    "type": "work",
                    "primary": True
                }
            ],
            "active": user.is_active,
            "meta": {
                "resourceType": "User",
                "created": user.created_at.isoformat() if user.created_at else None,
                "lastModified": user.updated_at.isoformat() if user.updated_at else None,
                "location": f"/scim/v2/Users/{user.id}"
            }
        }

        return scim_user

    def scim_to_user_attrs(self, scim_user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert SCIM User resource to user attributes dictionary.

        Args:
            scim_user: SCIM User resource

        Returns:
            Dictionary of user attributes
        """
        attrs = {}

        # External ID (Entra Object ID)
        if scim_user.get("externalId"):
            attrs["entra_id"] = scim_user["externalId"]

        # Username / Email
        if scim_user.get("userName"):
            attrs["email"] = scim_user["userName"]
            attrs["entra_upn"] = scim_user["userName"]

        # Also check emails array
        emails = scim_user.get("emails", [])
        if emails:
            primary_email = next(
                (e.get("value") for e in emails if e.get("primary")),
                emails[0].get("value") if emails else None
            )
            if primary_email and not attrs.get("email"):
                attrs["email"] = primary_email

        # Name attributes (givenName, familyName, formatted)
        if scim_user.get("name"):
            name = scim_user["name"]
            if name.get("givenName"):
                attrs["first_name"] = name["givenName"]
            if name.get("familyName"):
                attrs["last_name"] = name["familyName"]
            if name.get("formatted"):
                attrs["full_name"] = name["formatted"]
            elif attrs.get("first_name") or attrs.get("last_name"):
                attrs["full_name"] = f"{attrs.get('first_name', '')} {attrs.get('last_name', '')}".strip()

        # Display Name (fallback if name object not provided or formatted not set)
        if scim_user.get("displayName") and not attrs.get("full_name"):
            attrs["full_name"] = scim_user["displayName"]

        # Active status
        if "active" in scim_user:
            attrs["is_active"] = scim_user["active"]

        return attrs

    def get_service_provider_config(self) -> Dict[str, Any]:
        """
        Return SCIM ServiceProviderConfig.

        Describes the SCIM capabilities of this service.
        """
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "documentationUri": "https://docs.microsoft.com/azure/active-directory/app-provisioning/",
            "patch": {
                "supported": True
            },
            "bulk": {
                "supported": False,
                "maxOperations": 0,
                "maxPayloadSize": 0
            },
            "filter": {
                "supported": True,
                "maxResults": 200
            },
            "changePassword": {
                "supported": False
            },
            "sort": {
                "supported": False
            },
            "etag": {
                "supported": False
            },
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "OAuth Bearer Token",
                    "description": "Authentication using Bearer token in Authorization header"
                }
            ]
        }

    def get_schemas(self) -> Dict[str, Any]:
        """
        Return SCIM Schemas resource.
        """
        return {
            "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
            "totalResults": 1,
            "Resources": [
                {
                    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
                    "id": SCIM_USER_SCHEMA,
                    "name": "User",
                    "description": "User Account",
                    "attributes": [
                        {
                            "name": "userName",
                            "type": "string",
                            "multiValued": False,
                            "required": True,
                            "caseExact": False,
                            "mutability": "readWrite",
                            "returned": "default",
                            "uniqueness": "server"
                        },
                        {
                            "name": "displayName",
                            "type": "string",
                            "multiValued": False,
                            "required": False,
                            "caseExact": False,
                            "mutability": "readWrite",
                            "returned": "default"
                        },
                        {
                            "name": "active",
                            "type": "boolean",
                            "multiValued": False,
                            "required": False,
                            "mutability": "readWrite",
                            "returned": "default"
                        }
                    ]
                }
            ]
        }


def create_scim_error(status: int, detail: str) -> Dict[str, Any]:
    """
    Create a SCIM error response.

    Args:
        status: HTTP status code
        detail: Error detail message

    Returns:
        SCIM Error response
    """
    return {
        "schemas": [SCIM_ERROR_SCHEMA],
        "status": str(status),
        "detail": detail
    }
