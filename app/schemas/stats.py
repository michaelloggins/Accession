"""Statistics schemas."""

from pydantic import BaseModel


class TodayStats(BaseModel):
    """Today's processing statistics."""
    processed: int
    auto_approved: int
    manual_review: int


class StatsResponse(BaseModel):
    """System statistics response."""
    total_documents: int
    pending_review: int
    approved: int
    rejected: int
    submitted_to_lab: int
    average_confidence: float
    average_processing_time_seconds: float
    automation_rate: float
    today: TodayStats
