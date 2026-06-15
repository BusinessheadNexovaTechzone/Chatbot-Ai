from typing import List, Dict, Any
import re
from app.config.settings import get_settings

settings = get_settings()

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4

def _extract_structured_sections(text: str) -> List[Dict[str, str]]:
    """
    Extract sections from structured documents by direct content analysis.
    """
    sections = []

    # Direct section splitting based on known document structure
    text_lower = text.lower()

    # Find section boundaries
    sections_data = []

    # Look for contact information in the text
    contact_pos = text_lower.find('website:')
    if contact_pos >= 0:
        contact_text = text[contact_pos:]
        contact_end_markers = [
            'mission', 'vision', 'core services', 'achievements', 'recognition',
            'awards', 'since inception', 'headquarters', 'global presence'
        ]
        contact_end_pos = len(contact_text)
        for marker in contact_end_markers:
            marker_pos = contact_text.lower().find(marker)
            if marker_pos > 0 and marker_pos < contact_end_pos:
                contact_end_pos = marker_pos

        raw_contact = contact_text[:contact_end_pos].strip()
        website_match = re.search(r'website:\s*(\S+)', raw_contact, flags=re.IGNORECASE)
        contact_match = re.search(r'contact:\s*([^|\n]+)', raw_contact, flags=re.IGNORECASE)
        email_matches = re.findall(r'([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', raw_contact)
        phone_matches = re.findall(r'(\+?\d[\d\s\-\(\)]{7,}\d)', raw_contact)

        contact_parts = []
        seen_parts = set()

        def add_part(label: str, value: str):
            normalized = f"{label}: {value.strip()}"
            if normalized.lower() not in seen_parts:
                seen_parts.add(normalized.lower())
                contact_parts.append(normalized)

        if website_match:
            add_part("Website", website_match.group(1).strip())

        if contact_match:
            contact_value = contact_match.group(1).strip()
            add_part("Contact", contact_value)

        for email in email_matches:
            if not contact_match or email.lower() not in contact_match.group(1).lower():
                add_part("Email", email)

        for phone_value in phone_matches:
            if not contact_match or phone_value.strip() not in contact_match.group(1):
                add_part("Phone", phone_value.strip())

        contact_content = ' | '.join(contact_parts)
        if contact_content:
            sections_data.append(("Contact Information", contact_content))
            text = text.replace(raw_contact, '').strip()
            text_lower = text.lower()

    # Look for employee info in the text
    employee_pos = text_lower.find('employees:')
    if employee_pos >= 0:
        # Extract the employee information more precisely
        # Find the text starting from "Employees:" until the next major section
        employee_text = text[employee_pos:]
        # Find where this section ends (look for next section headers)
        end_markers = ['website:', 'contact:', 'mission', 'vision', 'core services', 'since inception', 'global presence']
        end_pos = len(employee_text)
        for marker in end_markers:
            marker_pos = employee_text.lower().find(marker)
            if marker_pos > 0 and marker_pos < end_pos:
                end_pos = marker_pos

        employee_content = employee_text[:end_pos].strip()

        # Create separate employee section
        sections_data.append(("Employees", employee_content))

        # Remove employee section from text and create company overview
        text_without_employee = text.replace(employee_content, '').strip()
        mission_start = text_without_employee.lower().find('our mission')
        if mission_start == -1:
            mission_start = text_without_employee.lower().find('mission')

        if mission_start > 0:
            company_overview = text_without_employee[:mission_start].strip()
            if company_overview:
                sections_data.append(("Company Overview", company_overview))
        else:
            # If no mission found, put everything else in company overview
            if text_without_employee.strip():
                sections_data.append(("Company Overview", text_without_employee.strip()))
    else:
        # No explicit employee section found
        mission_start = text_lower.find('our mission')
        if mission_start == -1:
            mission_start = text_lower.find('mission')
        if mission_start > 0:
            company_overview = text[:mission_start].strip()
            if company_overview:
                sections_data.append(("Company Overview", company_overview))

    # Look for headquarters info in the text
    hq_pos = text_lower.find('headquarters:')
    if hq_pos >= 0:
        # Extract headquarters information
        hq_text = text[hq_pos:]
        # Find where this section ends
        hq_end_markers = ['website:', 'contact:', 'employees:', 'global presence', 'mission', 'vision']
        hq_end_pos = len(hq_text)
        for marker in hq_end_markers:
            marker_pos = hq_text.lower().find(marker)
            if marker_pos > 0 and marker_pos < hq_end_pos:
                hq_end_pos = marker_pos

        hq_content = hq_text[:hq_end_pos].strip()

        # Also look for global presence section that mentions headquarters
        global_pos = text_lower.find('global presence')
        if global_pos >= 0:
            global_text = text[global_pos:]
            # Find end of global presence section
            global_end_pos = len(global_text)
            global_end_markers = ['achievements', 'recognition', 'awards', 'since inception']
            for marker in global_end_markers:
                marker_pos = global_text.lower().find(marker)
                if marker_pos > 0 and marker_pos < global_end_pos:
                    global_end_pos = marker_pos

            global_content = global_text[:global_end_pos].strip()
            hq_content += " " + global_content

        # Create separate headquarters section
        sections_data.append(("Headquarters", hq_content))

        # Remove headquarters section from remaining text processing
        text = text.replace(hq_content, '').strip()

    # Mission and Vision section
    vision_end = text_lower.find('core services')
    if vision_end == -1:
        vision_end = text_lower.find('services')

    if mission_start >= 0:
        if vision_end > mission_start:
            mission_vision = text[mission_start:vision_end].strip()
        else:
            mission_vision = text[mission_start:].strip()

        if mission_vision:
            sections_data.append(("Mission and Vision", mission_vision))

    # Core Services section
    leadership_start = text_lower.find('leadership')
    if leadership_start >= 0 and vision_end >= 0:
        services = text[vision_end:leadership_start].strip()
        if services:
            sections_data.append(("Core Services", services))

    # Leadership section
    achievements_start = text_lower.find('achievements')
    if achievements_start == -1:
        achievements_start = text_lower.find('awards')

    if leadership_start >= 0:
        if achievements_start > leadership_start:
            leadership = text[leadership_start:achievements_start].strip()
        else:
            leadership = text[leadership_start:].strip()

        if leadership:
            sections_data.append(("Leadership", leadership))

    # Achievements section
    if achievements_start >= 0:
        achievements = text[achievements_start:].strip()
        if achievements:
            sections_data.append(("Achievements and Recognition", achievements))

    # If no sections found, try fallback
    if not sections_data:
        return _fallback_sectioning(text)

    # Convert to expected format
    sections = [{"section_name": name, "content": content} for name, content in sections_data]

    return sections


