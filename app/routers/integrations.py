"""Integration management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from app.database import get_db
from app.models.integration import Integration, ApiKey
from app.services.integration_service import IntegrationService, ApiKeyService

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# ============================================
# Pydantic Models
# ============================================

class IntegrationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    integration_type: str
    config: Optional[dict] = None


class IntegrationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict] = None
    field_mapping: Optional[dict] = None
    mcp_enabled: Optional[bool] = None


class IntegrationStatusUpdate(BaseModel):
    status: str


class FieldMappingUpdate(BaseModel):
    field_mapping: dict


class SampleTestRequest(BaseModel):
    sample_data: str


class ApiKeyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    integration_id: Optional[int] = None
    scopes: Optional[List[str]] = None
    expires_at: Optional[datetime] = None
    rate_limit_per_minute: Optional[int] = 60
    rate_limit_per_day: Optional[int] = 10000


# ============================================
# Integration Types
# ============================================

@router.get("/types")
async def get_integration_types(db: Session = Depends(get_db)):
    """Get all available integration types and their configurations."""
    service = IntegrationService(db)
    return {"types": service.get_integration_types()}


# ============================================
# MCP Management
# ============================================

@router.get("/mcps")
async def get_mcps(db: Session = Depends(get_db)):
    """Get all available MCP servers and their status."""
    service = IntegrationService(db)
    return {
        "available": service.get_available_mcps(),
        "status": service.get_mcp_status()
    }


@router.get("/mcps/status")
async def get_mcp_status(db: Session = Depends(get_db)):
    """Get the current status of all MCP servers."""
    service = IntegrationService(db)
    return {"mcps": service.get_mcp_status()}


@router.post("/mcps/{server_name}/install")
async def install_mcp(server_name: str, db: Session = Depends(get_db)):
    """Install an MCP server."""
    import subprocess

    service = IntegrationService(db)
    available_mcps = {mcp["server_name"]: mcp for mcp in service.get_available_mcps()}

    if server_name not in available_mcps:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{server_name}' not found"
        )

    mcp_config = available_mcps[server_name]

    try:
        # Install MCP using claude mcp add
        result = subprocess.run(
            ["claude", "mcp", "add", server_name, "--"] + mcp_config["command"].split()[1:],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Installation failed"
            }

        return {
            "success": True,
            "message": f"MCP server '{server_name}' installed successfully",
            "server_name": server_name
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Installation timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.delete("/mcps/{server_name}")
async def remove_mcp(server_name: str, db: Session = Depends(get_db)):
    """Remove an MCP server."""
    import subprocess

    try:
        result = subprocess.run(
            ["claude", "mcp", "remove", server_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Removal failed"
            }

        return {
            "success": True,
            "message": f"MCP server '{server_name}' removed successfully"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# Integration CRUD
# ============================================

@router.get("/")
async def list_integrations(db: Session = Depends(get_db)):
    """Get all integrations."""
    service = IntegrationService(db)
    integrations = service.get_all_integrations()
    return {
        "integrations": [i.to_dict() for i in integrations],
        "count": len(integrations)
    }


@router.get("/{integration_id}")
async def get_integration(
    integration_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific integration."""
    service = IntegrationService(db)
    integration = service.get_integration(integration_id)

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    # Get associated API keys
    key_service = ApiKeyService(db)
    api_keys = key_service.get_api_keys_for_integration(integration_id)

    result = integration.to_dict()
    result["api_keys"] = [k.to_dict() for k in api_keys]

    return result


@router.post("/")
async def create_integration(
    data: IntegrationCreate,
    db: Session = Depends(get_db)
):
    """Create a new integration."""
    service = IntegrationService(db)

    try:
        integration = service.create_integration(
            name=data.name,
            description=data.description,
            integration_type=data.integration_type,
            config=data.config,
            created_by="admin"  # TODO: Get from auth
        )
        return integration.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put("/{integration_id}")
async def update_integration(
    integration_id: int,
    data: IntegrationUpdate,
    db: Session = Depends(get_db)
):
    """Update an integration."""
    service = IntegrationService(db)

    updates = data.dict(exclude_unset=True)
    integration = service.update_integration(
        integration_id=integration_id,
        updates=updates,
        updated_by="admin"  # TODO: Get from auth
    )

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    return integration.to_dict()


