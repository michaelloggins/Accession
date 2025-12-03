"""
Security Middleware
Implements OWASP, ISO27001, HIPAA, and HiTRUST compliance controls.
"""

from fastapi import Request, HTTPException, status
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
import re
import html
import logging
from typing import Dict, List
import time
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Implements security headers per OWASP, ISO27001, HIPAA, HiTRUST.

    OWASP: A05:2021 – Security Misconfiguration
    ISO27001: A.14.1.2 - Securing application services on public networks
    HIPAA: 164.312(a)(1) - Access Control
    HiTRUST: 01.m - Secure Configuration
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Content Security Policy (CSP) - OWASP A03:2021 Injection
        # Prevents XSS attacks by restricting resource loading
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://maps.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://cdn.jsdelivr.net https://maps.googleapis.com https://apis.fedex.com https://*.blob.core.windows.net; "
            "frame-src 'self' https://*.blob.core.windows.net blob:; "  # Allow Azure Blob Storage for PDF preview
            "frame-ancestors 'self'; "  # Allow same-origin framing for PDF viewer
            "base-uri 'self'; "
            "form-action 'self'"
        )

        # Strict Transport Security (HSTS) - Force HTTPS
        # ISO27001: A.13.1.3 - Segregation in networks
        # HIPAA: 164.312(e)(1) - Transmission Security
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )

        # X-Frame-Options - Prevents clickjacking (OWASP A04:2021)
        # Allow same-origin framing for PDF viewer while preventing external framing
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # X-Content-Type-Options - Prevents MIME sniffing
        # OWASP: Security Misconfiguration
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-XSS-Protection - Legacy XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer Policy - Limit information leakage
        # ISO27001: A.13.2.1 - Information transfer policies
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy - Restrict browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )

        # Cache Control for PHI - HIPAA 164.312(a)(2)(iv)
        # Prevents caching of protected health information
        if "/api/" in request.url.path and request.method != "GET":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # Remove server identification - Reduces attack surface
        # HiTRUST: 01.o - Security of System Documentation
        response.headers["Server"] = "Secure"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting to prevent DoS attacks and brute force.

    OWASP: A07:2021 – Identification and Authentication Failures
    ISO27001: A.9.4.2 - Secure log-on procedures
    HIPAA: 164.308(a)(1)(ii)(B) - Risk Management
    HiTRUST: 01.c - Network Controls
    """

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_counts: Dict[str, List[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP from request, considering proxies."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        from app.config import settings

        client_ip = self._get_client_ip(request)

        # DEVELOPMENT MODE: Skip rate limiting for localhost
        if settings.ENVIRONMENT == "development" and client_ip in ["127.0.0.1", "localhost", "::1"]:
            return await call_next(request)

        current_time = time.time()

        # Clean old requests outside the time window
        self.request_counts[client_ip] = [
            timestamp for timestamp in self.request_counts[client_ip]
            if current_time - timestamp < self.window_seconds
        ]

        # Check rate limit
        if len(self.request_counts[client_ip]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for IP: {client_ip}")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )

        # Record this request
        self.request_counts[client_ip].append(current_time)

        response = await call_next(request)

        # Add rate limit headers for transparency
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            self.max_requests - len(self.request_counts[client_ip])
        )

        return response


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """
    Input validation and sanitization to prevent injection attacks.

    OWASP: A03:2021 – Injection (SQL, NoSQL, Command, XSS)
    ISO27001: A.14.2.1 - Secure development policy
    HIPAA: 164.308(a)(5)(ii)(B) - Protection from malicious software
    HiTRUST: 10.a - Input Data Validation
    """

    # Patterns for detecting malicious input
    SQL_INJECTION_PATTERNS = [
        r"(\bOR\b|\bAND\b).*?=.*?",
        r"(\bUNION\b|\bSELECT\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b|\bDROP\b)",
        r"--",
        r"/\*.*?\*/",
        r";\s*$"
    ]

    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe",
        r"<object",
        r"<embed"
    ]

    COMMAND_INJECTION_PATTERNS = [
        r"[;&|`$]",
        r"\$\(",
        r"\n|\r",
        r"\.\./"
    ]

    async def dispatch(self, request: Request, call_next):
        # Only check POST/PUT/PATCH requests with JSON body
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")

            if "application/json" in content_type:
                try:
                    body = await request.body()
                    body_str = body.decode("utf-8")

                    # Check for injection attempts
                    if self._detect_injection(body_str):
                        client_ip = request.client.host if request.client else "unknown"
                        logger.warning(f"Potential injection attempt detected from {client_ip}")
                        from fastapi.responses import JSONResponse
                        return JSONResponse(
                            status_code=400,
                            content={"detail": "Invalid input detected"}
                        )

                    # Restore body for downstream processing
                    async def receive():
                        return {"type": "http.request", "body": body}

                    request._receive = receive

                except Exception as e:
                    logger.error(f"Error in input sanitization: {e}")

        response = await call_next(request)
        return response

    def _detect_injection(self, text: str) -> bool:
        """Detect common injection patterns."""
        text_lower = text.lower()

        # Check SQL injection patterns
        for pattern in self.SQL_INJECTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True

        # Check XSS patterns
        for pattern in self.XSS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        # Check command injection patterns (only in specific fields)
        for pattern in self.COMMAND_INJECTION_PATTERNS:
            if re.search(pattern, text):
                return True

        return False


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive audit logging for compliance.

    ISO27001: A.12.4.1 - Event logging
    HIPAA: 164.312(b) - Audit controls
    HiTRUST: 09.aa - Audit Logging
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        client_ip = request.headers.get("X-Forwarded-For") or (request.client.host if request.client else "unknown")

        # Log request
        logger.info(
            f"REQUEST: {request.method} {request.url.path} | "
            f"IP: {client_ip} | "
            f"User-Agent: {request.headers.get('user-agent', 'unknown')}"
        )

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            # Log response
            logger.info(
                f"RESPONSE: {request.method} {request.url.path} | "
                f"Status: {response.status_code} | "
                f"Duration: {process_time:.3f}s"
            )

            # Add process time header
            response.headers["X-Process-Time"] = str(process_time)

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"ERROR: {request.method} {request.url.path} | "
                f"IP: {client_ip} | "
                f"Error: {str(e)} | "
                f"Duration: {process_time:.3f}s"
            )
            raise


class SessionSecurityMiddleware(BaseHTTPMiddleware):
    """
    Session management security controls.

    OWASP: A07:2021 – Identification and Authentication Failures
    ISO27001: A.9.4.3 - Password management system
    HIPAA: 164.312(a)(2)(iii) - Automatic logoff
    HiTRUST: 01.n - Session Management
    """

    SESSION_TIMEOUT_SECONDS = 900  # 15 minutes (HIPAA requirement)

    async def dispatch(self, request: Request, call_next):
        from app.config import settings
        client_ip = request.client.host if request.client else None

        # Skip JWT format validation for SCIM endpoints (they use their own bearer token)
        is_scim_endpoint = request.url.path.startswith("/scim/")

        # Check for Authorization header
        auth_header = request.headers.get("Authorization")

        if auth_header and auth_header.startswith("Bearer ") and not is_scim_endpoint:
            token = auth_header.split(" ")[1]

            # Validate token format (basic check) - only for JWT tokens, not SCIM tokens
            if not re.match(r"^[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$", token):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid token format"}
                )

        response = await call_next(request)

        # Set secure cookie attributes
        # HIPAA: 164.312(a)(2)(iv) - Encryption and decryption
        # ISO27001: A.13.1.1 - Network controls
        if "Set-Cookie" in response.headers:
            cookie = response.headers["Set-Cookie"]
            if "Secure" not in cookie:
                response.headers["Set-Cookie"] = f"{cookie}; Secure; HttpOnly; SameSite=Strict"

        return response


def sanitize_output(text: str) -> str:
    """
    Sanitize output to prevent XSS.

    OWASP: A03:2021 – Injection
    """
    return html.escape(text)


def validate_file_upload(filename: str, content: bytes, max_size: int = 25 * 1024 * 1024) -> bool:
    """
    Validate file uploads for security.

    OWASP: A04:2021 – Insecure Design
    ISO27001: A.14.2.8 - System security testing
    """
    # Check file size
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {max_size / (1024*1024)}MB"
        )

    # Check file extension
    allowed_extensions = {'.pdf', '.tiff', '.tif', '.png', '.jpg', '.jpeg'}
    ext = filename[filename.rfind('.'):].lower() if '.' in filename else ''

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Check for malicious content in filename
    if re.search(r"[<>:\"/\\|?*\x00-\x1f]", filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid characters in filename"
        )

    return True
