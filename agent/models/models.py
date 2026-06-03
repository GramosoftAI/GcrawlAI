from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AgentRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    urls: Optional[List[str]] = None
    schema: Optional[Dict[str, Any]] = None
    strictConstrainToURLs: bool = False
    model: Optional[str] = None
    maxCredits: int = Field(2500, ge=1)

    @field_validator("urls")
    @classmethod
    def normalize_urls(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if not v:
            return None
        cleaned = []
        for url in v:
            if not isinstance(url, str) or not url.strip():
                raise ValueError("urls must be a list of non-empty strings")
            cleaned.append(url.strip())
        return cleaned


class AgentStartResponse(BaseModel):
    success: bool = True
    id: str


class AgentStatusResponse(BaseModel):
    success: bool = True
    status: str
    data: Optional[Any] = None
    creditsUsed: int = 0
    expiresAt: Optional[datetime] = None
    model: Optional[str] = None
    error: Optional[str] = None


class AgentCancelResponse(BaseModel):
    success: bool = True


class SearchResult(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None


class ScrapeResult(BaseModel):
    url: str
    title: Optional[str] = None
    text: Optional[str] = None
    html: Optional[str] = None
    status_code: Optional[int] = None
    error: Optional[str] = None


class Plan(BaseModel):
    search_queries: List[str] = Field(default_factory=list)
    target_urls: List[str] = Field(default_factory=list)
    strategy: Optional[str] = None
    notes: Optional[str] = None
    max_pages: Optional[int] = None
