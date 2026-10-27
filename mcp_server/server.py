"""Stdio MCP server for the AI Research Platform.

Run with:

    python -m mcp_server.server
"""

from __future__ import annotations

from typing import Any

from mcp_server.adapters.research_platform import ResearchPlatformMCPAdapter
from src.core.logging import configure_logging


def create_server() -> Any:
    """Create and configure the MCP server."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The 'mcp' package is required to run the MCP server. "
            "Install project dependencies with: pip install -r requirements.in"
        ) from exc

    adapter = ResearchPlatformMCPAdapter()
    server = FastMCP("ai-research-platform")

    @server.tool()
    async def upload_document(
        user_id: str,
        filename: str,
        content_base64: str,
        idempotency_key: str,
        tenant_id: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload a base64-encoded document and queue ingestion."""
        return await adapter.upload_document(
            user_id=user_id,
            tenant_id=tenant_id,
            filename=filename,
            content_base64=content_base64,
            idempotency_key=idempotency_key,
            mime_type=mime_type,
        )

    @server.tool()
    async def list_documents(
        user_id: str,
        tenant_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List non-deleted documents for a user."""
        return await adapter.list_documents(
            user_id=user_id,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
        )

    @server.tool()
    async def get_document(
        user_id: str,
        document_id: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one document scoped to a user."""
        return await adapter.get_document(
            user_id=user_id,
            tenant_id=tenant_id,
            document_id=document_id,
        )

    @server.tool()
    async def search(
        user_id: str,
        query: str,
        tenant_id: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Run hybrid retrieval over a user's document corpus."""
        return await adapter.search(
            user_id=user_id,
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
        )

    @server.tool()
    async def get_job(
        user_id: str,
        job_id: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch ingestion job status scoped to a user."""
        return await adapter.get_job(
            user_id=user_id, tenant_id=tenant_id, job_id=job_id
        )

    @server.tool()
    async def evaluate_relevance(
        user_id: str,
        query: str,
        chunk_ids: list[str],
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Grade retrieved chunks for relevance using the configured LLM."""
        return await adapter.evaluate_relevance(
            user_id=user_id,
            tenant_id=tenant_id,
            query=query,
            chunk_ids=chunk_ids,
        )

    return server


def main() -> None:
    """Start the MCP stdio server."""
    configure_logging()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
