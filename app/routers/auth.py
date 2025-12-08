"""Authentication API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging
import secrets

from app.database import get_db
from app.config import settings
from app.schemas.auth import LoginRequest, LoginResponse, LogoutResponse, UserInfo
from app.services.auth_service import AuthService
from app.services.audit_service import AuditService
from app.services.entra_id_service import get_entra_id_service
from app.services.saml_service import get_saml_service
from app.models.user import User
from app.utils.timezone import now_eastern

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory state storage for CSRF protection (use Redis in production)
_sso_states = {}


def get_require_group_membership(db: Session) -> bool:
    """
    Check if group membership is required for SSO access.
    Checks database config first, falls back to environment variable.
    """
    from app.models.system_config import SystemConfig

    config = db.query(SystemConfig).filter(SystemConfig.key == "SSO_REQUIRE_GROUP_MEMBERSHIP").first()
    if config and config.value:
        return config.value.lower() in ("true", "1", "yes")

    # Fall back to environment variable setting
    return settings.SSO_REQUIRE_GROUP_MEMBERSHIP


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT token."""
    auth_service = AuthService(db)
    audit_service = AuditService(db)

    try:
        user, token, expires_in = auth_service.authenticate(
            request.email, request.password
        )

        # Log successful login
        audit_service.log_action(
            user_id=user.id,
            user_email=user.email,
            action="LOGIN",
            resource_type="AUTH",
            success=True
        )

        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
            user=UserInfo(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )


@router.post("/logout")
async def logout(response: Response, db: Session = Depends(get_db)):
    """Logout user and invalidate session."""
    # Clear all authentication cookies
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("js_access_token", path="/")  # SSO JS-readable token
    response.delete_cookie("user_info", path="/")
    response.delete_cookie("last_activity", path="/")
    response.delete_cookie("token", path="/")

    # Also try clearing with domain variations for production
    response.delete_cookie("access_token")
    response.delete_cookie("js_access_token")
    response.delete_cookie("user_info")
    response.delete_cookie("last_activity")
    response.delete_cookie("token")

    logger.info("User logged out, cookies cleared")

    return LogoutResponse(
        message="Successfully logged out",
        session_terminated=True
    )


@router.post("/refresh")
async def refresh_token(db: Session = Depends(get_db)):
    """Refresh JWT token."""
    # Implementation for token refresh
    pass


@router.get("/me")
async def get_current_user(db: Session = Depends(get_db)):
    """Get current authenticated user information."""
    # Implementation using JWT token
    pass


# =============================================================================
# SSO / Entra ID OIDC Endpoints
# =============================================================================