def _fallback_sectioning(text: str) -> List[Dict[str, str]]:
    """Fallback sectioning for unstructured documents.

    When structured markers are missing, preserve the full document content as
    a single section instead of dropping text.
    """
    heading_re = re.compile(r'^(#{1,3}|\d+\.)\s+(.+)$', re.MULTILINE)
    matches = list(heading_re.finditer(text))
    if not matches:
        return [{"section_name": "main", "content": text}]

    sections = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            sections.append({"section_name": match.group(2).strip(), "content": content})

    if not sections:
        return [{"section_name": "main", "content": text}]

    return sections


def chunk_text(
    text: str,
    source: str,
    url: str,
    section: str = "main",
    chunk_size: int = None,
    overlap: int = None,
    timestamp: str = "",
) -> List[Dict[str, Any]]:
    """
    Splits text into overlapping chunks with metadata.
    Prioritizes section boundaries, then sentence boundaries.
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP
    
    # For large documents, use smaller chunks for better precision
    chunk_size = max(chunk_size // 2, 256)  # At least 256 tokens per chunk
    
    # First, try to extract structured sections
    structured_sections = _extract_structured_sections(text)
    
    chunks = []
    
    for struct_section in structured_sections:
        section_name = struct_section["section_name"]
        section_content = struct_section["content"]
        
        # Split section into sentences
        sentences = re.split(r'(?<=[.!?])\s+', section_content)
        current_tokens = 0
        current_sentences = []
        
        for sentence in sentences:
            s_tokens = estimate_tokens(sentence)
            
            # If adding this sentence exceeds chunk size, flush the chunk
            if current_tokens + s_tokens > chunk_size and current_sentences:
                chunk_text_str = ' '.join(current_sentences)
                chunks.append({
                    "content": chunk_text_str,
                    "source": source,
                    "url": url,
                    "section": section_name,
                    "timestamp": timestamp,
                })
                
                # Keep overlap sentences
                overlap_tokens = 0
                overlap_sentences = []
                for s in reversed(current_sentences):
                    t = estimate_tokens(s)
                    if overlap_tokens + t <= overlap:
                        overlap_sentences.insert(0, s)
                        overlap_tokens += t
                    else:
                        break
                
                current_sentences = overlap_sentences
                current_tokens = overlap_tokens
            
            current_sentences.append(sentence)
            current_tokens += s_tokens
        
        # Add final chunk from this section
        if current_sentences:
            chunk_text_str = ' '.join(current_sentences)
            chunks.append({
                "content": chunk_text_str,
                "source": source,
                "url": url,
                "section": section_name,
                "timestamp": timestamp,
            })
    
    return chunks if chunks else [{
        "content": text,
        "source": source,
        "url": url,
        "section": section,
        "timestamp": timestamp,
    }]