@router.put("/{integration_id}/status")
async def update_integration_status(
    integration_id: int,
    data: IntegrationStatusUpdate,
    db: Session = Depends(get_db)
):
    """Update integration status (pending/active/inactive/error)."""
    service = IntegrationService(db)

    try:
        integration = service.update_integration_status(
            integration_id=integration_id,
            status=data.status,
            updated_by="admin"  # TODO: Get from auth
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Integration not found"
            )

        return {
            "message": f"Status updated to {data.status}",
            "integration": integration.to_dict()
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: int,
    db: Session = Depends(get_db)
):
    """Delete an integration."""
    service = IntegrationService(db)

    if not service.delete_integration(integration_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    return {"message": "Integration deleted"}


# ============================================
# Field Mapping
# ============================================

@router.put("/{integration_id}/field-mapping")
async def update_field_mapping(
    integration_id: int,
    data: FieldMappingUpdate,
    db: Session = Depends(get_db)
):
    """Update field mapping for an integration."""
    service = IntegrationService(db)

    integration = service.update_field_mapping(
        integration_id=integration_id,
        field_mapping=data.field_mapping,
        updated_by="admin"
    )

    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    return {
        "message": "Field mapping updated",
        "field_mapping": integration.field_mapping
    }


# ============================================
# Sample Testing
# ============================================

@router.post("/{integration_id}/test-sample")
async def test_sample(
    integration_id: int,
    data: SampleTestRequest,
    db: Session = Depends(get_db)
):
    """
    Test an integration with sample data.

    Upload sample data (CSV, JSON, etc.) and see how it would be parsed
    and mapped to document fields. Data is NOT processed into the system.
    """
    service = IntegrationService(db)

    result = service.test_integration_sample(
        integration_id=integration_id,
        sample_data=data.sample_data
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Sample test failed")
        )

    return result


@router.post("/{integration_id}/upload-sample")
async def upload_sample_file(
    integration_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload a sample file for testing an integration."""
    service = IntegrationService(db)

    integration = service.get_integration(integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    # Read file content
    try:
        content = await file.read()
        sample_data = content.decode("utf-8")
    except UnicodeDecodeError:
        # Try latin-1 for non-UTF8 files
        try:
            sample_data = content.decode("latin-1")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not decode file: {str(e)}"
            )

    # Test the sample
    result = service.test_integration_sample(
        integration_id=integration_id,
        sample_data=sample_data
    )

    result["filename"] = file.filename
    return result


# ============================================
# Integration Logs
# ============================================

@router.get("/{integration_id}/logs")
async def get_integration_logs(
    integration_id: int,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get recent logs for an integration."""
    service = IntegrationService(db)

    integration = service.get_integration(integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    logs = service.get_integration_logs(integration_id, limit)

    return {
        "logs": [
            {
                "id": log.id,
                "event_type": log.event_type,
                "success": log.success,
                "error_message": log.error_message,
                "document_id": log.document_id,
                "processing_time_ms": log.processing_time_ms,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ],
        "count": len(logs)
    }


# ============================================
# API Keys
# ============================================

@router.get("/api-keys/all")
async def list_all_api_keys(db: Session = Depends(get_db)):
    """Get all API keys."""
    service = ApiKeyService(db)
    keys = service.get_all_api_keys()
    return {
        "api_keys": [k.to_dict() for k in keys],
        "count": len(keys)
    }


@router.get("/{integration_id}/api-keys")
async def list_integration_api_keys(
    integration_id: int,
    db: Session = Depends(get_db)
):
    """Get API keys for a specific integration."""
    service = ApiKeyService(db)
    keys = service.get_api_keys_for_integration(integration_id)
    return {
        "api_keys": [k.to_dict() for k in keys],
        "count": len(keys)
    }


@router.post("/api-keys")
async def create_api_key(
    data: ApiKeyCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new API key.

    Returns the full key which should be copied immediately.
    The key will not be shown again.
    """
    service = ApiKeyService(db)

    api_key, full_key = service.create_api_key(
        name=data.name,
        description=data.description,
        integration_id=data.integration_id,
        scopes=data.scopes,
        expires_at=data.expires_at,
        rate_limit_per_minute=data.rate_limit_per_minute,
        rate_limit_per_day=data.rate_limit_per_day,
        created_by="admin"  # TODO: Get from auth
    )

    # Include the full key in response (shown once)
    return api_key.to_dict(include_key=True, full_key=full_key)


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db)
):
    """Revoke an API key."""
    service = ApiKeyService(db)

    if not service.revoke_api_key(key_id, revoked_by="admin"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    return {"message": "API key revoked"}


# ============================================
# Webhook Receiver Endpoint
# ============================================

@router.post("/webhook/{integration_id}")
async def receive_webhook(
    integration_id: int,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Receive webhook data from an external system.

    Data will only be processed if the integration is in 'active' status.
    In 'pending' status, data is logged but not processed.
    """
    service = IntegrationService(db)

    integration = service.get_integration(integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )

    # Log the received data
    import json
    request_summary = json.dumps(payload)[:500]  # Truncate for logging

    # Check if data flow is allowed
    if not integration.is_data_flow_allowed():
        # Log but don't process
        service.log_integration_event(
            integration_id=integration_id,
            event_type="received",
            success=True,
            request_summary=request_summary,
            response_summary="Data received but not processed (integration pending)"
        )

        return {
            "status": "received",
            "processed": False,
            "message": "Integration is in pending mode. Data logged but not processed."
        }

    # TODO: Process the data into the document stream
    # For now, just log it
    service.log_integration_event(
        integration_id=integration_id,
        event_type="received",
        success=True,
        request_summary=request_summary,
        response_summary="Data received and queued for processing"
    )

    return {
        "status": "received",
        "processed": True,
        "message": "Data received and queued for processing"
    }