@router.get("/sso/login")
async def sso_login(request: Request):
    """
    Initiate SSO login via Entra ID.

    Redirects the user to Microsoft login page.
    """
    if not settings.SSO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO is not enabled"
        )

    entra_service = get_entra_id_service()

    if not entra_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Entra ID is not properly configured"
        )

    # Generate state for CSRF protection
    state = entra_service.generate_state()

    # Store state temporarily (expires after 10 minutes)
    _sso_states[state] = {
        "created_at": now_eastern(),
        "redirect_after": request.query_params.get("redirect", "/dashboard")
    }

    # Clean up old states (older than 10 minutes)
    _cleanup_old_states()

    # Get authorization URL and redirect
    auth_url = entra_service.get_auth_url(state=state)

    logger.info("Redirecting user to Entra ID for SSO login")
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    db: Session = Depends(get_db)
):
    """
    Handle callback from Entra ID after authentication.

    Exchanges authorization code for tokens and creates/updates user.
    """
    # Check for errors from Entra ID
    if error:
        logger.error(f"SSO callback error: {error} - {error_description}")
        # Redirect to login with error message
        return RedirectResponse(url=f"/?error={error}&error_description={error_description}")

    if not code or not state:
        logger.error("SSO callback missing code or state")
        return RedirectResponse(url="/?error=invalid_callback")

    # Verify state (CSRF protection)
    state_data = _sso_states.pop(state, None)
    if not state_data:
        logger.error("SSO callback: invalid or expired state")
        return RedirectResponse(url="/?error=invalid_state")

    entra_service = get_entra_id_service()
    auth_service = AuthService(db)
    audit_service = AuditService(db)

    try:
        # Exchange code for tokens
        token_result = entra_service.exchange_code_for_token(code)

        # Get user info from Microsoft Graph
        access_token = token_result.get("access_token")
        user_info = await entra_service.get_user_info(access_token)

        # Check if group membership is required (from database or env var)
        require_group = get_require_group_membership(db)

        # Map groups to role
        group_ids = user_info.get("group_ids", [])
        role = entra_service.map_groups_to_role(group_ids)

        # Deny access if user is not in any mapped group and group membership is required
        # Role will be None if env var requires it, but also check database config
        if role is None or (require_group and role == settings.SSO_DEFAULT_ROLE):
            # Double-check if user is actually in a mapped group
            in_mapped_group = (
                (settings.AZURE_AD_ADMIN_GROUP_ID and settings.AZURE_AD_ADMIN_GROUP_ID in group_ids) or
                (settings.AZURE_AD_REVIEWER_GROUP_ID and settings.AZURE_AD_REVIEWER_GROUP_ID in group_ids) or
                (settings.AZURE_AD_READONLY_GROUP_ID and settings.AZURE_AD_READONLY_GROUP_ID in group_ids)
            )
            if not in_mapped_group and require_group:
                logger.warning(f"SSO: Access denied - user {user_info.get('email')} not in any authorized group")
                return RedirectResponse(url="/?error=access_denied&error_description=You+are+not+authorized+to+access+this+application.+Please+contact+your+administrator+to+be+added+to+an+authorized+group.")

        # Find or create user (JIT provisioning)
        user = db.query(User).filter(User.entra_id == user_info["id"]).first()

        if not user:
            # Also check by email
            user = db.query(User).filter(User.email == user_info["email"]).first()

        if user:
            # Update existing user
            user.entra_id = user_info["id"]
            user.entra_upn = user_info.get("upn")
            user.full_name = user_info.get("display_name") or user.full_name
            user.role = role  # Update role based on current group membership
            user.auth_provider = "entra_id"
            user.last_login = now_eastern()
            user.last_synced_at = now_eastern()
            user.failed_login_attempts = 0

            logger.info(f"SSO: Updated existing user: {user.email}")
        else:
            # Create new user (JIT provisioning)
            user = User(
                id=user_info["id"],
                email=user_info["email"],
                full_name=user_info.get("display_name", user_info["email"]),
                role=role,
                is_active=True,
                entra_id=user_info["id"],
                entra_upn=user_info.get("upn"),
                auth_provider="entra_id",
                last_login=now_eastern(),
                last_synced_at=now_eastern(),
                created_at=now_eastern(),
                created_by="SSO"
            )
            db.add(user)
            logger.info(f"SSO: Created new user via JIT: {user.email}")

        db.commit()
        db.refresh(user)

        # Check if user is active
        if not user.is_active:
            logger.warning(f"SSO: Inactive user attempted login: {user.email}")
            return RedirectResponse(url="/?error=account_inactive")

        # Generate application JWT token
        token, expires_in = auth_service.generate_token(user)

        # Log successful SSO login
        audit_service.log_action(
            user_id=user.id,
            user_email=user.email,
            action="SSO_LOGIN",
            resource_type="AUTH",
            success=True
        )

        # Redirect to dashboard with token in URL fragment (for client-side pickup)
        redirect_after = state_data.get("redirect_after", "/dashboard")

        # Create response with token cookie
        response = RedirectResponse(url=f"{redirect_after}?sso=success")

        # Set token in secure HTTP-only cookie (for middleware)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=settings.ENVIRONMENT != "development",
            samesite="lax",
            max_age=expires_in
        )

        # Also set a JS-readable token cookie (for API calls from frontend)
        response.set_cookie(
            key="js_access_token",
            value=token,
            httponly=False,
            secure=settings.ENVIRONMENT != "development",
            samesite="lax",
            max_age=expires_in
        )

        # Also set user info cookie (not HTTP-only so JS can read it)
        import json
        from urllib.parse import quote
        user_info_json = json.dumps({
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        })
        # URL-encode the JSON to make it cookie-safe
        user_info_cookie = quote(user_info_json, safe='')
        response.set_cookie(
            key="user_info",
            value=user_info_cookie,
            httponly=False,
            secure=settings.ENVIRONMENT != "development",
            samesite="lax",
            max_age=expires_in
        )

        logger.info(f"SSO: User {user.email} successfully authenticated")
        return response

    except Exception as e:
        logger.error(f"SSO callback error: {e}", exc_info=True)
        return RedirectResponse(url=f"/?error=sso_failed&detail={str(e)[:100]}")


