from typing import Optional

from deep_translator import GoogleTranslator
from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

SUPPORTED_LANGUAGE_CODES = {
    "en": "english",
    "hi": "hindi",
    "ta": "tamil",
    "te": "telugu",
    "ml": "malayalam",
    "kn": "kannada",
}


def detect_language(text: str) -> str:
    """Detect the most likely language code for the given text."""
    if not text or not text.strip():
        return "en"

    try:
        language = detect(text)
    except LangDetectException:
        return "en"

    return language if language in SUPPORTED_LANGUAGE_CODES else "en"


def translate_text(text: str, target_language: str) -> str:
    """Translate text into the target language using Deep Translator."""
    if not text or not target_language:
        return text

    target_language = target_language.lower()
    if target_language == "en":
        return text

    if target_language not in SUPPORTED_LANGUAGE_CODES:
        return text

    try:
        translator = GoogleTranslator(
            source="auto",
            target=SUPPORTED_LANGUAGE_CODES[target_language],
        )
        return translator.translate(text)
    except Exception:
        return text
