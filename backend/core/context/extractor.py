import json
import re
from typing import Dict, Any, List

from backend.core.llm import call_llm
from backend.schemas.context import ExtractedEvent, ExtractedEntity

EXTRACTION_SYSTEM_PROMPT = """You are an expert Document Intelligence AI.
Your job is to read document text and extract structured Context (Entities and Events).
Extract ONLY explicit, high-confidence information. DO NOT guess or infer things not present in the text.
Return the result as a valid JSON object matching the exact schema requested. Do not include markdown formatting or extra text.

Extraction Rules:
1. EVENT TYPES: 'meeting', 'interview', 'deadline', 'exam', 'submission', 'appointment'
2. ENTITY TYPES: 'person', 'organization', 'location', 'technology', 'project'
3. EVIDENCE: Always include a short snippet (1-2 sentences) of the exact text where you found this information.
4. CONFIDENCE: Give a confidence score between 0.0 and 1.0 (1.0 = explicitly stated).
"""

async def extract_context_from_text(text: str, document_id: str, filename: str) -> Dict[str, List[Any]]:
    """
    Extracts structured entities and events from raw text using NVIDIA AI.
    """
    prompt = f"""
    Analyze the following text from the document: '{filename}'
    
    TEXT:
    {text}
    
    Format your output as a JSON object with three keys: "summary", "entities", and "events".
    "summary" should be a brief 1-2 sentence overview of the document's contents.
    
    Example output format:
    {{
        "summary": "This document outlines the Alpha project plan and timeline.",
        "entities": [
            {{
                "entity_type": "person",
                "value": "John Doe",
                "confidence": 0.95,
                "evidence": "John Doe will be leading the new initiative."
            }}
        ],
        "events": [
            {{
                "title": "Project Kickoff",
                "event_type": "meeting",
                "start_date": "2026-10-15T09:00:00Z",
                "end_date": "2026-10-15T10:00:00Z",
                "location": "Conference Room A",
                "description": "Kickoff meeting for the new Alpha project.",
                "confidence": 0.9,
                "evidence": "The kickoff meeting is scheduled for Oct 15 at 9 AM in Conference Room A."
            }}
        ]
    }}
    """
    
    try:
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        # Use a high-quality model available on NVIDIA for extraction
        response = await call_llm(
            provider="nvidia",
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            messages=messages,
            temperature=0.1
        )
        
        content = response.get("content", "")
        if not content:
            return {"entities": [], "events": []}
            
        # Strip markdown json blocks if present
        content = re.sub(r'^```json\s*', '', content.strip(), flags=re.IGNORECASE)
        content = re.sub(r'\s*```$', '', content.strip())
        
        # Also remove reasoning blocks if the model dumped them
        content = re.sub(r'<think>.*?</think>\s*', '', content, flags=re.DOTALL).strip()
            
        data = json.loads(content)
        
        # Inject document_id into the results
        entities = []
        events = []
        
        for e in data.get("entities", []):
            e["document_id"] = document_id
            entities.append(e)
            
        for ev in data.get("events", []):
            ev["document_id"] = document_id
            events.append(ev)
            
        summary = data.get("summary", "")
            
        return {"summary": summary, "entities": entities, "events": events}
        
    except Exception as e:
        print(f"Error during context extraction with NVIDIA: {e}")
        return {"summary": "", "entities": [], "events": []}
