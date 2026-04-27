from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from app.config import PROJECT_ROOT

router = APIRouter(tags=["Web UI"])

_UI_FILE = PROJECT_ROOT / "resources" / "web" / "index.html"


@router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/ui", status_code=302)


@router.get("/ui", include_in_schema=False)
async def ui():
    return FileResponse(_UI_FILE)
