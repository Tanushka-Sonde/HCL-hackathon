"""Locust load testing suite for the AI Research Platform."""

import uuid

from locust import HttpUser, between, task


class APIUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Create a user and organization to use for the load test."""
        # Register a unique user
        self.username = f"loadtest_{uuid.uuid4().hex[:8]}@example.com"
        self.password = "loadtest123"

        reg_resp = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": self.username,
                "password": self.password,
                "full_name": "Load Test User",
            },
        )
        if reg_resp.status_code != 201:
            print(f"Failed to register: {reg_resp.text}")
            return

        # Login
        token_resp = self.client.post(
            "/api/v1/auth/token",
            data={"username": self.username, "password": self.password},
        )
        if token_resp.status_code != 200:
            print(f"Failed to login: {token_resp.text}")
            return

        self.token = token_resp.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # Create Org
        org_resp = self.client.post(
            "/api/v1/organizations",
            json={
                "name": f"Org {uuid.uuid4().hex[:6]}",
                "slug": f"org-{uuid.uuid4().hex[:6]}",
            },
            headers=self.headers,
        )

        if org_resp.status_code == 201:
            self.tenant_id = org_resp.json()["id"]
            self.headers["X-Tenant-ID"] = self.tenant_id

    @task(3)
    def list_documents(self):
        """Test document listing."""
        if hasattr(self, "headers") and "X-Tenant-ID" in self.headers:
            self.client.get("/api/v1/documents", headers=self.headers)

    @task(2)
    def hybrid_search(self):
        """Test hybrid search."""
        if hasattr(self, "headers") and "X-Tenant-ID" in self.headers:
            self.client.post(
                "/api/v1/search",
                json={"query": "machine learning architecture", "top_k": 5},
                headers=self.headers,
            )

    @task(1)
    def semantic_search(self):
        """Test semantic search."""
        if hasattr(self, "headers") and "X-Tenant-ID" in self.headers:
            self.client.post(
                "/api/v1/search/semantic",
                json={"query": "scalability and fault tolerance", "top_k": 5},
                headers=self.headers,
            )

    @task(1)
    def keyword_search(self):
        """Test keyword search."""
        if hasattr(self, "headers") and "X-Tenant-ID" in self.headers:
            self.client.post(
                "/api/v1/search/keyword",
                json={"query": "docker compose nginx", "top_k": 5},
                headers=self.headers,
            )
