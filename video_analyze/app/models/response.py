from __future__ import annotations
from typing import Any, Optional

from pydantic import BaseModel


class ApiResult(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any = None
    request_id: Optional[str] = None

    @classmethod
    def ok(cls, data: Any = None, request_id: str | None = None) -> ApiResult:
        return cls(code=200, message="success", data=data, request_id=request_id)

    @classmethod
    def error(cls, code: int, message: str, request_id: str | None = None) -> ApiResult:
        return cls(code=code, message=message, request_id=request_id)
