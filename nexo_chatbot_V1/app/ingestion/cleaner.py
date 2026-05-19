import re
from typing import Optional

BOILERPLATE_PATTERNS = [
    r'(cookie|privacy) policy.*?accept',
    r'subscribe to.*?newsletter',
    r'follow us on (twitter|instagram|facebook|linkedin)',
    r'©\s*\d{4}.*?reserved',
    r'all rights reserved',
    r'terms (of use|and conditions)',
    r'skip to (main )?content',
    r'toggle (navigation|menu)',
    r'back to top',
    r'\[VERSION \d+\]',  # Remove version headers like [VERSION 1777352980]
    r'Page \d+ – ',      # Remove page headers like Page 1 –
]

BOILERPLATE_RE = re.compile(
    '|'.join(BOILERPLATE_PATTERNS),
    re.IGNORECASE | re.DOTALL,
)

def clean_text(raw_text: str) -> str:
    """Remove boilerplate, normalize whitespace, strip HTML artifacts."""
    # Remove HTML tags if any slipped through
    text = re.sub(r'<[^>]+>', ' ', raw_text)
    # Remove boilerplate patterns
    text = BOILERPLATE_RE.sub(' ', text)
    # Split into lines and filter out unwanted lines
    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        line = line.strip()
        # Skip empty lines or lines that are just page headers or too short
        if not line or len(line) < 10:
            continue
        # Skip lines that look like headers (all caps, short, etc.)
        if re.match(r'^[A-Z\s]{1,50}$', line) and len(line) < 50:
            continue
        filtered_lines.append(line)
    # Join back and normalize whitespace
    text = ' '.join(filtered_lines)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def extract_sections(text: str) -> list[dict]:
    """Split text into sections by headings."""
    heading_re = re.compile(r'^(#{1,3}|\d+\.)\s+(.+)$', re.MULTILINE)
    sections = []
    matches = list(heading_re.finditer(text))
    if not matches:
        return [{"section": "main", "content": text}]

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            sections.append({"section": match.group(2).strip(), "content": content})
    return sections
