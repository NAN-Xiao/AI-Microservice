import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from app.models.response import ApiResult
from app.services.comfy_client import ComfyError, convert_image_to_psd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image2psd", tags=["图片转PSD"])

MAX_IMAGE_SIZE = 30 * 1024 * 1024


@router.post("/convert")
async def convert_to_psd(image: UploadFile = File(..., description="输入图片（png/jpg/webp）")):
    if not image.content_type or not image.content_type.startswith("image/"):
        return ApiResult.error(400, f"仅支持图片文件，当前类型: {image.content_type}")

    image_bytes = await image.read()
    if not image_bytes:
        return ApiResult.error(400, "图片内容为空")

    if len(image_bytes) > MAX_IMAGE_SIZE:
        return ApiResult.error(400, f"图片过大，最大 {MAX_IMAGE_SIZE // (1024 * 1024)} MB")

    filename = image.filename or "input.png"

    try:
        psd_bytes, psd_name = await convert_image_to_psd(image_bytes, filename, image.content_type)
    except ComfyError as exc:
        logger.warning("转换失败: %s", exc)
        return ApiResult.error(502, str(exc))
    except httpx.HTTPError as exc:
        logger.warning("ComfyUI HTTP 错误: %s", exc)
        return ApiResult.error(502, "调用 ComfyUI 失败")
    except Exception:
        logger.exception("转换异常")
        return ApiResult.error(500, "转换失败，请稍后重试")

    safe_name = Path(psd_name).name
    if not safe_name.lower().endswith(".psd"):
        safe_name = f"{Path(filename).stem}.psd"

    return Response(
        content=psd_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )
