"""Audit trail (SkullChain) models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AuditAppendRequest(BaseModel):
    action: str = Field(..., description="Action name, e.g. DEVICE_PLACED")
    payload: dict = Field(default_factory=dict, description="Arbitrary JSON payload for the event")
    username: str = ""
    patient_id: str = ""
    patient_dob: str = ""


class AuditBlock(BaseModel):
    id: int
    iso_ts: str
    username: str
    action: str
    patient_hash: str
    payload_json: str
    block_hash: str
    prev_hash: str


class BrokenBlock(BaseModel):
    id: int
    iso_ts: str
    action: str
    reason: str


class AuditVerifyResult(BaseModel):
    ok: bool = Field(..., description="True if the whole chain verifies")
    total_blocks: int
    broken: list[BrokenBlock] = Field(default_factory=list)
