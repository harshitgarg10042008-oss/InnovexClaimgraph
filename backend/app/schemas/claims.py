"""Pydantic v2 schemas for Claims API endpoints."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class BlockerItem(BaseModel):
    field: str
    document: str
    reason: str


class LinkRunResponse(BaseModel):
    case_id: uuid.UUID
    status: str
    linking_status: str
    stale: bool
    blockers: list[BlockerItem] = Field(default_factory=list)
    run_at: str | None = None
    summary: dict[str, Any] | None = None
    findings: list[dict[str, Any]] | None = None


class GraphNode(BaseModel):
    id: str
    type: str
    position: dict[str, float]
    data: dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    animated: bool = False
    data: dict[str, Any]


class GraphResponse(BaseModel):
    case_id: uuid.UUID
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stale: bool


class LedgerResponse(BaseModel):
    case_id: uuid.UUID
    stale: bool
    run_at: str | None = None
    summary: dict[str, Any] | None = None
    claim_items: list[dict[str, Any]] = Field(default_factory=list)
    allocations: list[dict[str, Any]] = Field(default_factory=list)


class FindingResponseItem(BaseModel):
    id: str
    code: str
    severity: str
    title: str | None = None
    message: str
    explanation_template: str | None = None
    computed_numbers: dict[str, Any] | None = None
    needs_human_or_legal_review: bool = False
    blocks_ready: bool = False
    refs: list[dict[str, Any]] = Field(default_factory=list)
    refs_json: list[dict[str, Any]] | None = None
    created_at: str | None = None


class FindingsResponse(BaseModel):
    case_id: uuid.UUID
    stale: bool
    findings: list[FindingResponseItem] = Field(default_factory=list)


class LinkResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    from_type: str
    from_id: uuid.UUID
    to_type: str
    to_id: uuid.UUID
    method: str
    confidence: Decimal | None = None
    confirmed: bool
    status: str
    reason: str | None = None
    evidence_fact_ids: list[str] | None = None

    class Config:
        from_attributes = True
