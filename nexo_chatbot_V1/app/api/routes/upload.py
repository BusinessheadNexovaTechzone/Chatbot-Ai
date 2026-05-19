from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from app.models.schemas import FileUploadResponse, RetrieveRequest, RetrieveResponse
from app.ingestion.cleaner import clean_text
from app.ingestion.chunker import chunk_text
from app.retrieval.embeddings import embedding_service
from app.retrieval.vector_store import vector_store
from app.utils.file_processor import FileProcessor
from app.utils.logger import logger
from app.config.settings import get_settings
from app.services.orchestrator import orchestrator
import base64
import os
import time
from datetime import datetime

router = APIRouter(prefix="/api/v1", tags=["upload"])

EMBED_BATCH_SIZE = 50
settings = get_settings()

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)) -> FileUploadResponse:
    """
    Upload a file and process it for storage in the vector database.

    All file formats are accepted. For supported formats (PDF, Word, Excel, PowerPoint, text),
    text is extracted, cleaned, chunked, and embedded. For other formats, basic metadata
    is stored. Files are versioned automatically.
    """
    try:
        # Read file content
        content = await file.read()
        size = len(content)

        # Check file size limit
        max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if size > max_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.MAX_FILE_SIZE_MB}MB, got {size / (1024*1024):.1f}MB"
            )

        # Process the file: extract, clean, chunk, embed, and store
        return await _process_and_embed_file(file, content, size)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"File upload failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_data(request: RetrieveRequest) -> RetrieveResponse:
    """
    Retrieve relevant data chunks from uploaded files based on a query.

    This endpoint searches the vector database for content related to the query
    and returns the matching document chunks from uploaded files.
    """
    try:
        logger.info(f"Retrieve request: query='{request.query}'")
        t_start = time.perf_counter()
        chunks = await orchestrator._retrieve_domain(request.query)
        latency_ms = (time.perf_counter() - t_start) * 1000

        logger.info(f"Retrieved {len(chunks)} chunks in {latency_ms:.2f}ms")
        if chunks:
            logger.info(f"Top chunk score: {chunks[0].score:.3f}, content preview: {chunks[0].content[:100]}...")

        return RetrieveResponse(chunks=chunks, latency_ms=latency_ms)
    except Exception as exc:
        logger.error(f"Retrieve error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def _process_and_embed_file(file: UploadFile, content: bytes, size: int) -> FileUploadResponse:
    """Process any file: extract text if possible, clean, chunk, embed, and store."""
    errors = []
    chunks_created = 0
    chunks_indexed = 0

    try:
        logger.info(f"File uploaded for processing: {file.filename}, size: {size}")

        # Try to extract text from any file format
        try:
            extracted_text, is_extractable = await FileProcessor.extract_text(content, file.filename)

            if not is_extractable or not extracted_text.strip():
                # For non-extractable files, create a metadata chunk
                extracted_text = f"File: {file.filename}\nSize: {size} bytes\nType: {file.content_type or 'unknown'}\nUploaded at: {datetime.now().isoformat()}"
                logger.info(f"Created metadata for non-extractable file: {file.filename}")

        except Exception as exc:
            errors.append(f"Text extraction failed: {exc}")
            # Create metadata chunk even if extraction fails
            extracted_text = f"File: {file.filename}\nSize: {size} bytes\nType: {file.content_type or 'unknown'}\nError: Could not extract content\nUploaded at: {datetime.now().isoformat()}"

        # Clean the text
        try:
            cleaned_text = clean_text(extracted_text)
            if not cleaned_text:
                cleaned_text = extracted_text  # Use original if cleaning removes everything
        except Exception as exc:
            errors.append(f"Text cleaning failed: {exc}")
            cleaned_text = extracted_text

        # Add versioning information
        version = await _get_next_version(file.filename)
        versioned_text = f"[VERSION {version}] {cleaned_text}"

        # Chunk the text
        try:
            chunks = chunk_text(
                text=versioned_text,
                source="uploaded_file",
                url=file.filename,
                section="main",
            )
            chunks_created = len(chunks)
            logger.info(f"Created {chunks_created} chunks from file: {file.filename}")
        except Exception as exc:
            errors.append(f"Text chunking failed: {exc}")
            raise HTTPException(status_code=500, detail=f"Text chunking failed: {exc}")

        # Generate embeddings and store in vector database
        if chunks:
            try:
                # Ensure vector store is connected
                await vector_store.connect()

                # Process in batches
                for i in range(0, len(chunks), EMBED_BATCH_SIZE):
                    batch = chunks[i:i + EMBED_BATCH_SIZE]
                    try:
                        texts = [c["content"] for c in batch]
                        embeddings = await embedding_service.embed_texts(texts)
                        await vector_store.upsert_chunks(batch, embeddings)
                        chunks_indexed += len(batch)
                        logger.info(f"Indexed batch {i//EMBED_BATCH_SIZE + 1}: {len(batch)} chunks")
                    except Exception as exc:
                        errors.append(f"Embedding/indexing error at batch {i}: {exc}")
                        logger.error(f"Batch processing failed: {exc}", exc_info=True)

                logger.info(f"Successfully indexed {chunks_indexed} chunks from file: {file.filename}")

            except Exception as exc:
                error_msg = f"Vector storage failed: {exc}"
                errors.append(error_msg)
                logger.error(f"Vector store error: {exc}", exc_info=True)
                # Don't fail the upload if vector storage fails - the file was processed successfully
                # The chunks are still created and can be stored later when the service is available

        return FileUploadResponse(
            filename=file.filename,
            content_type=FileProcessor.get_mime_type(file.filename),
            size=size,
            content="",  # No raw content returned for processed files
            is_text=True,  # All files are processed to text/metadata
            chunks_created=chunks_created,
            chunks_indexed=chunks_indexed,
            version=version,
            errors=errors if errors else None
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"File processing failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"File processing failed: {exc}")


async def _get_next_version(filename: str) -> int:
    """Get the next version number for a file based on existing chunks."""
    try:
        # Try to connect to vector store to check existing versions
        await vector_store.connect()

        # Search for existing chunks with this filename
        # This is a simplified version check - in production you'd want more sophisticated versioning
        # For now, we'll use a simple counter based on current date/time
        import time
        version = int(time.time())  # Use timestamp as version
        return version

    except Exception:
        # If vector store is not available, use timestamp
        import time
        return int(time.time())
    """Get the next version number for a file based on existing chunks."""
    try:
        # Try to connect to vector store to check existing versions
        await vector_store.connect()

        # Search for existing chunks with this filename
        # This is a simplified version check - in production you'd want more sophisticated versioning
        # For now, we'll use a simple counter based on current date/time
        import time
        version = int(time.time())  # Use timestamp as version
        return version

    except Exception:
        # If vector store is not available, use timestamp
        import time
        return int(time.time())


@router.delete("/upload", response_model=dict)
async def clear_uploaded_documents() -> dict:
    """
    Clear all uploaded document vectors from the vector database and reset the upload index.

    This removes all stored chunks from the Qdrant collection used for uploaded files.
    """
    try:
        await vector_store.connect()
        success = await vector_store.clear_collection()
        try:
            from app.retrieval.bm25_search import bm25_search
            bm25_search.clear()
        except Exception as bm25_exc:
            logger.warning(f"BM25 cleanup failed: {bm25_exc}")

        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear uploaded documents from the vector database.")

        return {
            "status": "cleared",
            "collection_name": settings.QDRANT_COLLECTION,
            "message": "All uploaded document vectors have been cleared and the upload index has been reset.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Clear uploaded documents failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Clear uploaded documents failed: {exc}")


@router.get("/verify/vectors", response_model=dict)
async def verify_vectors_in_db() -> dict:
    """
    Verify and inspect vectors stored in the vector database.
    
    Returns information about:
    - Total vectors stored in the collection
    - Embedding dimensions
    - Embedding model used
    - Sample vector metadata
    """
    try:
        from app.config.settings import get_settings
        from qdrant_client import AsyncQdrantClient
        
        settings = get_settings()
        
        # Connect to Qdrant
        if settings.QDRANT_URL:
            client = AsyncQdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )
        elif settings.QDRANT_HOST.startswith(("http://", "https://")):
            client = AsyncQdrantClient(
                url=settings.QDRANT_HOST,
                api_key=settings.QDRANT_API_KEY,
            )
        else:
            client = AsyncQdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=settings.QDRANT_API_KEY,
            )
        
        # Get collection info
        collection_info = await client.get_collection(settings.QDRANT_COLLECTION)
        total_vectors = collection_info.points_count
        vector_size = collection_info.config.vectors.size
        
        logger.info(f"✓ Vector Database Verification")
        logger.info(f"  - Collection: {settings.QDRANT_COLLECTION}")
        logger.info(f"  - Total Vectors: {total_vectors:,}")
        logger.info(f"  - Vector Dimension: {vector_size}")
        logger.info(f"  - Embedding Model: {settings.EMBEDDING_MODEL}")
        
        # Scroll some sample vectors
        sample_vectors = []
        if total_vectors > 0:
            scroll_result = await client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                limit=5
            )
            
            for point in scroll_result[0]:
                sample_vectors.append({
                    "id": str(point.id),
                    "vector_dimension": len(point.vector) if point.vector else 0,
                    "source": point.payload.get("source", "unknown"),
                    "url": point.payload.get("url", "unknown"),
                    "content_preview": point.payload.get("content", "")[:100] + "..." if point.payload.get("content") else "",
                })
        
        await client.close()
        
        return {
            "collection_name": settings.QDRANT_COLLECTION,
            "total_vectors": total_vectors,
            "embedding_dimension": vector_size,
            "embedding_model": settings.EMBEDDING_MODEL,
            "sample_vectors": sample_vectors,
            "storage_status": "✓ VERIFIED" if total_vectors > 0 else "✓ EMPTY (ready for uploads)"
        }
        
    except Exception as exc:
        logger.error(f"Vector verification failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vector verification failed: {exc}")