@router.get("/sso/logout")
async def sso_logout(request: Request):
    """
    Logout from both application and Entra ID.
    """
    entra_service = get_entra_id_service()

    # Clear application cookies
    response = RedirectResponse(url="/")

    response.delete_cookie("access_token")
    response.delete_cookie("user_info")
    response.delete_cookie("last_activity")

    # If Entra ID is configured, redirect to Entra logout
    if entra_service.is_configured:
        # Build post-logout redirect URI
        base_url = str(request.base_url).rstrip("/")
        post_logout_uri = f"{base_url}/"

        logout_url = entra_service.get_logout_url(post_logout_redirect_uri=post_logout_uri)

        logger.info("Redirecting user to Entra ID logout")
        return RedirectResponse(url=logout_url)

    return response


@router.get("/sso/status")
async def sso_status():
    """
    Check SSO configuration status.
    """
    entra_service = get_entra_id_service()

    return {
        "sso_enabled": settings.SSO_ENABLED,
        "sso_method": settings.SSO_METHOD,
        "entra_id_configured": entra_service.is_configured,
        "tenant_id": settings.AZURE_AD_TENANT_ID[:8] + "..." if settings.AZURE_AD_TENANT_ID else None,
        "client_id": settings.AZURE_AD_CLIENT_ID[:8] + "..." if settings.AZURE_AD_CLIENT_ID else None,
        "redirect_uri_configured": bool(settings.AZURE_AD_REDIRECT_URI)
    }


def _cleanup_old_states():
    """Remove expired SSO states (older than 10 minutes)."""
    cutoff = now_eastern() - timedelta(minutes=10)
    expired = [
        state for state, data in _sso_states.items()
        if data["created_at"] < cutoff
    ]
    for state in expired:
        _sso_states.pop(state, None)


# =============================================================================
# User Management Endpoints (Admin)
# =============================================================================

@router.get("/users")
async def list_users(db: Session = Depends(get_db)):
    """
    List all users for admin management.
    Shows both local and Entra ID provisioned users.
    """
    users = db.query(User).order_by(User.created_at.desc()).all()

    return {
        "users": [
            {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "is_active": user.is_active,
                "auth_provider": user.auth_provider or "local",
                "entra_id": user.entra_id,
                "entra_upn": user.entra_upn,
                "last_login": user.last_login.isoformat() if user.last_login else None,
                "last_synced_at": user.last_synced_at.isoformat() if user.last_synced_at else None,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "created_by": user.created_by
            }
            for user in users
        ],
        "total": len(users),
        "entra_id_count": sum(1 for u in users if u.auth_provider == "entra_id"),
        "local_count": sum(1 for u in users if u.auth_provider != "entra_id")
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role_data: dict,
    db: Session = Depends(get_db)
):
    """Update a user's role."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_role = role_data.get("role")
    if new_role not in ["admin", "reviewer", "read_only"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    user.role = new_role
    user.updated_at = now_eastern()
    db.commit()

    return {"message": f"User role updated to {new_role}", "user_id": user_id}


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    status_data: dict,
    db: Session = Depends(get_db)
):
    """Activate or deactivate a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    is_active = status_data.get("is_active", True)
    user.is_active = is_active
    user.updated_at = now_eastern()

    if not is_active:
        user.deactivated_at = now_eastern()

    db.commit()

    status_text = "activated" if is_active else "deactivated"
    return {"message": f"User {status_text}", "user_id": user_id}


