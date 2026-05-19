#!/usr/bin/env python3
"""Test the new section-aware chunking logic."""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.ingestion.chunker import _extract_structured_sections, chunk_text
from app.models.schemas import DocumentChunk

# Sample document content from the user's PDF (from the API response)
sample_text = """NexaVault Technologies NexaVault Technologies Pvt. Ltd. is a premier cybersecurity and cloud infrastructure company founded in 2015 and headquartered in Bengaluru, India. With a presence across 12 countries and a team of over 850 certified professionals, NexaVault delivers enterprise-grade security solutions, zero-trust architecture frameworks, and AI-driven threat intelligence platforms to clients in banking, healthcare, e-commerce, and government sectors. Our proprietary NexaShield™ platform has protected over 3,200 organizations from advanced persistent threats, ransomware, and supply-chain attacks. We combine deep human expertise with cutting-edge automation to provide 24×7 managed security operations. Headquarters Bengaluru, Karnataka, India Arjun Mehrotra U72900KA2015PTC081234 Revenue (FY 2024–25) ■ 420 Crore www.nexavault.in contact@nexavault.in Our Mission To empower organizations worldwide with proactive, intelligent, and scalable cybersecurity solutions that eliminate vulnerabilities before they become breaches. Our Vision To be the world's most trusted digital security partner by 2030, driving a future where cyber threats no longer disrupt human progress. Core Services ■ Managed Security Operations (MSOC) Round-the-clock monitoring, triage, and incident response powered by AI-based SIEM and SOAR platforms. ■ Cloud Security & Compliance End-to-end security for AWS, Azure, and GCP environments — including CSPM, CWPP, and CIS benchmark hardening. ■ Zero-Trust Architecture Design and deployment of identity-centric, least-privilege access models using SASE and micro-segmentation. ■ AI-Driven Threat Intelligence Real-time threat feeds, dark-web monitoring, and predictive analytics via the NexaShield™ TI ■ GRC & Audit Readiness Governance, Risk, and Compliance consulting for ISO 27001, SOC 2 Type II, GDPR, RBI, and ■ Penetration Testing & Red Teaming Adversary simulation, vulnerability assessments, and VAPT reports aligned to OWASP and PTES standards. Since inception, NexaVault has protected over 3,200 organizations from advanced cyber threats, including ransomware, supply-chain attacks, and nation-state intrusions. Core Details Legal Name: NexaVault Technologies Pvt. Ltd. CIN: U72900KA2015PTC081234 Founded: March 2015 Headquarters: 14th Floor, Embassy TechVillage, Outer Ring Road, Devarabeesanahalli, Bengaluru – 560103 Employees: 850+ across 12 global offices Annual Revenue (FY 2024–25): ■ 420 Crore Website: www.nexavault.in Contact: contact@nexavault.in | +91 80 4120 9900 Global Presence In addition to its Bengaluru headquarters, NexaVault has offices in Mumbai, Delhi, Chennai, and Hyderabad within India. Internationally, the company operates from Dubai, Singapore, London, and New York, with partner networks extending to Australia, Germany, Canada, and South Africa. This footprint enables NexaVault to deliver localized support while adhering to regional data residency and regulatory requirements. . This document is confidential and intended for informational purposes only. Achievements and Recognition Over the past decade, NexaVault has received 42 industry awards, including recognition from NASSCOM, Data Security Council of India (DSCI), and Gartner's Cool Vendor list for AI-driven security. The company maintains a 99.97% uptime SLA across all managed service contracts and an average threat response time of under 8 minutes — well below the industry average of NexaVault holds ISO 27001:2022 certification, SOC 2 Type II attestation, and PCI-DSS Level 1 service provider status. Its team includes over 200 professionals holding CISSP, CISA, CEH, OSCP, and AWS Security Specialty certifications. Global Presence In addition to its Bengaluru headquarters, NexaVault has offices in Mumbai, Delhi, Chennai, and Hyderabad within India. Internationally, the company operates from Dubai, Singapore, London, and New York, with partner networks extending to Australia, Germany, Canada, and South Africa."""

