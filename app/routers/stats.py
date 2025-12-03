"""Statistics API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.schemas.stats import StatsResponse, TodayStats
from app.services.stats_service import StatsService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stats", response_model=StatsResponse)
async def get_system_stats(db: Session = Depends(get_db)):
    """Get system statistics."""
    stats_service = StatsService(db)

    stats = stats_service.get_all_stats()

    return StatsResponse(
        total_documents=stats["total_documents"],
        pending_review=stats["pending_review"],
        approved=stats["approved"],
        rejected=stats["rejected"],
        submitted_to_lab=stats["submitted_to_lab"],
        average_confidence=stats["average_confidence"],
        average_processing_time_seconds=stats["average_processing_time_seconds"],
        automation_rate=stats["automation_rate"],
        today=TodayStats(
            processed=stats["today"]["processed"],
            auto_approved=stats["today"]["auto_approved"],
            manual_review=stats["today"]["manual_review"]
        )
    )
