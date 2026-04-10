"""
内存任务存储：追踪每个分析任务的阶段、进度百分比和最终结果。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    task_id: str
    status: str = "pending"         # pending / running / done / error / cancelled
    step: str = "已提交"
    message: str = ""
    result: Any = None
    error_code: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


_tasks: dict[str, Task] = {}


def create(task_id: str) -> Task:
    t = Task(task_id=task_id, status="pending", step="已提交")
    _tasks[task_id] = t
    return t


def get(task_id: str) -> Task | None:
    return _tasks.get(task_id)


def update_step(task_id: str, step: str):
    t = _tasks.get(task_id)
    if not t:
        return
    t.step = step
    t.status = "running"
    t.updated_at = time.time()


def complete(task_id: str, result: Any):
    t = _tasks.get(task_id)
    if not t:
        return
    t.status = "done"
    t.step = "完成"
    t.result = result
    t.updated_at = time.time()


def fail(task_id: str, error_code: int, message: str):
    t = _tasks.get(task_id)
    if not t:
        return
    t.status = "error"
    t.error_code = error_code
    t.message = message
    t.updated_at = time.time()


def cancel(task_id: str) -> bool:
    """请求取消任务。返回 True 表示已发出取消信号。"""
    t = _tasks.get(task_id)
    if not t:
        return False
    if t.status in ("done", "error", "cancelled"):
        return False
    t.cancel_event.set()
    t.status = "cancelled"
    t.step = "已取消"
    t.message = "用户取消了任务"
    t.updated_at = time.time()
    return True


def is_cancelled(task_id: str) -> bool:
    t = _tasks.get(task_id)
    return t is not None and t.cancel_event.is_set()


def to_dict(t: Task) -> dict:
    d = {
        "taskId": t.task_id,
        "status": t.status,
        "step": t.step,
    }
    if t.status == "done":
        d["result"] = t.result
    if t.status == "error":
        d["errorCode"] = t.error_code
        d["message"] = t.message
    if t.status == "cancelled":
        d["message"] = t.message
    return d


def cleanup_old(max_age: float = 600):
    """清理超过 max_age 秒的已完成/失败/取消任务，防止内存泄漏。"""
    now = time.time()
    to_remove = [
        tid for tid, t in _tasks.items()
        if t.status in ("done", "error", "cancelled") and (now - t.updated_at) > max_age
    ]
    for tid in to_remove:
        del _tasks[tid]


def task_store_summary() -> dict:
    """返回任务统计信息，供健康检查接口使用。"""
    stats: dict[str, int] = {}
    for t in _tasks.values():
        stats[t.status] = stats.get(t.status, 0) + 1
    return {"total": len(_tasks), **stats}
