import re
import time
import asyncio
from typing import List
from app.config.settings import get_settings
from app.models.schemas import (
    Intent, IntentResult, DocumentChunk, ChatRequest, ChatResponse,
    Citation, TokenUsage,
)
from app.services.intent_classifier import intent_classifier
from app.services.cache import cache_service
from app.services.llm_generator import llm_generator, _build_rag_citations
from app.services.query_processor import query_processor  # NEW: Query rewriting & spelling
from app.retrieval.vector_store import vector_store
from app.retrieval.embeddings import embedding_service
from app.retrieval.reranker import reranker
from app.retrieval.bm25_search import bm25_search  # NEW: BM25 keyword search
from app.utils.logger import logger
from app.utils.metrics import track_latency

settings = get_settings()


class RetrievalOrchestrator:

    def _is_direct_extractable_query(self, query: str) -> bool:
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in ['ceo', 'company name', 'headquarters', 'website', 'contact', 'address', 'email', 'phone', 'founded', 'location', 'office', 'telephone', 'products'])

    def _is_business_inquiry_query(self, query: str) -> bool:
        """Detect if query is a business inquiry (pricing, timeline, negotiation, etc.)"""
        inquiry_keywords = [
            'cost', 'price', 'pricing', 'budget', 'rate', 'quote',
            'days', 'timeline', 'deadline', 'how long', 'how much',
            'payment', 'plan', 'package', 'discount', 'offer',
            'negotiate', 'bargain', 'deal', 'contract', 'agreement',
            'customization', 'custom', 'specific requirement', 'requirement',
            'can you', 'will you', 'can i', 'will i', 'would you',
            'availability', 'available', 'support', 'maintenance',
            'license', 'licensing', 'subscription', 'onboarding',
            'training', 'deployment', 'implementation', 'setup',
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in inquiry_keywords)

    def _is_generic_fallback_answer(self, answer: str) -> bool:
        if not answer:
            return False
        normalized = answer.strip().lower()
        fallback_indicators = [
            'not available',
            'does not mention',
            'no relevant',
            'i do not have',
            'cannot answer',
            'i don\'t have',
            'not present in',
            'insufficient information',
            'could not find',
            'not found',
        ]
        return any(indicator in normalized for indicator in fallback_indicators)

    def _get_contact_details_response(self) -> str:
        """Return contact details for business inquiries"""
        return """For business inquiries, pricing, timelines, or custom requirements, please reach out to our team:

📧 Email: businesshead@nexovatechzone.com
📞 Phone: +91 7810001706

Our team will be happy to discuss your specific needs, provide quotes, and create customized solutions within your timeline and budget.

Office: NexovaTechzone, Head Office No1/2 Dharmambal Palaniappan Complex, First Floor, Mount Poonamallee Rd, Ramapuram, Chennai - 600089"""

    def _query_has_domain_signals(self, query: str) -> bool:
        domain_signals = [
            "website",
            "link",
            "contact",
            "address",
            "phone",
            "email",
            "company",
            "product",
            "service",
            "pricing",
            "policy",
            "ceo",
            "team",
            "about",
            "founded",
            "headquarters",
        ]
        query_lower = query.lower()
        return any(signal in query_lower for signal in domain_signals)

    def _is_simple_greeting(self, query: str) -> bool:
        if not query:
            return False
        normalized = re.sub(r"[^a-zA-Z0-9\s']", "", query.lower()).strip()
        if not normalized:
            return False
        greetings = [
            "hello",
            "hi",
            "hey",
            "greetings",
            "how are you",
            "how are you doing",
            "what's up",
            "whats up",
            "good morning",
            "good afternoon",
            "good evening",
            "hey there",
            "hi there",
        ]
        return any(normalized == phrase or normalized.startswith(phrase + " ") for phrase in greetings)

    def _query_uses_non_english_text(self, query: str) -> bool:
        # Detect non-ASCII script usage (Hindi, Arabic, Chinese, Cyrillic, etc.)
        return bool(re.search(r"[^\x00-\x7F]", query))

    async def _translate_if_needed(self, answer: str, query: str) -> str:
        if not answer or not query:
            return answer
        if self._query_uses_non_english_text(query):
            try:
                logger.info(f"Translating answer to query language. Query: {query}, Answer: {answer}")
                translated = await llm_generator.translate_to_query_language(answer, query)
                logger.info(f"Translated answer: {translated}")
                return translated
            except Exception as exc:
                logger.warning(f"Translation fallback failed: {exc}")
        return answer

    async def _translate_query_for_retrieval(self, query: str) -> str:
        if not query or not self._query_uses_non_english_text(query):
            return query
        try:
            translated = await llm_generator.translate_query_to_english(query)
            if translated and translated != query:
                return translated
            if "ceo" in query.lower():
                return "Who is the CEO?"
            return query
        except Exception as exc:
            logger.warning(f"Query translation to English failed: {exc}")
            if "ceo" in query.lower():
                return "Who is the CEO?"
            return query

    async def handle(self, request: ChatRequest) -> ChatResponse:
        t_start = time.perf_counter()
        
        # ✅ NEW: Process query for spelling correction and normalization
        original_query = request.query
        _, processed_query, was_query_modified = query_processor.process_query(request.query)
        use_uploaded_docs = request.use_uploaded_docs if request.use_uploaded_docs is not None else True

        cache_prefix = "response_docs" if use_uploaded_docs else "response_no_docs"

        # ✅ FAST CACHE READ (using processed query for better hit rates)
        try:
            cached = await cache_service.get(cache_prefix, processed_query)
        except Exception as e:
            logger.warning(f"Cache GET failed: {e}")
            cached = None

        if cached:
            if self._is_direct_extractable_query(processed_query) and self._is_generic_fallback_answer(cached.get("answer", "")):
                logger.info("Bypassing stale cached fallback for direct-extractable query")
                cached = None
            else:
                logger.info("Cache HIT — returning cached response")
                cached["cached"] = True
                return ChatResponse(**cached)

        if not use_uploaded_docs:
            logger.info("use_uploaded_docs is false: answering from Gemini AI instead of uploaded documents")
            async with track_latency("llm_generation"):
                answer, citations, token_usage = await llm_generator.generate(
                    query=request.query,
                    assistant_name=request.assistant_name,
                    conversation_history=[],
                    require_context=False,
                )
            answer = await self._translate_if_needed(answer, request.query)
            latency_ms = (time.perf_counter() - t_start) * 1000
            response = ChatResponse(
                answer=answer,
                assistant_name=request.assistant_name,
                intent=Intent.GENERAL,
                sources=citations,
                confidence=1.0,
                latency_ms=round(latency_ms, 2),
                cached=False,
                token_usage=token_usage,
                session_id=request.session_id,
                detected_language="en",
            )
            try:
                await cache_service.set(cache_prefix, processed_query, response.model_dump())
            except Exception as e:
                logger.warning(f"Cache SET failed: {e}")
            return response

        if self._is_simple_greeting(processed_query):
            logger.info("Detected simple greeting — returning canned response")
            latency_ms = (time.perf_counter() - t_start) * 1000
            return ChatResponse(
                answer="Hello! How can I help you today?",
                assistant_name=request.assistant_name,
                intent=Intent.GENERAL,
                sources=[],
                confidence=1.0,
                latency_ms=round(latency_ms, 2),
                cached=False,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0),
                session_id=request.session_id,
                detected_language="en",
            )

        # ✅ NEW: Detect business inquiries and return contact details
        if self._is_business_inquiry_query(processed_query):
            logger.info(f"Detected business inquiry query: {processed_query}")
            latency_ms = (time.perf_counter() - t_start) * 1000
            return ChatResponse(
                answer=self._get_contact_details_response(),
                assistant_name=request.assistant_name,
                intent=Intent.GENERAL,
                sources=[],
                confidence=1.0,
                latency_ms=round(latency_ms, 2),
                cached=False,
                token_usage=TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0),
                session_id=request.session_id,
                detected_language="en",
            )

        # SKIP MongoDB history for speed — use empty history
        # History slows down queries by 2+ seconds; skip it to respond faster
        conversation_history: List[dict] = []
        
        # Initialize variables
        answer = ""
        citations: List[Citation] = []
        token_usage: TokenUsage = None
        direct_answer: str | None = None
        retrieval_query = processed_query  # Use processed query for retrieval

        # ✅ Intent classification
        async with track_latency("intent_classification"):
            intent_result = await intent_classifier.classify(processed_query)

        # ✅ Domain retrieval if needed
        domain_chunks = []
        if intent_result.intent == Intent.DOMAIN or self._query_has_domain_signals(processed_query):
            async with track_latency("domain_retrieval"):
                domain_chunks = await self._retrieve_domain(processed_query, skip_rerank=self._is_direct_extractable_query(processed_query))

        if intent_result.intent == Intent.GENERAL and self._query_has_domain_signals(processed_query):
            logger.info("General intent but query contains domain signals; attempting domain retrieval.")
            # domain_chunks already retrieved
            top_score = domain_chunks[0].score if domain_chunks else 0.0
            if domain_chunks and top_score >= settings.SIMILARITY_THRESHOLD:
                intent_result = IntentResult(
                    intent=Intent.DOMAIN,
                    confidence=max(intent_result.confidence, 0.65),
                    rewritten_query=request.query,
                )
                logger.info(
                    "Promoted query to domain intent based on retrieval results",
                    extra={"top_score": top_score},
                )

        if ("ceo" in request.query.lower() or self._is_company_name_query(request.query)) and not direct_answer and domain_chunks:
            direct_answer = await self._extract_direct_answer_from_chunks(request.query, domain_chunks)
            if direct_answer:
                direct_answer = self._build_direct_answer_for_translation(direct_answer, request.query)
                answer = await self._translate_if_needed(direct_answer, request.query)
                citations = _build_rag_citations(domain_chunks)
                token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                logger.info("Extracted direct answer from domain chunks before generation")

        try:
            # 🚀 ROUTING LOGIC

            if intent_result.intent == Intent.WEB:
                async with track_latency("web_search"):
                    answer, citations, token_usage = await llm_generator.generate_with_search(
                        query=request.query,
                        assistant_name=request.assistant_name,
                        conversation_history=conversation_history,
                    )

            elif intent_result.intent == Intent.DOMAIN:
                # domain_chunks already retrieved in parallel; reuse it
                # Try direct extraction for all domain queries first
                if not direct_answer and domain_chunks and self._is_direct_extractable_query(request.query):
                    direct_answer = await self._extract_direct_answer_from_chunks(request.query, domain_chunks)
                    if direct_answer:
                        direct_answer = self._build_direct_answer_for_translation(direct_answer, request.query)
                        answer = await self._translate_if_needed(direct_answer, request.query)
                        citations = _build_rag_citations(domain_chunks)
                        token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                        logger.info("Extracted direct answer from domain chunks before generation")

                if not direct_answer:
                    if domain_chunks:
                        async with track_latency("llm_generation"):
                            answer, citations, token_usage = await llm_generator.generate(
                                query=request.query,
                                assistant_name=request.assistant_name,
                                domain_chunks=domain_chunks,
                                conversation_history=conversation_history,
                                require_context=True,
                            )
                    else:
                        logger.info("No domain chunks available, falling back to search")
                        async with track_latency("search_fallback"):
                            answer, citations, token_usage = await llm_generator.generate_with_search(
                                query=request.query,
                                assistant_name=request.assistant_name,
                                conversation_history=conversation_history,
                            )

            else:  # GENERAL
                if domain_chunks and self._query_has_domain_signals(processed_query):
                    async with track_latency("llm_generation"):
                        answer, citations, token_usage = await llm_generator.generate(
                            query=request.query,
                            assistant_name=request.assistant_name,
                            domain_chunks=domain_chunks,
                            conversation_history=conversation_history,
                            require_context=True,
                        )
                else:
                    async with track_latency("llm_generation"):
                        answer, citations, token_usage = await llm_generator.generate(
                            query=request.query,
                            assistant_name=request.assistant_name,
                            conversation_history=conversation_history,
                            require_context=False,
                        )

        except Exception as e:
            logger.error(f"LLM generation failed: {e}", exc_info=True)
            direct_answer = await self._extract_direct_answer_from_chunks(request.query, domain_chunks)
            if direct_answer:
                direct_answer = self._build_direct_answer_for_translation(direct_answer, request.query)
                answer = await self._translate_if_needed(direct_answer, request.query)
                citations = _build_rag_citations(domain_chunks)
                token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                logger.info("Using direct answer extracted from domain chunks")
            else:
                if intent_result.intent == Intent.DOMAIN and domain_chunks:
                    logger.info("LLM generation failed for domain query, falling back to search")
                    try:
                        answer, citations, token_usage = await llm_generator.generate_with_search(
                            query=request.query,
                            assistant_name=request.assistant_name,
                            domain_chunks=domain_chunks,
                            conversation_history=conversation_history,
                            require_context=False,
                        )
                    except Exception as e2:
                        logger.error(f"Search fallback also failed: {e2}")
                        answer = "The requested information is not available in the provided documents."
                        citations = []
                        token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                else:
                    # Fallback: do not return raw domain chunks to avoid dumping context
                    answer = "The requested information is not available in the provided documents."
                    citations = []
                    token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                    logger.info("Using fallback response due to generation failure")

        answer = await self._translate_if_needed(answer, request.query)
        latency_ms = (time.perf_counter() - t_start) * 1000

        response = ChatResponse(
            answer=answer,
            assistant_name=request.assistant_name,
            intent=intent_result.intent,
            sources=citations,
            confidence=intent_result.confidence,
            latency_ms=round(latency_ms, 2),
            cached=False,
            token_usage=token_usage,
        )

        # ✅ SAFE CACHE WRITE
        try:
            if not self._is_generic_fallback_answer(response.answer):
                await cache_service.set(cache_prefix, processed_query, response.model_dump())
            else:
                logger.info("Skipping cache write for generic fallback response")
        except Exception as e:
            logger.warning(f"Cache SET failed: {e}")

        # ✅ FIRE-AND-FORGET Mongo save (don't block response)
        if request.session_id:
            try:
                from app.services.mongodb import mongo_service
                from app.utils.encryption import encrypt
                # Don't await — save in background
                asyncio.create_task(
                    mongo_service.save_chat(
                        session_id=request.session_id,
                        encrypted_query=encrypt(request.query, settings.ENCRYPTION_KEY),
                        encrypted_response=encrypt(answer, settings.ENCRYPTION_KEY),
                        token_usage=token_usage.model_dump() if token_usage else None,
                    )
                )
            except Exception as e:
                logger.warning(f"Mongo save background task failed: {e}")

        return response

    # ───────────────────────────────────────────────
    # DOMAIN RETRIEVAL (SAFE VERSION)
    # ───────────────────────────────────────────────

    def _is_company_name_query(self, query: str) -> bool:
        if not query:
            return False
        lower_query = query.lower()
        return (
            "company name" in lower_query
            or "business name" in lower_query
            or "name of the company" in lower_query
            or ("name" in lower_query and "company" in lower_query)
            or ("name" in lower_query and "business" in lower_query)
        )

    def _build_direct_answer_for_translation(self, direct_answer: str, query: str) -> str:
        if not direct_answer:
            return direct_answer

        lower_query = query.lower()
        if self._is_company_name_query(query):
            return f"The company name is {direct_answer}"
        if "ceo" in lower_query or "chief executive officer" in lower_query or "யார்" in lower_query:
            return f"The CEO is {direct_answer}."
        return direct_answer

    async def _extract_direct_answer_from_chunks(self, query: str, chunks: List[DocumentChunk]) -> str | None:
        if not chunks:
            return None

        lower_query = query.lower()
        if self._is_company_name_query(query):
            logger.info(f"Attempting direct company name extraction for query: {query}")
            patterns = [
                r"\bCompany Name\b\s*[:\-–]?\s*([A-Z][A-Za-z0-9&\.\-\s]{2,200}?)\b(?:$|\n|,|;)",
                r"\bName of the Company\b\s*[:\-–]?\s*([A-Z][A-Za-z0-9&\.\-\s]{2,200}?)\b(?:$|\n|,|;)",
                r"\bCompany\s+Name\b\s*[:\-–]?\s*([A-Z][A-Za-z0-9&\.\-\s]{2,200}?)\b(?:$|\n|,|;)",
                r"^([A-Z][A-Za-z0-9&\.\-\s]+?(?:Pvt\. Ltd\.|Private Limited|LLC|Inc\.|Ltd\.|Limited|Corporation|Corp\.|Company|Technologies|Solutions|Systems))\b",
                r"^([A-Z][A-Za-z0-9&\.\-\s]+?)\s+is\s+(?:a|an)\b",
            ]
            for chunk in chunks:
                text = chunk.content.strip()
                logger.info(f"Checking chunk content for company name: {text[:200]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
                    if match:
                        extracted = match.group(1).strip()
                        logger.info(f"Extracted company name: {extracted} using pattern: {pat}")
                        return extracted
                for line in text.splitlines():
                    if 'company name' in line.lower() or 'name of the company' in line.lower():
                        match = re.search(r"(?:Company Name|Name of the Company)\s*[:\-–]?\s*(.+)$", line, flags=re.IGNORECASE)
                        if match:
                            extracted = match.group(1).strip()
                            logger.info(f"Extracted company name from line: {extracted}")
                            return extracted
                first_line = text.splitlines()[0] if text.splitlines() else ""
                if first_line:
                    match = re.match(r"^([A-Z][A-Za-z0-9&\.\-\s]+?)\s+is\s+(?:a|an)\b", first_line)
                    if match:
                        extracted = match.group(1).strip()
                        logger.info(f"Extracted company name from first line: {extracted}")
                        return extracted

        if "ceo" in lower_query or "chief executive officer" in lower_query or "யார்" in lower_query:
            logger.info(f"Attempting direct CEO extraction for query: {query}")
            patterns = [
                r"^\s*CEO\s*[:\-–]?\s*(?:is\s*)?([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})\s*$",
                r"^\s*Chief Executive Officer\s*[:\-–]?\s*(?:is\s*)?([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})\s*$",
                r"^\s*CEO\s*(?:is|:)\s*([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})\s*$",
                r"^\s*Chief Executive Officer\s*(?:is|:)\s*([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})\s*$",
                r"led by\s+([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})",
                r"headed by\s+([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})",
                r"managed by\s+([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})",
                r"([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})\s+is the CEO",
                r"([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})\s+is Chief Executive Officer",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk content: {text[:200]}...")
                text_clean = re.sub(r"\*+", "", text)
                for line in text_clean.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    for pat in patterns:
                        match = re.search(pat, line, flags=re.IGNORECASE)
                        if match:
                            extracted = match.group(1).strip()
                            logger.info(f"Extracted CEO name: {extracted} using pattern: {pat}")
                            return extracted
                for line in text_clean.splitlines():
                    if "ceo" in line.lower() or "chief executive officer" in line.lower():
                        match = re.search(
                            r"(?:ceo|chief executive officer)\s*[:\-–]?\s*(?:is\s*)?([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,3})",
                            line,
                            flags=re.IGNORECASE,
                        )
                        if match:
                            extracted = match.group(1).strip()
                            logger.info(f"Extracted CEO name from line: {extracted}")
                            return extracted

        if "founded" in lower_query or "year of establishment" in lower_query:
            logger.info(f"Attempting direct founded year extraction for query: {query}")
            patterns = [
                r"\bFounded\b\s*[:\-–]?\s*(\d{4})",
                r"\bEstablished\b\s*[:\-–]?\s*(\d{4})",
                r"\bIncorporated\b\s*[:\-–]?\s*(\d{4})",
                r"founded in\s+(\d{4})",
                r"established in\s+(\d{4})",
                r"launched in\s+(\d{4})",
                r"started in\s+(\d{4})",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for founded year: {text[:200]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE)
                    if match:
                        extracted = match.group(1).strip()
                        logger.info(f"Extracted founded year: {extracted} using pattern: {pat}")
                        return f"The company was founded in {extracted}."

        if "phone" in lower_query or "contact number" in lower_query or "telephone" in lower_query:
            logger.info(f"Attempting direct phone extraction for query: {query}")
            patterns = [
                r"\bPhone\b\s*[:\-–]?\s*(\+?[\d\s\-\(\)]{10,})",
                r"\bTelephone\b\s*[:\-–]?\s*(\+?[\d\s\-\(\)]{10,})",
                r"\bContact\b\s*[:\-–]?\s*(\+?[\d\s\-\(\)]{10,})",
                r"phone\s*(?:number|no\.?)\s*:?\s*(\+?[\d\s\-\(\)]{10,})",
                r"\+\d{1,3}[\d\s\-\(\)]{9,}",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for phone: {text[:200]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE)
                    if match:
                        extracted = match.group(1).strip() if match.lastindex else match.group(0).strip()
                        logger.info(f"Extracted phone: {extracted} using pattern: {pat}")
                        return f"The company phone number is {extracted}."

        if "email" in lower_query or "mail" in lower_query:
            logger.info(f"Attempting direct email extraction for query: {query}")
            patterns = [
                r"\bEmail\b\s*[:\-–]?\s*([\w\.\-]+@[\w\.\-]+\.\w+)",
                r"\bMail\b\s*[:\-–]?\s*([\w\.\-]+@[\w\.\-]+\.\w+)",
                r"email\s*(?:address|id)?\s*:?\s*([\w\.\-]+@[\w\.\-]+\.\w+)",
                r"([\w\.\-]+@[\w\.\-]+\.\w+)",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for email: {text[:200]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE)
                    if match:
                        extracted = match.group(1).strip()
                        logger.info(f"Extracted email: {extracted} using pattern: {pat}")
                        return f"The company email is {extracted}."

        if "address" in lower_query or "location" in lower_query or "office" in lower_query:
            logger.info(f"Attempting direct address extraction for query: {query}")
            patterns = [
                r"\bAddress\b\s*[:\-–]?\s*(.+?)(?:\n|$|\.(?:\s|$))",
                r"\bLocation\b\s*[:\-–]?\s*(.+?)(?:\n|$|\.(?:\s|$))",
                r"\bHeadquarters\b\s*[:\-–]?\s*(.+?)(?:\n|$|\.(?:\s|$))",
                r"(\d+.+?(?:Road|Street|Lane|Avenue|Boulevard|Plaza|Building|Floor).+?(?:India|City|Country))",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for address: {text[:300]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
                    if match:
                        extracted = match.group(1).strip()
                        logger.info(f"Extracted address: {extracted[:100]} using pattern: {pat}")
                        return f"The company address is: {extracted}"
        
        if "products" in lower_query:
            logger.info(f"Attempting direct products extraction for query: {query}")
            patterns = [
                r"## Our Products\s*(.+?)(?:##|$)",
                r"Our Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                r"Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for products: {text[:200]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
                    if match:
                        extracted = match.group(1).strip()
                        logger.info(f"Extracted products: {extracted} using pattern: {pat}")
                        return extracted
        
        logger.info("No direct answer extracted")
        return None

    async def _retrieve_domain(self, query: str, skip_rerank: bool = False) -> List[DocumentChunk]:

        logger.info(f"Domain retrieval for query: '{query}'")
        original_query = query.strip()
        expanded_query = original_query
        if len(original_query.split()) <= 2:
            expanded_query = (
                f"{original_query} concepts explanation definition examples information"
            )
            logger.info(f"Expanded query: '{expanded_query}'")

        # ✅ SAFE CACHE READ
        try:
            cached_docs = await cache_service.get("docs", original_query)
            if cached_docs:
                logger.info(f"Cache hit: {len(cached_docs)} cached chunks")
                # return [DocumentChunk(**d) for d in cached_docs]  # Commented out to test
        except Exception as e:
            logger.warning(f"Cache GET failed (docs): {e}")

        # ✅ EMBEDDING
        try:
            async with track_latency("embedding"):
                query_vector = await embedding_service.embed_query(original_query)
            logger.info(f"Query embedded successfully, vector length: {len(query_vector)}")
        except Exception as e:
            logger.error(f"Embedding failed: {e}", exc_info=True)
            return []

        # ✅ VECTOR SEARCH
        try:
            await vector_store.connect()
        except Exception as e:
            logger.error(f"❌ Failed to connect to vector store: {e}", exc_info=True)
            return []
        
        try:
            query_top_k = settings.TOP_K
            use_hybrid_search = self._is_direct_extractable_query(query) or len(original_query.split()) <= 2
            if use_hybrid_search:
                query_top_k = max(settings.TOP_K * 3, 6)
                async with track_latency("hybrid_search"):
                    chunks = await vector_store.search_with_text(
                        query=original_query,
                        query_vector=query_vector,
                        top_k=query_top_k,
                    )
            else:
                async with track_latency("vector_search"):
                    chunks = await vector_store.search(
                        query_vector=query_vector,
                        top_k=query_top_k,
                        score_threshold=settings.SIMILARITY_THRESHOLD,
                    )
            logger.info(f"Search returned {len(chunks)} chunks")
            if chunks:
                logger.info(f"Chunk scores: {[f'{c.score:.3f}' for c in chunks[:3]]}")
        except Exception as e:
            logger.error(f"Vector search failed: {e}", exc_info=True)
            return []

        if not chunks and expanded_query != original_query:
            logger.info("No relevant chunks from original query, retrying with expanded query")
            try:
                async with track_latency("embedding"):
                    expanded_vector = await embedding_service.embed_query(expanded_query)
                async with track_latency("vector_search"):
                    chunks = await vector_store.search_with_text(
                        query=expanded_query,
                        query_vector=expanded_vector,
                        top_k=settings.TOP_K * 2,
                    )
                logger.info(f"Expanded vector search returned {len(chunks)} chunks")
            except Exception as e:
                logger.error(f"Expanded query search failed: {e}", exc_info=True)
                return []

        # ✅ BM25 search for keyword matching
        if chunks:
            bm25_results = []
            try:
                async with track_latency("bm25_search"):
                    bm25_results = await bm25_search.search(
                        query=original_query,
                        top_k=settings.TOP_K * 2
                    )
                if bm25_results:
                    logger.info(f"BM25 search returned {len(bm25_results)} results")
                    # Incorporate BM25 scores into chunks
                    chunks = reranker.incorporate_bm25_scores(chunks, bm25_results)
            except Exception as e:
                logger.warning(f"BM25 search failed (non-blocking): {e}")
            
            # ✅ Enhanced reranking with hybrid scoring
            try:
                async with track_latency("enhanced_reranking"):
                    chunks = await reranker.rerank(
                        query=original_query,
                        chunks=chunks,
                        top_n=settings.RERANK_TOP_N,
                        use_cross_encoder=True,
                        use_hybrid=True
                    )
                logger.info(f"Enhanced reranking completed: {len(chunks)} chunks returned")
            except Exception as e:
                logger.warning(f"Enhanced reranking failed (continuing): {e}")

            # Filter chunks for specific queries to improve accuracy
            chunks = self._filter_chunks_by_relevance(query, chunks)

            # Clean the content of retrieved chunks to remove unwanted text
            from app.ingestion.cleaner import clean_text
            for chunk in chunks:
                chunk.content = clean_text(chunk.content)

            # ✅ SAFE CACHE WRITE
            try:
                await cache_service.set(
                    "docs", original_query, [c.model_dump() for c in chunks], ttl=600
                )
            except Exception as e:
                logger.warning(f"Cache SET failed (docs): {e}")

        return chunks

    def _filter_chunks_by_relevance(self, query: str, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """Filter chunks to prioritize the most relevant sections for specific queries."""
        if not chunks:
            return chunks

        query_lower = query.lower().strip()

        # Define section mappings for specific queries
        section_mappings = {
            'headquarters': ['headquarters'],
            'headquarter': ['headquarters'],
            'location': ['headquarters'],
            'address': ['headquarters'],
            'office': ['headquarters'],
            'offices': ['headquarters'],
            'employees': ['employees'],
            'staff': ['employees'],
            'team': ['employees'],
            'people': ['employees'],
            'website': ['contact information'],
            'contact': ['contact information'],
            'email': ['contact information'],
            'phone': ['contact information'],
            'mission': ['mission and vision'],
            'vision': ['mission and vision'],
            'leadership': ['leadership'],
            'ceo': ['leadership'],
            'executive': ['leadership'],
            'management': ['leadership'],
            'services': ['core services'],
            'achievements': ['achievements and recognition'],
            'awards': ['achievements and recognition'],
            'recognition': ['achievements and recognition'],
            'certifications': ['achievements and recognition'],
            'company name': ['company overview', 'about us'],
            'business name': ['company overview', 'about us'],
            'about us': ['company overview', 'about us'],
            'about': ['company overview', 'about us'],
            'company': ['company overview', 'about us'],
        }

        # Check if query matches a specific section
        target_sections = []
        for keyword, sections in section_mappings.items():
            if keyword in query_lower:
                target_sections.extend(sections)
                target_sections.append('main')  # Always include main sections for broader coverage
                break

        if target_sections:
            # Filter to only include chunks from target sections
            filtered_chunks = []
            for chunk in chunks:
                if chunk.section and any(target.lower() in chunk.section.lower() for target in target_sections):
                    filtered_chunks.append(chunk)
                    break  # Only take the first matching chunk for precision

            # If we found a matching section chunk, return only that
            if filtered_chunks:
                logger.info(f"Filtered to {len(filtered_chunks)} chunk(s) from section(s): {target_sections}")
                return filtered_chunks

            # Fallback: if section not found, choose the best chunk by content overlap
            query_words = set(re.findall(r"\w+", query_lower))
            fallback = []
            for chunk in chunks:
                content_words = set(re.findall(r"\w+", chunk.content.lower()))
                overlap = len(query_words & content_words) / max(len(query_words), 1)
                if overlap > 0:
                    fallback.append((overlap, chunk))
            if fallback:
                fallback.sort(key=lambda x: x[0], reverse=True)
                logger.info("Fallback to best-matching chunk by content for specific query")
                return [fallback[0][1]]

        # For general queries, return all chunks to ensure full document coverage
        return chunks


orchestrator = RetrievalOrchestrator()