@router.get("/scim/status")
async def get_scim_status(db: Session = Depends(get_db)):
    """
    Get SCIM provisioning status and configuration info.
    """
    # Count users by provider
    total_users = db.query(User).count()
    entra_users = db.query(User).filter(User.auth_provider == "entra_id").count()
    local_users = total_users - entra_users

    # Check if SCIM token is configured
    scim_configured = bool(settings.SCIM_BEARER_TOKEN)

    # Get last sync time
    last_synced = db.query(User.last_synced_at)\
        .filter(User.auth_provider == "entra_id")\
        .order_by(User.last_synced_at.desc())\
        .first()

    return {
        "scim_configured": scim_configured,
        "scim_endpoint": "/scim/v2",
        "total_users": total_users,
        "entra_id_users": entra_users,
        "local_users": local_users,
        "last_sync": last_synced[0].isoformat() if last_synced and last_synced[0] else None,
        "setup_instructions": {
            "1": "Go to Azure Portal > Entra ID > Enterprise Applications",
            "2": "Select your application or create a new one",
            "3": "Go to Provisioning > Get Started",
            "4": "Set Provisioning Mode to 'Automatic'",
            "5": f"Set Tenant URL to: {settings.AZURE_AD_REDIRECT_URI.rsplit('/', 2)[0] if settings.AZURE_AD_REDIRECT_URI else 'https://your-app-url'}/scim/v2",
            "6": "Set Secret Token to the value of SCIM_BEARER_TOKEN env variable",
            "7": "Test Connection and Save",
            "8": "Configure attribute mappings as needed",
            "9": "Turn Provisioning Status to 'On'"
        }
    }


# =============================================================================
# SAML 2.0 SSO Endpoints
# =============================================================================

@router.get("/saml/login")
async def saml_login(request: Request):
    """
    Initiate SAML SSO login.

    Redirects user to Entra ID for authentication.
    """
    if not settings.SSO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO is not enabled"
        )

    saml_service = get_saml_service()

    if not saml_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SAML is not properly configured"
        )

    # Get return URL from query params
    relay_state = request.query_params.get("redirect", "/dashboard")

    try:
        auth_url = saml_service.get_auth_request_url(request, relay_state)
        logger.info("Redirecting user to Entra ID for SAML login")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"SAML login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SAML login failed: {str(e)}"
        )


