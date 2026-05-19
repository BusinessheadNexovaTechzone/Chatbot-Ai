from fastapi import APIRouter, HTTPException
from app.models.schemas import IngestRequest, IngestResponse
from app.ingestion.pipeline import run_ingestion_pipeline
from app.utils.logger import logger

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    """
    Scrape a website and index its content into Qdrant.

    Body:
      {
        "site_name": "My Company",
        "urls": ["https://example.com"],
        "force_refresh": false
      }

    - `site_name`     : Label for the content source (used in citations).
    - `urls`          : One or more seed URLs. The scraper will discover all
                        pages on the same domain via sitemap + BFS link crawl.
    - `force_refresh` : Reserved — currently unused; re-ingestion always upserts.
    """
    logger.info(f"Ingest request: site={request.site_name} urls={request.urls}")
    try:
        return await run_ingestion_pipeline(request)
    except Exception as exc:
        logger.error(f"Ingestion failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}")
