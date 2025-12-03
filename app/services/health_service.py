"""
Health Check Service - Comprehensive system health monitoring.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional
from enum import Enum

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.utils.timezone import now_eastern, format_eastern_iso, get_timezone_info

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status indicators."""
    HEALTHY = "healthy"      # Green check - fully operational
    DEGRADED = "degraded"    # Yellow warning - operational with issues
    UNHEALTHY = "unhealthy"  # Red X - not operational


class HealthService:
    """Service for checking health of all system components."""

    def __init__(self, db: Session):
        self.db = db

    async def check_all(self) -> dict:
        """Run all health checks and return comprehensive status."""
        start_time = now_eastern()

        # Run all checks concurrently
        checks = await asyncio.gather(
            self._check_database(),
            self._check_azure_openai(),
            self._check_blob_storage(),
            self._check_key_vault(),
            self._check_extraction_worker(),
            self._check_blob_watcher(),
            self._check_sso_authentication(),
            self._check_scim_provisioning(),
            self._check_app_instances(),
            return_exceptions=True
        )

        # Map results
        results = {
            "database": checks[0] if not isinstance(checks[0], Exception) else self._error_result("database", checks[0]),
            "azure_openai": checks[1] if not isinstance(checks[1], Exception) else self._error_result("azure_openai", checks[1]),
            "blob_storage": checks[2] if not isinstance(checks[2], Exception) else self._error_result("blob_storage", checks[2]),
            "key_vault": checks[3] if not isinstance(checks[3], Exception) else self._error_result("key_vault", checks[3]),
            "extraction_worker": checks[4] if not isinstance(checks[4], Exception) else self._error_result("extraction_worker", checks[4]),
            "blob_watcher": checks[5] if not isinstance(checks[5], Exception) else self._error_result("blob_watcher", checks[5]),
            "sso_authentication": checks[6] if not isinstance(checks[6], Exception) else self._error_result("sso_authentication", checks[6]),
            "scim_provisioning": checks[7] if not isinstance(checks[7], Exception) else self._error_result("scim_provisioning", checks[7]),
            "app_instances": checks[8] if not isinstance(checks[8], Exception) else self._error_result("app_instances", checks[8]),
        }

        # Calculate overall status
        statuses = [r["status"] for r in results.values()]
        if all(s == HealthStatus.HEALTHY for s in statuses):
            overall_status = HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            overall_status = HealthStatus.UNHEALTHY
        else:
            overall_status = HealthStatus.DEGRADED

        elapsed_ms = (now_eastern() - start_time).total_seconds() * 1000

        # Get timezone info for the response
        tz_info = get_timezone_info()

        return {
            "status": overall_status,
            "version": "1.0.0",
            "environment": settings.ENVIRONMENT,
            "timestamp": format_eastern_iso(now_eastern()),
            "timezone": tz_info["abbreviation"],  # EST or EDT
            "response_time_ms": round(elapsed_ms, 2),
            "services": results
        }

    def _error_result(self, service: str, error: Exception) -> dict:
        """Create an error result for a failed check."""
        return {
            "name": service,
            "status": HealthStatus.UNHEALTHY,
            "message": f"Check failed: {str(error)}",
            "response_time_ms": None
        }

    async def _check_database(self) -> dict:
        """Check database connectivity and health."""
        start = datetime.utcnow()
        try:
            # Simple connectivity test
            result = self.db.execute(text("SELECT 1"))
            result.fetchone()

            # Check table counts for additional validation
            doc_count = self.db.execute(text("SELECT COUNT(*) FROM documents")).scalar()
            user_count = self.db.execute(text("SELECT COUNT(*) FROM users")).scalar()

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            return {
                "name": "Azure SQL Database",
                "status": HealthStatus.HEALTHY,
                "message": f"Connected. {doc_count} documents, {user_count} users.",
                "response_time_ms": round(elapsed, 2),
                "details": {
                    "documents": doc_count,
                    "users": user_count
                }
            }
        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"Database health check failed: {e}")
            return {
                "name": "Azure SQL Database",
                "status": HealthStatus.UNHEALTHY,
                "message": f"Connection failed: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_azure_openai(self) -> dict:
        """Check Azure OpenAI service availability."""
        start = datetime.utcnow()
        try:
            if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_API_KEY:
                return {
                    "name": "Azure OpenAI (GPT-4 Vision)",
                    "status": HealthStatus.DEGRADED,
                    "message": "Not configured - credentials missing",
                    "response_time_ms": 0
                }

            # Quick validation call - try a minimal chat completion
            import httpx
            deployment_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME

            # Use the chat completions endpoint with a minimal request
            test_url = f"{settings.AZURE_OPENAI_ENDPOINT}/openai/deployments/{deployment_name}/chat/completions?api-version={settings.AZURE_OPENAI_API_VERSION}"

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    test_url,
                    headers={
                        "api-key": settings.AZURE_OPENAI_API_KEY,
                        "Content-Type": "application/json"
                    },
                    json={
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 1
                    }
                )

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            if response.status_code == 200:
                return {
                    "name": "Azure OpenAI (GPT-4 Vision)",
                    "status": HealthStatus.HEALTHY,
                    "message": "Service available and responding",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "endpoint": settings.AZURE_OPENAI_ENDPOINT[:50] + "..." if len(settings.AZURE_OPENAI_ENDPOINT) > 50 else settings.AZURE_OPENAI_ENDPOINT,
                        "deployment": deployment_name
                    }
                }
            elif response.status_code == 401:
                return {
                    "name": "Azure OpenAI (GPT-4 Vision)",
                    "status": HealthStatus.UNHEALTHY,
                    "message": "Authentication failed - invalid API key",
                    "response_time_ms": round(elapsed, 2)
                }
            elif response.status_code == 404:
                return {
                    "name": "Azure OpenAI (GPT-4 Vision)",
                    "status": HealthStatus.UNHEALTHY,
                    "message": f"Deployment '{deployment_name}' not found",
                    "response_time_ms": round(elapsed, 2)
                }
            elif response.status_code == 429:
                # Rate limited but service is working
                return {
                    "name": "Azure OpenAI (GPT-4 Vision)",
                    "status": HealthStatus.HEALTHY,
                    "message": "Service available (rate limited)",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "endpoint": settings.AZURE_OPENAI_ENDPOINT[:50] + "..." if len(settings.AZURE_OPENAI_ENDPOINT) > 50 else settings.AZURE_OPENAI_ENDPOINT,
                        "deployment": deployment_name
                    }
                }
            else:
                return {
                    "name": "Azure OpenAI (GPT-4 Vision)",
                    "status": HealthStatus.DEGRADED,
                    "message": f"Service returned status {response.status_code}",
                    "response_time_ms": round(elapsed, 2)
                }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"Azure OpenAI health check failed: {e}")
            return {
                "name": "Azure OpenAI (GPT-4 Vision)",
                "status": HealthStatus.UNHEALTHY,
                "message": f"Check failed: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_blob_storage(self) -> dict:
        """Check Azure Blob Storage connectivity."""
        start = datetime.utcnow()
        try:
            if not settings.AZURE_STORAGE_CONNECTION_STRING:
                return {
                    "name": "Azure Blob Storage",
                    "status": HealthStatus.DEGRADED,
                    "message": "Not configured - connection string missing",
                    "response_time_ms": 0
                }

            from azure.storage.blob import BlobServiceClient

            blob_service = BlobServiceClient.from_connection_string(
                settings.AZURE_STORAGE_CONNECTION_STRING
            )

            # List containers to verify connectivity (limit via iteration)
            containers = []
            for i, container in enumerate(blob_service.list_containers()):
                if i >= 5:
                    break
                containers.append(container)
            container_names = [c.name for c in containers]

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            return {
                "name": "Azure Blob Storage",
                "status": HealthStatus.HEALTHY,
                "message": f"Connected. Found {len(containers)} container(s).",
                "response_time_ms": round(elapsed, 2),
                "details": {
                    "containers": container_names[:5],
                    "document_container": settings.AZURE_STORAGE_CONTAINER
                }
            }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"Blob storage health check failed: {e}")
            return {
                "name": "Azure Blob Storage",
                "status": HealthStatus.UNHEALTHY,
                "message": f"Connection failed: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_key_vault(self) -> dict:
        """Check Azure Key Vault connectivity (if configured)."""
        start = datetime.utcnow()
        try:
            key_vault_url = getattr(settings, 'AZURE_KEY_VAULT_URL', None)

            if not key_vault_url:
                return {
                    "name": "Azure Key Vault",
                    "status": HealthStatus.DEGRADED,
                    "message": "Not configured - using environment variables",
                    "response_time_ms": 0,
                    "details": {
                        "note": "Secrets loaded from environment/app settings"
                    }
                }

            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=key_vault_url, credential=credential)

            # Try to list secrets (just metadata, not values)
            secrets = list(client.list_properties_of_secrets(max_page_size=1))

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            return {
                "name": "Azure Key Vault",
                "status": HealthStatus.HEALTHY,
                "message": "Connected and accessible",
                "response_time_ms": round(elapsed, 2),
                "details": {
                    "vault_url": key_vault_url
                }
            }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            error_msg = str(e)[:100]

            # If Key Vault isn't configured, it's just degraded not unhealthy
            if "not configured" in error_msg.lower() or "credential" in error_msg.lower():
                return {
                    "name": "Azure Key Vault",
                    "status": HealthStatus.DEGRADED,
                    "message": "Not accessible - using environment variables",
                    "response_time_ms": round(elapsed, 2)
                }

            logger.error(f"Key Vault health check failed: {e}")
            return {
                "name": "Azure Key Vault",
                "status": HealthStatus.UNHEALTHY,
                "message": f"Connection failed: {error_msg}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_extraction_worker(self) -> dict:
        """Check extraction worker status."""
        start = datetime.utcnow()
        try:
            from app.services.extraction_worker import get_worker_status

            status = get_worker_status()
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            if status.get("running", False):
                return {
                    "name": "Extraction Worker",
                    "status": HealthStatus.HEALTHY,
                    "message": f"Running. Processed {status.get('documents_processed', 0)} documents.",
                    "response_time_ms": round(elapsed, 2),
                    "details": status
                }
            else:
                return {
                    "name": "Extraction Worker",
                    "status": HealthStatus.DEGRADED,
                    "message": "Worker not running - background extraction paused",
                    "response_time_ms": round(elapsed, 2),
                    "details": status
                }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"Extraction worker health check failed: {e}")
            return {
                "name": "Extraction Worker",
                "status": HealthStatus.DEGRADED,
                "message": f"Status unknown: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_blob_watcher(self) -> dict:
        """Check blob watcher status."""
        start = datetime.utcnow()
        try:
            from app.services.blob_watcher import get_blob_watcher_status

            status = get_blob_watcher_status()
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            if status.get("running", False):
                return {
                    "name": "Blob Watcher",
                    "status": HealthStatus.HEALTHY,
                    "message": f"Running. Watching for new documents.",
                    "response_time_ms": round(elapsed, 2),
                    "details": status
                }
            elif status.get("enabled", True) is False:
                return {
                    "name": "Blob Watcher",
                    "status": HealthStatus.DEGRADED,
                    "message": "Disabled in configuration",
                    "response_time_ms": round(elapsed, 2),
                    "details": status
                }
            else:
                return {
                    "name": "Blob Watcher",
                    "status": HealthStatus.DEGRADED,
                    "message": "Watcher not running",
                    "response_time_ms": round(elapsed, 2),
                    "details": status
                }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"Blob watcher health check failed: {e}")
            return {
                "name": "Blob Watcher",
                "status": HealthStatus.DEGRADED,
                "message": f"Status unknown: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_sso_authentication(self) -> dict:
        """Check SSO/Entra ID authentication configuration."""
        start = datetime.utcnow()
        try:
            sso_enabled = settings.SSO_ENABLED
            sso_method = settings.SSO_METHOD
            tenant_id = settings.AZURE_AD_TENANT_ID
            client_id = settings.AZURE_AD_CLIENT_ID

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            if not sso_enabled:
                return {
                    "name": "SSO Authentication",
                    "status": HealthStatus.DEGRADED,
                    "message": "SSO disabled - using local authentication only",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "sso_enabled": False,
                        "note": "Enable SSO_ENABLED to use Entra ID"
                    }
                }

            if not tenant_id or not client_id:
                return {
                    "name": "SSO Authentication",
                    "status": HealthStatus.DEGRADED,
                    "message": "SSO enabled but not configured",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "sso_enabled": True,
                        "sso_method": sso_method,
                        "tenant_configured": bool(tenant_id),
                        "client_configured": bool(client_id),
                        "note": "Configure AZURE_AD_TENANT_ID and AZURE_AD_CLIENT_ID"
                    }
                }

            # SSO is enabled and configured
            if sso_method == "saml":
                from app.services.saml_service import get_saml_service
                saml_service = get_saml_service()
                configured = saml_service.is_configured
            else:
                from app.services.entra_id_service import get_entra_id_service
                entra_service = get_entra_id_service()
                configured = entra_service.is_configured

            if configured:
                return {
                    "name": "SSO Authentication",
                    "status": HealthStatus.HEALTHY,
                    "message": f"{sso_method.upper()} SSO configured and ready",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "sso_enabled": True,
                        "sso_method": sso_method,
                        "tenant_id": tenant_id[:8] + "..." if tenant_id else None,
                        "client_id": client_id[:8] + "..." if client_id else None,
                        "admin_link": "/admin#integrations"
                    }
                }
            else:
                return {
                    "name": "SSO Authentication",
                    "status": HealthStatus.DEGRADED,
                    "message": f"{sso_method.upper()} SSO partially configured",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "sso_enabled": True,
                        "sso_method": sso_method,
                        "note": "Check configuration in Admin > Integrations"
                    }
                }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"SSO health check failed: {e}")
            return {
                "name": "SSO Authentication",
                "status": HealthStatus.DEGRADED,
                "message": f"Status check failed: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_scim_provisioning(self) -> dict:
        """Check SCIM user provisioning configuration."""
        start = datetime.utcnow()
        try:
            scim_token = settings.SCIM_BEARER_TOKEN
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            if not scim_token:
                return {
                    "name": "SCIM Provisioning",
                    "status": HealthStatus.DEGRADED,
                    "message": "Not configured - using manual user management",
                    "response_time_ms": round(elapsed, 2),
                    "details": {
                        "scim_configured": False,
                        "endpoint": "/scim/v2",
                        "note": "Configure SCIM_BEARER_TOKEN to enable"
                    }
                }

            # Count Entra ID users
            from app.models.user import User
            entra_users = self.db.query(User).filter(User.auth_provider == "entra_id").count()
            total_users = self.db.query(User).count()

            return {
                "name": "SCIM Provisioning",
                "status": HealthStatus.HEALTHY,
                "message": f"Configured. {entra_users} Entra ID users synced.",
                "response_time_ms": round(elapsed, 2),
                "details": {
                    "scim_configured": True,
                    "endpoint": "/scim/v2",
                    "entra_id_users": entra_users,
                    "total_users": total_users,
                    "admin_link": "/admin#integrations"
                }
            }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"SCIM health check failed: {e}")
            return {
                "name": "SCIM Provisioning",
                "status": HealthStatus.DEGRADED,
                "message": f"Status check failed: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }

    async def _check_app_instances(self) -> dict:
        """
        Check Azure App Service container instances health.

        Retrieves instance status similar to the Azure Portal health check view:
        - Server name (instance ID)
        - Physical zone (availability zone)
        - Status (Started/Stopped/etc)
        - Last error info
        - Health check status (Healthy/Degraded)
        """
        start = datetime.utcnow()
        try:
            # Only available in Azure environments
            if settings.ENVIRONMENT == "development":
                return {
                    "name": "App Instances",
                    "status": HealthStatus.HEALTHY,
                    "message": "Local development environment",
                    "response_time_ms": 0,
                    "details": {
                        "instances": [{
                            "server": "localhost",
                            "physical_zone": "local",
                            "status": "Started",
                            "last_error": None,
                            "last_error_info": None,
                            "last_error_occurred": None,
                            "health_check_status": "Healthy"
                        }],
                        "healthy_count": 1,
                        "degraded_count": 0,
                        "total_count": 1,
                        "health_percentage": 100.0
                    }
                }

            # Get the web app name from settings or environment
            import os
            webapp_name = os.environ.get("WEBSITE_SITE_NAME", "mvd-docintel-app")
            resource_group = os.environ.get("WEBSITE_RESOURCE_GROUP", "DocIntel-rg")
            subscription_id = os.environ.get("WEBSITE_OWNER_NAME", "").split("+")[0] if os.environ.get("WEBSITE_OWNER_NAME") else None

            # Try to get instance info from Azure environment variables
            instance_id = os.environ.get("WEBSITE_INSTANCE_ID", "unknown")
            role_instance_id = os.environ.get("WEBSITE_ROLE_INSTANCE_ID", os.environ.get("RoleDeploymentId", "unknown"))

            # Azure App Service provides some info via environment
            instances = []

            # Try to use Azure Management API if we have credentials
            try:
                from azure.identity import DefaultAzureCredential
                import httpx

                if subscription_id:
                    credential = DefaultAzureCredential()
                    token = credential.get_token("https://management.azure.com/.default")

                    # Get web app instances
                    api_url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Web/sites/{webapp_name}/instances?api-version=2022-03-01"

                    async with httpx.AsyncClient(timeout=15.0) as client:
                        response = await client.get(
                            api_url,
                            headers={
                                "Authorization": f"Bearer {token.token}",
                                "Content-Type": "application/json"
                            }
                        )

                        if response.status_code == 200:
                            data = response.json()
                            for instance in data.get("value", []):
                                props = instance.get("properties", {})
                                inst_name = instance.get("name", "unknown")

                                # Map instance properties to our format
                                instances.append({
                                    "server": inst_name[:15] if len(inst_name) > 15 else inst_name,
                                    "physical_zone": props.get("availabilityZone", "---"),
                                    "status": "Started" if props.get("state") == "READY" else props.get("state", "Unknown"),
                                    "last_error": props.get("healthCheckUrl"),
                                    "last_error_info": None,
                                    "last_error_occurred": None,
                                    "health_check_status": "Healthy" if props.get("state") == "READY" else "Degraded"
                                })
            except Exception as api_error:
                logger.debug(f"Could not get instances from Azure API: {api_error}")

            # Fallback: provide current instance info from environment
            if not instances:
                # Get instance count from WEBSITE_INSTANCE_COUNT or default
                instance_count = int(os.environ.get("WEBSITE_INSTANCE_COUNT", "1"))

                # Current instance is healthy if we got this far
                instances.append({
                    "server": instance_id[:15] if len(instance_id) > 15 else instance_id,
                    "physical_zone": os.environ.get("REGION_NAME", "---"),
                    "status": "Started",
                    "last_error": "---",
                    "last_error_info": "---",
                    "last_error_occurred": "---",
                    "health_check_status": "Healthy"
                })

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            # Calculate summary
            healthy_count = sum(1 for i in instances if i["health_check_status"] == "Healthy")
            degraded_count = len(instances) - healthy_count
            total_count = len(instances)
            health_percentage = (healthy_count / total_count * 100) if total_count > 0 else 0

            # Determine overall status
            if health_percentage == 100:
                status = HealthStatus.HEALTHY
                message = f"All {total_count} instance(s) healthy"
            elif health_percentage >= 50:
                status = HealthStatus.DEGRADED
                message = f"{healthy_count}/{total_count} instances healthy"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"Only {healthy_count}/{total_count} instances healthy"

            return {
                "name": "App Instances",
                "status": status,
                "message": message,
                "response_time_ms": round(elapsed, 2),
                "details": {
                    "instances": instances,
                    "healthy_count": healthy_count,
                    "degraded_count": degraded_count,
                    "total_count": total_count,
                    "health_percentage": round(health_percentage, 2)
                }
            }

        except Exception as e:
            elapsed = (datetime.utcnow() - start).total_seconds() * 1000
            logger.error(f"App instances health check failed: {e}")
            return {
                "name": "App Instances",
                "status": HealthStatus.DEGRADED,
                "message": f"Status check failed: {str(e)[:100]}",
                "response_time_ms": round(elapsed, 2)
            }
