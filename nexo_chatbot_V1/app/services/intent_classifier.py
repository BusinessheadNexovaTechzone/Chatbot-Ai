import asyncio
import json
import re
from typing import Optional
import google.generativeai as genai
from app.config.settings import get_settings
from app.models.schemas import Intent, IntentResult
from app.utils.logger import logger

settings = get_settings()

DOMAIN_SIGNALS = [
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
]


def _contains_domain_signal(query: str) -> bool:
    query_lower = query.lower()
    return any(signal in query_lower for signal in DOMAIN_SIGNALS)

def _build_client():
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for online Gemini classification.")
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai

INTENT_SYSTEM_PROMPT = """You are a high-accuracy intent classification engine for a domain-specific chatbot.

Classify the user query into EXACTLY ONE of these three intents:

1. "domain" — The query is about domain-specific information found in internal documentation, product knowledge bases, or industry-specific content. Examples: company policies, service procedures, pricing tiers, product features.

2. "web" — The query requires current, real-time, or recent information from the internet. Examples: current news, stock prices, recent events, live data, today's date/time.

3. "general" — The query is about general knowledge, common facts, math, coding concepts, definitions, or historical information that can be answered from training data.

Return ONLY valid JSON in this exact format:
{
  "intent": "domain" | "web" | "general",
  "confidence": <float 0.0-1.0>,
  "rewritten_query": "<improved, retrieval-friendly query>"
}"""


class IntentClassifier:
    def __init__(self):
        self._client = _build_client()
        self._system_prompt = INTENT_SYSTEM_PROMPT

    async def classify(self, query: str, domain_keywords: Optional[list] = None) -> IntentResult:
        """Classify query intent using LLM. Falls back to heuristics on failure."""
        # Force strong domain evidence to domain intent before calling the LLM.
        if _contains_domain_signal(query):
            logger.info("Query contains domain signal; applying domain-level heuristics.")
            heuristic_result = self._heuristic_classify(query)
            if heuristic_result.intent == Intent.DOMAIN:
                return heuristic_result

        try:
            result = await self._llm_classify(query, domain_keywords)
            if result.intent != Intent.DOMAIN and _contains_domain_signal(query):
                logger.info(
                    "LLM classified as non-domain but query contains domain signal; overriding to domain intent."
                )
                return IntentResult(
                    intent=Intent.DOMAIN,
                    confidence=max(result.confidence, 0.65),
                    rewritten_query=query,
                )
            return result
        except Exception as e:
            logger.warning(f"LLM classification failed, using heuristics: {e}")
            return self._heuristic_classify(query)

    async def _llm_classify(self, query: str, domain_keywords: Optional[list] = None) -> IntentResult:
        model = self._client.GenerativeModel(settings.LLM_MODEL)
        
        prompt = self._system_prompt
        if domain_keywords:
            prompt += f"\n\nDomain keywords for reference: {', '.join(domain_keywords)}"
        
        response = await model.generate_content_async(
            f"{prompt}\n\nUser query: {query}\n\nRespond with valid JSON only:"
        )
        
        try:
            text = response.text.strip()
            # Remove markdown code blocks if present
            if text.startswith('```json'):
                text = text[7:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()
            
            result = json.loads(text)
            intent_str = result.get("intent", "general")
            confidence = float(result.get("confidence", 0.5))
            rewritten_query = result.get("rewritten_query", query)
            
            intent = Intent(intent_str.lower())
            return IntentResult(
                intent=intent,
                confidence=min(confidence, 1.0),
                rewritten_query=rewritten_query,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {response.text}, error: {e}")
            raise RuntimeError(f"Invalid LLM response format: {response.text}")

    def _heuristic_classify(self, query: str) -> IntentResult:
        """Lightweight heuristic fallback."""
        query_lower = query.lower()

        web_signals = ["latest", "today", "current", "now", "recent", "live", "breaking", "weather"]
        general_signals = ["define", "explain", "how does", "history of", "when was"]
        domain_signals = ["website", "link", "contact", "address", "phone", "email", "company", "product", "service", "pricing", "policy", "ceo", "team", "about"]

        if any(s in query_lower for s in web_signals):
            return IntentResult(intent=Intent.WEB, confidence=0.75, rewritten_query=query)
        if any(s in query_lower for s in general_signals):
            return IntentResult(intent=Intent.GENERAL, confidence=0.70, rewritten_query=query)
        if any(s in query_lower for s in domain_signals):
            return IntentResult(intent=Intent.DOMAIN, confidence=0.65, rewritten_query=query)

        # Short conversational queries (< 8 words) are often general knowledge questions
        # unless they include strong domain-specific signals.
        if len(query_lower.split()) < 8:
            if any(word in query_lower for word in ["who", "what", "where", "when", "why", "how"]):
                if any(signal in query_lower for signal in domain_signals):
                    return IntentResult(intent=Intent.DOMAIN, confidence=0.60, rewritten_query=query)
                return IntentResult(intent=Intent.GENERAL, confidence=0.60, rewritten_query=query)
            return IntentResult(intent=Intent.GENERAL, confidence=0.60, rewritten_query=query)

        return IntentResult(intent=Intent.DOMAIN, confidence=0.60, rewritten_query=query)


intent_classifier = IntentClassifier()