def test_chunking():
    sections = _extract_structured_sections(sample_text)

    print(f"📄 Extracted {len(sections)} sections:")
    print("=" * 50)

    for i, section in enumerate(sections, 1):
        print(f"\n{i}. Section: '{section['section_name']}'")
        content_preview = section['content'][:300] + "..." if len(section['content']) > 300 else section['content']
        print(f"   Content: {content_preview}")

        # Check if this section contains employee info
        if 'employee' in section['content'].lower() or '850' in section['content']:
            print("   ✅ Contains employee information!")
            # Show the exact employee part
            import re
            employee_match = re.search(r'employees[^.]*\d+', section['content'], re.IGNORECASE)
            if employee_match:
                print(f"   📍 Employee info: '{employee_match.group()}'")

    print("\n" + "=" * 50)


def test_fallback_chunking():
    fallback_text = "This is a simple uploaded document with no headings, but it must still be stored and searchable."
    fallback_chunks = chunk_text(fallback_text, source='test', url='test.txt')
    assert len(fallback_chunks) >= 1
    assert fallback_text in fallback_chunks[0]['content']
    print("✅ Fallback chunking preserves plain document text.")


def test_chunking():
    sections = _extract_structured_sections(sample_text)

    print(f"📄 Extracted {len(sections)} sections:")
    print("=" * 50)

    for i, section in enumerate(sections, 1):
        print(f"\n{i}. Section: '{section['section_name']}'")
        content_preview = section['content'][:300] + "..." if len(section['content']) > 300 else section['content']
        print(f"   Content: {content_preview}")

        # Check if this section contains employee info
        if 'employee' in section['content'].lower() or '850' in section['content']:
            print("   ✅ Contains employee information!")
            # Show the exact employee part
            import re
            employee_match = re.search(r'employees[^.]*\d+', section['content'], re.IGNORECASE)
            if employee_match:
                print(f"   📍 Employee info: '{employee_match.group()}'")

    print("\n" + "=" * 50)
    print("🎯 Test query: 'Headquarters'")
    print("Expected: Should find section with 'Headquarters: 14th Floor, Embassy TechVillage...'")

    from app.services.orchestrator import orchestrator

    # Create mock chunks similar to what would be retrieved
    mock_chunks = [
        DocumentChunk(id="1", content="Leadership info...", section="Leadership", score=0.8, source="", url="", timestamp=""),
        DocumentChunk(id="2", content="Headquarters: 14th Floor, Embassy TechVillage...", section="Headquarters", score=0.9, source="", url="", timestamp=""),
        DocumentChunk(id="3", content="Website: www.nexavault.in | Contact: contact@nexavault.in | Phone: +91 80 4120 9900", section="Contact Information", score=0.7, source="", url="", timestamp=""),
    ]

    # Test headquarters filtering
    filtered_hq = orchestrator._filter_chunks_by_relevance("headquarters", mock_chunks)
    print(f"\n📋 Filtering test for 'headquarters' query:")
    print(f"Original chunks: {len(mock_chunks)}")
    print(f"Filtered chunks: {len(filtered_hq)}")
    if filtered_hq:
        print(f"Selected section: {filtered_hq[0].section}")

    # Test website filtering
    filtered_web = orchestrator._filter_chunks_by_relevance("website", mock_chunks)
    print(f"\n📋 Filtering test for 'website' query:")
    print(f"Original chunks: {len(mock_chunks)}")
    print(f"Filtered chunks: {len(filtered_web)}")
    if filtered_web:
        print(f"Selected section: {filtered_web[0].section}")
        print(f"Content preview: {filtered_web[0].content[:100]}...")


if __name__ == "__main__":
    test_fallback_chunking()
    test_chunking()