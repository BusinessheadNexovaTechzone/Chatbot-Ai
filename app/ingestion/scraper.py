"""
Web scraper with full-domain coverage.

Discovery order (most complete → least complete):
  1. sitemap.xml   — explicit list of every URL the site owner published
  2. sitemap index — a sitemap that points to child sitemaps (multi-sitemap sites)
  3. robots.txt    — may reveal a non-standard sitemap location
  4. BFS crawl     — follow every <a href> on every visited page

All four sources feed a single deduplicated BFS queue, so inner-inner pages
discovered by any source are visited and indexed.
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Set, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from datetime import datetime, timezone
import httpx
from app.config.settings import get_settings
from app.utils.logger import logger

settings = get_settings()

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed — falling back to httpx scraper.")

# Non-HTML file extensions — skip without fetching
_SKIP_EXTENSIONS = {
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".mp4", ".mp3", ".avi", ".mov", ".webm",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".xml", ".json", ".csv", ".xlsx", ".xls", ".docx", ".doc",
}


# ── URL helpers ───────────────────────────────────────────────────────────────

def _is_hash_route(url: str) -> bool:
    """
    Distinguish SPA hash-based routes from plain anchor links.
      Hash route  →  https://example.com/#/about   (fragment starts with '/')
      Anchor link →  https://example.com/page#section
    Only hash routes should be treated as separate navigable pages.
    """
    fragment = urlparse(url).fragment
    return fragment.startswith("/")


def _normalize(url: str) -> str:
    """
    Canonical URL key for deduplication.

    - Hash routes  (#/path): keep fragment intact — each route is a distinct page.
    - Anchor links (#section): strip fragment — same page, different scroll position.
    - Always strip trailing slash from path.
    """
    try:
        p = urlparse(url)
        fragment = p.fragment if _is_hash_route(url) else ""
        return urlunparse((
            p.scheme, p.netloc,
            p.path.rstrip("/") or "/",
            p.params, p.query, fragment,
        ))
    except Exception:
        return url


def _same_domain(url: str, origin: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(origin).netloc
    except Exception:
        return False


def _crawlable(url: str) -> bool:
    lower = url.lower()
    if any(lower.startswith(s) for s in ("mailto:", "tel:", "javascript:", "data:")):
        return False
    # Plain anchor-only href (e.g. "#top") with no host — not navigable
    parsed = urlparse(url)
    if not parsed.scheme and not parsed.netloc and not parsed.path:
        return False
    path = parsed.path.lower()
    return not any(path.endswith(ext) for ext in _SKIP_EXTENSIONS)


def _origin(url: str) -> str:
    """Return scheme + netloc only: https://example.com"""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


# ── Sitemap + robots.txt discovery ───────────────────────────────────────────

async def _fetch_text(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        r = await client.get(url, timeout=10.0)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


async def _sitemap_urls_from_xml(client: httpx.AsyncClient, sitemap_url: str,
                                  visited_sitemaps: Set[str], depth: int = 0) -> List[str]:
    """
    Recursively parse a sitemap or sitemap-index and return all page URLs.
    Handles:
      - <sitemapindex> → child <sitemap><loc> entries (nested sitemaps)
      - <urlset>       → <url><loc> entries (actual page URLs)
    """
    if depth > 5 or sitemap_url in visited_sitemaps:
        return []
    visited_sitemaps.add(sitemap_url)

    xml_text = await _fetch_text(client, sitemap_url)
    if not xml_text:
        return []

    urls: List[str] = []
    try:
        root = ET.fromstring(xml_text)
        # Strip XML namespace for easier tag matching
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        ns  = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
        loc_tag = f"{{{ns}}}loc" if ns else "loc"

        if tag == "sitemapindex":
            # Points to child sitemaps — recurse into each
            child_tag = f"{{{ns}}}sitemap" if ns else "sitemap"
            for child in root.findall(child_tag):
                loc = child.find(loc_tag)
                if loc is not None and loc.text:
                    child_urls = await _sitemap_urls_from_xml(
                        client, loc.text.strip(), visited_sitemaps, depth + 1
                    )
                    urls.extend(child_urls)
        elif tag == "urlset":
            url_tag = f"{{{ns}}}url" if ns else "url"
            for url_el in root.findall(url_tag):
                loc = url_el.find(loc_tag)
                if loc is not None and loc.text:
                    urls.append(loc.text.strip())
    except ET.ParseError as exc:
        logger.warning(f"Sitemap XML parse error ({sitemap_url}): {exc}")

    return urls


async def _discover_sitemap_urls(client: httpx.AsyncClient, base_url: str) -> List[str]:
    """
    Find and parse all sitemaps for the domain.

    Strategy:
      1. Try standard /sitemap.xml
      2. Try /sitemap_index.xml
      3. Parse robots.txt for Sitemap: directives
    """
    origin        = _origin(base_url)
    all_urls:     List[str] = []
    visited_sitemaps: Set[str] = set()

    candidate_sitemaps: List[str] = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap-index.xml",
    ]

    # robots.txt may declare non-standard sitemap paths
    robots_text = await _fetch_text(client, f"{origin}/robots.txt")
    if robots_text:
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap_loc = line.split(":", 1)[1].strip()
                if sitemap_loc not in candidate_sitemaps:
                    candidate_sitemaps.append(sitemap_loc)

    for sitemap_url in candidate_sitemaps:
        urls = await _sitemap_urls_from_xml(client, sitemap_url, visited_sitemaps)
        if urls:
            logger.info(f"Sitemap {sitemap_url} → {len(urls)} URLs")
            all_urls.extend(urls)

    return all_urls


# ── Main scraper class ────────────────────────────────────────────────────────

class WebScraper:
    def __init__(self, site_name: str, base_urls: List[str], max_pages: int = None):
        self.site_name = site_name
        self.base_urls = base_urls
        self.max_pages = max_pages or settings.MAX_PAGES_PER_DOMAIN
        self._visited: Set[str] = set()
        self._results: List[Dict[str, Any]] = []

    async def scrape_all(self) -> List[Dict[str, Any]]:
        if PLAYWRIGHT_AVAILABLE:
            return await self._scrape_playwright()
        return await self._scrape_httpx()

    def _record(self, url: str, title: str, content: str):
        self._results.append({
            "url": url,
            "title": title,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            f"Scraped [{len(self._visited)}/{self.max_pages}]: {url}"
        )

    async def _build_queue(self, client: httpx.AsyncClient) -> List[str]:
        """
        Build the initial BFS queue by combining:
          - Caller-supplied seed URLs
          - All URLs discovered from sitemaps / robots.txt
        """
        origin = self.base_urls[0]
        seed   = [_normalize(u) for u in self.base_urls]

        sitemap_urls = await _discover_sitemap_urls(client, origin)
        logger.info(f"Total sitemap URLs discovered: {len(sitemap_urls)}")

        queue: List[str] = list(seed)
        seen_in_queue: Set[str] = set(seed)

        for url in sitemap_urls:
            norm = _normalize(url)
            if (
                _same_domain(norm, origin)
                and _crawlable(norm)
                and norm not in seen_in_queue
            ):
                queue.append(norm)
                seen_in_queue.add(norm)

        logger.info(f"Initial queue size (seed + sitemap): {len(queue)}")
        return queue

    # ── Playwright ────────────────────────────────────────────────────────────

    async def _scrape_playwright(self) -> List[Dict[str, Any]]:
        origin = self.base_urls[0]

        # Use httpx just for sitemap/robots discovery (lightweight)
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "NexoBot/1.0"},
        ) as client:
            queue = await self._build_queue(client)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx     = await browser.new_context(
                user_agent="Mozilla/5.0 (compatible; NexoBot/1.0)"
            )
            page = await ctx.new_page()
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,ico,css,woff,woff2,ttf,mp4,mp3}",
                lambda r: r.abort(),
            )

            queued: Set[str] = set(queue)   # track what's in queue to avoid duplicates

            while queue and len(self._visited) < self.max_pages:
                url = queue.pop(0)
                if url in self._visited or not _crawlable(url):
                    continue
                self._visited.add(url)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)

                    content = await page.evaluate("""() => {
                        const selectors = [
                            'main', 'article', '[role=main]',
                            '.content', '#content', '#main', 'body'
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.innerText.trim().length > 100)
                                return el.innerText;
                        }
                        return document.body.innerText;
                    }""")

                    title = await page.title()
                    self._record(url, title, content)

                    # Discover new links on this page and add to BFS queue
                    raw_links: List[str] = await page.eval_on_selector_all(
                        "a[href]", "els => els.map(e => e.href)"
                    )
                    for raw in raw_links:
                        norm = _normalize(raw)
                        if (
                            _same_domain(norm, origin)
                            and _crawlable(norm)
                            and norm not in self._visited
                            and norm not in queued
                        ):
                            queue.append(norm)
                            queued.add(norm)

                except Exception as exc:
                    logger.warning(f"Playwright error on {url}: {exc}")

            await browser.close()

        logger.info(f"Playwright crawl complete: {len(self._results)} pages")
        return self._results

    # ── httpx (static / server-rendered sites) ───────────────────────────────

    async def _scrape_httpx(self) -> List[Dict[str, Any]]:
        from html.parser import HTMLParser

        class PageParser(HTMLParser):
            """Single-pass: extracts visible text + all href links."""

            _SKIP_TAGS = {"script", "style", "nav", "footer", "header",
                          "noscript", "aside", "form", "button"}

            def __init__(self, base_url: str):
                super().__init__()
                self.base_url = base_url
                self.texts:  List[str] = []
                self.links:  List[str] = []
                self._skip = False
                self._skip_depth = 0

            def handle_starttag(self, tag, attrs):
                if tag in self._SKIP_TAGS:
                    self._skip = True
                    self._skip_depth += 1
                if tag == "a":
                    href = dict(attrs).get("href", "")
                    if href:
                        self.links.append(urljoin(self.base_url, href))

            def handle_endtag(self, tag):
                if tag in self._SKIP_TAGS and self._skip_depth > 0:
                    self._skip_depth -= 1
                    if self._skip_depth == 0:
                        self._skip = False

            def handle_data(self, data):
                if not self._skip and data.strip():
                    self.texts.append(data.strip())

        origin = self.base_urls[0]

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": "NexoBot/1.0"},
            timeout=15.0,
        ) as client:
            queue  = await self._build_queue(client)
            queued: Set[str] = set(queue)

            while queue and len(self._visited) < self.max_pages:
                url = queue.pop(0)
                if url in self._visited or not _crawlable(url):
                    continue
                self._visited.add(url)

                try:
                    resp = await client.get(url)
                    resp.raise_for_status()

                    if "text/html" not in resp.headers.get("content-type", ""):
                        continue

                    parser = PageParser(base_url=url)
                    parser.feed(resp.text)

                    content = " ".join(parser.texts)
                    self._record(url, url, content)

                    # Enqueue newly discovered same-domain links
                    for raw in parser.links:
                        norm = _normalize(raw)
                        if (
                            _same_domain(norm, origin)
                            and _crawlable(norm)
                            and norm not in self._visited
                            and norm not in queued
                        ):
                            queue.append(norm)
                            queued.add(norm)

                except Exception as exc:
                    logger.warning(f"httpx error on {url}: {exc}")

        logger.info(f"httpx crawl complete: {len(self._results)} pages")
        return self._results
