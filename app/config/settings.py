try:
    from pydantic import model_validator
    _PYDANTIC_USE_MODEL_VALIDATOR = True
except ImportError:
    from pydantic import root_validator
    _PYDANTIC_USE_MODEL_VALIDATOR = False

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

LLM_MODEL_ALIASES = {
    "gemini-1.5-flash": "gemini-2.5-flash",
    "gemini-1.0-pro": "gemini-2.5-flash",
    "gemini-1.0-flash": "gemini-2.5-flash",
    "gemini-2.0": "gemini-2.5-flash",
}

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Nexo Chatbot"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8081

    # Gemini / Vertex settings
    GEMINI_API_KEY: Optional[str] = None
    USE_VERTEX_AI: bool = False
    VERTEX_PROJECT: Optional[str] = None
    VERTEX_LOCATION: str = "us-central1"
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_MAX_TOKENS: int = 512
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_RETRIES: int = 1                    # Retry attempts on quota or rate-limit errors

    # MongoDB
    MONGODB_URL: str = "mongodb+srv://deepang_db_user:bNhnLJyiyA4K4wOf@deepan.7g36kzf.mongodb.net/"
    MONGODB_DB: str = "nexo"
    # Encryption
    ENCRYPTION_KEY: str = "change-me-to-a-strong-secret-key"

    # Local TurboVec index
    USE_TURBOVEC: bool = True
    TURBOVEC_INDEX_PATH: str = "turbovec_index.tvim"
    TURBOVEC_PAYLOAD_PATH: str = "turbovec_payloads.json"
    TURBOVEC_BIT_WIDTH: int = 4

    if _PYDANTIC_USE_MODEL_VALIDATOR:
        @model_validator(mode="before")
        def normalize_settings(cls, values):
            values = cls._normalize_llm_model(values)
            return values
    else:
        @root_validator(pre=True)
        def normalize_settings(cls, values):
            values = cls._normalize_llm_model(values)
            return values

    @staticmethod
    def _normalize_llm_model(values):
        model = values.get("LLM_MODEL")
        if isinstance(model, str):
            normalized = model.strip()
            if normalized in LLM_MODEL_ALIASES:
                normalized = LLM_MODEL_ALIASES[normalized]
            values["LLM_MODEL"] = normalized
        return values

    # Embeddings
    # Gemini (GEMINI_API_KEY set): model=gemini-embedding-001, dim=3072
    # Local  (no API key):           model=all-MiniLM-L6-v2,      dim=384
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIM: int = 384              # set 384 when using local fallback only

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_SECONDS: int = 3600

    # Web Search (Tavily)
    TAVILY_API_KEY: Optional[str] = None
    SERPAPI_KEY: Optional[str] = None

    # Retrieval - Optimized for TurboVec parallel multi-search
    TOP_K: int = 1          # Minimal retrieval: only fetch the single best chunk
    SIMILARITY_THRESHOLD: float = 0.0  # Lowered from 0.65 for testing
    RERANK_TOP_N: int = 1   # Minimal reranking: keep only top result
    # TurboVec fast mode: when True, skip expensive reranking (cross-encoder/BM25)
    # to prioritize low-latency retrieval from the local TurboVec index.
    TURBOVEC_FAST_MODE: bool = True
    # When True, skip BM25 entirely in fast mode to avoid timeout overhead
    SKIP_BM25_IN_FAST_MODE: bool = True

    # Ingestion
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 75
    MAX_PAGES_PER_DOMAIN: int = 100

    # TurboVec keyword search cache TTL (seconds)
    TURBOVEC_KEYWORD_CACHE_TTL_SECONDS: int = 300
    # TurboVec warmup queries (used at startup to prime keyword cache)
    TURBOVEC_WARM_QUERIES: list[str] = [
        "company",
        "products",
        "pricing",
        "contact",
        "address",
        "website",
    ]
    
    # File Upload Limits
    MAX_FILE_SIZE_MB: int = 10                 # Maximum file size in MB
    MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB in bytes

    # WhatsApp Business API (Meta Cloud API)
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None     # Secret token for webhook verification
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None     # Meta system-user permanent access token
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None  # Phone Number ID from Meta App Dashboard

    # Azure Application Insights
    APPLICATIONINSIGHTS_CONNECTION_STRING: Optional[str] = None

    # WebSocket
    WS_TIMEOUT_SECONDS: int = 120               # Auto-close idle connections after 2 min

    # Admin contact (used for fallback recommendation when uploaded docs lack answer)
    ADMIN_CONTACT_EMAIL: Optional[str] = "admin@example.com"
    ADMIN_CONTACT_PHONE: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"          # silently ignore unknown env vars

@lru_cache()
def get_settings() -> Settings:
    return Settings()
