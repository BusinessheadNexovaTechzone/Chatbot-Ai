from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from app.models.schemas import ChatRequest, ChatResponse, IngestRequest, IngestResponse, Intent
from app.services.orchestrator import orchestrator
from app.services.intent_classifier import intent_classifier
from app.services.llm_generator import llm_generator
from app.utils.logger import logger
from app.utils.translation import detect_language, translate_text
from app.ingestion.pipeline import run_ingestion_pipeline
import time

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint.

    Frontend sends: { query, session_id, stream }
    Conversation history is fetched server-side from MongoDB using session_id.

    Routing:
      - web intent    → external web search grounding
      - domain intent → Vector DB retrieval; search fallback if low confidence
      - general intent → LLM direct
    """
    try:
        if request.stream:
            raise HTTPException(status_code=400, detail="Use /chat/stream for streaming responses")

        detected_language = detect_language(request.query)
        response = await orchestrator.handle(request)
        response.session_id = request.session_id
        response.detected_language = detected_language

        if detected_language != "en":
            try:
                response.answer = translate_text(response.answer, detected_language)
            except Exception as exc:
                logger.warning(
                    f"Translation failed for detected language {detected_language}: {exc}"
                )

        return response
    except Exception as exc:
        logger.error(f"Chat error: {exc}", exc_info=True)
        error_text = str(exc).lower()
        if any(keyword in error_text for keyword in [
            "invalid api key",
            "invalid key",
            "unauthorized",
            "authentication",
            "401",
        ]):
            raise HTTPException(
                status_code=401,
                detail="Language model authentication failed. Check GEMINI_API_KEY in .env.",
            )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming chat via Server-Sent Events.

    Frontend sends: { query, session_id, stream: true }
    Conversation history is fetched server-side from MongoDB using session_id.
    """
    async def generate():
        try:
            # Fetch conversation history server-side
            conversation_history = []
            if request.session_id:
                try:
                    from app.services.mongodb import mongo_service
                    conversation_history = await mongo_service.get_conversation_history(
                        request.session_id
                    )
                except Exception as e:
                    logger.warning(f"Could not fetch conversation history: {e}")

            intent_result = await intent_classifier.classify(request.query)
            full_response = ""

            if intent_result.intent == Intent.WEB:
                async for token in llm_generator.generate_stream_with_search(
                    query=request.query,
                    assistant_name=request.assistant_name,
                    conversation_history=conversation_history,
                ):
                    full_response += token
                    yield f"data: {token}\n\n"
                if request.session_id:
                    try:
                        from app.services.mongodb import mongo_service
                        from app.utils.encryption import encrypt
                        from app.config.settings import get_settings

                        cfg = get_settings()
                        await mongo_service.save_chat(
                            session_id=request.session_id,
                            encrypted_query=encrypt(request.query, cfg.ENCRYPTION_KEY),
                            encrypted_response=encrypt(full_response, cfg.ENCRYPTION_KEY),
                        )
                    except Exception as e:
                        logger.warning(f"Could not save streamed chat history: {e}")
                yield "data: [DONE]\n\n"

            elif intent_result.intent == Intent.DOMAIN:
                from app.config.settings import get_settings
                cfg           = get_settings()
                domain_chunks = await orchestrator._retrieve_domain(intent_result.rewritten_query)
                top_score     = domain_chunks[0].score if domain_chunks else 0.0
                is_confident  = (
                    bool(domain_chunks)
                    and top_score >= cfg.SIMILARITY_THRESHOLD
                    and intent_result.confidence >= 0.60
                )

                if is_confident:
                    async for token in llm_generator.generate_stream(
                        query=request.query,
                        assistant_name=request.assistant_name,
                        domain_chunks=domain_chunks,
                        conversation_history=conversation_history,
                    ):
                        full_response += token
                        yield f"data: {token}\n\n"
                else:
                    async for token in llm_generator.generate_stream_with_search(
                        query=request.query,
                        assistant_name=request.assistant_name,
                        domain_chunks=domain_chunks,
                        conversation_history=conversation_history,
                    ):
                        full_response += token
                        yield f"data: {token}\n\n"
                if request.session_id:
                    try:
                        from app.services.mongodb import mongo_service
                        from app.utils.encryption import encrypt
                        await mongo_service.save_chat(
                            session_id=request.session_id,
                            encrypted_query=encrypt(request.query, cfg.ENCRYPTION_KEY),
                            encrypted_response=encrypt(full_response, cfg.ENCRYPTION_KEY),
                        )
                    except Exception as e:
                        logger.warning(f"Could not save streamed chat history: {e}")
                yield "data: [DONE]\n\n"

            else:  # GENERAL
                async for token in llm_generator.generate_stream(
                    query=request.query,
                    assistant_name=request.assistant_name,
                    conversation_history=conversation_history,
                    require_context=False,
                ):
                    full_response += token
                    yield f"data: {token}\n\n"
                if request.session_id:
                    try:
                        from app.services.mongodb import mongo_service
                        from app.utils.encryption import encrypt
                        from app.config.settings import get_settings

                        cfg = get_settings()
                        await mongo_service.save_chat(
                            session_id=request.session_id,
                            encrypted_query=encrypt(request.query, cfg.ENCRYPTION_KEY),
                            encrypted_response=encrypt(full_response, cfg.ENCRYPTION_KEY),
                        )
                    except Exception as e:
                        logger.warning(f"Could not save streamed chat history: {e}")
                yield "data: [DONE]\n\n"

        except Exception as exc:
            logger.error(f"Stream error: {exc}", exc_info=True)
            yield f"data: [ERROR] {str(exc)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest, background_tasks: BackgroundTasks) -> IngestResponse:
    """Scrape websites and index content into the vector database."""
    try:
        return await run_ingestion_pipeline(request)
    except Exception as exc:
        logger.error(f"Ingestion error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(exc)}")
