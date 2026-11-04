"""Planning-graph state. Flat, typed, lean (no result rows, no blobs), versioned."""

import operator
from datetime import date
from typing import Annotated, Literal, TypedDict

from app.llm.base import ChatTurn, Usage

STATE_VERSION = 2

Outcome = Literal["blocked", "answered", "clarification", "access_required", "rejected", "awaiting_approval"]
RiskLevel = Literal["low", "high"]


class PlanState(TypedDict, total=False):
    state_version: int

    # ---- inputs (set by the caller) ----
    question: str
    history: list[ChatTurn]
    accessible_datasets: list[str]
    today: date

    # ---- analyze_question ----
    intent: str
    standalone_question: str
    needs_clarification: bool
    clarification_question: str | None
    dataset_candidates: list[str]
    direct_reply: str | None

    # ---- select_dataset / check_access ----
    dataset_code: str | None

    # ---- generate_sql / validate_sql (override reducers) ----
    draft_sql: str | None
    interpretation: str | None
    assumptions: list[str]
    sql: str | None  # validated + limited; the only SQL that may be shown for approval
    validation_errors: list[str]
    attempts: int
    from_cache: bool

    # ---- assess_risk / terminal ----
    risk_level: RiskLevel | None
    block_reason: str | None
    outcome: Outcome
    reply: str

    # ---- accounting (append reducer) ----
    usage: Annotated[list[Usage], operator.add]
