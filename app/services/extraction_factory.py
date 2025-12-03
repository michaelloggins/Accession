"""Factory for selecting AI extraction service provider."""

from app.config import settings
import logging

logger = logging.getLogger(__name__)


def get_extraction_service():
    """Get the configured AI extraction service."""
    if settings.AZURE_OPENAI_ENDPOINT and settings.AZURE_OPENAI_API_KEY:
        logger.info("Loading Azure OpenAI extraction service")
        from app.services.azure_openai_service import AzureOpenAIExtractionService
        return AzureOpenAIExtractionService()
    else:
        logger.info("Loading Mock extraction service (Azure OpenAI not configured)")
        from app.services.mock_extraction_service import MockExtractionService
        return MockExtractionService()
