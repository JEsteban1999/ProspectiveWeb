"""WebSocket progress router — real-time processing feedback."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/api", tags=["progress"])


async def _send(ws: WebSocket, event: str, step: str, pct: int, message: str) -> None:
    await ws.send_text(json.dumps({
        "event": event,
        "step": step,
        "pct": pct,
        "message": message,
        "detail": None,
    }))


@router.websocket("/progress/{session_id}")
async def progress_ws(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint that streams processing progress.

    The client connects once and receives ProgressEvent JSON messages
    until the pipeline finishes ("done") or fails ("error").

    Mock implementation: simulates a full segmentation run with realistic
    timing so the UI progress bar can be developed and tested.
    """
    await websocket.accept()

    try:
        steps = [
            ("reading_dicom",          5,  "Leyendo archivos DICOM…"),
            ("computing_thresholds",  15,  "Calculando umbrales automáticos…"),
            ("segmenting",            35,  "Segmentando volumen (marching cubes)…"),
            ("segmenting",            55,  "Segmentando volumen…"),
            ("cleaning_mesh",         70,  "Limpiando fragmentos desconectados…"),
            ("smoothing_mesh",        85,  "Suavizando malla…"),
            ("smoothing_mesh",        95,  "Finalizando malla…"),
            ("done",                 100,  "Segmentación completada"),
        ]

        for step_name, pct, msg in steps:
            event = "done" if step_name == "done" else "progress"
            await _send(websocket, event, step_name, pct, msg)
            await asyncio.sleep(0.6)   # simulate processing time

    except WebSocketDisconnect:
        pass   # client disconnected — normal during navigation
