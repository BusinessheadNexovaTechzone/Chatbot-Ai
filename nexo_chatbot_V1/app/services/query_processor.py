"""
Query Processing Module: Spelling correction, query rewriting, and normalization.
Handles common spelling mistakes and improves query understanding.
"""

import re
from typing import Optional, Tuple
from app.utils.logger import logger
from app.config.settings import get_settings

settings = get_settings()

class QueryProcessor:
    """
    Handles query preprocessing including:
    - Spelling correction for common mistakes
    - Query normalization
    - Query rewriting for better retrieval
    """
    
    def __init__(self):
        self.spell_checker = None
        self._init_spell_checker()
    
    def _init_spell_checker(self):
        """Initialize spell checker with textblob."""
        try:
            from textblob import TextBlob
            self.spell_checker = TextBlob
            logger.info("TextBlob spell checker initialized")
        except ImportError:
            logger.warning("textblob not installed — spell checking disabled")
            self.spell_checker = None
    
    def fix_spelling(self, query: str) -> str:
        """
        Attempt to fix spelling mistakes in query using TextBlob.
        Falls back to original query if spell checker unavailable.
        """
        if not query or not self.spell_checker:
            return query
        
        try:
            # Use TextBlob for spell correction
            corrected = str(self.spell_checker(query).correct())
            if corrected != query:
                logger.info(f"Spelling correction: '{query}' → '{corrected}'")
                return corrected
            return query
        except Exception as e:
            logger.warning(f"Spelling correction failed: {e}")
            return query
    
    def normalize_query(self, query: str) -> str:
        """
        Normalize query by:
        - Converting to lowercase
        - Removing extra whitespace
        - Removing special characters (except meaningful ones)
        """
        if not query:
            return query
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', query).strip()
        
        # Remove common filler words at the beginning
        filler_prefixes = [
            r'^(can you|could you|please|kindly|can|could)\s+',
            r'^(i want to|i need to|i am looking for|looking for|find|search for)\s+'
        ]
        
        for pattern in filler_prefixes:
            normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE).strip()
        
        return normalized
    
    def expand_abbreviations(self, query: str) -> str:
        """
        Expand common abbreviations to improve retrieval.
        Examples: 'FAQ' -> 'frequently asked questions', 'CEO' -> stays as is (important term)
        """
        if not query:
            return query
        
        abbreviations = {
            r'\bQ&A\b': 'questions and answers',
            r'\bFAQ\b': 'frequently asked questions',
            r'\bAPI\b': 'application programming interface',
            r'\bUI\b': 'user interface',
            r'\bUX\b': 'user experience',
            r'\bURL\b': 'web address',
            r'\bhttp\b': 'hypertext transfer protocol',
        }
        
        expanded = query
        for abbr, full_form in abbreviations.items():
            if re.search(abbr, expanded, re.IGNORECASE):
                expanded = re.sub(abbr, full_form, expanded, flags=re.IGNORECASE)
                logger.debug(f"Expanded abbreviation: {abbr} → {full_form}")
        
        return expanded

    def rewrite_short_query(self, query: str) -> str:
        """Rewrite short or keyword-only queries into retrieval-friendly questions."""
        if not query:
            return query

        normalized = query.lower().strip().rstrip('?.')
        rewrites = {
            'ceo': 'Who is the CEO of the company?',
            'who is ceo': 'Who is the CEO of the company?',
            'company name': 'What is the company name?',
            'business name': 'What is the business name?',
            'name of the company': 'What is the company name?',
            'address': 'What is the company address?',
            'headquarters': 'What is the company headquarters?',
            'location': 'What is the company location?',
            'office': 'What is the company office address?',
            'website': 'What is the company website?',
            'website link': 'What is the company website?',
            'contact': 'How can I contact the company?',
            'phone': 'What is the company phone number?',
            'telephone': 'What is the company phone number?',
            'contact number': 'What is the company phone number?',
            'email': 'What is the company email address?',
            'mail': 'What is the company email address?',
            'founded': 'When was the company founded?',
            'founded year': 'When was the company founded?',
            'year of establishment': 'When was the company founded?',
        }

        if normalized in rewrites:
            return rewrites[normalized]

        for key, rewrite in rewrites.items():
            if normalized.startswith(key + ' ') or normalized.endswith(' ' + key):
                return rewrite

        return query
    
    def handle_common_typos(self, query: str) -> str:
        """
        Handle common typos before spell checking.
        Examples: 'hii' -> 'hi', 'thankyou' -> 'thank you'
        """
        if not query:
            return query
        
        common_typos = {
            r'\bhii+\b': 'hi',
            r'\bhelo+\b': 'hello',
            r'\bthanku+\b': 'thank you',
            r'\bthnx\b': 'thanks',
            r'\bpls\b': 'please',
            r'\bcuz\b': 'because',
            r'\bc\s+u\b': 'see you',
            r'\bwanna\b': 'want to',
            r'\bgotta\b': 'got to',
            r'\bwannabe\b': 'want to be',
            r'\btryna\b': 'trying to',
            r'\bcant\b': 'cannot',
            r'\bdont\b': 'do not',
            r'\bwont\b': 'will not',
        }
        
        corrected = query
        for typo_pattern, correction in common_typos.items():
            if re.search(typo_pattern, corrected, re.IGNORECASE):
                corrected = re.sub(typo_pattern, correction, corrected, flags=re.IGNORECASE)
                logger.debug(f"Fixed typo: {typo_pattern} → {correction}")
        
        return corrected
    
    def process_query(self, query: str) -> Tuple[str, str, bool]:
        """
        Complete query processing pipeline.
        Returns: (original_query, processed_query, was_modified)
        """
        if not query:
            return query, query, False
        
        original = query
        
        # Step 1: Handle common typos
        query = self.handle_common_typos(query)
        
        # Step 2: Expand abbreviations
        query = self.expand_abbreviations(query)
        
        # Step 3: Normalize
        query = self.normalize_query(query)

        # Step 3.5: Rewrite short queries into retrievable questions
        query = self.rewrite_short_query(query)
        
        # Step 4: Fix spelling (most expensive operation)
        query = self.fix_spelling(query)
        
        was_modified = (query != original)
        
        if was_modified:
            logger.info(
                f"Query processed",
                extra={
                    "original": original,
                    "processed": query,
                    "modified": True
                }
            )
        
        return original, query, was_modified


# Singleton instance
query_processor = QueryProcessor()
