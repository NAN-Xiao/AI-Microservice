"""
内存任务存储：追踪每个分析任务的阶段、进度百分比和最终结果。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    task_id: str
    status: str = "pending"         # pending / running / done / error
    step: str = "已提交"
    message: str = ""
    result: Any = None
    error_code: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


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
    return d


def cleanup_old(max_age: float = 600):
    """清理超过 max_age 秒的已完成/失败任务，防止内存泄漏。"""
    now = time.time()
    to_remove = [
        tid for tid, t in _tasks.items()
        if t.status in ("done", "error") and (now - t.updated_at) > max_age
    ]
    for tid in to_remove:
        del _tasks[tid]
