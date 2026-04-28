from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from app.config import PROJECT_ROOT

router = APIRouter(tags=["Web UI"])

_UI_FILE = PROJECT_ROOT / "resources" / "web" / "index.html"



@router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/api/see-through/ui", status_code=302)


@router.get("/api/see-through/ui", include_in_schema=False)
async def api_ui():
    return FileResponse(_UI_FILE)


@router.get("/api/see-through", include_in_schema=False)
@router.get("/api/see-through/", include_in_schema=False)
async def api_root():
    return RedirectResponse(url="/api/see-through/ui", status_code=302)
