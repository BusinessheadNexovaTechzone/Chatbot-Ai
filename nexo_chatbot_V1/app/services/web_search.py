import httpx
from typing import List, Optional
from app.config.settings import get_settings
from app.models.schemas import WebSearchResult
from app.utils.logger import logger

settings = get_settings()

class WebSearchService:
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None

    async def connect(self):
        self._http_client = httpx.AsyncClient(timeout=10.0)

    async def disconnect(self):
        if self._http_client:
            await self._http_client.aclose()

    async def search(self, query: str, max_results: int = 5) -> List[WebSearchResult]:
        """Search with Tavily (primary) -> SerpAPI (fallback)."""
        if settings.TAVILY_API_KEY:
            try:
                return await self._tavily_search(query, max_results)
            except Exception as e:
                logger.warning(f"Tavily search failed: {e}")

        if settings.SERPAPI_KEY:
            try:
                return await self._serpapi_search(query, max_results)
            except Exception as e:
                logger.warning(f"SerpAPI search failed: {e}")

        logger.warning("No web search API configured")
        return []

    async def _tavily_search(self, query: str, max_results: int) -> List[WebSearchResult]:
        response = await self._http_client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", []):
            results.append(WebSearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                score=item.get("score", 0.0),
            ))
        return results

    async def _serpapi_search(self, query: str, max_results: int) -> List[WebSearchResult]:
        response = await self._http_client.get(
            "https://serpapi.com/search",
            params={
                "q": query,
                "api_key": settings.SERPAPI_KEY,
                "num": max_results,
                "engine": "google",
            },
        )
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("organic_results", [])[:max_results]:
            results.append(WebSearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                score=0.7,
            ))
        return results

web_search_service = WebSearchService()
