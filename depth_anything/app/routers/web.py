from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

from app.config import PROJECT_ROOT

router = APIRouter(tags=["Web UI"])

_UI_FILE = PROJECT_ROOT / "resources" / "web" / "index.html"


@router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/api/depth-anything/ui", status_code=302)


@router.get("/api/depth-anything/ui", include_in_schema=False)
async def api_ui():
    return FileResponse(_UI_FILE)


@router.get("/api/depth-anything", include_in_schema=False)
@router.get("/api/depth-anything/", include_in_schema=False)
async def api_root():
    return RedirectResponse(url="/api/depth-anything/ui", status_code=302)
