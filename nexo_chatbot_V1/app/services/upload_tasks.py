import asyncio
from typing import Dict, Any, List
from app.utils.file_processor import FileProcessor
from app.ingestion.cleaner import clean_text
from app.ingestion.chunker import chunk_text
from app.retrieval.embeddings import embedding_service
from app.retrieval.vector_store import vector_store
from app.utils.logger import logger
from app.config.settings import get_settings

settings = get_settings()
EMBED_BATCH_SIZE = 50

def process_upload_chunks(
    content: bytes,
    filename: str,
    job_id: str,
) -> Dict[str, Any]:
    """
    Background task to process uploaded file into chunks and generate embeddings.
    
    This function:
    1. Validates file size
    2. Extracts text from the file
    3. Cleans the text
    4. Splits into chunks
    5. Generates embeddings (vectors)
    6. Stores in vector database with verification
    
    Args:
        content: File content as bytes
        filename: Name of the uploaded file
        job_id: ID of the background job
        
    Returns:
        Dictionary with processing results
    """
    errors = []
    chunks_created = 0
    chunks_indexed = 0
    vectors_generated = 0
    verification_checks = {}
    result = {
        "job_id": job_id,
        "filename": filename,
        "status": "processing",
    }
    
    try:
        size = len(content)
        logger.info(f"[{job_id}] ========================================")
        logger.info(f"[{job_id}] STARTING UPLOAD PROCESSING")
        logger.info(f"[{job_id}] Filename: {filename}")
        logger.info(f"[{job_id}] File Size: {size:,} bytes ({size / (1024*1024):.2f} MB)")
        logger.info(f"[{job_id}] ========================================")
        
        # ======== STEP 1: FILE SIZE VALIDATION ========
        logger.info(f"[{job_id}] STEP 1: Validating file size...")
        max_size = settings.MAX_FILE_SIZE_BYTES
        if size > max_size:
            error_msg = f"File size {size:,} bytes exceeds maximum {max_size:,} bytes ({settings.MAX_FILE_SIZE_MB} MB)"
            errors.append(error_msg)
            verification_checks["size_validation"] = "FAILED"
            logger.error(f"[{job_id}] ✗ {error_msg}")
            result["status"] = "failed"
            result["error"] = error_msg
            result["verification_checks"] = verification_checks
            return result
        
        verification_checks["size_validation"] = f"✓ PASSED ({size:,} bytes < {max_size:,} bytes limit)"
        logger.info(f"[{job_id}] ✓ File size validation passed: {size:,} bytes")
        
        # ======== STEP 2: FILE FORMAT CHECK ========
        logger.info(f"[{job_id}] STEP 2: Checking file format...")
        if not FileProcessor.is_supported_format(filename):
            supported_formats = list(FileProcessor.SUPPORTED_FORMATS.keys())
            error_msg = f"Unsupported file format. Supported formats: {', '.join(supported_formats)}"
            errors.append(error_msg)
            verification_checks["format_validation"] = "FAILED"
            logger.error(f"[{job_id}] ✗ {error_msg}")
            result["status"] = "failed"
            result["error"] = error_msg
            result["verification_checks"] = verification_checks
            return result
        
        file_format = filename.split('.')[-1].upper()
        verification_checks["format_validation"] = f"✓ PASSED ({file_format})"
        logger.info(f"[{job_id}] ✓ File format validation passed: {file_format}")
        
        # ======== STEP 3: TEXT EXTRACTION ========
        logger.info(f"[{job_id}] STEP 3: Extracting text from file...")
        try:
            extracted_text, is_extractable = asyncio.run(
                FileProcessor.extract_text(content, filename)
            )
            
            if not is_extractable or not extracted_text.strip():
                error_msg = "Could not extract readable text from the file. The file may be corrupted, password-protected, or in an unsupported format."
                errors.append(error_msg)
                verification_checks["text_extraction"] = "FAILED"
                logger.error(f"[{job_id}] ✗ {error_msg}")
                result["status"] = "failed"
                result["error"] = error_msg
                result["verification_checks"] = verification_checks
                return result
            
            extracted_chars = len(extracted_text)
            verification_checks["text_extraction"] = f"✓ PASSED ({extracted_chars:,} characters extracted)"
            logger.info(f"[{job_id}] ✓ Text extraction successful: {extracted_chars:,} characters")
            
        except Exception as exc:
            error_msg = f"Text extraction failed: {exc}"
            errors.append(error_msg)
            verification_checks["text_extraction"] = "FAILED"
            logger.error(f"[{job_id}] ✗ {error_msg}", exc_info=True)
            result["status"] = "failed"
            result["error"] = error_msg
            result["verification_checks"] = verification_checks
            return result
        
        # ======== STEP 4: TEXT CLEANING ========
        logger.info(f"[{job_id}] STEP 4: Cleaning and normalizing text...")
        try:
            cleaned_text = clean_text(extracted_text)
            if not cleaned_text:
                error_msg = "File content is empty or contains only boilerplate text after cleaning."
                errors.append(error_msg)
                verification_checks["text_cleaning"] = "FAILED"
                logger.error(f"[{job_id}] ✗ {error_msg}")
                result["status"] = "failed"
                result["error"] = error_msg
                result["verification_checks"] = verification_checks
                return result
            
            cleaned_chars = len(cleaned_text)
            reduction_percent = ((extracted_chars - cleaned_chars) / extracted_chars) * 100
            verification_checks["text_cleaning"] = f"✓ PASSED ({cleaned_chars:,} chars, {reduction_percent:.1f}% reduction)"
            logger.info(f"[{job_id}] ✓ Text cleaned: {cleaned_chars:,} characters ({reduction_percent:.1f}% reduction)")
        except Exception as exc:
            error_msg = f"Text cleaning failed: {exc}"
            errors.append(error_msg)
            verification_checks["text_cleaning"] = "FAILED"
            logger.error(f"[{job_id}] ✗ {error_msg}", exc_info=True)
            result["status"] = "failed"
            result["error"] = error_msg
            result["verification_checks"] = verification_checks
            return result
        
        # ======== STEP 5: CHUNKING ========
        logger.info(f"[{job_id}] STEP 5: Splitting text into chunks...")
        try:
            chunks = chunk_text(
                text=cleaned_text,
                source="uploaded_file",
                url=filename,
                section="main",
            )
            chunks_created = len(chunks)
            verification_checks["chunking"] = f"✓ PASSED ({chunks_created} chunks created)"
            logger.info(f"[{job_id}] ✓ Chunking successful: {chunks_created} chunks created")
            
            # Log sample chunk info
            if chunks:
                avg_chunk_size = sum(len(c.get("content", "")) for c in chunks) / len(chunks)
                logger.info(f"[{job_id}]   - Average chunk size: {avg_chunk_size:.0f} characters")
                logger.info(f"[{job_id}]   - Min chunk size: {min(len(c.get('content', '')) for c in chunks)} characters")
                logger.info(f"[{job_id}]   - Max chunk size: {max(len(c.get('content', '')) for c in chunks)} characters")
        except Exception as exc:
            error_msg = f"Text chunking failed: {exc}"
            errors.append(error_msg)
            verification_checks["chunking"] = "FAILED"
            logger.error(f"[{job_id}] ✗ {error_msg}", exc_info=True)
            result["status"] = "failed"
            result["error"] = error_msg
            result["verification_checks"] = verification_checks
            return result
        
        # ======== STEP 6: VECTOR GENERATION & STORAGE ========
        if chunks:
            logger.info(f"[{job_id}] STEP 6: Generating embeddings (vectors) and storing in database...")
            logger.info(f"[{job_id}] Embedding model: {settings.EMBEDDING_MODEL}")
            logger.info(f"[{job_id}] Embedding dimension: {settings.EMBEDDING_DIM}")
            logger.info(f"[{job_id}] Batch size: {EMBED_BATCH_SIZE} chunks per batch")
            
            try:
                # Ensure vector store is connected
                asyncio.run(vector_store.connect())
                logger.info(f"[{job_id}] Connected to vector database: {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
                logger.info(f"[{job_id}] Vector collection: {settings.QDRANT_COLLECTION}")
                
                # Process in batches
                total_batches = (len(chunks) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE
                
                for batch_idx in range(0, len(chunks), EMBED_BATCH_SIZE):
                    batch = chunks[batch_idx:batch_idx + EMBED_BATCH_SIZE]
                    batch_num = (batch_idx // EMBED_BATCH_SIZE) + 1
                    
                    logger.info(f"[{job_id}] ► Processing batch {batch_num}/{total_batches} ({len(batch)} chunks)...")
                    
                    try:
                        # ======== EMBEDDING GENERATION ========
                        texts = [c["content"] for c in batch]
                        logger.debug(f"[{job_id}]   Generating embeddings for {len(texts)} texts...")
                        
                        embeddings = asyncio.run(embedding_service.embed_texts(texts))
                        vectors_generated += len(embeddings)
                        
                        # Verify embeddings
                        if not embeddings or len(embeddings) != len(texts):
                            raise ValueError(f"Embedding mismatch: got {len(embeddings)} embeddings for {len(texts)} texts")
                        
                        # Verify embedding dimensions
                        for i, emb in enumerate(embeddings):
                            if len(emb) != settings.EMBEDDING_DIM:
                                raise ValueError(f"Embedding {i} has dimension {len(emb)}, expected {settings.EMBEDDING_DIM}")
                        
                        logger.debug(f"[{job_id}]   ✓ Generated {len(embeddings)} vectors with dimension {settings.EMBEDDING_DIM}")
                        
                        # ======== VECTOR STORAGE ========
                        logger.debug(f"[{job_id}]   Storing vectors in Qdrant database...")
                        asyncio.run(vector_store.upsert_chunks(batch, embeddings))
                        chunks_indexed += len(batch)
                        
                        logger.info(f"[{job_id}] ✓ Batch {batch_num} indexed: {len(batch)} chunks → {len(embeddings)} vectors stored")
                        
                    except Exception as exc:
                        error_msg = f"Embedding/indexing error at batch {batch_num}: {exc}"
                        errors.append(error_msg)
                        logger.error(f"[{job_id}] ✗ {error_msg}", exc_info=True)
                
                verification_checks["vector_generation"] = f"✓ PASSED ({vectors_generated} vectors generated)"
                verification_checks["vector_storage"] = f"✓ PASSED ({chunks_indexed} vectors stored in Qdrant)"
                logger.info(f"[{job_id}] ✓ Vector generation and storage completed: {chunks_indexed} chunks indexed")
                
            except Exception as exc:
                error_msg = f"Vector store operation failed: {exc}"
                errors.append(error_msg)
                verification_checks["vector_generation_storage"] = "FAILED"
                logger.error(f"[{job_id}] ✗ {error_msg}", exc_info=True)
                result["status"] = "failed"
                result["error"] = error_msg
                result["verification_checks"] = verification_checks
                return result
        
        # ======== FINAL SUCCESS ========
        result["status"] = "completed"
        result["chunks_created"] = chunks_created
        result["chunks_indexed"] = chunks_indexed
        result["vectors_generated"] = vectors_generated
        result["file_size"] = size
        result["extracted_chars"] = extracted_chars
        result["cleaned_chars"] = cleaned_chars
        result["errors"] = errors if errors else []
        result["verification_checks"] = verification_checks
        
        logger.info(f"[{job_id}] ========================================")
        logger.info(f"[{job_id}] ✓ UPLOAD PROCESSING COMPLETED SUCCESSFULLY")
        logger.info(f"[{job_id}] Summary:")
        logger.info(f"[{job_id}]   - File Size: {size:,} bytes ({size / (1024*1024):.2f} MB)")
        logger.info(f"[{job_id}]   - Extracted: {extracted_chars:,} characters")
        logger.info(f"[{job_id}]   - Cleaned: {cleaned_chars:,} characters")
        logger.info(f"[{job_id}]   - Chunks Created: {chunks_created}")
        logger.info(f"[{job_id}]   - Chunks Indexed: {chunks_indexed}")
        logger.info(f"[{job_id}]   - Vectors Generated & Stored: {vectors_generated}")
        logger.info(f"[{job_id}]   - Embedding Dimension: {settings.EMBEDDING_DIM}")
        logger.info(f"[{job_id}] ========================================")
        
        return result
        
    except Exception as exc:
        error_msg = f"Upload processing failed: {exc}"
        errors.append(error_msg)
        result["status"] = "failed"
        result["error"] = error_msg
        result["verification_checks"] = verification_checks
        logger.error(f"[{job_id}] ✗ FATAL ERROR: {error_msg}", exc_info=True)
        return result
