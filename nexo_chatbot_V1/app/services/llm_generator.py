import asyncio
import re
from typing import List, Optional, AsyncGenerator
import google.generativeai as genai
from app.config.settings import get_settings
from app.models.schemas import DocumentChunk, WebSearchResult, Citation, TokenUsage
from app.services.web_search import web_search_service
from app.utils.logger import logger

settings = get_settings()

BASE_SYSTEM_PROMPT = """You are a helpful AI assistant named {assistant_name}. Answer clearly and concisely."""


def _build_system_prompt(
    assistant_name: str = "Assistant",
    user_language: str = "English",
    require_context: bool = True,
) -> str:
    """Build system prompt with dynamic assistant name, query language, and context guidance."""
    prompt = BASE_SYSTEM_PROMPT.format(assistant_name=assistant_name)
    if require_context:
        prompt += (
            "\n\nRULES:\n"
            "1. Answer from provided context only. Do not add information not present in it.\n"
            "2. If no relevant context is available, say you don't have the information.\n"
            "3. Be brief—prefer 1-2 sentences.\n"
            "4. If the user asks in a language other than English, respond in that language.\n"
            "5. Do NOT hallucinate facts or URLs not in the context."
        )
    else:
        prompt += (
            "\n\nRULES:\n"
            "1. Use the provided context if available.\n"
            "2. If no relevant context is available, answer the user's question from general knowledge.\n"
            "3. Be brief—prefer 1-2 sentences.\n"
            "4. If the user asks in a language other than English, respond in that language.\n"
            "5. Do NOT hallucinate facts or URLs."
        )
    if user_language != "English":
        prompt += (
            f"\n\nIMPORTANT: The user's query is in {user_language}. "
            f"Answer in {user_language} using the appropriate script. Do not answer in English."
        )
    return prompt


def _detect_language_from_query(query: str) -> str:
    """Detect likely language name from unicode script in the query."""
    if not query:
        return "English"
    if re.search(r"[\u0B80-\u0BFF]", query):
        return "Tamil"
    if re.search(r"[\u0900-\u097F]", query):
        return "Hindi"
    if re.search(r"[\u0400-\u04FF]", query):
        return "Russian"
    if re.search(r"[\u4E00-\u9FFF]", query):
        return "Chinese"
    if re.search(r"[\uAC00-\uD7AF]", query):
        return "Korean"
    if re.search(r"[\u0590-\u05FF]", query):
        return "Hebrew"
    if re.search(r"[\u0600-\u06FF]", query):
        return "Arabic"
    if re.search(r"[\u0E00-\u0E7F]", query):
        return "Thai"
    return "English"


def _build_client():
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for online Gemini model usage.")
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai


def _format_domain_context(chunks: List[DocumentChunk]) -> str:
    if not chunks:
        return ""
    parts = ["## Retrieved Domain Context\n"]
    for i, chunk in enumerate(chunks, 1):
        parts.append(f"[Source {i}: {chunk.source} — {chunk.url}]\n{chunk.content}\n")
    return "\n".join(parts)


def _format_search_results(results: List[WebSearchResult]) -> str:
    if not results:
        return ""
    parts = ["## Web Search Results\n"]
    for i, result in enumerate(results, 1):
        parts.append(
            f"[Result {i}] {result.title}\nURL: {result.url}\n{result.snippet}\n"
        )
    return "\n".join(parts)


def _build_rag_citations(chunks: List[DocumentChunk]) -> List[Citation]:
    citations = []
    seen: set = set()
    for chunk in chunks:
        if chunk.url not in seen:
            citations.append(Citation(
                title=chunk.source,
                url=chunk.url,
                snippet=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
            ))
            seen.add(chunk.url)
    return citations


def _build_search_citations(results: List[WebSearchResult]) -> List[Citation]:
    citations = []
    seen: set = set()
    for result in results:
        if result.url and result.url not in seen:
            citations.append(Citation(title=result.title or result.url, url=result.url, snippet=result.snippet))
            seen.add(result.url)
    return citations


def _extract_token_usage(response) -> TokenUsage:
    usage = getattr(response, "usage_metadata", {}) or {}
    if hasattr(usage, 'prompt_token_count'):
        input_tokens = usage.prompt_token_count
        output_tokens = usage.candidates_token_count
        total_tokens = usage.total_token_count
    else:
        # Fallback for old API
        input_tokens = getattr(usage, 'get', lambda k, d: d)('prompt_tokens', 0)
        output_tokens = getattr(usage, 'get', lambda k, d: d)('completion_tokens', 0)
        total_tokens = getattr(usage, 'get', lambda k, d: d)('total_tokens', 0)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thoughts_tokens=0,
        total_tokens=total_tokens,
    )


def _build_history(conversation_history: Optional[List[dict]]) -> List[dict]:
    history = []
    for msg in (conversation_history or [])[-6:]:
        role = "user" if msg["role"] == "user" else "assistant"
        history.append({"role": role, "content": msg["content"]})
    return history


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "quota" in msg or "resource exhausted" in msg


