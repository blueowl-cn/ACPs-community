import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Request

from acps_ca_challenge.config import settings

router_status = APIRouter()
LOGGER = logging.getLogger("challenge_server")
BASE_URL=settings.BASE_URL.rstrip("/") or "/"

def iter_challenge_files(challenge_dir: Path) -> Iterable[Path]:
    if not challenge_dir.is_dir():
        return ()
    return (path for path in challenge_dir.rglob("*") if path.is_file())


@router_status.get("/status", tags=["System"])
async def status_check(request: Request):
    """状态检查端点。"""

    payload = {
        "server": "Agent HTTP-01 Challenge Server",
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": settings.UVICORN_HOST,
        "port": settings.UVICORN_PORT,
        "api_base_path": BASE_URL,
        "challenge_dir": str(settings.CHALLENGE_DIR),
        "challenges_count": sum(1 for _ in iter_challenge_files(settings.CHALLENGE_DIR)),
    }
    return payload

