"""
Main FastAPI Application Entry Point
"""

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
import logging
import traceback
import os
from pathlib import Path

# Get the base directory (parent of app/)
BASE_DIR = Path(__file__).resolve().parent.parent

from app.config import settings
from app.database import engine, Base
# Import all models to register them with Base before create_all
from app.models import (
    Document, User, AuditLog, SystemConfig, ExtractionBatch,
    Facility, FacilityPhysician, FacilityMatchLog, Species, Patient,
    Test, TestSpecimenType, Order, OrderTest, Integration, ApiKey,
    IntegrationLog, ScanningStation, LabelPrinter, LaserPrinter, UserWorkstationPreference,
    CodeAuditResult, CodeAuditSchedule, CodeAuditJob
)
from app.routers import auth, documents, compliance, stats, tests, facilities, config, scim, queue, integrations, patients, workstation, scan, print as print_router, code_audit
from app.middleware.audit import AuditMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.security import (
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    InputSanitizationMiddleware,
    AuditLoggingMiddleware,
    SessionSecurityMiddleware
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Lab Document Intelligence System")

    # Create all tables (this only creates tables that don't exist)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        # Continue anyway - tables might already exist

    # Run schema migrations for new columns (SQLAlchemy create_all doesn't add columns to existing tables)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        existing_columns = [col['name'] for col in inspector.get_columns('users')]

        migrations = [
            ("entra_id", "NVARCHAR(100) NULL"),
            ("entra_upn", "NVARCHAR(255) NULL"),
            ("auth_provider", "NVARCHAR(50) DEFAULT 'local'"),
            ("last_synced_at", "DATETIME2 NULL"),
            ("first_name", "NVARCHAR(100) NULL"),
            ("last_name", "NVARCHAR(100) NULL"),
        ]

        with engine.connect() as conn:
            for col_name, col_def in migrations:
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE users ADD {col_name} {col_def}"))
                        conn.commit()
                        logger.info(f"Added column '{col_name}' to users table")
                    except Exception as col_err:
                        if "already exists" not in str(col_err).lower():
                            logger.warning(f"Could not add column '{col_name}': {col_err}")
        logger.info("Schema migrations completed")
    except Exception as e:
        logger.error(f"Schema migration error: {e}")

    # Run schema migrations for documents table (scan station columns)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        existing_doc_columns = [col['name'] for col in inspector.get_columns('documents')]

        doc_migrations = [
            ("scan_station_id", "INT NULL"),
            ("scan_station_name", "NVARCHAR(100) NULL"),
            ("scanned_by", "NVARCHAR(100) NULL"),
            ("scanned_at", "DATETIME2 NULL"),
        ]

        with engine.connect() as conn:
            for col_name, col_def in doc_migrations:
                if col_name not in existing_doc_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE documents ADD {col_name} {col_def}"))
                        conn.commit()
                        logger.info(f"Added column '{col_name}' to documents table")
                    except Exception as col_err:
                        if "already exists" not in str(col_err).lower():
                            logger.warning(f"Could not add column '{col_name}': {col_err}")
        logger.info("Documents schema migrations completed")
    except Exception as e:
        logger.error(f"Documents schema migration error: {e}")

    # Run schema migrations for label_printers table (Universal Print columns)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        existing_printer_columns = [col['name'] for col in inspector.get_columns('label_printers')]

        printer_migrations = [
            ("universal_print_id", "NVARCHAR(255) NULL"),
            ("print_method", "NVARCHAR(50) DEFAULT 'universal_print'"),
            ("label_width_dpi", "INT DEFAULT 203"),
            ("label_width_inches", "NVARCHAR(10) DEFAULT '2'"),
            ("label_height_inches", "NVARCHAR(10) DEFAULT '1'"),
        ]

        with engine.connect() as conn:
            for col_name, col_def in printer_migrations:
                if col_name not in existing_printer_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE label_printers ADD {col_name} {col_def}"))
                        conn.commit()
                        logger.info(f"Added column '{col_name}' to label_printers table")
                    except Exception as col_err:
                        if "already exists" not in str(col_err).lower():
                            logger.warning(f"Could not add column '{col_name}': {col_err}")
        logger.info("Label printers schema migrations completed")
    except Exception as e:
        logger.error(f"Label printers schema migration error: {e}")

    # Run schema migrations for document_types table (Form Recognizer training columns)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        existing_dt_columns = [col['name'] for col in inspector.get_columns('document_types')]

        dt_migrations = [
            ("training_enabled", "BIT NOT NULL DEFAULT 1"),
            ("use_form_recognizer", "BIT NOT NULL DEFAULT 0"),
            ("form_recognizer_model_id", "NVARCHAR(200) NULL"),
            ("fr_confidence_threshold", "FLOAT NOT NULL DEFAULT 0.90"),
            ("fr_extraction_count", "INT NOT NULL DEFAULT 0"),
            ("openai_extraction_count", "INT NOT NULL DEFAULT 0"),
            ("openai_fallback_count", "INT NOT NULL DEFAULT 0"),
        ]

        with engine.connect() as conn:
            for col_name, col_def in dt_migrations:
                if col_name not in existing_dt_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE document_types ADD {col_name} {col_def}"))
                        conn.commit()
                        logger.info(f"Added column '{col_name}' to document_types table")
                    except Exception as col_err:
                        if "already exists" not in str(col_err).lower():
                            logger.warning(f"Could not add column '{col_name}': {col_err}")
        logger.info("Document types schema migrations completed")
    except Exception as e:
        logger.error(f"Document types schema migration error: {e}")

    # Run schema migrations for documents table (extraction_method column)
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(engine)
        existing_doc_cols = [col['name'] for col in inspector.get_columns('documents')]

        if 'extraction_method' not in existing_doc_cols:
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE documents ADD extraction_method NVARCHAR(50) NULL"))
                    conn.commit()
                    logger.info("Added column 'extraction_method' to documents table")
                except Exception as col_err:
                    if "already exists" not in str(col_err).lower():
                        logger.warning(f"Could not add column 'extraction_method': {col_err}")
        logger.info("Documents extraction_method migration completed")
    except Exception as e:
        logger.error(f"Documents extraction_method migration error: {e}")

    # Initialize default configuration values and read startup config
    blob_watch_enabled = True  # Default if config service fails
    from app.database import SessionLocal
    from app.services.config_service import ConfigService
    db = SessionLocal()
    try:
        config_service = ConfigService(db)
        config_service.initialize_defaults()
        # Read config values while db session is open
        blob_watch_enabled = config_service.get_bool("BLOB_WATCH_ENABLED", True)
        logger.info("Configuration initialized")
    except Exception as e:
        logger.error(f"Failed to initialize configuration: {e}")
    finally:
        db.close()

    # Start background extraction worker
    try:
        from app.services.extraction_worker import start_extraction_worker
        await start_extraction_worker()
        logger.info("Extraction worker started")
    except Exception as e:
        logger.error(f"Failed to start extraction worker: {e}")

    # Start blob watcher (monitors container for new files)
    try:
        from app.services.blob_watcher import start_blob_watcher
        if blob_watch_enabled:
            await start_blob_watcher()
            logger.info("Blob watcher started")
        else:
            logger.info("Blob watcher disabled by configuration")
    except Exception as e:
        logger.error(f"Failed to start blob watcher: {e}")

    yield

    # Stop services on shutdown
    from app.services.extraction_worker import stop_extraction_worker
    from app.services.blob_watcher import stop_blob_watcher
    stop_extraction_worker()
    stop_blob_watcher()
    logger.info("Shutting down Lab Document Intelligence System")


app = FastAPI(
    title="Lab Document Intelligence System",
    description="HIPAA-Compliant AI-Powered Lab Requisition Processing",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
)

# Static files - use absolute path and create directory if it doesn't exist
STATIC_DIR = BASE_DIR / "static"
if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created static directory at {STATIC_DIR}")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory="app/templates")


# Global exception handler to catch and log all unhandled exceptions
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return proper JSON response with logging."""
    # Log the full stack trace
    error_trace = traceback.format_exc()
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    logger.error(f"Stack trace:\n{error_trace}")

    # Don't catch HTTPException, let FastAPI handle those
    if isinstance(exc, HTTPException):
        raise exc

    # For database errors, include more details to help debug
    error_message = "An unexpected error occurred"
    if settings.DEBUG:
        error_message = str(exc)
    elif "ProgrammingError" in type(exc).__name__ or "sqlalchemy" in str(type(exc).__module__).lower():
        # Include SQL error details for database issues (helpful for debugging schema issues)
        error_message = str(exc)[:500]  # Truncate to avoid leaking too much info

    # Return a proper JSON error response
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error_type": type(exc).__name__,
            "message": error_message,
            "path": str(request.url.path),
        }
    )


# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Security Middleware Stack (Order matters!)
# 1. Security Headers (OWASP, ISO27001, HIPAA, HiTRUST)
app.add_middleware(SecurityHeadersMiddleware)

# 2. Rate Limiting (DoS protection)
app.add_middleware(RateLimitMiddleware, max_requests=100, window_seconds=60)

# 3. Input Sanitization (Injection prevention)
app.add_middleware(InputSanitizationMiddleware)

# 4. Audit Logging (Compliance)
app.add_middleware(AuditLoggingMiddleware)

# 5. Session Security (Authentication controls)
app.add_middleware(SessionSecurityMiddleware)

# 6. Existing Audit and Auth Middleware
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthMiddleware)

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(compliance.router, prefix="/api/compliance", tags=["Compliance"])
app.include_router(stats.router, prefix="/api", tags=["Statistics"])
app.include_router(tests.router, prefix="/api/tests", tags=["Tests"])
app.include_router(facilities.router, prefix="/api/facilities", tags=["Facilities"])
app.include_router(config.router, prefix="/api/config", tags=["Configuration"])
app.include_router(scim.router, prefix="/scim/v2", tags=["SCIM Provisioning"])
# Azure AD SCIM provisioning adds "/scim" prefix to paths, so also mount at /scim
app.include_router(scim.router, prefix="/scim/v2/scim", tags=["SCIM Provisioning (Azure AD compat)"])
app.include_router(queue.router, tags=["Queue Management"])
app.include_router(integrations.router, tags=["Integrations"])
app.include_router(patients.router, prefix="/api/patients", tags=["Patients"])
app.include_router(workstation.router, prefix="/api/workstation", tags=["Workstation Equipment"])
app.include_router(scan.router, prefix="/api/scan", tags=["Scanner"])
app.include_router(print_router.router, prefix="/api/print", tags=["Printing"])
app.include_router(code_audit.router, prefix="/api/audit", tags=["Code Audit"])


@app.get("/")
async def root(request: Request):
    # In development mode, skip login and go straight to dashboard
    if settings.ENVIRONMENT == "development":
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/login")
async def login_page(request: Request):
    """Login page - separate route for redirects from protected pages."""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/emergency-access")
async def emergency_access_page(request: Request):
    """Emergency access page for break glass accounts."""
    return templates.TemplateResponse("emergency_access.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "google_places_api_key": settings.GOOGLE_PLACES_API_KEY,
        "environment": settings.ENVIRONMENT
    })


@app.get("/review/{document_id}")
async def review_document(request: Request, document_id: int):
    return templates.TemplateResponse("review.html", {
        "request": request,
        "document_id": document_id,
        "environment": settings.ENVIRONMENT
    })


@app.get("/history")
async def history(request: Request):
    return templates.TemplateResponse("history.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/admin")
async def admin_panel(request: Request):
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/compliance")
async def compliance_reports(request: Request):
    return templates.TemplateResponse("compliance.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/documents")
async def documents_page(request: Request):
    """Documents listing page."""
    return templates.TemplateResponse("documents.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/queue")
async def queue_management_page(request: Request):
    """Queue management page for power users."""
    return templates.TemplateResponse("queue.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/scan")
async def scan_page(request: Request):
    """Document scanning page for power users."""
    return templates.TemplateResponse("scan.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.get("/health")
async def health_check():
    """Simple health check for load balancers."""
    return {"status": "healthy", "version": "1.0.0", "environment": settings.ENVIRONMENT}


@app.get("/health/detailed")
async def health_check_detailed():
    """
    Comprehensive health check of all system components.

    Returns status of:
    - Database (Azure SQL)
    - Azure OpenAI (GPT-4 Vision)
    - Blob Storage
    - Key Vault
    - Extraction Worker
    - Blob Watcher
    """
    from app.database import SessionLocal
    from app.services.health_service import HealthService

    db = SessionLocal()
    try:
        health_service = HealthService(db)
        return await health_service.check_all()
    finally:
        db.close()


@app.get("/system-health")
async def system_health_page(request: Request):
    """System health dashboard page."""
    return templates.TemplateResponse("health.html", {
        "request": request,
        "environment": settings.ENVIRONMENT
    })


@app.post("/api/validate-address")
async def validate_address(address_data: dict):
    """
    Validate address using FedEx Address Validation API.

    Expected input:
    {
        "address": "123 Main St",
        "city": "Indianapolis",
        "state": "IN",
        "zipcode": "46204"
    }
    """
    import httpx
    import json
    from app.database import SessionLocal
    from app.services.config_service import ConfigService

    # Check if FedEx credentials are configured
    if not settings.FEDEX_API_KEY or not settings.FEDEX_API_SECRET:
        return {
            "valid": True,
            "message": "FedEx validation not configured. Address accepted as-is.",
            "original_address": address_data
        }

    # Get FedEx base URL from config
    db = SessionLocal()
    try:
        config_service = ConfigService(db)
        fedex_base_url = config_service.get("FEDEX_API_BASE_URL", "https://apis.fedex.com")
    finally:
        db.close()

    # FedEx API endpoints
    fedex_url = f"{fedex_base_url}/address/v1/addresses/resolve"
    token_url = f"{fedex_base_url}/oauth/token"

    try:
        token_data = {
            "grant_type": "client_credentials",
            "client_id": settings.FEDEX_API_KEY,
            "client_secret": settings.FEDEX_API_SECRET
        }

        async with httpx.AsyncClient() as client:
            # Get OAuth token
            token_response = await client.post(
                token_url,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if token_response.status_code != 200:
                logger.error(f"FedEx OAuth failed: {token_response.text}")
                return {
                    "valid": True,
                    "message": "Address validation service unavailable. Address accepted.",
                    "original_address": address_data
                }

            access_token = token_response.json().get("access_token")

            # Validate address
            validation_payload = {
                "addressesToValidate": [{
                    "address": {
                        "streetLines": [address_data.get("address", "")],
                        "city": address_data.get("city", ""),
                        "stateOrProvinceCode": address_data.get("state", ""),
                        "postalCode": address_data.get("zipcode", ""),
                        "countryCode": "US"
                    }
                }]
            }

            validation_response = await client.post(
                fedex_url,
                json=validation_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )

            if validation_response.status_code == 200:
                result = validation_response.json()

                # Parse FedEx response
                if "output" in result and "resolvedAddresses" in result["output"]:
                    resolved = result["output"]["resolvedAddresses"][0]

                    return {
                        "valid": True,
                        "message": "Address validated successfully",
                        "original_address": address_data,
                        "validated_address": {
                            "address": " ".join(resolved["address"].get("streetLines", [])),
                            "city": resolved["address"].get("city", ""),
                            "state": resolved["address"].get("stateOrProvinceCode", ""),
                            "zipcode": resolved["address"].get("postalCode", "")
                        },
                        "classification": resolved.get("classification", "Unknown")
                    }
                else:
                    return {
                        "valid": False,
                        "message": "Address could not be validated. Please verify the address.",
                        "original_address": address_data
                    }
            else:
                logger.error(f"FedEx validation failed: {validation_response.text}")
                return {
                    "valid": True,
                    "message": "Address validation service error. Address accepted.",
                    "original_address": address_data
                }

    except Exception as e:
        logger.error(f"Address validation error: {str(e)}")
        return {
            "valid": True,
            "message": "Address validation error. Address accepted.",
            "original_address": address_data,
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
