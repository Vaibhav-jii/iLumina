from typing import Optional
from backend.db.store import get_space_documents
from backend.db.context_store import get_entities_by_document, get_events_by_document, list_memories
from backend.services.calendar_service import list_upcoming_events, get_calendar_status

def resolve_context_prompt(space_id: Optional[str] = None) -> str:
    """
    Builds a markdown string containing all relevant context for the AI Agent:
    - Upcoming Calendar Events
    - Document Entities (from Knowledge Space if active)
    - Document Events (from Knowledge Space if active)
    """
    context_blocks = []
    
    # 1. Google Calendar Context
    cal_status = get_calendar_status()
    if cal_status["status"] == "connected":
        events = list_upcoming_events(days_ahead=14)
        if events:
            cal_str = "📅 **Upcoming Calendar Events (Next 14 Days):**\n"
            for e in events:
                cal_str += f"- {e['title']} ({e['start']} to {e['end']})\n"
                if e.get("location"):
                    cal_str += f"  Location: {e['location']}\n"
            context_blocks.append(cal_str)
        else:
            context_blocks.append("📅 **Google Calendar:** No upcoming events found for the next 14 days.")
    else:
        context_blocks.append("📅 **Google Calendar:** Not connected. Cannot view or create events.")

    # 2. Permanent User Memory Context
    memories = list_memories()
    if memories:
        mem_str = "🧠 **Permanent User Memory / Facts:**\n"
        for mem in memories:
            mem_str += f"- [{mem['category'].upper()}] {mem['content']}\n"
        context_blocks.append(mem_str)

    # 3. Document Intelligence Context (Only if a Space is active)
    # If no space is active, we don't dump the whole DB to save tokens.
    if space_id:
        allowed_docs = get_space_documents(space_id)
        if allowed_docs:
            all_entities = []
            all_events = []
            for doc_id in allowed_docs:
                all_entities.extend(get_entities_by_document(doc_id))
                all_events.extend(get_events_by_document(doc_id))
                
            if all_events:
                evt_str = "📄 **Extracted Events from Knowledge Space:**\n"
                for ev in all_events:
                    date_info = f" (Start: {ev['start_date']})" if ev.get('start_date') else ""
                    evt_str += f"- [{ev['event_type'].upper()}] {ev['title']}{date_info} - *Evidence: \"{ev['evidence']}\"*\n"
                context_blocks.append(evt_str)
                
            if all_entities:
                ent_str = "🧠 **Extracted Entities from Knowledge Space:**\n"
                for ent in all_entities:
                    ent_str += f"- [{ent['entity_type'].upper()}] {ent['value']} - *Evidence: \"{ent['evidence']}\"*\n"
                context_blocks.append(ent_str)
                
    if not context_blocks:
        return ""
        
    final_prompt = "\n\n" + "="*40 + "\n"
    final_prompt += "🔴 BACKGROUND CONTEXT (Do not hallucinate outside of this)\n"
    final_prompt += "="*40 + "\n\n"
    final_prompt += "\n\n".join(context_blocks)
    final_prompt += "\n\n" + "="*40 + "\n"
    
    return final_prompt


def resolve_document_scope(space_id: Optional[str] = None) -> Optional[str]:
    """
    If a space_id is active, return a compact instruction listing
    the allowed document filenames so the LLM restricts its queries.
    Returns None if no scope restriction applies (general mode).
    """
    if not space_id:
        return None
    
    allowed_docs = get_space_documents(space_id)
    if not allowed_docs:
        return None
    
    # Build a compact constraint message
    doc_list = ", ".join(f'"{doc_id}"' for doc_id in allowed_docs)
    return (
        f"⚠️ DOCUMENT SCOPE RESTRICTION: The user has selected specific documents. "
        f"You MUST restrict your `query_documents` calls to ONLY these document IDs: [{doc_list}]. "
        f"Do NOT search outside this scope. If the user asks about documents not in this list, inform them."
    )

