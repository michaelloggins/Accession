"""
SCIM 2.0 API Router for Entra ID User Provisioning.

Implements SCIM 2.0 protocol endpoints for automatic user provisioning.
Reference: https://datatracker.ietf.org/doc/html/rfc7644
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.services.scim_service import SCIMService, create_scim_error

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_scim_token(authorization: Optional[str] = Header(None)) -> bool:
    """
    Verify SCIM Bearer token.

    Args:
        authorization: Authorization header value

    Returns:
        True if token is valid

    Raises:
        HTTPException: If token is missing or invalid
    """
    # Check authorization header first (before checking config)
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required"
        )

    try:
        # Get the expected token
        expected_token = getattr(settings, 'SCIM_BEARER_TOKEN', None)

        if not expected_token:
            logger.warning("SCIM_BEARER_TOKEN not configured - SCIM endpoints disabled")
            raise HTTPException(
                status_code=403,
                detail="SCIM provisioning not configured"
            )

        # Extract token from "Bearer <token>" format
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization header format"
            )

        token = parts[1].strip()
        expected_token = expected_token.strip()

        if token != expected_token:
            logger.warning(f"Invalid SCIM bearer token received (length: {len(token)} vs expected: {len(expected_token)})")
            raise HTTPException(
                status_code=401,
                detail="Invalid bearer token"
            )

        logger.debug("SCIM token verification successful")
        return True

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SCIM token verification error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Token verification failed: {str(e)}"
        )


# =============================================================================
# Root & ServiceProviderConfig & Schemas
# =============================================================================

@router.get("")
@router.get("/")
async def scim_root(
    _: bool = Depends(verify_scim_token)
):
    """
    SCIM Root endpoint - Returns ServiceProviderConfig.
    Required for Azure AD SCIM validation which calls the base URL.
    """
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://docs.microsoft.com/azure/active-directory/app-provisioning/",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication using Bearer token in Authorization header"
            }
        ]
    }


@router.get("/ServiceProviderConfig")
async def get_service_provider_config(
    _: bool = Depends(verify_scim_token)
):
    """
    Return SCIM ServiceProviderConfig.

    Describes the capabilities of this SCIM service provider.
    Note: This endpoint doesn't require database access.
    """
    # ServiceProviderConfig is static, no db needed
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://docs.microsoft.com/azure/active-directory/app-provisioning/",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication using Bearer token in Authorization header"
            }
        ]
    }


@router.get("/Schemas")
async def get_schemas(
    _: bool = Depends(verify_scim_token)
):
    """
    Return supported SCIM schemas.
    Note: This endpoint doesn't require database access.
    """
    # Schemas are static, no db needed
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 1,
        "Resources": [
            {
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
                "id": "urn:ietf:params:scim:schemas:core:2.0:User",
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


# =============================================================================
# Users Endpoints
# =============================================================================

@router.get("/Users")
async def list_users(
    filter: Optional[str] = None,
    startIndex: int = 1,
    count: int = 100,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_scim_token)
):
    """
    List users with optional SCIM filtering.

    Supports filters like:
    - userName eq "user@example.com"
    - externalId eq "azure-object-id"
    - active eq true
    """
    logger.info(f"SCIM: List users - filter={filter}, startIndex={startIndex}, count={count}")

    try:
        scim_service = SCIMService(db)
        result = scim_service.list_users(
            filter_str=filter,
            start_index=startIndex,
            count=count
        )
        return result
    except Exception as e:
        logger.error(f"SCIM: Error listing users: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=create_scim_error(500, f"Database error: {str(e)}")
        )


@router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_scim_token)
):
    """
    Get a single user by ID.
    """
    logger.info(f"SCIM: Get user - id={user_id}")

    scim_service = SCIMService(db)
    user = scim_service.get_user(user_id)

    if not user:
        return JSONResponse(
            status_code=404,
            content=create_scim_error(404, f"User {user_id} not found")
        )

    return user


@router.post("/Users", status_code=201)
async def create_user(
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_scim_token)
):
    """
    Create a new user from SCIM payload.
    """
    try:
        scim_user = await request.json()
    except Exception as e:
        logger.error(f"SCIM: Invalid JSON in create request: {e}")
        return JSONResponse(
            status_code=400,
            content=create_scim_error(400, "Invalid JSON payload")
        )

    logger.info(f"SCIM: Create user - userName={scim_user.get('userName')}")

    scim_service = SCIMService(db)

    try:
        result, created = scim_service.create_user(scim_user)

        if created:
            return JSONResponse(status_code=201, content=result)
        else:
            # User already existed, was updated
            return JSONResponse(status_code=200, content=result)

    except Exception as e:
        logger.error(f"SCIM: Error creating user: {e}")
        return JSONResponse(
            status_code=400,
            content=create_scim_error(400, str(e))
        )


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_scim_token)
):
    """
    Replace user (full update) from SCIM payload.
    """
    try:
        scim_user = await request.json()
    except Exception as e:
        logger.error(f"SCIM: Invalid JSON in update request: {e}")
        return JSONResponse(
            status_code=400,
            content=create_scim_error(400, "Invalid JSON payload")
        )

    logger.info(f"SCIM: Replace user - id={user_id}")

    scim_service = SCIMService(db)

    try:
        result, created = scim_service.update_user(user_id, scim_user)

        if created:
            return JSONResponse(status_code=201, content=result)
        else:
            return result

    except Exception as e:
        logger.error(f"SCIM: Error updating user: {e}")
        return JSONResponse(
            status_code=400,
            content=create_scim_error(400, str(e))
        )


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_scim_token)
):
    """
    Partially update user using SCIM PATCH operations.

    Supports operations:
    - {"op": "replace", "path": "active", "value": false}
    - {"op": "replace", "path": "displayName", "value": "New Name"}
    """
    try:
        patch_request = await request.json()
    except Exception as e:
        logger.error(f"SCIM: Invalid JSON in patch request: {e}")
        return JSONResponse(
            status_code=400,
            content=create_scim_error(400, "Invalid JSON payload")
        )

    operations = patch_request.get("Operations", [])
    logger.info(f"SCIM: Patch user - id={user_id}, operations={len(operations)}")

    scim_service = SCIMService(db)
    result = scim_service.patch_user(user_id, operations)

    if not result:
        return JSONResponse(
            status_code=404,
            content=create_scim_error(404, f"User {user_id} not found")
        )

    return result


@router.delete("/Users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_scim_token)
):
    """
    Delete (deactivate) a user.

    Note: This soft-deletes by setting is_active=False.
    """
    logger.info(f"SCIM: Delete user - id={user_id}")

    scim_service = SCIMService(db)
    success = scim_service.delete_user(user_id)

    if not success:
        return JSONResponse(
            status_code=404,
            content=create_scim_error(404, f"User {user_id} not found")
        )

    # 204 No Content on successful delete
    return None
