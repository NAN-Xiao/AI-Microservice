from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiResult(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any = None

    @classmethod
    def ok(cls, data: Any = None) -> "ApiResult":
        return cls(code=200, message="success", data=data)

    @classmethod
    def error(cls, code: int, message: str) -> "ApiResult":
        return cls(code=code, message=message)
