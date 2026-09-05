"""
Pydantic request/response schemas for the iLumina API.
"""

from pydantic import BaseModel


class ChatResponse(BaseModel):
    response: str
    screenshots: list[str] = []
    tool_calls_made: list[str] = []
    trace: list[dict] = []


class ChatTitleUpdate(BaseModel):
    title: str
