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
    custom_tags: Optional[dict] = None

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
        self._cleanup_handle: asyncio.TimerHandle | None = None

    def start_periodic_cleanup(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """启动定期清理（每 60 秒），在 lifespan 中调用。"""
        interval = 60

        def _schedule():
            self._cleanup_expired_sync()
            self._cleanup_handle = asyncio.get_event_loop().call_later(interval, _schedule)

        self._cleanup_handle = (loop or asyncio.get_event_loop()).call_later(interval, _schedule)

    def stop_periodic_cleanup(self) -> None:
        if self._cleanup_handle:
            self._cleanup_handle.cancel()
            self._cleanup_handle = None

    async def create(self, video_url: str, *, custom_tags: dict | None = None) -> Task:
        task_id = uuid.uuid4().hex
        task = Task(task_id=task_id, video_url=video_url, custom_tags=custom_tags)
        async with self._lock:
            self._cleanup_expired()
            # 超过上限时驱逐最旧的已完成/失败任务
            if len(self._tasks) >= self._max_tasks:
                self._evict_oldest()
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

    def _cleanup_expired_sync(self) -> None:
        """非 async 版本，供定时器回调使用。"""
        self._cleanup_expired()

    def _evict_oldest(self) -> None:
        """驱逐最旧的已结束任务（completed/failed），腾出空间。"""
        finished = [
            (tid, t) for tid, t in self._tasks.items()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        if not finished:
            return
        finished.sort(key=lambda x: x[1].created_at)
        to_remove = finished[: max(1, len(finished) // 4)]  # 驱逐 25% 或至少 1 个
        for tid, _ in to_remove:
            del self._tasks[tid]
        logger.debug("驱逐旧任务: %d 个", len(to_remove))


task_store = TaskStore()
