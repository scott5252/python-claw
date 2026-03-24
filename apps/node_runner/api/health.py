from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "python-claw-node-runner"}


@router.get("/health/ready")
def ready() -> dict[str, str]:
    return {"status": "ok", "service": "python-claw-node-runner"}
