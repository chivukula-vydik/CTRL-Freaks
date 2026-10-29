"""API contract (Section 6). Field names are fixed: judges script against them."""
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AnswerType(str, Enum):
    retrieved_fact = "retrieved_fact"
    calculated = "calculated"
    not_found = "not_found"
    clarification_needed = "clarification_needed"
    refused = "refused"
    conflict_flagged = "conflict_flagged"


NOT_FOUND_MSG = "I could not find this information in the authorised sources."


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of_date: date | None = None



class CalcRequest(BaseModel):
    """Direct call of a pipeline metric (app/pipeline.py), no question parsing."""
    metric: str
    filters: dict | None = None
    group_by: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class Citation(BaseModel):
    doc_id: str
    title: str
    section: str | None = None
    page: int | None = None
    version: str | None = None
    effective_from: str | None = None


class ToolCall(BaseModel):
    tool: str
    input: dict[str, Any] = {}
    output: dict[str, Any] = {}


class AppliedRule(BaseModel):
    rule_id: str
    parameter: str | None = None
    value: Any
    source_doc_id: str
    source_section: str | None = None


class Conflict(BaseModel):
    parameter: str
    winner: str
    losers: list[str] = []
    resolution: list[str] = []


class AskResponse(BaseModel):
    trace_id: str
    answer: str
    answer_type: AnswerType
    citations: list[Citation] = []
    tools_invoked: list[ToolCall] = []
    applied_rules: list[AppliedRule] = []
    conflicts_detected: list[Conflict] = []
    upcoming_changes: list[str] = []
    assumptions: list[str] = []
    explanation: str = ""
    as_of_date: str


class RuleIn(BaseModel):
    rule_id: str
    description: str = ""
    parameter: str
    operator: str = "="
    value: str
    scope_categories: str = "ALL"
    scope_tiers: str = "ALL"
    effective_from: str | None = None  # defaults to the doc's effective_from
    effective_to: str | None = None
    source_section: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _str(cls, v):
        return str(v)


class IngestMeta(BaseModel):
    """Annex B Source Register fields, plus optional rules the doc introduces/changes."""
    doc_id: str
    title: str
    issuer: str = ""
    authority_level: int = Field(ge=1, le=5)
    doc_type: str = "notice"
    version: str = "1.0"
    effective_from: str
    effective_to: str | None = None
    supersedes: str = ""
    scope_categories: str = "ALL"
    scope_tiers: str = "ALL"
    provenance: str = ""
    retrieved_on: str = ""
    synthetic: str = "N"
    rules: list[RuleIn] = []
    extract_rules: bool = False  # ask the LLM to propose rules if none are given

    @field_validator("effective_to", mode="before")
    @classmethod
    def _empty_none(cls, v):
        return v or None


class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: str
    rules_added: list[str] = []
    warnings: list[str] = []
