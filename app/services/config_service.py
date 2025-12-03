"""Configuration service for dynamic settings management."""

import json
import logging
from typing import Any, Optional, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from app.models.system_config import SystemConfig
from app.config import settings as env_settings

logger = logging.getLogger(__name__)


class ConfigService:
    """Service for managing dynamic configuration settings."""

    _cache: Dict[str, Any] = {}
    _cache_timestamp: Optional[datetime] = None
    _cache_ttl_seconds: int = 60  # Refresh cache every 60 seconds

    def __init__(self, db: Session):
        self.db = db

    def _should_refresh_cache(self) -> bool:
        """Check if cache should be refreshed."""
        if not ConfigService._cache_timestamp:
            return True
        elapsed = (datetime.utcnow() - ConfigService._cache_timestamp).total_seconds()
        return elapsed > ConfigService._cache_ttl_seconds

    def _refresh_cache(self):
        """Refresh the configuration cache from database."""
        try:
            configs = self.db.query(SystemConfig).all()
            ConfigService._cache = {c.key: c for c in configs}
            ConfigService._cache_timestamp = datetime.utcnow()
        except Exception as e:
            logger.warning(f"Failed to refresh config cache: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key.

        Priority:
        1. Database value (if exists)
        2. Default from SystemConfig.DEFAULTS
        3. Provided default parameter
        """
        # Refresh cache if needed
        if self._should_refresh_cache():
            self._refresh_cache()

        # Try to get from cache
        config = ConfigService._cache.get(key)
        if config:
            return self._convert_value(config.value, config.value_type)

        # Try to get from defaults
        if key in SystemConfig.DEFAULTS:
            default_config = SystemConfig.DEFAULTS[key]
            return self._convert_value(default_config["value"], default_config["value_type"])

        return default

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer configuration value."""
        value = self.get(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float configuration value."""
        value = self.get(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean configuration value."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def _convert_value(self, value: str, value_type: str) -> Any:
        """Convert string value to appropriate type."""
        if value is None:
            return None

        try:
            if value_type == "int":
                return int(value)
            elif value_type == "float":
                return float(value)
            elif value_type == "bool":
                return value.lower() in ("true", "1", "yes", "on")
            elif value_type == "json":
                return json.loads(value)
            else:
                return value
        except (ValueError, json.JSONDecodeError):
            return value

    def set(self, key: str, value: Any, updated_by: str = "system") -> bool:
        """Set a configuration value."""
        try:
            # Get existing or create new
            config = self.db.query(SystemConfig).filter(SystemConfig.key == key).first()

            if config:
                config.value = str(value)
                config.updated_by = updated_by
                config.updated_at = datetime.utcnow()
            else:
                # Get defaults if available
                defaults = SystemConfig.DEFAULTS.get(key, {})
                config = SystemConfig(
                    key=key,
                    value=str(value),
                    value_type=defaults.get("value_type", "string"),
                    description=defaults.get("description", ""),
                    category=defaults.get("category", "general"),
                    display_order=defaults.get("display_order", "999"),
                    updated_by=updated_by
                )
                self.db.add(config)

            self.db.commit()

            # Invalidate cache
            ConfigService._cache_timestamp = None

            return True
        except Exception as e:
            logger.error(f"Failed to set config {key}: {e}")
            self.db.rollback()
            return False

    def get_all(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all configuration settings, optionally filtered by category."""
        # Start with defaults
        all_configs = {}

        # Add defaults first
        for key, default in SystemConfig.DEFAULTS.items():
            if category and default.get("category") != category:
                continue
            all_configs[key] = {
                "key": key,
                "value": self._convert_value(default["value"], default["value_type"]),
                "value_type": default["value_type"],
                "description": default["description"],
                "category": default["category"],
                "display_order": default["display_order"],
                "source": "default",
                "updated_at": None,
                "updated_by": None
            }

        # Override with database values
        query = self.db.query(SystemConfig)
        if category:
            query = query.filter(SystemConfig.category == category)

        for config in query.all():
            if config.key in all_configs or not category:
                all_configs[config.key] = {
                    "key": config.key,
                    "value": self._convert_value(config.value, config.value_type or "string"),
                    "value_type": config.value_type or "string",
                    "description": config.description,
                    "category": config.category,
                    "display_order": config.display_order or "999",
                    "source": "database",
                    "updated_at": config.updated_at.isoformat() if config.updated_at else None,
                    "updated_by": config.updated_by
                }

        # Sort by category and display_order
        result = sorted(
            all_configs.values(),
            key=lambda x: (x["category"] or "zzz", x["display_order"] or "999")
        )

        return result

    def get_categories(self) -> List[str]:
        """Get list of all configuration categories."""
        categories = set()
        for default in SystemConfig.DEFAULTS.values():
            if default.get("category"):
                categories.add(default["category"])
        return sorted(list(categories))

    def initialize_defaults(self):
        """Initialize database with default values if not present."""
        for key, default in SystemConfig.DEFAULTS.items():
            existing = self.db.query(SystemConfig).filter(SystemConfig.key == key).first()
            if not existing:
                config = SystemConfig(
                    key=key,
                    value=default["value"],
                    value_type=default["value_type"],
                    description=default["description"],
                    category=default["category"],
                    display_order=default["display_order"],
                    updated_by="system"
                )
                self.db.add(config)
        self.db.commit()
        logger.info("Configuration defaults initialized")


def get_config_value(db: Session, key: str, default: Any = None) -> Any:
    """Convenience function to get a config value."""
    service = ConfigService(db)
    return service.get(key, default)


def get_config_int(db: Session, key: str, default: int = 0) -> int:
    """Convenience function to get an integer config value."""
    service = ConfigService(db)
    return service.get_int(key, default)


def get_config_float(db: Session, key: str, default: float = 0.0) -> float:
    """Convenience function to get a float config value."""
    service = ConfigService(db)
    return service.get_float(key, default)


def get_config_bool(db: Session, key: str, default: bool = False) -> bool:
    """Convenience function to get a boolean config value."""
    service = ConfigService(db)
    return service.get_bool(key, default)
