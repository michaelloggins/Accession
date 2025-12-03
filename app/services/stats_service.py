"""Statistics service for system metrics."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging

from app.models.document import Document

logger = logging.getLogger(__name__)


class StatsService:
    """Service for calculating system statistics."""

    def __init__(self, db: Session):
        self.db = db

    def get_all_stats(self) -> dict:
        """Get all system statistics."""
        total_documents = self.db.query(Document).count()

        pending_review = self.db.query(Document).filter(
            Document.status == "pending"
        ).count()

        approved = self.db.query(Document).filter(
            Document.status.in_(["approved", "auto_approved"])
        ).count()

        rejected = self.db.query(Document).filter(
            Document.status == "rejected"
        ).count()

        submitted_to_lab = self.db.query(Document).filter(
            Document.submitted_to_lab == True
        ).count()

        # Calculate average confidence
        avg_confidence = self.db.query(
            func.avg(Document.confidence_score)
        ).scalar() or 0.0

        # Calculate average processing time (placeholder)
        avg_processing_time = 23.4  # In production, calculate from actual times

        # Calculate automation rate
        auto_approved = self.db.query(Document).filter(
            Document.status == "auto_approved"
        ).count()

        automation_rate = 0.0
        if total_documents > 0:
            automation_rate = auto_approved / total_documents

        # Today's stats
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        today_processed = self.db.query(Document).filter(
            Document.upload_date >= today_start
        ).count()

        today_auto_approved = self.db.query(Document).filter(
            Document.upload_date >= today_start,
            Document.status == "auto_approved"
        ).count()

        today_manual_review = today_processed - today_auto_approved

        return {
            "total_documents": total_documents,
            "pending_review": pending_review,
            "approved": approved,
            "rejected": rejected,
            "submitted_to_lab": submitted_to_lab,
            "average_confidence": float(avg_confidence),
            "average_processing_time_seconds": avg_processing_time,
            "automation_rate": float(automation_rate),
            "today": {
                "processed": today_processed,
                "auto_approved": today_auto_approved,
                "manual_review": today_manual_review
            }
        }

    def get_processing_trends(self, days: int = 30) -> list:
        """Get document processing trends over time."""
        trends = []
        start_date = datetime.utcnow() - timedelta(days=days)

        for i in range(days):
            day_start = start_date + timedelta(days=i)
            day_end = day_start + timedelta(days=1)

            count = self.db.query(Document).filter(
                Document.upload_date >= day_start,
                Document.upload_date < day_end
            ).count()

            trends.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "count": count
            })

        return trends

    def get_confidence_distribution(self) -> dict:
        """Get distribution of confidence scores."""
        # Group by confidence ranges
        low = self.db.query(Document).filter(
            Document.confidence_score < 0.70
        ).count()

        medium = self.db.query(Document).filter(
            Document.confidence_score >= 0.70,
            Document.confidence_score < 0.90
        ).count()

        high = self.db.query(Document).filter(
            Document.confidence_score >= 0.90
        ).count()

        return {
            "low_confidence": low,
            "medium_confidence": medium,
            "high_confidence": high
        }

    def get_reviewer_stats(self) -> list:
        """Get statistics by reviewer."""
        reviewers = (
            self.db.query(
                Document.reviewed_by,
                func.count(Document.id).label("count")
            )
            .filter(Document.reviewed_by.isnot(None))
            .group_by(Document.reviewed_by)
            .all()
        )

        return [
            {"reviewer": r[0], "documents_reviewed": r[1]}
            for r in reviewers
        ]