class LLMGenerator:
    def __init__(self):
        self._client = _build_client()

    async def _chat_completion(self, messages: List[dict], temperature: float, max_tokens: int):
        model = self._client.GenerativeModel(settings.LLM_MODEL)
        
        # Convert messages to Gemini format
        gemini_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                # For old Gemini API, include system as first user message
                gemini_messages.append({"role": "user", "parts": [msg["content"]]})
                gemini_messages.append({"role": "model", "parts": ["Understood."]})
            elif msg["role"] == "user":
                gemini_messages.append({"role": "user", "parts": [msg["content"]]})
            elif msg["role"] == "assistant":
                gemini_messages.append({"role": "model", "parts": [msg["content"]]})
        
        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        response = await model.generate_content_async(
            contents=gemini_messages,
            generation_config=generation_config,
        )
        
        # Convert to OpenAI-like format for compatibility
        return type('Response', (), {
            'choices': [type('Choice', (), {
                'message': {
                    'content': response.text
                }
            })()],
            'usage': getattr(response, 'usage_metadata', {}) or {}
        })()

    async def _stream_chat_completion(
        self,
        messages: List[dict],
        temperature: float,
        max_tokens: int,
    ):
        # For simplicity, use non-streaming for now
        response = await self._chat_completion(messages, temperature, max_tokens)
        return [response]

    async def _generate_with_retry(self, messages: List[dict]):
        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(settings.LLM_MAX_RETRIES):
            try:
                return await self._chat_completion(
                    messages=messages,
                    temperature=settings.LLM_TEMPERATURE,
                    max_tokens=settings.LLM_MAX_TOKENS,
                )
            except Exception as exc:
                if _is_quota_error(exc) and attempt < settings.LLM_MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Gemini rate limit error (attempt {attempt + 1}), retrying in {wait}s: {exc}"
                    )
                    await asyncio.sleep(wait)
                    last_exc = exc
                else:
                    raise
        raise last_exc

    def _build_messages(
        self,
        query: str,
        assistant_name: str = "Assistant",
        domain_chunks: Optional[List[DocumentChunk]] = None,
        conversation_history: Optional[List[dict]] = None,
        search_results: Optional[List[WebSearchResult]] = None,
        require_context: bool = True,
    ) -> List[dict]:
        user_language = _detect_language_from_query(query)
        system_prompt = _build_system_prompt(
            assistant_name, user_language, require_context=require_context
        )
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(_build_history(conversation_history))

        if search_results:
            messages.append({
                "role": "user",
                "content": _format_search_results(search_results),
            })

        if domain_chunks:
            messages.append({
                "role": "user",
                "content": _format_domain_context(domain_chunks),
            })

        if require_context:
            prompt_instruction = (
                "Use the retrieved context to answer the user's question directly. Do not simply copy the context verbatim. "
                "If the user's query is not in English, answer in the same language as the query."
            )
        else:
            prompt_instruction = (
                "Use the retrieved context if available, but if it is not relevant, answer the user's question from your general knowledge. "
                "Do not simply copy the context verbatim. If the user's query is not in English, answer in the same language as the query."
            )

        messages.append({"role": "user", "content": prompt_instruction})
        messages.append({"role": "user", "content": f"Question: {query}\n\nAnswer this question based on the provided context. Provide a direct answer, not the raw context."})
        return messages

    async def translate_to_query_language(self, answer: str, query: str) -> str:
        """Translate or preserve the response in the user's query language."""
        if not answer or not query:
            return answer

        user_language = _detect_language_from_query(query)
        if user_language == "Tamil":
            system_instruction = (
                "You are a Tamil translation assistant. Translate the text below into Tamil script only. "
                "Do not use English letters or transliteration in Latin script. "
                "Use a natural Tamil sentence whenever the text is an answer to a question. "
                "Transliterate names like Arjun Mehrotra into Tamil script as well. "
                "Output only the translated Tamil text with no extra commentary."
            )
        else:
            system_instruction = (
                f"You are a translation assistant. Translate the text below into {user_language}. "
                "If the user's query is in English, return the original text unchanged. "
                "Do not add any commentary or extra explanation."
            )

        prompt = (
            f"User query: {query}\n\n"
            f"Text to translate:\n{answer}"
        )
        translated, _ = await self.generate_raw(
            prompt=prompt,
            assistant_name="Translator",
            system_instruction=system_instruction,
            temperature=0.0,
            max_output_tokens=max(128, min(len(answer) * 2, 1024)),
        )
        translated = translated.strip()
        if user_language == "Tamil" and not re.search(r"[\u0B80-\u0BFF]", translated):
            logger.warning("Tamil translation did not produce Tamil script; retrying with stricter Tamil-only prompt.")
            system_instruction = (
                "You are a Tamil translation assistant. Translate the text below into Tamil script only. "
                "Do not use any English or Latin letters. "
                "If the text is an answer, create a natural Tamil answer sentence. "
                "Output only Tamil text, with no commentary."
            )
            translated, _ = await self.generate_raw(
                prompt=prompt,
                assistant_name="Translator",
                system_instruction=system_instruction,
                temperature=0.0,
                max_output_tokens=max(128, min(len(answer) * 2, 1024)),
            )
            translated = translated.strip()
        return translated
    async def translate_query_to_english(self, query: str) -> str:
        """Translate a non-English user query into English for retrieval and generation."""
        if not query:
            return query

        system_instruction = (
            "You are a translation assistant. Translate the user's query into English. "
            "Return only the translated English query without any extra commentary."
        )
        prompt = f"User query: {query}"
        translated, _ = await self.generate_raw(
            prompt=prompt,
            assistant_name="Translator",
            system_instruction=system_instruction,
            temperature=0.0,
            max_output_tokens=128,
        )
        return translated.strip()

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate(
        self,
        query: str,
        assistant_name: str = "Assistant",
        domain_chunks: Optional[List[DocumentChunk]] = None,
        conversation_history: Optional[List[dict]] = None,
        require_context: bool = True,
    ) -> tuple[str, List[Citation], TokenUsage]:
        messages = self._build_messages(
            query=query,
            assistant_name=assistant_name,
            domain_chunks=domain_chunks,
            conversation_history=conversation_history,
            require_context=require_context,
        )
        response = await self._generate_with_retry(messages)
        answer = response.choices[0].message["content"].strip()
        citations = _build_rag_citations(domain_chunks or [])
        token_usage = _extract_token_usage(response)
        return answer, citations, token_usage

    async def generate_with_search(
        self,
        query: str,
        assistant_name: str = "Assistant",
        domain_chunks: Optional[List[DocumentChunk]] = None,
        conversation_history: Optional[List[dict]] = None,
        require_context: bool = True,
    ) -> tuple[str, List[Citation], TokenUsage]:
        search_results = []
        try:
            search_results = await web_search_service.search(query, max_results=5)
        except Exception as exc:
            logger.warning(f"Web search failed: {exc}")

        messages = self._build_messages(
            query=query,
            assistant_name=assistant_name,
            domain_chunks=domain_chunks,
            conversation_history=conversation_history,
            search_results=search_results,
            require_context=require_context,
        )
        response = await self._generate_with_retry(messages)
        answer = response.choices[0].message["content"].strip()
        citations = _build_search_citations(search_results) or _build_rag_citations(domain_chunks or [])
        token_usage = _extract_token_usage(response)
        return answer, citations, token_usage

    async def generate_raw(
        self,
        prompt: str,
        assistant_name: str = "Assistant",
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 1024,
        response_mime_type: Optional[str] = None,
    ) -> tuple[str, TokenUsage]:
        system_prompt = system_instruction or _build_system_prompt(assistant_name)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        response = await self._chat_completion(messages, temperature, max_output_tokens)
        answer = response.choices[0].message["content"].strip()
        return answer, _extract_token_usage(response)

    async def generate_raw_with_search(
        self,
        prompt: str,
        assistant_name: str = "Assistant",
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 1024,
    ) -> tuple[str, List[Citation], TokenUsage]:
        search_results = []
        try:
            search_results = await web_search_service.search(prompt, max_results=5)
        except Exception as exc:
            logger.warning(f"Web search failed: {exc}")

        system_prompt = system_instruction or _build_system_prompt(assistant_name)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _format_search_results(search_results)},
            {"role": "user", "content": prompt},
        ]
        response = await self._chat_completion(messages, temperature, max_output_tokens)
        answer = response.choices[0].message["content"].strip()
        citations = _build_search_citations(search_results)
        return answer, citations, _extract_token_usage(response)

    async def generate_stream(
        self,
        query: str,
        assistant_name: str = "Assistant",
        domain_chunks: Optional[List[DocumentChunk]] = None,
        conversation_history: Optional[List[dict]] = None,
        require_context: bool = True,
    ) -> AsyncGenerator[str, None]:
        messages = self._build_messages(
            query=query,
            assistant_name=assistant_name,
            domain_chunks=domain_chunks,
            conversation_history=conversation_history,
            require_context=require_context,
        )
        stream = await self._stream_chat_completion(
            messages,
            settings.LLM_TEMPERATURE,
            settings.LLM_MAX_TOKENS,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.get("content", "")
            if delta:
                yield delta

    async def generate_stream_with_search(
        self,
        query: str,
        assistant_name: str = "Assistant",
        domain_chunks: Optional[List[DocumentChunk]] = None,
        conversation_history: Optional[List[dict]] = None,
        require_context: bool = True,
    ) -> AsyncGenerator[str, None]:
        search_results = []
        try:
            search_results = await web_search_service.search(query, max_results=5)
        except Exception as exc:
            logger.warning(f"Web search failed: {exc}")

        messages = self._build_messages(
            query=query,
            assistant_name=assistant_name,
            domain_chunks=domain_chunks,
            conversation_history=conversation_history,
            search_results=search_results,
            require_context=require_context,
        )
        stream = await self._stream_chat_completion(
            messages,
            settings.LLM_TEMPERATURE,
            settings.LLM_MAX_TOKENS,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.get("content", "")
            if delta:
                yield delta


llm_generator = LLMGenerator()
