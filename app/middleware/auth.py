"""Authentication middleware for session management."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import logging
from datetime import datetime, timedelta

from app.config import settings
from app.services.config_service import ConfigService

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = [
    "/",
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/sso",        # SSO login initiation (OIDC)
    "/api/auth/callback",   # SSO callback from Entra ID (OIDC)
    "/api/auth/saml",       # SAML SSO endpoints (login, acs, logout, slo, metadata, status)
    "/api/tests",           # Test catalog is public for all authenticated pages
    "/health",
    "/static",
    "/api/docs",
    "/api/redoc",
    "/openapi.json",
    "/scim",                # SCIM provisioning (uses its own bearer token auth)
]


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware for authentication and session management."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Check authentication and session validity."""
        path = request.url.path

        # Skip authentication for public paths
        if self._is_public_path(path):
            return await call_next(request)

        # Check for authentication token (from header or cookie)
        auth_header = request.headers.get("Authorization")
        access_token_cookie = request.cookies.get("access_token")  # SSO sets this
        session_cookie = request.cookies.get("session_token")  # Legacy

        # Get token from any available source
        token = None
        if auth_header:
            token = auth_header.replace("Bearer ", "")
        elif access_token_cookie:
            token = access_token_cookie
        elif session_cookie:
            token = session_cookie

        if not token:
            # Check if auth bypass is enabled (allows unauthenticated access)
            config_service = ConfigService()
            if config_service.get_bool("DEV_AUTH_BYPASS", False):
                logger.debug(f"Auth bypass enabled: allowing unauthenticated access to {path}")
                return await call_next(request)

            # For API requests, return 401
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"}
                )
            # For page requests, redirect to login (handled by frontend)
            return await call_next(request)

        # Verify token
        if not self._verify_token(token):
            # If auth bypass enabled, treat invalid tokens as "no token" and allow access
            config_service = ConfigService()
            if config_service.get_bool("DEV_AUTH_BYPASS", False):
                logger.debug(f"Auth bypass enabled: ignoring invalid token for {path}")
                return await call_next(request)

            # For API requests, return 401
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or expired token"}
                )
            # For page requests, let it through (frontend will redirect)
            return await call_next(request)

        # Check session timeout
        last_activity = request.cookies.get("last_activity")
        if last_activity:
            try:
                last_time = datetime.fromisoformat(last_activity)
                if datetime.utcnow() - last_time > timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES):
                    logger.warning("Session timeout detected")
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Session expired due to inactivity"}
                    )
            except ValueError:
                pass

        # Process request
        response = await call_next(request)

        # Update last activity timestamp
        response.set_cookie(
            key="last_activity",
            value=datetime.utcnow().isoformat(),
            httponly=True,
            secure=settings.ENVIRONMENT != "development",
            samesite="strict"
        )

        return response

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        # Special case: document file endpoints with token parameter
        if "/api/documents/" in path and "/file" in path:
            return True

        for public_path in PUBLIC_PATHS:
            if path == public_path or path.startswith(public_path + "/"):
                return True
        return False

    def _verify_token(self, token: str) -> bool:
        """Verify JWT token (placeholder)."""
        # In production, use AuthService.verify_token()
        try:
            import jwt
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            return True
        except Exception:
            return False
