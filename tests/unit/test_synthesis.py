"""Unit tests for retrieval synthesis and web fallback."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from groq import AsyncGroq
from tavily import AsyncTavilyClient

from src.core.config import Settings
from src.retrieval.service import (
    RankedChunk,
    RankedWebResult,
    _fallback_web_search,
    _synthesize_answer,
    hybrid_search,
)
from src.ingestion.pipeline import Embedder


@pytest.mark.asyncio
class TestSynthesisAndFallback:
    async def test_fallback_web_search_success(self):
        settings = Settings(tavily_api_key="test-tavily-key")
        
        with patch("src.retrieval.service.AsyncTavilyClient") as mock_tavily:
            mock_client = AsyncMock()
            mock_client.search.return_value = {
                "results": [
                    {"url": "https://example.com/1", "title": "Test 1", "content": "Content 1", "score": 0.9},
                    {"url": "https://example.com/2", "title": "Test 2", "content": "Content 2"},
                ]
            }
            mock_tavily.return_value = mock_client
            
            results = await _fallback_web_search("test query", settings, top_k=2)
            
            assert len(results) == 2
            assert isinstance(results[0], RankedWebResult)
            assert results[0].url == "https://example.com/1"
            assert results[0].score == 0.9
            assert results[1].score == 0.9  # fallback calculated 1.0 - (1*0.1)
            mock_client.search.assert_called_once_with(query="test query", max_results=2)

    async def test_fallback_web_search_no_api_key(self):
        settings = Settings(tavily_api_key="")
        results = await _fallback_web_search("test query", settings, top_k=2)
        assert results == []

    async def test_fallback_web_search_exception(self):
        settings = Settings(tavily_api_key="test")
        with patch("src.retrieval.service.AsyncTavilyClient") as mock_tavily:
            mock_client = AsyncMock()
            mock_client.search.side_effect = Exception("API error")
            mock_tavily.return_value = mock_client
            
            results = await _fallback_web_search("test query", settings, top_k=2)
            assert results == []

    async def test_synthesize_answer_success_internal(self):
        settings = Settings(groq_api_key="test-groq")
        chunks = [
            RankedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                content="internal doc content",
                chunk_index=0,
                page_number=1,
                score=0.9,
                document_filename="doc.pdf",
            )
        ]
        
        with patch("src.retrieval.service.AsyncGroq") as mock_groq:
            mock_client = AsyncMock()
            mock_choice = AsyncMock()
            mock_choice.message.content = "AI Answer"
            mock_completion = AsyncMock()
            mock_completion.choices = [mock_choice]
            mock_client.chat.completions.create.return_value = mock_completion
            mock_groq.return_value = mock_client
            
            answer = await _synthesize_answer("test query", chunks, settings)
            assert answer == "AI Answer"
            
            # verify prompt structure
            call_args = mock_client.chat.completions.create.call_args[1]
            messages = call_args["messages"]
            assert "internal workspace documents" in messages[0]["content"]
            assert "internal doc content" in messages[1]["content"]

    async def test_synthesize_answer_success_web(self):
        settings = Settings(groq_api_key="test-groq")
        chunks = [
            RankedWebResult(
                url="https://example.com",
                title="Web page",
                content="web content",
                score=0.9,
            )
        ]
        
        with patch("src.retrieval.service.AsyncGroq") as mock_groq:
            mock_client = AsyncMock()
            mock_choice = AsyncMock()
            mock_choice.message.content = "Web Answer"
            mock_completion = AsyncMock()
            mock_completion.choices = [mock_choice]
            mock_client.chat.completions.create.return_value = mock_completion
            mock_groq.return_value = mock_client
            
            answer = await _synthesize_answer("test query", chunks, settings)
            assert answer == "Web Answer"
            
            call_args = mock_client.chat.completions.create.call_args[1]
            messages = call_args["messages"]
            assert "web search results" in messages[0]["content"]

    async def test_synthesize_answer_no_api_key(self):
        settings = Settings(groq_api_key="")
        answer = await _synthesize_answer("test query", [], settings)
        assert answer is None

    async def test_synthesize_answer_exception(self):
        settings = Settings(groq_api_key="test")
        with patch("src.retrieval.service.AsyncGroq") as mock_groq:
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = Exception("API error")
            mock_groq.return_value = mock_client
            
            answer = await _synthesize_answer("test query", [], settings)
            assert answer is None
