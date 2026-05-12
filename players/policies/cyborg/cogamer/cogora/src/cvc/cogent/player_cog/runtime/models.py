from __future__ import annotations

from pydantic import BaseModel, Field


class PolicyGenerationRecord(BaseModel):
    step: int
    agent_id: int
    prompt: str
    raw_response: str
    policy_source: str | None = None
    success: bool
    error_message: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ExperienceTraceRecord(BaseModel):
    step: int
    agent_id: int
    summary: str
    policy_source: str = ""
    return_repr: str = ""
    logs: list[str] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ReviewDecisionRecord(BaseModel):
    step: int
    agent_id: int
    trigger_name: str = ""
    action: str
    request_summary: str = ""
    summary: str = ""
    policy_updated: bool = False
    scratchpad_updated: bool = False
    plan_updated: bool = False
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
