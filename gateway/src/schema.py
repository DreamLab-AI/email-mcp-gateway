"""Egress abstraction schema — the privacy contract (PRD §6.1).

Everything returned over MCP MUST conform to these models. The remote client receives
abstractions only; raw mail never appears here.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PolicyLabel(str, Enum):
    ok = "ok"
    redacted = "redacted"
    dropped = "dropped"


class Evidence(BaseModel):
    ref_id: str = Field(..., description="Opaque hash; NOT the real message-id.")
    sender_role: str = Field(
        "unknown",
        description="Generalized sender role, e.g. bank|employer|family|vendor|unknown.",
    )
    period: str = Field(..., description="Bucketed time, e.g. '2024-Q1', not an exact date.")
    topic: str = Field(..., description="Coarse topic, e.g. invoice|travel|medical|legal.")
    abstract: str = Field(..., description="1-2 sentence sanitized gist, PII masked.")
    policy_label: PolicyLabel = PolicyLabel.ok


class EgressResult(BaseModel):
    answer: str = Field(..., description="Sanitized natural-language answer.")
    evidence: list[Evidence] = Field(default_factory=list)
    dropped_count: int = 0

    def model_dump_mcp(self) -> dict:
        """Plain dict for MCP transport."""
        return self.model_dump(mode="json")


# --- Internal (pre-sanitization) retrieval record — NEVER leaves the container ---
class RetrievedChunk(BaseModel):
    message_id: str
    sender: str
    sender_domain: str
    date_iso: str
    folder: str
    subject: str
    text: str
    chunk_idx: int
    score: float
