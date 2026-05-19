import asyncio
from typing import List
from app.ingestion.scraper import WebScraper
from app.ingestion.cleaner import clean_text
from app.ingestion.chunker import chunk_text
from app.retrieval.embeddings import embedding_service
from app.retrieval.vector_store import vector_store
from app.models.schemas import IngestRequest, IngestResponse
from app.utils.logger import logger

EMBED_BATCH_SIZE = 50

async def run_ingestion_pipeline(request: IngestRequest) -> IngestResponse:
    """Full pipeline: scrape -> clean -> chunk -> embed -> index."""
    errors = []
    total_chunks = 0
    pages_scraped = 0

    scraper = WebScraper(
        site_name=request.site_name,
        base_urls=request.urls,
    )
    pages = await scraper.scrape_all()
    pages_scraped = len(pages)
    logger.info(f"Scraped {pages_scraped} pages for site: {request.site_name}")

    all_chunks = []
    for page in pages:
        try:
            cleaned = clean_text(page["content"])
            if not cleaned:
                continue
            chunks = chunk_text(
                text=cleaned,
                source=request.site_name,
                url=page["url"],
                section=page.get("title", ""),
                timestamp=page.get("timestamp", ""),
            )
            all_chunks.extend(chunks)
        except Exception as e:
            errors.append(f"Chunking error for {page['url']}: {str(e)}")

    logger.info(f"Generated {len(all_chunks)} chunks")

    # Embed and index in batches
    for i in range(0, len(all_chunks), EMBED_BATCH_SIZE):
        batch = all_chunks[i:i + EMBED_BATCH_SIZE]
        try:
            texts = [c["content"] for c in batch]
            embeddings = await embedding_service.embed_texts(texts)
            await vector_store.upsert_chunks(batch, embeddings)
            total_chunks += len(batch)
        except Exception as e:
            errors.append(f"Embedding/indexing error at batch {i}: {str(e)}")

    logger.info(f"Ingestion complete: {total_chunks} chunks indexed")
    return IngestResponse(
        status="success" if not errors else "partial",
        pages_scraped=pages_scraped,
        chunks_indexed=total_chunks,
        errors=errors,
    )
