import re
import time
import json
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
from app.services.web_search import web_search_service
from app.services.query_processor import query_processor  # NEW: Query rewriting & spelling
from app.retrieval.vector_store import vector_store
from app.retrieval.embeddings import embedding_service
from app.retrieval.reranker import reranker
from app.retrieval.bm25_search import bm25_search  # NEW: BM25 keyword search
from app.utils.logger import logger
from app.utils.metrics import track_latency

settings = get_settings()


class RetrievalOrchestrator:
    _fast_payload_cache: dict | None = None

    async def _load_cached_payloads(self, payload_path: str) -> dict | None:
        if self._fast_payload_cache is not None:
            return self._fast_payload_cache
        from pathlib import Path
        p = Path(payload_path)
        if not p.exists():
            return None

        def _load():
            with open(p, "r", encoding="utf-8") as fp:
                return json.load(fp)

        try:
            self._fast_payload_cache = await asyncio.to_thread(_load)
            return self._fast_payload_cache
        except Exception as exc:
            logger.warning(f"Failed to load TurboVec payloads for fast extract: {exc}")
            return None

    def _expand_query_variants(self, query: str) -> List[str]:
        """Generate semantic variants of the query for parallel multi-search.
        This makes TurboVec's speed advantage visible by multiplying searches.
        
        Example: "tell about company?" → [
            "tell about company",
            "company products services",
            "company overview information"
        ]
        """
        query_lower = query.lower().strip()
        # If TurboVec fast mode is enabled, avoid generating extra variants
        # to keep embedding + search latency minimal.
        try:
            from app.config.settings import get_settings
            if get_settings().TURBOVEC_FAST_MODE:
                return [query_lower]
        except Exception:
            pass

        variants = [query_lower]  # Original query
        
        # Company/About queries
        if any(kw in query_lower for kw in ['company', 'about', 'tell', 'overview', 'what does', 'who are you', 'business overview']):
            variants.append("company products services solutions")
            variants.append("company overview information details")

        # Product/Service queries
        elif any(kw in query_lower for kw in ['product', 'service', 'offer', 'offerings', 'provide']):
            variants.append("company products services solutions")
            variants.append("product offerings capabilities details")

        # Address/Location queries
        elif any(kw in query_lower for kw in ['address', 'location', 'office', 'headquarters', 'head office', 'where is', 'where are', 'visit', 'located']):
            variants.append("company address location headquarters")
            variants.append("office location contact information")

        # Team/Leadership queries
        elif any(kw in query_lower for kw in ['ceo', 'founder', 'team', 'leadership', 'founder', 'executive']):
            variants.append("company founder co-founder owner")
            variants.append("leadership experience background")

        # General history/about short queries
        elif any(kw in query_lower for kw in ['founded', 'established', 'started', 'year']):
            variants.append("company history founding year")
            variants.append("company origin establishment details")
        
        # Default expansion for short queries
        elif len(query_lower.split()) <= 2:
            variants.append(f"{query_lower} details information")
            variants.append(f"{query_lower} explanation overview")
        
        return variants[:3]  # Limit to 3 variants to keep TurboVec speedup realistic

    def _is_direct_extractable_query(self, query: str) -> bool:
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in ['ceo', 'company name', 'headquarters', 'website', 'contact', 'address', 'email', 'phone', 'founded', 'location', 'office', 'telephone', 'products'])

    def _is_address_query(self, query: str) -> bool:
        if not query:
            return False
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in [
            'address', 'location', 'office', 'headquarters', 'head office',
            'visit', 'located', 'where is', 'where are', 'find you', 'company location',
        ])

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
            # transactional / procurement keywords
            'purchase', 'buy', 'procure', 'order', 'hire', 'build', 'develop', 'create',
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
        admin_email = getattr(settings, "ADMIN_CONTACT_EMAIL", None) or "businesshead@nexovatechzone.com"
        admin_phone = getattr(settings, "ADMIN_CONTACT_PHONE", None) or "+91 7810001706"
        return (
            "For business inquiries, pricing, timelines, or custom requirements, please reach out to our team:\n\n"
            f"📧 Email: {admin_email}\n"
            f"📞 Phone: {admin_phone}\n\n"
            "Our team will be happy to discuss your specific needs, provide quotes, and create customized solutions within your timeline and budget.\n\n"
            "Office: NexovaTechzone, Head Office No1/2 Dharmambal Palaniappan Complex, First Floor, Mount Poonamallee Rd, Ramapuram, Chennai - 600089"
        )

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

    async def _fast_local_extract(self, query: str) -> tuple[str, list] | None:
        """Fast local extraction from TurboVec payload JSON to avoid LLM calls.
        Returns (answer, citations) or None if not found.
        """
        from pathlib import Path
        payload_path = getattr(settings, "TURBOVEC_PAYLOAD_PATH", "turbovec_payloads.json")
        p = Path(payload_path)
        if not p.exists():
            return None

        # First try in-memory TurboVec keyword search (fast)
        try:
            if getattr(vector_store, "_use_turbovec", False) and getattr(vector_store, "_turbovec", None):
                try:
                    # run keyword-only search in thread to avoid blocking event loop
                    def _kv():
                        return vector_store._turbovec._keyword_only_search(query, top_k=6)
                    candidates = await asyncio.to_thread(_kv)
                    if candidates:
                        # pick best candidate
                        c = candidates[0]
                        content = (c.content or "")
                        q = query.lower()
                        if "ceo" in q or "founder" in q or "chief" in q:
                            if m := __import__("re").search(r"(?:\b(?:ceo|chief executive officer|founder)\b)[:\s\-]*([^\n,;]+)", content, flags=__import__("re").IGNORECASE):
                                name = m.group(1).strip()
                                ans = f"The CEO is {name}."
                                citation = {"title": c.source or "uploaded_file", "url": c.url or "", "snippet": content[:300]}
                                return (ans, [citation])
                        if any(k in q for k in ["product", "products", "service", "offerings"]):
                            prod = None
                            for pat in [
                                r"## Our Products\s*(.+?)(?:##|$)",
                                r"Our Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                                r"Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                                r"## Services We Provide\s*(.+?)(?:##|$)",
                                r"Services We Provide\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                            ]:
                                if m := __import__("re").search(pat, content, flags=__import__("re").IGNORECASE | __import__("re").DOTALL):
                                    prod = m.group(1).strip()
                                    break
                            if prod:
                                cleaned = __import__("re").sub(r"\s*\*\s*", "\n- ", prod).strip()
                                ans = f"Our products include:\n{cleaned}"
                                citation = {"title": c.source or "uploaded_file", "url": c.url or "", "snippet": content[:300]}
                                return (ans, [citation])
                        if any(k in q for k in ["website", "site", "web address", "link", "url"]):
                            if m := __import__("re").search(r"\b(?:https?://|www\.)[^\n\s,;]+", content, flags=__import__("re").IGNORECASE):
                                url = m.group(0).rstrip('.,;')
                                ans = f"The company website is {url}."
                                citation = {"title": c.source or "uploaded_file", "url": c.url or "", "snippet": content[:300]}
                                return (ans, [citation])
                            if m := __import__("re").search(r"website\s*[:\-–]?\s*((?:https?://|www\.)[^\n\s,;]+)", content, flags=__import__("re").IGNORECASE):
                                url = m.group(1).rstrip('.,;')
                                ans = f"The company website is {url}."
                                citation = {"title": c.source or "uploaded_file", "url": c.url or "", "snippet": content[:300]}
                                return (ans, [citation])
                except Exception:
                    # fall through to file scan
                    pass

        except Exception:
            pass

        def _search_payloads(payloads: dict, query: str):
            # raw is dict of id -> payload
            q = query.lower()
            if "ceo" in q or "chief executive" in q or "founder" in q:
                for payload in payloads.values():
                    content = (payload.get("content") or "").lower()
                    if m := re.search(r"(?:\b(?:ceo|chief executive officer|founder)\b)[:\s\-]*([^\n,;]+)", content, flags=re.IGNORECASE):
                        name = m.group(1).strip()
                        ans = f"The CEO is {name}."
                        citation = {
                            "title": payload.get("source", "uploaded_file"),
                            "url": payload.get("url", ""),
                            "snippet": (payload.get("content") or "")[:300],
                        }
                        return (ans, [citation])
            if "company name" in q or "who are you" in q or "about company" in q:
                for payload in payloads.values():
                    content = (payload.get("content") or "").lower()
                    m = re.search(r"company name[:\s\-]*([A-Z][\w &.,-]{1,120})", content, flags=re.IGNORECASE)
                    if m:
                        cname = m.group(1).strip()
                        ans = f"The company name is {cname}."
                        citation = {"title": payload.get("source", "uploaded_file"), "url": payload.get("url", ""), "snippet": (payload.get("content") or "")[:300]}
                        return (ans, [citation])
            if any(k in q for k in ["product", "products", "offerings", "services"]):
                for payload in payloads.values():
                    content = (payload.get("content") or "")
                    product_text = None
                    for pat in [
                        r"## Our Products\s*(.+?)(?:##|$)",
                        r"Our Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                        r"Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                        r"## Services We Provide\s*(.+?)(?:##|$)",
                        r"Services We Provide\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                    ]:
                        if m := re.search(pat, content, flags=re.IGNORECASE | re.DOTALL):
                            product_text = m.group(1).strip()
                            break
                    if product_text:
                        cleaned = re.sub(r"\s*\*\s*", "\n- ", product_text).strip()
                        ans = f"Our products include:\n{cleaned}"
                        citation = {
                            "title": payload.get("source", "uploaded_file"),
                            "url": payload.get("url", ""),
                            "snippet": content[:300],
                        }
                        return (ans, [citation])
                hits = []
                for payload in payloads.values():
                    content = (payload.get("content") or "")
                    if "product" in content.lower() or "service" in content.lower() or "offers" in content.lower():
                        snippet = content[:500]
                        hits.append({"title": payload.get("source", "uploaded_file"), "url": payload.get("url", ""), "snippet": snippet})
                if hits:
                    first = hits[0]["snippet"].splitlines()[:5]
                    ans = "\n".join(first)
                    return (ans, hits[:3])
            if any(k in q for k in ["website", "site", "web address", "link", "url"]):
                for payload in payloads.values():
                    content = payload.get("content") or ""
                    if m := re.search(r"\b(?:https?://|www\.)[^\n\s,;]+", content, flags=re.IGNORECASE):
                        extracted = m.group(0).rstrip('.,;')
                        citation = {"title": payload.get("source", "uploaded_file"), "url": payload.get("url", ""), "snippet": content[:300]}
                        return (f"The company website is {extracted}.", [citation])
                    if m := re.search(r"website\s*[:\-–]?\s*((?:https?://|www\.)[^\n\s,;]+)", content, flags=re.IGNORECASE):
                        extracted = m.group(1).rstrip('.,;')
                        citation = {"title": payload.get("source", "uploaded_file"), "url": payload.get("url", ""), "snippet": content[:300]}
                        return (f"The company website is {extracted}.", [citation])
            if any(k in q for k in ["address", "location", "office", "headquarters"]):
                for payload in payloads.values():
                    content = payload.get("content") or ""
                    if extracted := self._extract_address_from_text(content):
                        citation = {"title": payload.get("source", "uploaded_file"), "url": payload.get("url", ""), "snippet": content[:300]}
                        return (f"The company address is: {extracted}", [citation])
            return None

        payloads = await self._load_cached_payloads(str(p))
        if payloads is None:
            return None
        result = await asyncio.to_thread(_search_payloads, payloads, query)
        return result

    def _extract_address_from_text(self, text: str) -> str | None:
        if not text:
            return None

        patterns = [
            r"(?mi)^(?:\*+\s*)?\*{0,2}\s*(?:Address|Location|Headquarters|Head Office)\s*\*{0,2}\s*[:\-–]?\s*(.+?)(?=\n(?:\s*\*+\s*|\s*[-#*]{1,}|$))",
            r"(?mi)^(?:\*+\s*)?\s*(?:Address|Location|Headquarters|Head Office)\s*[:\-–]?\s*(.+?)$",
            r"(?mi)\b(?:No\.?|Plot No\.?|House No\.?|Door No\.?|Suite|Floor|Building|Office|Floor No\.|Wing)\b[^\n]*(?:\n(?!\s*(?:##|#|\*{2,}|[-=]{3,}))[^\n]*)*",
            r"(?mi)(?:located at|is located at|located in)\s*(.+?)(?=\n\s*$|\n\s*(?:##|#|\*{2,}|[-=]{3,})|$)",
        ]

        for pat in patterns:
            match = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue

            extracted = match.group(1).strip() if match.lastindex else match.group(0).strip()
            remainder = text[match.end():].splitlines() if match.lastindex else []
            continuation = []
            for line in remainder:
                next_line = line.strip()
                if not next_line:
                    break
                if re.match(r"^(?:\*+\s*|\s*[-#*]{1,}|\*\*.+\*\*)", next_line):
                    break
                continuation.append(next_line)
            if continuation:
                extracted = " ".join([extracted] + continuation).strip()
            return extracted

        return None

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
        global_search = request.global_search if hasattr(request, 'global_search') and request.global_search is not None else True

        cache_prefix = f"response_{'global' if global_search else 'uploaded_only'}_{'docs' if use_uploaded_docs else 'no_docs'}"

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

        # ✅ FAST LOCAL EXTRACTION: try to answer directly from TurboVec payloads
        if use_uploaded_docs:
            try:
                fast = await self._fast_local_extract(processed_query)
                if fast:
                    ans, citations = fast
                    latency_ms = (time.perf_counter() - t_start) * 1000
                    response = ChatResponse(
                        answer=ans,
                        assistant_name=request.assistant_name,
                        intent=Intent.DOMAIN,
                        sources=[Citation(title=c.get('title','uploaded_file'), url=c.get('url',''), snippet=c.get('snippet','')) for c in citations],
                        confidence=0.95,
                        latency_ms=round(latency_ms, 2),
                        cached=False,
                        token_usage=TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0),
                        session_id=request.session_id,
                        detected_language="en",
                    )
                    try:
                        await cache_service.set(cache_prefix, processed_query, response.model_dump())
                    except Exception:
                        logger.warning("Cache SET failed for fast local extract")
                    return response
            except Exception as e:
                logger.warning(f"Fast local extract failed: {e}")

        if not use_uploaded_docs:
            logger.info("use_uploaded_docs is false: answering from Gemini AI instead of uploaded documents")
            # Record LLM generation timing to telemetry for debugging latency
            try:
                from app.services.telemetry import record_timing
            except Exception:
                record_timing = None

            start_gen = time.perf_counter()
            try:
                async with track_latency("llm_generation"):
                    if global_search:
                        answer, citations, token_usage = await llm_generator.generate_with_search(
                            query=request.query,
                            assistant_name=request.assistant_name,
                            conversation_history=[],
                            require_context=False,
                        )
                    else:
                        answer, citations, token_usage = await llm_generator.generate(
                            query=request.query,
                            assistant_name=request.assistant_name,
                            conversation_history=[],
                            require_context=False,
                        )
                try:
                    if record_timing:
                        record_timing("llm_generation_ms", (time.perf_counter() - start_gen) * 1000.0)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"LLM generation failed in non-uploaded-docs branch: {e}", exc_info=True)
                if global_search:
                    try:
                        search_results = await web_search_service.search(request.query, max_results=5)
                        if search_results:
                            try:
                                answer = llm_generator._build_answer_from_search_results(request.query, search_results)
                            except Exception as fallback_exc:
                                logger.warning(f"Failed to build fallback answer from search results: {fallback_exc}")
                                answer = search_results[0].snippet or "I could not fetch the answer from the search results."
                            citations = [Citation(title=r.title, url=r.url, snippet=r.snippet) for r in search_results[:3]]
                            token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                            latency_ms = (time.perf_counter() - t_start) * 1000
                            return ChatResponse(
                                answer=answer,
                                assistant_name=request.assistant_name,
                                intent=Intent.GENERAL,
                                sources=citations,
                                confidence=0.65,
                                latency_ms=round(latency_ms, 2),
                                cached=False,
                                token_usage=token_usage,
                                session_id=request.session_id,
                                detected_language="en",
                            )
                    except Exception as search_exc:
                        logger.warning(f"Search fallback failed after LLM failure: {search_exc}")
                # Safe fallback: return friendly message instead of raising 500
                latency_ms = (time.perf_counter() - t_start) * 1000
                fallback = (
                    "Sorry — the external generation service is temporarily unavailable. "
                    "Please try again in a few moments or contact admin for urgent help."
                )
                admin_email = getattr(settings, "ADMIN_CONTACT_EMAIL", None) or "businesshead@nexovatechzone.com"
                admin_phone = getattr(settings, "ADMIN_CONTACT_PHONE", None) or "+91 7810001706"
                contact = f"Contact: {admin_email} / {admin_phone}"
                return ChatResponse(
                    answer=f"{fallback}\n\n{contact}",
                    assistant_name=request.assistant_name,
                    intent=Intent.GENERAL,
                    sources=[],
                    confidence=0.5,
                    latency_ms=round(latency_ms, 2),
                    cached=False,
                    token_usage=TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0),
                    session_id=request.session_id,
                    detected_language="en",
                )
            answer = await self._translate_if_needed(answer, request.query)
            if global_search and self._is_generic_fallback_answer(answer):
                logger.info("LLM returned generic fallback; trying search-based direct answer instead.")
                try:
                    search_results = await web_search_service.search(request.query, max_results=5)
                    if search_results:
                        answer = llm_generator._build_answer_from_search_results(request.query, search_results)
                        citations = [Citation(title=r.title, url=r.url, snippet=r.snippet) for r in search_results[:3]]
                except Exception as search_exc:
                    logger.warning(f"Search fallback after generic LLM answer failed: {search_exc}")
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
                domain_chunks = await self._retrieve_domain(
                    processed_query, 
                    skip_rerank=self._is_direct_extractable_query(processed_query),
                    use_uploaded_only=(use_uploaded_docs and not global_search),
                )

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

        query_lower = processed_query.lower()
        if (
            "ceo" in query_lower
            or self._is_company_name_query(processed_query)
            or any(k in query_lower for k in ["product", "products", "offerings", "service", "services"])
        ) and not direct_answer and domain_chunks:
            direct_answer = await self._extract_direct_answer_from_chunks(processed_query, domain_chunks)
            if direct_answer:
                direct_answer = self._build_direct_answer_for_translation(direct_answer, request.query)
                answer = await self._translate_if_needed(direct_answer, request.query)
                citations = _build_rag_citations(domain_chunks)
                token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                logger.info("Extracted direct answer from domain chunks before generation")

        if not direct_answer and self._is_company_overview_query(processed_query) and domain_chunks:
            direct_answer = await self._extract_company_overview_from_chunks(domain_chunks)
            if direct_answer:
                answer = await self._translate_if_needed(direct_answer, request.query)
                citations = _build_rag_citations(domain_chunks)
                token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                logger.info("Extracted company overview from domain chunks before generation")

        try:
            # 🚀 ROUTING LOGIC
            
            # ✅ NEW: Handle global_search flag - if False, restrict all intents to uploaded documents only
            if not global_search:
                logger.info(f"global_search=False: restricting to uploaded documents only. Original intent: {intent_result.intent}")
                if not domain_chunks:
                    domain_chunks = await self._retrieve_domain(
                        processed_query, 
                        skip_rerank=self._is_direct_extractable_query(processed_query),
                        use_uploaded_only=True,
                    )

                if not domain_chunks:
                    logger.info("No uploaded documents found for query - global_search disabled")
                    latency_ms = (time.perf_counter() - t_start) * 1000
                    # Provide a friendly recommendation with admin contact details and avoid heavy LLM work
                    admin_email = getattr(settings, "ADMIN_CONTACT_EMAIL", None)
                    admin_phone = getattr(settings, "ADMIN_CONTACT_PHONE", None)
                    contact_parts = []
                    if admin_email:
                        contact_parts.append(f"email: {admin_email}")
                    if admin_phone:
                        contact_parts.append(f"phone: {admin_phone}")
                    contact_str = "; ".join(contact_parts) if contact_parts else "our admin"
                    message = (
                        "We couldn't find the requested information in the uploaded documents. "
                        f"Please contact {contact_str} for assistance and share the details so we can help further."
                    )
                    return ChatResponse(
                        answer=message,
                        assistant_name=request.assistant_name,
                        intent=Intent.DOMAIN,
                        sources=[],
                        confidence=0.6,
                        latency_ms=round(latency_ms, 2),
                        cached=False,
                        token_usage=TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0),
                        session_id=request.session_id,
                        detected_language="en",
                    )
                intent_result = IntentResult(
                    intent=Intent.DOMAIN,
                    confidence=0.85,
                    rewritten_query=request.query,
                )

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
                    if domain_chunks and self._is_direct_extractable_query(processed_query):
                        direct_answer = await self._extract_direct_answer_from_chunks(processed_query, domain_chunks)
                        if direct_answer:
                            direct_answer = self._build_direct_answer_for_translation(direct_answer, request.query)
                            answer = await self._translate_if_needed(direct_answer, request.query)
                            citations = _build_rag_citations(domain_chunks)
                            token_usage = TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0)
                            logger.info("Extracted direct answer from domain chunks before generation")

                    if not direct_answer:
                        if domain_chunks:
                            # If the best domain chunk is low-confidence, avoid costly LLM generation
                            try:
                                top_score = max(getattr(c, 'score', 0.0) for c in domain_chunks)
                            except Exception:
                                top_score = 0.0
                            if top_score < 0.2:
                                logger.info(f"Domain chunks low-confidence (top_score={top_score:.3f}) - returning fast 'not found' response")
                                latency_ms = (time.perf_counter() - t_start) * 1000
                                return ChatResponse(
                                    answer="The requested information is not available in the provided documents.",
                                    assistant_name=request.assistant_name,
                                    intent=Intent.DOMAIN,
                                    sources=[],
                                    confidence=0.6,
                                    latency_ms=round(latency_ms, 2),
                                    cached=False,
                                    token_usage=TokenUsage(input_tokens=0, output_tokens=0, thoughts_tokens=0, total_tokens=0),
                                    session_id=request.session_id,
                                    detected_language="en",
                                )
                        
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
                elif global_search:
                    async with track_latency("llm_generation"):
                        answer, citations, token_usage = await llm_generator.generate_with_search(
                            query=request.query,
                            assistant_name=request.assistant_name,
                            conversation_history=conversation_history,
                            require_context=False,
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

    def _is_company_overview_query(self, query: str) -> bool:
        if not query:
            return False
        lower_query = query.lower()
        overview_terms = [
            "about the company",
            "tell me about the company",
            "tell about the company",
            "company overview",
            "overview of the company",
            "about us",
            "about company",
            "company info",
            "our products",
            "what products",
            "products we offer",
            "products you offer",
            "product offerings",
            "our services",
            "services we provide",
        ]
        return any(term in lower_query for term in overview_terms)

    def _summarize_overview_text(self, text: str) -> str:
        if not text:
            return text
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= 1000:
            return cleaned
        truncated = cleaned[:1000].rsplit(' ', 1)[0]
        return f"{truncated}..."

    async def _extract_company_overview_from_chunks(self, chunks: List[DocumentChunk]) -> str | None:
        if not chunks:
            return None

        # Collect all relevant chunks for comprehensive overview
        all_overviews = []
        
        # First pass: look for explicitly tagged overview sections
        for chunk in chunks:
            if chunk.section and re.search(r"company overview|about us|about the company", chunk.section, flags=re.IGNORECASE):
                overview = self._summarize_overview_text(chunk.content)
                if overview and overview not in all_overviews:
                    all_overviews.append(overview)

        # Second pass: look for content with overview keywords
        overview_keywords = [
            r"company overview",
            r"about us",
            r"we are a",
            r"our company",
            r"enterprise experience",
            r"we have delivered",
            r"we are an?",
            r"provides .* solutions",
            r"providing .* services",
            r"specializes in",
            r"products",
            r"offerings",
            r"services",
            r"solutions",
            r"delivered",
            r"handled",
            r"managed",
            r"developed",
        ]

        for chunk in chunks:
            content = chunk.content or ""
            if any(re.search(pattern, content, flags=re.IGNORECASE) for pattern in overview_keywords):
                overview = self._summarize_overview_text(content)
                if overview and overview not in all_overviews:
                    all_overviews.append(overview)

        # Return combined overview if we found multiple sections, otherwise first
        if all_overviews:
            if len(all_overviews) > 1:
                # Combine all relevant sections for comprehensive response
                return "\n\n".join(all_overviews)
            return all_overviews[0]

        # No obvious overview content found
        return None

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

        if "website" in lower_query or "site" in lower_query or "web address" in lower_query or "link" in lower_query or "url" in lower_query:
            logger.info(f"Attempting direct website extraction for query: {query}")
            url_patterns = [
                r"\b(?:https?://|www\.)[^\n\s,;]+",
                r"website\s*[:\-–]?\s*((?:https?://|www\.)[^\n\s,;]+)",
                r"site\s*[:\-–]?\s*((?:https?://|www\.)[^\n\s,;]+)",
                r"web address\s*[:\-–]?\s*((?:https?://|www\.)[^\n\s,;]+)",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for website: {text[:300]}...")
                for pat in url_patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE)
                    if match:
                        extracted = match.group(1).strip() if match.lastindex else match.group(0).strip()
                        extracted = extracted.rstrip('.,;')
                        logger.info(f"Extracted website: {extracted} using pattern: {pat}")
                        return f"The company website is {extracted}."

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

        if "address" in lower_query or "location" in lower_query or "office" in lower_query or "headquarters" in lower_query:
            logger.info(f"Attempting direct address extraction for query: {query}")
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for address: {text[:300]}...")
                if extracted := self._extract_address_from_text(text):
                    logger.info(f"Extracted address: {extracted[:200]}")
                    return f"The company address is: {extracted}"
        if any(k in lower_query for k in ["product", "products", "offerings", "services"]):
            logger.info(f"Attempting direct products extraction for query: {query}")
            patterns = [
                r"## Our Products\s*(.+?)(?:##|$)",
                r"Our Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                r"Products\s*[:\-–]?\s*(.+?)(?:\n##|$)",
                r"## Services We Provide\s*(.+?)(?:##|$)",
                r"Services We Provide\s*[:\-–]?\s*(.+?)(?:\n##|$)",
            ]
            for chunk in chunks:
                text = chunk.content
                logger.info(f"Checking chunk for products: {text[:300]}...")
                for pat in patterns:
                    match = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
                    if match:
                        extracted = match.group(1).strip()
                        cleaned = re.sub(r"\s*\*\s*", "\n- ", extracted).strip()
                        logger.info(f"Extracted products: {cleaned} using pattern: {pat}")
                        return f"Our products include:\n{cleaned}"
        
        logger.info("No direct answer extracted")
        return None

    async def _retrieve_domain(self, query: str, skip_rerank: bool = False, use_uploaded_only: bool = False) -> List[DocumentChunk]:

        logger.info(f"Domain retrieval for query: '{query}' (use_uploaded_only={use_uploaded_only})")
        original_query = query.strip()
        
        # ✅ UPLOADED-DOCS-ONLY MODE: Skip embeddings entirely, use keyword-only search for all queries
        if use_uploaded_only:
            logger.info("Uploaded-docs-only mode: using keyword-only fast path for all queries")
            try:
                await vector_store.connect()
                keyword_candidates = await vector_store.keyword_search(original_query, settings.TOP_K * 2)
                if keyword_candidates:
                    logger.info(f"Keyword-only search returned {len(keyword_candidates)} results")
                    try:
                        from app.services.telemetry import record_fast_path_hit, record_timing
                        record_fast_path_hit()
                        # record latency for fast-path
                        record_timing("fast_path_latency_ms", (time.perf_counter() - t_start) * 1000.0)
                    except Exception:
                        pass
                    chunks = keyword_candidates
                    try:
                        await cache_service.set("docs", original_query, [c.model_dump() for c in chunks])
                        logger.info("Cached keyword-only domain chunks for query")
                    except Exception:
                        logger.warning("Failed to cache keyword-only domain chunks")
                    # Filter and clean
                    chunks = self._filter_chunks_by_relevance(original_query, chunks)
                    from app.ingestion.cleaner import clean_text
                    for chunk in chunks:
                        chunk.content = clean_text(chunk.content)
                    return chunks
                else:
                    logger.info("Keyword-only search returned no results for uploaded-docs-only query")
                    try:
                        from app.services.telemetry import record_fast_path_miss
                        record_fast_path_miss()
                    except Exception:
                        pass
                    return []
            except Exception as e:
                logger.warning(f"Keyword-only retrieval in uploaded-only mode failed: {e}")
                return []
        
        # ✅ NORMAL MODE: Full retrieval pipeline
        query_variants = self._expand_query_variants(original_query)
        expanded_query = query_variants[1] if len(query_variants) > 1 else original_query
        logger.info(f"Query variants for parallel search: {query_variants}")

        # ✅ SAFE CACHE READ
        try:
            cached_docs = await cache_service.get("docs", original_query)
            if cached_docs:
                logger.info(f"Cache hit: {len(cached_docs)} cached chunks")
                return [DocumentChunk(**d) for d in cached_docs]
        except Exception as e:
            logger.warning(f"Cache GET failed (docs): {e}")

        # ✅ FAST KEYWORD-ONLY CHECK: avoid embedding when there are strong direct keyword matches
        try:
            await vector_store.connect()
            keyword_candidates = []
            # For common queries, try keyword-only search first to avoid embedding cost
            common_keywords = ["company details", "company info", "company information", "about company", "company overview"]
            is_common_query = any(kw in original_query.lower() for kw in common_keywords)
            
            is_direct_query = self._is_direct_extractable_query(original_query)
            is_address_query = self._is_address_query(original_query)
            if is_address_query:
                logger.info("Address/location query detected — prioritizing fast keyword-only path")
            if is_common_query or self._query_has_domain_signals(original_query) or len(original_query.split()) <= 4 or is_address_query:
                keyword_candidates = await vector_store.keyword_search(original_query, settings.TOP_K)
                if keyword_candidates and (keyword_candidates[0].score >= 0.1 or is_direct_query or is_address_query):
                    logger.info("Using fast TurboVec keyword-only results before embedding")
                    chunks = keyword_candidates
                    try:
                        await cache_service.set("docs", original_query, [c.model_dump() for c in chunks])
                        logger.info("Cached keyword-only domain chunks for query")
                    except Exception:
                        logger.warning("Failed to cache keyword-only domain chunks")
                    return chunks
        except Exception as e:
            logger.warning(f"Keyword-only retrieval failed: {e}")

        # ✅ EMBEDDING (parallel for all variants)
        try:
            async with track_latency("embedding_parallel"):
                vectors = await asyncio.gather(
                    *[embedding_service.embed_query(q) for q in query_variants]
                )
            logger.info(f"Parallel embedding for {len(query_variants)} variants completed")
        except Exception as e:
            logger.error(f"Embedding failed: {e}", exc_info=True)
            return []

        # ✅ PARALLEL VECTOR SEARCH (TurboVec advantage multiplies here!)
        try:
            await vector_store.connect()
        except Exception as e:
            logger.error(f"❌ Failed to connect to vector store: {e}", exc_info=True)
            return []
        
        try:
            async with track_latency("parallel_vector_search"):
                search_tasks = []
                for q, vec in zip(query_variants, vectors):
                    task = vector_store.search_with_text(
                        query=q,
                        query_vector=vec,
                        top_k=settings.TOP_K,
                    )
                    search_tasks.append(task)
                
                # Execute all searches in parallel
                search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
            
            # Flatten and deduplicate results
            chunks = []
            seen_ids = set()
            for result in search_results:
                if isinstance(result, Exception):
                    logger.error(f"Search error: {result}")
                    continue
                for chunk in result:
                    chunk_id = f"{chunk.url}_{hash(chunk.content) % 1000}"
                    if chunk_id not in seen_ids:
                        chunks.append(chunk)
                        seen_ids.add(chunk_id)
            
            logger.info(f"Parallel search returned {len(chunks)} unique chunks from {len(query_variants)} variants")
            if chunks:
                logger.info(f"Top chunk scores: {[f'{c.score:.3f}' for c in chunks[:3]]}")
                # Cache retrieved chunks for faster next-time retrieval
                try:
                    await cache_service.set("docs", original_query, [c.model_dump() for c in chunks])
                    logger.info("Cached domain chunks for query")
                except Exception:
                    logger.warning("Failed to cache domain chunks")
                
                # TurboVec fast path: when enabled, avoid BM25 and cross-encoder reranking
                # to prioritize low-latency responses. We still filter and clean chunks.
                try:
                    from app.config.settings import get_settings
                    settings_local = get_settings()
                    if settings_local.USE_TURBOVEC and getattr(settings_local, 'TURBOVEC_FAST_MODE', False):
                        logger.info("Using TurboVec fast path: skipping BM25 and rerank for low latency")
                        # Filter to the most relevant chunk(s)
                        chunks = self._filter_chunks_by_relevance(original_query, chunks)
                        from app.ingestion.cleaner import clean_text
                        for chunk in chunks:
                            chunk.content = clean_text(chunk.content)
                        try:
                            await cache_service.set("docs", original_query, [c.model_dump() for c in chunks], ttl=600)
                        except Exception:
                            logger.warning("Failed to cache TurboVec fast-path chunks")
                        return chunks
                except Exception as _:
                    # If anything fails here, fall through to the standard (slower) pipeline
                    logger.debug("TurboVec fast-path setup failed, continuing with full pipeline")
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
            # Skip BM25 entirely in fast mode to avoid time overhead
            skip_bm25 = getattr(settings, 'SKIP_BM25_IN_FAST_MODE', False) and settings.TURBOVEC_FAST_MODE
            if not skip_bm25:
                try:
                    # Bound BM25 latency to a short timeout to keep overall request under target
                    bm25_timeout = 0.5  # seconds
                    async with track_latency("bm25_search"):
                        bm25_results = await asyncio.wait_for(
                            bm25_search.search(query=original_query, top_k=settings.TOP_K * 2),
                            timeout=bm25_timeout,
                        )
                    if bm25_results:
                        logger.info(f"BM25 search returned {len(bm25_results)} results")
                        # Incorporate BM25 scores into chunks
                        chunks = reranker.incorporate_bm25_scores(chunks, bm25_results)
                except asyncio.TimeoutError:
                    logger.warning("BM25 search timed out (continuing without BM25)")
                except Exception as e:
                    logger.warning(f"BM25 search failed (non-blocking): {e}")
            else:
                logger.info("Skipping BM25 in TurboVec fast mode")
            
            # ✅ Enhanced reranking with hybrid scoring
            # Skip reranking entirely in fast mode
            skip_rerank = getattr(settings, 'TURBOVEC_FAST_MODE', False) and skip_bm25
            if not skip_rerank:
                try:
                    # Bound reranking latency with a timeout. If the cross-encoder is slow,
                    # we'll continue with partial results.
                    rerank_timeout = 1.0  # seconds (reduced)
                    async with track_latency("enhanced_reranking"):
                        chunks = await asyncio.wait_for(
                            reranker.rerank(
                                query=original_query,
                                chunks=chunks,
                                top_n=settings.RERANK_TOP_N,
                                use_cross_encoder=False,  # Disable cross-encoder in fast mode
                                use_hybrid=False
                            ),
                            timeout=rerank_timeout,
                        )
                    logger.info(f"Enhanced reranking completed: {len(chunks)} chunks returned")
                except asyncio.TimeoutError:
                    logger.warning("Reranking timed out — proceeding with available results")
                except Exception as e:
                    logger.warning(f"Enhanced reranking failed (continuing): {e}")
            else:
                logger.info("Skipping reranking in TurboVec fast mode")

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
            'product': ['core services', 'products'],
            'products': ['core services', 'products'],
            'service': ['core services', 'products'],
            'services': ['core services', 'products'],
            'offerings': ['core services', 'products'],
            'mission': ['mission and vision'],
            'vision': ['mission and vision'],
            'leadership': ['leadership'],
            'ceo': ['leadership'],
            'executive': ['leadership'],
            'management': ['leadership'],
            'founder': ['leadership'],
            'founders': ['leadership'],
            'team': ['leadership'],
            'contact': ['contact information'],
            'phone': ['contact information'],
            'telephone': ['contact information'],
            'email': ['contact information'],
            'address': ['contact information', 'headquarters'],
            'location': ['contact information', 'headquarters'],
            'headquarters': ['contact information', 'headquarters'],
            'office': ['contact information', 'headquarters'],
            'founded': ['company overview', 'about us'],
            'established': ['company overview', 'about us'],
            'history': ['company overview', 'about us'],
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