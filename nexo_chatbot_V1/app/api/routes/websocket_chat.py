import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.models.schemas import Intent, IntentResult, ChatRequest
from app.services.connection_manager import manager
from app.services.intent_classifier import intent_classifier
from app.services.llm_generator import llm_generator
from app.services.orchestrator import orchestrator
from app.services.mongodb import mongo_service
from app.utils.encryption import encrypt
from app.config.settings import get_settings
from app.utils.logger import logger

router = APIRouter(prefix="/v1", tags=["websocket"])
settings = get_settings()

# Active generation tasks — keyed by session_id for cancellation support
_generation_tasks: dict = {}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/web_chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """
    Real-time streaming chat over WebSocket.

    Client → server (JSON):
      {"question": "<query>", "query_time": "<iso-string>"}

    Server → client:
      {"status": "connected"}                        — on connect
      {"type": "status",    "message": "processing"} — before generation
      {"type": "stream",    "token": "<text>"}        — streamed tokens
      {"type": "final",
       "message":       "<full response>",
       "answer_time":   "<iso-string>",
       "input_tokens":  <int>,
       "output_tokens": <int>}
      {"type": "cancelled", "message": "<partial>", "answer_time": "<iso>"}
      {"type": "error",     "message": "<detail>"}
    """
    await manager.connect(session_id, websocket)
    disconnect_task = None

    try:
        # ── Auto-disconnect after inactivity ──────────────────────────────────
        async def _auto_disconnect():
            await asyncio.sleep(settings.WS_TIMEOUT_SECONDS)
            await manager.send(session_id, {"type": "error", "message": "WebSocket session timed out."})
            if manager.is_connected(session_id):
                await websocket.close()
                manager.disconnect(session_id)

        disconnect_task = asyncio.create_task(_auto_disconnect())

        # ── On-connect confirmation ────────────────────────────────────────────
        await manager.send(session_id, {"status": "connected"})

        while True:
            raw = await websocket.receive_text()

            # Reset inactivity timer on each message
            if disconnect_task:
                disconnect_task.cancel()
            disconnect_task = asyncio.create_task(_auto_disconnect())

            # ── Parse client message ──────────────────────────────────────────
            try:
                request_data = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(session_id, {"type": "error", "message": "Invalid JSON format"})
                continue

            query      = (request_data.get("question") or request_data.get("message", "")).strip()
            query_time = request_data.get("query_time", datetime.utcnow().isoformat())

            if not query:
                await manager.send(session_id, {"type": "error", "message": "Question is empty"})
                continue

            logger.info(f"WS query session={session_id}: {query[:80]}")

            # ── Status ────────────────────────────────────────────────────────
            await manager.send(session_id, {"type": "status", "message": "processing"})

            # ── Intent classification ─────────────────────────────────────────
            try:
                intent_result = await intent_classifier.classify(query)
            except Exception as exc:
                logger.warning(f"Intent classification failed: {exc}")
                intent_result = IntentResult(
                    intent=Intent.GENERAL, confidence=0.5, rewritten_query=query
                )

            logger.info(f"Intent: {intent_result.intent} confidence={intent_result.confidence:.2f}")

            # ── Fetch conversation history ─────────────────────────────────
            conversation_history = []
            try:
                conversation_history = await mongo_service.get_conversation_history(session_id)
                logger.info(f"History fetched: {len(conversation_history)} turns for session={session_id}")
            except Exception as exc:
                logger.warning(f"Could not fetch conversation history: {exc}")

            # ── Generation ────────────────────────────────────────────────────
            full_response = ""
            input_tokens  = 0
            output_tokens = 0
            answer_time   = datetime.utcnow().replace(tzinfo=timezone.utc)

            try:
                if intent_result.intent == Intent.WEB:
                    async for token in llm_generator.generate_stream_with_search(
                        query=query, conversation_history=conversation_history
                    ):
                        full_response += token
                        await manager.send(session_id, {"type": "stream", "token": token})

                elif intent_result.intent == Intent.DOMAIN:
                    domain_chunks = await orchestrator._retrieve_domain(intent_result.rewritten_query)
                    top_score     = domain_chunks[0].score if domain_chunks else 0.0
                    is_confident  = (
                        bool(domain_chunks)
                        and top_score >= settings.SIMILARITY_THRESHOLD
                        and intent_result.confidence >= 0.60
                    )
                    stream_fn = (
                        llm_generator.generate_stream(
                            query=query, domain_chunks=domain_chunks,
                            conversation_history=conversation_history,
                        )
                        if is_confident else
                        llm_generator.generate_stream_with_search(
                            query=query, domain_chunks=domain_chunks,
                            conversation_history=conversation_history,
                        )
                    )
                    async for token in stream_fn:
                        full_response += token
                        await manager.send(session_id, {"type": "stream", "token": token})

                else:  # GENERAL
                    async for token in llm_generator.generate_stream(
                        query=query,
                        conversation_history=conversation_history,
                        require_context=False,
                    ):
                        full_response += token
                        await manager.send(session_id, {"type": "stream", "token": token})

                answer_time = datetime.utcnow().replace(tzinfo=timezone.utc)

            except asyncio.CancelledError:
                answer_time = datetime.utcnow().replace(tzinfo=timezone.utc)
                await manager.send(session_id, {
                    "type": "cancelled",
                    "message": full_response.strip(),
                    "answer_time": str(answer_time),
                })
                _generation_tasks.pop(session_id, None)
                continue

            except Exception as exc:
                logger.error(f"Generation error session={session_id}: {exc}", exc_info=True)
                await manager.send(session_id, {"type": "error", "message": str(exc)})
                _generation_tasks.pop(session_id, None)
                continue

            _generation_tasks.pop(session_id, None)

            # ── MongoDB persist ────────────────────────────────────────────────
            try:
                await mongo_service.save_chat(
                    session_id=session_id,
                    encrypted_query=encrypt(query, settings.ENCRYPTION_KEY),
                    encrypted_response=encrypt(full_response, settings.ENCRYPTION_KEY),
                )
            except Exception as exc:
                logger.warning(f"MongoDB save failed (non-fatal): {exc}")

            # ── Final result ───────────────────────────────────────────────────
            await manager.send(session_id, {
                "type":         "final",
                "message":      full_response.strip(),
                "answer_time":  str(answer_time),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })

    except WebSocketDisconnect:
        logger.info(f"WS client disconnected: session={session_id}")
    except Exception as exc:
        logger.error(f"WS fatal error session={session_id}: {exc}", exc_info=True)
    finally:
        if disconnect_task:
            disconnect_task.cancel()
        task = _generation_tasks.pop(session_id, None)
        if task:
            task.cancel()
        manager.disconnect(session_id)