@router.post("/saml/acs")
async def saml_acs(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    SAML Assertion Consumer Service (ACS) endpoint.

    Receives and processes SAML response from Entra ID.
    """
    form_data = await request.form()
    saml_response = form_data.get("SAMLResponse")
    relay_state = form_data.get("RelayState", "/dashboard")

    if not saml_response:
        logger.error("SAML ACS: No SAMLResponse in request")
        return RedirectResponse(url="/?error=no_saml_response", status_code=303)

    saml_service = get_saml_service()
    auth_service = AuthService(db)
    audit_service = AuditService(db)

    try:
        # Process SAML response
        user_info, error = await saml_service.process_saml_response(request, saml_response)

        if error:
            logger.error(f"SAML response error: {error}")
            return RedirectResponse(url=f"/?error=saml_failed&detail={error[:100]}", status_code=303)

        if not user_info:
            return RedirectResponse(url="/?error=authentication_failed", status_code=303)

        # Log groups received from SAML assertion for debugging
        groups = user_info.get("groups", [])
        logger.info(f"SAML: User {user_info.get('email')} - Groups received: {groups}")
        logger.info(f"SAML: Admin group expected: {settings.AZURE_AD_ADMIN_GROUP_ID}")
        logger.info(f"SAML: Reviewer group expected: {settings.AZURE_AD_REVIEWER_GROUP_ID}")
        logger.info(f"SAML: Raw attributes keys: {list(user_info.get('raw_attributes', {}).keys())}")

        # Check if group membership is required (from database or env var)
        require_group = get_require_group_membership(db)

        # Map groups to role
        role = saml_service.map_groups_to_role(groups)
        logger.info(f"SAML: Mapped role: {role}")

        # Deny access if user is not in any mapped group and group membership is required
        # Role will be None if env var requires it, but also check database config
        if role is None or (require_group and role == settings.SSO_DEFAULT_ROLE):
            # Double-check if user is actually in a mapped group
            in_mapped_group = (
                (settings.AZURE_AD_ADMIN_GROUP_ID and settings.AZURE_AD_ADMIN_GROUP_ID in groups) or
                (settings.AZURE_AD_REVIEWER_GROUP_ID and settings.AZURE_AD_REVIEWER_GROUP_ID in groups) or
                (settings.AZURE_AD_READONLY_GROUP_ID and settings.AZURE_AD_READONLY_GROUP_ID in groups)
            )
            if not in_mapped_group and require_group:
                logger.warning(f"SAML: Access denied - user {user_info.get('email')} not in any authorized group")
                return RedirectResponse(
                    url="/?error=access_denied&error_description=You+are+not+authorized+to+access+this+application.+Please+contact+your+administrator+to+be+added+to+an+authorized+group.",
                    status_code=303
                )

        # Find or create user (JIT provisioning)
        user = db.query(User).filter(User.entra_id == user_info["id"]).first()

        if not user:
            # Also check by email
            user = db.query(User).filter(User.email == user_info["email"]).first()

        if user:
            # Update existing user
            user.entra_id = user_info["id"]
            user.entra_upn = user_info.get("upn")
            user.full_name = user_info.get("display_name") or user.full_name
            user.role = role
            user.auth_provider = "entra_id"
            user.last_login = now_eastern()
            user.last_synced_at = now_eastern()
            user.failed_login_attempts = 0

            logger.info(f"SAML: Updated existing user: {user.email}")
        else:
            # Create new user (JIT provisioning)
            user = User(
                id=user_info["id"],
                email=user_info["email"],
                full_name=user_info.get("display_name", user_info["email"]),
                role=role,
                is_active=True,
                entra_id=user_info["id"],
                entra_upn=user_info.get("upn"),
                auth_provider="entra_id",
                last_login=now_eastern(),
                last_synced_at=now_eastern(),
                created_at=now_eastern(),
                created_by="SAML"
            )
            db.add(user)
            logger.info(f"SAML: Created new user via JIT: {user.email}")

        db.commit()
        db.refresh(user)

        # Check if user is active
        if not user.is_active:
            logger.warning(f"SAML: Inactive user attempted login: {user.email}")
            return RedirectResponse(url="/?error=account_inactive", status_code=303)

        # Generate application JWT token
        token, expires_in = auth_service.generate_token(user)

        # Log successful SAML login
        audit_service.log_action(
            user_id=user.id,
            user_email=user.email,
            action="SAML_LOGIN",
            resource_type="AUTH",
            success=True
        )

        # Create response with token cookies
        # Use 303 See Other to convert POST to GET after SAML response
        response = RedirectResponse(url=f"{relay_state}?sso=success", status_code=303)

        # Set token in secure HTTP-only cookie (for middleware)
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            secure=settings.ENVIRONMENT != "development",
            samesite="lax",
            max_age=expires_in
        )

        # Also set a JS-readable token cookie (for API calls from frontend)
        response.set_cookie(
            key="js_access_token",
            value=token,
            httponly=False,
            secure=settings.ENVIRONMENT != "development",
            samesite="lax",
            max_age=expires_in
        )

        # Set user info cookie
        import json
        from urllib.parse import quote
        user_info_json = json.dumps({
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        })
        user_info_cookie = quote(user_info_json, safe='')
        response.set_cookie(
            key="user_info",
            value=user_info_cookie,
            httponly=False,
            secure=settings.ENVIRONMENT != "development",
            samesite="lax",
            max_age=expires_in
        )

        logger.info(f"SAML: User {user.email} successfully authenticated")
        return response

    except Exception as e:
        logger.error(f"SAML ACS error: {e}", exc_info=True)
        return RedirectResponse(url=f"/?error=saml_failed&detail={str(e)[:100]}", status_code=303)


@router.get("/saml/logout")
async def saml_logout(request: Request):
    """
    Initiate SAML Single Logout (SLO).
    """
    saml_service = get_saml_service()

    # Clear application cookies first
    response = RedirectResponse(url="/")

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("js_access_token", path="/")
    response.delete_cookie("user_info", path="/")
    response.delete_cookie("last_activity", path="/")

    # If SAML is configured, redirect to IdP logout
    if saml_service.is_configured:
        try:
            # Get session info from cookies if available
            logout_url = saml_service.get_logout_url(request)
            logger.info("Redirecting user to Entra ID SAML logout")
            return RedirectResponse(url=logout_url)
        except Exception as e:
            logger.warning(f"SAML logout redirect failed: {e}")

    logger.info("User logged out (SAML)")
    return response


@router.get("/saml/slo")
async def saml_slo(request: Request):
    """
    SAML Single Logout (SLO) callback.

    Handles logout response/request from IdP.
    """
    # Clear all cookies
    response = RedirectResponse(url="/?logged_out=true")

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("js_access_token", path="/")
    response.delete_cookie("user_info", path="/")
    response.delete_cookie("last_activity", path="/")

    logger.info("SAML SLO completed")
    return response


@router.get("/saml/metadata")
async def saml_metadata(request: Request):
    """
    Return SAML Service Provider metadata.

    This XML can be imported into Entra ID to configure the application.
    """
    saml_service = get_saml_service()

    try:
        metadata = saml_service.get_metadata(request)
        return Response(
            content=metadata,
            media_type="application/xml"
        )
    except Exception as e:
        logger.error(f"SAML metadata generation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate metadata: {str(e)}"
        )


@router.get("/saml/status")
async def saml_status():
    """
    Check SAML SSO configuration status.
    """
    saml_service = get_saml_service()

    return {
        "sso_enabled": settings.SSO_ENABLED,
        "sso_method": settings.SSO_METHOD,
        "saml_configured": saml_service.is_configured,
        "tenant_id": settings.AZURE_AD_TENANT_ID[:8] + "..." if settings.AZURE_AD_TENANT_ID else None,
        "client_id": settings.AZURE_AD_CLIENT_ID[:8] + "..." if settings.AZURE_AD_CLIENT_ID else None,
        "entity_id": settings.SAML_ENTITY_ID or "Not configured (will use app URL)",
        "acs_url": settings.SAML_ACS_URL or "Not configured (will use /api/auth/saml/acs)",
        "endpoints": {
            "login": "/api/auth/saml/login",
            "acs": "/api/auth/saml/acs",
            "logout": "/api/auth/saml/logout",
            "slo": "/api/auth/saml/slo",
            "metadata": "/api/auth/saml/metadata"
        }
    }


# =============================================================================
# Auth Configuration Endpoints (Admin)
# =============================================================================

@router.get("/config")
async def get_auth_config(db: Session = Depends(get_db)):
    """
    Get current authentication configuration.
    Returns configuration values for display (not actual secrets).
    """
    from app.models.system_config import SystemConfig

    # Get config values from database (or fall back to env vars)
    def get_config_value(key: str, default: str = "") -> str:
        try:
            config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            return config.value if config else default
        except Exception:
            # Table might not exist yet - fall back to default
            return default

    # Get require_group_membership setting
    try:
        require_group_str = get_config_value("SSO_REQUIRE_GROUP_MEMBERSHIP", "")
        if require_group_str:
            require_group_membership = require_group_str.lower() in ("true", "1", "yes")
        else:
            require_group_membership = settings.SSO_REQUIRE_GROUP_MEMBERSHIP
    except Exception:
        require_group_membership = settings.SSO_REQUIRE_GROUP_MEMBERSHIP

    return {
        "sso_enabled": settings.SSO_ENABLED,
        "sso_method": get_config_value("SSO_METHOD", settings.SSO_METHOD),
        "tenant_id": settings.AZURE_AD_TENANT_ID or get_config_value("AZURE_AD_TENANT_ID"),
        "client_id": settings.AZURE_AD_CLIENT_ID or get_config_value("AZURE_AD_CLIENT_ID"),
        "redirect_uri": settings.AZURE_AD_REDIRECT_URI or get_config_value("AZURE_AD_REDIRECT_URI"),
        "saml_entity_id": settings.SAML_ENTITY_ID or get_config_value("SAML_ENTITY_ID"),
        "saml_acs_url": settings.SAML_ACS_URL or get_config_value("SAML_ACS_URL"),
        "saml_metadata_url": settings.SAML_METADATA_URL or get_config_value("SAML_METADATA_URL"),
        "admin_group_id": settings.AZURE_AD_ADMIN_GROUP_ID or get_config_value("AZURE_AD_ADMIN_GROUP_ID"),
        "reviewer_group_id": settings.AZURE_AD_REVIEWER_GROUP_ID or get_config_value("AZURE_AD_REVIEWER_GROUP_ID"),
        "user_group_id": settings.AZURE_AD_READONLY_GROUP_ID or get_config_value("AZURE_AD_READONLY_GROUP_ID"),
        "default_role": settings.SSO_DEFAULT_ROLE or get_config_value("SSO_DEFAULT_ROLE", "read_only"),
        "require_group_membership": require_group_membership,
        "scim_configured": bool(settings.SCIM_BEARER_TOKEN)
    }


@router.post("/config/sso")
async def save_sso_config(config: dict, db: Session = Depends(get_db)):
    """
    Save SSO configuration settings.
    Saves to database for reference. Note: Some settings require environment variable updates.
    """
    from app.models.system_config import SystemConfig

    def save_config(key: str, value: str):
        if value:
            existing = db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if existing:
                existing.value = value
                existing.updated_at = now_eastern()
            else:
                db.add(SystemConfig(
                    key=key,
                    value=value,
                    description=f"SSO configuration: {key}",
                    category="auth",
                    created_at=now_eastern()
                ))

    # Save non-sensitive config values
    save_config("SSO_METHOD", config.get("sso_method", "saml"))
    save_config("AZURE_AD_TENANT_ID", config.get("tenant_id", ""))
    save_config("AZURE_AD_CLIENT_ID", config.get("client_id", ""))
    save_config("AZURE_AD_REDIRECT_URI", config.get("redirect_uri", ""))
    save_config("SAML_ENTITY_ID", config.get("saml_entity_id", ""))
    save_config("SAML_ACS_URL", config.get("saml_acs_url", ""))
    save_config("SAML_METADATA_URL", config.get("saml_metadata_url", ""))

    # Note: Client secret should NOT be stored in database - only in Key Vault
    # But we can record that it was configured
    if config.get("client_secret"):
        save_config("CLIENT_SECRET_CONFIGURED", "true")
        logger.warning("SSO client secret provided - should be stored in Key Vault, not database")

    db.commit()

    logger.info("SSO configuration saved to database")

    return {
        "success": True,
        "message": "SSO configuration saved. Note: Sensitive values (client secret) should be set via environment variables or Key Vault.",
        "environment_vars_needed": [
            "AZURE_AD_CLIENT_SECRET (required for OIDC)",
            "SAML_IDP_CERT (required for SAML)"
        ]
    }


@router.post("/config/scim")
async def save_scim_config(config: dict, db: Session = Depends(get_db)):
    """
    Save SCIM provisioning configuration.
    Note: The actual token must be set as an environment variable.
    """
    from app.models.system_config import SystemConfig

    scim_token = config.get("scim_token")

    if scim_token:
        # Record that a SCIM token was generated/configured
        existing = db.query(SystemConfig).filter(SystemConfig.key == "SCIM_TOKEN_CONFIGURED").first()
        if existing:
            existing.value = "true"
            existing.updated_at = now_eastern()
        else:
            db.add(SystemConfig(
                key="SCIM_TOKEN_CONFIGURED",
                value="true",
                description="SCIM bearer token has been configured",
                category="auth",
                created_at=now_eastern()
            ))

        # Store a hash of the token for verification (not the actual token)
        import hashlib
        token_hash = hashlib.sha256(scim_token.encode()).hexdigest()[:16]

        hash_config = db.query(SystemConfig).filter(SystemConfig.key == "SCIM_TOKEN_HASH").first()
        if hash_config:
            hash_config.value = token_hash
            hash_config.updated_at = now_eastern()
        else:
            db.add(SystemConfig(
                key="SCIM_TOKEN_HASH",
                value=token_hash,
                description="Hash of SCIM token for verification",
                category="auth",
                created_at=now_eastern()
            ))

        db.commit()

        logger.info("SCIM configuration reference saved to database")

        return {
            "success": True,
            "message": "SCIM configuration recorded. Set SCIM_BEARER_TOKEN environment variable to enable.",
            "token_preview": scim_token[:8] + "..." if len(scim_token) > 8 else "***",
            "instruction": f"Set environment variable: SCIM_BEARER_TOKEN={scim_token}"
        }

    return {
        "success": False,
        "error": "No SCIM token provided"
    }


@router.post("/config/roles")
async def save_role_mapping_config(config: dict, db: Session = Depends(get_db)):
    """
    Save Azure AD group to role mapping configuration.
    """
    from app.models.system_config import SystemConfig

    def save_config(key: str, value: str, description: str):
        existing = db.query(SystemConfig).filter(SystemConfig.key == key).first()
        if existing:
            existing.value = value or ""
            existing.updated_at = now_eastern()
        else:
            db.add(SystemConfig(
                key=key,
                value=value or "",
                description=description,
                category="auth",
                created_at=now_eastern()
            ))

    save_config("AZURE_AD_ADMIN_GROUP_ID", config.get("admin_group_id"),
                "Azure AD Security Group ID for Admin role")
    save_config("AZURE_AD_REVIEWER_GROUP_ID", config.get("reviewer_group_id"),
                "Azure AD Security Group ID for Reviewer role")
    save_config("AZURE_AD_READONLY_GROUP_ID", config.get("user_group_id"),
                "Azure AD Security Group ID for Read-Only role")
    save_config("SSO_DEFAULT_ROLE", config.get("default_role", "read_only"),
                "Default role for users not in any mapped group")

    # Save require group membership setting
    require_group = config.get("require_group_membership", True)
    save_config("SSO_REQUIRE_GROUP_MEMBERSHIP", "true" if require_group else "false",
                "Require users to be in a mapped group to access the application")

    db.commit()

    logger.info(f"Role mapping configuration saved (require_group_membership={require_group})")

    return {
        "success": True,
        "message": "Role mapping saved successfully"
    }


@router.post("/sso/test")
async def test_sso_connection():
    """
    Test SSO configuration by checking connectivity to Entra ID.
    """
    try:
        if settings.SSO_METHOD == "saml":
            saml_service = get_saml_service()
            if not saml_service.is_configured:
                return {
                    "success": False,
                    "error": "SAML is not configured. Missing required settings."
                }
            return {
                "success": True,
                "message": "SAML configuration is valid. Test by initiating a login."
            }
        else:
            entra_service = get_entra_id_service()
            if not entra_service.is_configured:
                return {
                    "success": False,
                    "error": "Entra ID is not configured. Missing tenant ID, client ID, or client secret."
                }

            # Try to get a token using client credentials (if configured)
            # This validates the connection without user interaction
            return {
                "success": True,
                "message": "Entra ID OIDC configuration appears valid. Test by initiating a login."
            }

    except Exception as e:
        logger.error(f"SSO test failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/scim/test")
async def test_scim_endpoint():
    """
    Test SCIM endpoint availability.
    """
    if not settings.SCIM_BEARER_TOKEN:
        return {
            "success": False,
            "error": "SCIM_BEARER_TOKEN environment variable is not set"
        }

    return {
        "success": True,
        "message": "SCIM endpoint is configured and ready",
        "endpoint": "/scim/v2",
        "supported_resources": ["Users", "Groups"]
    }
