import os
import datetime
from typing import List, Dict, Any, Optional

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None
    build = None

# Scope definitions for Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_PATH = "token.json"


def get_calendar_service():
    """Retrieve the Google Calendar API service if a valid token exists."""
    if not Credentials or not build:
        return None
        
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
            if creds and creds.valid:
                return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"Error loading Google Calendar credentials: {e}")
    return None


def get_calendar_status() -> Dict[str, str]:
    """Check if the Calendar integration is active."""
    service = get_calendar_service()
    if service:
        return {"status": "connected"}
    return {"status": "disconnected"}


def list_upcoming_events(days_ahead: int = 7) -> List[Dict[str, Any]]:
    """List upcoming Google Calendar events."""
    service = get_calendar_service()
    if not service:
        return []
        
    try:
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        max_time = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + 'Z'
        
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=now,
            timeMax=max_time,
            maxResults=50, 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        formatted_events = []
        
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            formatted_events.append({
                "id": event.get("id"),
                "title": event.get("summary", "Untitled Event"),
                "start": start,
                "end": end,
                "description": event.get("description", ""),
                "location": event.get("location", ""),
                "htmlLink": event.get("htmlLink", "")
            })
            
        return formatted_events
    except Exception as e:
        print(f"Error fetching calendar events: {e}")
        return []


def execute_calendar_create(payload: Dict[str, Any]) -> str:
    """Execute event creation on Google Calendar. Only called by the Action Framework after approval."""
    service = get_calendar_service()
    if not service:
        raise Exception("Google Calendar is not connected")
        
    try:
        event_body = {
            'summary': payload.get('title', 'New Event'),
            'location': payload.get('location', ''),
            'description': payload.get('description', ''),
            'start': {
                'dateTime': payload.get('start_date'),
                'timeZone': payload.get('timezone', 'UTC'),
            },
            'end': {
                'dateTime': payload.get('end_date'),
                'timeZone': payload.get('timezone', 'UTC'),
            }
        }
        
        # Remove empty fields
        event_body = {k: v for k, v in event_body.items() if v}
        
        event = service.events().insert(calendarId='primary', body=event_body).execute()
        return event.get('htmlLink')
    except Exception as e:
        raise Exception(f"Failed to create calendar event: {str(e)}")
