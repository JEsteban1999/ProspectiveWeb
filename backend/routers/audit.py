"""Tamper-evident audit trail (SkullChain) router."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from models.audit import AuditAppendRequest, AuditBlock, AuditVerifyResult
from services.audit import SkullChain, ACT_INTEGRITY_CHECK

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.post("", summary="Append an event to the audit chain")
async def append_event(req: AuditAppendRequest) -> dict:
    block_hash = SkullChain.instance().append(
        req.action, req.payload, req.username, req.patient_id, req.patient_dob,
    )
    return {"block_hash": block_hash}


@router.get(
    "/blocks",
    response_model=list[AuditBlock],
    summary="List all audit-trail blocks",
    description="Returns every block of the tamper-evident SkullChain audit trail, oldest first.",
)
async def list_blocks() -> list[AuditBlock]:
    return [AuditBlock(**b) for b in SkullChain.instance().get_all_blocks()]


@router.get(
    "/verify",
    response_model=AuditVerifyResult,
    summary="Verify the integrity of the audit chain",
    description=(
        "Recomputes every block hash and checks the prev-hash linkage. Any "
        "tampering with a block invalidates it and all following blocks."
    ),
)
async def verify_chain() -> AuditVerifyResult:
    chain = SkullChain.instance()
    ok, broken = chain.verify_integrity()
    # Record that a verification was run (does not affect the result reported).
    chain.append(ACT_INTEGRITY_CHECK, {"ok": ok, "broken": len(broken)})
    return AuditVerifyResult(ok=ok, total_blocks=len(chain.get_all_blocks()), broken=broken)


@router.get("/export", response_class=PlainTextResponse, summary="Export the audit trail as text")
async def export_txt() -> str:
    return SkullChain.instance().export_txt()
