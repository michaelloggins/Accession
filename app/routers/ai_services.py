"""AI Services configuration API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json
import logging

from app.database import get_db
from app.services.config_service import ConfigService

router = APIRouter()
logger = logging.getLogger(__name__)


class AiServiceConfigResponse(BaseModel):
    """Response for AI service config."""
    learning_mode: bool


class AiServiceConfigUpdate(BaseModel):
    """Request to update AI service config."""
    learning_mode: bool


@router.get("/config", response_model=AiServiceConfigResponse)
async def get_ai_services_config(db: Session = Depends(get_db)):
    """Get AI services configuration (learning mode status)."""
    config_service = ConfigService(db)
    config_str = config_service.get("AI_SERVICE_CONFIG", "{}")

    try:
        ai_config = json.loads(config_str) if isinstance(config_str, str) else config_str
    except (json.JSONDecodeError, TypeError):
        ai_config = {}

    return AiServiceConfigResponse(
        learning_mode=ai_config.get("learning_mode", False)
    )


@router.put("/config", response_model=AiServiceConfigResponse)
async def update_ai_services_config(
    update: AiServiceConfigUpdate,
    db: Session = Depends(get_db)
):
    """Update AI services configuration (learning mode)."""
    config_service = ConfigService(db)
    config_str = config_service.get("AI_SERVICE_CONFIG", "{}")

    try:
        ai_config = json.loads(config_str) if isinstance(config_str, str) else config_str
    except (json.JSONDecodeError, TypeError):
        ai_config = {}

    # Update learning mode
    ai_config["learning_mode"] = update.learning_mode

    # Save back to config
    config_service.set("AI_SERVICE_CONFIG", json.dumps(ai_config))
    db.commit()

    logger.info(f"AI services config updated: learning_mode={update.learning_mode}")

    return AiServiceConfigResponse(
        learning_mode=ai_config.get("learning_mode", False)
    )
