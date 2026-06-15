import httpx
import re
import urllib.parse
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
        """Search with Tavily (primary) -> SerpAPI (fallback) -> DuckDuckGo HTML fallback."""
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

        logger.info("Using DuckDuckGo HTML fallback for web search")
        try:
            return await self._duckduckgo_search(query, max_results)
        except Exception as e:
            logger.warning(f"DuckDuckGo fallback search failed: {e}")
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

    async def _duckduckgo_search(self, query: str, max_results: int) -> List[WebSearchResult]:
        if not self._http_client:
            await self.connect()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
        response = await self._http_client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
        )
        response.raise_for_status()
        html = response.text

        titles = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.S)
        snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html, flags=re.S)

        results: List[WebSearchResult] = []
        for idx, (url, title_html) in enumerate(titles[:max_results]):
            title = re.sub(r'<.*?>', '', title_html).strip()
            snippet = re.sub(r'<.*?>', '', snippets[idx].strip()) if idx < len(snippets) else ""
            normalized_url = self._normalize_web_url(url)
            if title and normalized_url:
                results.append(WebSearchResult(
                    title=title,
                    url=normalized_url,
                    snippet=snippet,
                    score=1.0 - float(idx) * 0.1,
                ))
        return results

    def _normalize_web_url(self, url: str) -> str:
        url = url.strip()
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url

        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("duckduckgo.com"):
            query = urllib.parse.parse_qs(parsed.query)
            uddg_values = query.get("uddg") or query.get("u")
            if uddg_values:
                decoded = urllib.parse.unquote(uddg_values[0])
                if decoded:
                    return decoded
        if not parsed.scheme:
            return "https://" + url
        return url

web_search_service = WebSearchService()
