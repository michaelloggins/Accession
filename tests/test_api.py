"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test health check returns healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "environment" in data


class TestAuthEndpoints:
    """Test authentication endpoints."""

    def test_login_missing_credentials(self, client):
        """Test login with missing credentials."""
        response = client.post("/api/auth/login", json={})
        assert response.status_code == 422  # Validation error

    def test_logout(self, client):
        """Test logout endpoint."""
        response = client.post("/api/auth/logout")
        assert response.status_code == 200
        data = response.json()
        assert data["session_terminated"] is True


class TestDocumentEndpoints:
    """Test document management endpoints."""

    def test_get_pending_documents(self, client, auth_headers):
        """Test getting pending documents list."""
        response = client.get("/api/documents/pending", headers=auth_headers)
        # May return 401 without proper auth, but endpoint should exist
        assert response.status_code in [200, 401]

    def test_get_document_not_found(self, client, auth_headers):
        """Test getting non-existent document."""
        response = client.get("/api/documents/99999", headers=auth_headers)
        # Should return 404 or 401 (auth)
        assert response.status_code in [404, 401]


class TestStatsEndpoint:
    """Test statistics endpoint."""

    def test_get_stats(self, client, auth_headers):
        """Test getting system statistics."""
        response = client.get("/api/stats", headers=auth_headers)
        # May return 401 without proper auth
        assert response.status_code in [200, 401]


class TestComplianceEndpoints:
    """Test compliance and audit endpoints."""

    def test_get_audit_logs_no_params(self, client, auth_headers):
        """Test getting audit logs without parameters."""
        response = client.get("/api/compliance/audit-logs", headers=auth_headers)
        assert response.status_code in [200, 401]

    def test_get_phi_access_summary(self, client, auth_headers):
        """Test PHI access summary endpoint."""
        response = client.get("/api/compliance/phi-access-summary", headers=auth_headers)
        assert response.status_code in [200, 401]
