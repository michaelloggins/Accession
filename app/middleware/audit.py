"""Audit logging middleware for request tracking."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import logging
import time

logger = logging.getLogger(__name__)


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware for audit logging of all requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Log request details for audit trail."""
        start_time = time.time()

        # Extract request information
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""

        # Process request
        try:
            response = await call_next(request)
            status_code = response.status_code
            success = status_code < 400

        except Exception as e:
            logger.error(f"Request error: {e}")
            status_code = 500
            success = False
            raise

        finally:
            # Calculate processing time
            process_time = time.time() - start_time

            # Log request (in production, store in audit_logs table)
            logger.info(
                f"Request: {method} {path} | "
                f"Status: {status_code} | "
                f"Time: {process_time:.3f}s | "
                f"IP: {client_ip} | "
                f"Agent: {user_agent[:50]}"
            )

        # Add custom headers
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "")

        return response
