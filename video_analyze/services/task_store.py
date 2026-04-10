"""
异步任务存储。
管理视频分析任务的生命周期：pending → processing → completed / failed。
支持轮询查询、自动清理过期任务。
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    video_url: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    error_code: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    extra_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "video_url": self.video_url,
            "status": self.status.value,
            "created_at": self.created_at,
        }
        if self.started_at:
            d["started_at"] = self.started_at
        if self.finished_at:
            d["finished_at"] = self.finished_at
            d["duration_seconds"] = round(self.finished_at - (self.started_at or self.created_at), 2)
        if self.status == TaskStatus.COMPLETED:
            d["result"] = self.result
        if self.status == TaskStatus.FAILED:
            d["error"] = self.error
            d["error_code"] = self.error_code
        return d


class TaskStore:
    """线程安全的任务存储，支持自动清理。"""

    def __init__(self, max_tasks: int = 1000, expire_seconds: int = 3600):
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._max_tasks = max_tasks
        self._expire_seconds = expire_seconds

    async def create(self, video_url: str, extra_prompt: str = "") -> Task:
        task_id = uuid.uuid4().hex
        task = Task(task_id=task_id, video_url=video_url, extra_prompt=extra_prompt)
        async with self._lock:
            self._cleanup_expired()
            self._tasks[task_id] = task
        logger.info("任务已创建: %s -> %s", task_id[:8], video_url)
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        async with self._lock:
            return self._tasks.get(task_id)

    async def set_processing(self, task_id: str) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.PROCESSING
                task.started_at = time.time()

    async def set_completed(self, task_id: str, result: dict) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.finished_at = time.time()
        logger.info("任务完成: %s", task_id[:8])

    async def set_failed(self, task_id: str, error: str, error_code: int = 500) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error = error
                task.error_code = error_code
                task.finished_at = time.time()
        logger.warning("任务失败: %s — %s", task_id[:8], error)

    async def list_all(self) -> list[dict]:
        async with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            tid for tid, t in self._tasks.items()
            if now - t.created_at > self._expire_seconds
        ]
        for tid in expired:
            del self._tasks[tid]
        if expired:
            logger.debug("清理过期任务: %d 个", len(expired))

        # 超过容量上限时清理最老的
        if len(self._tasks) >= self._max_tasks:
            sorted_tasks = sorted(self._tasks.items(), key=lambda x: x[1].created_at)
            to_remove = len(self._tasks) - self._max_tasks + 100  # 多清理一些
            for tid, _ in sorted_tasks[:to_remove]:
                del self._tasks[tid]
            logger.debug("容量清理: 移除 %d 个旧任务", to_remove)


# 全局单例
task_store = TaskStore()
