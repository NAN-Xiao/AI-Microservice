"""
请求进度打印（仅控制台，不写日志文件）。
用彩色 + 计时让开发者在终端里一眼看到当前请求走到哪一步、耗时多久。
"""

import time
import sys

_REQ_START: dict[str, float] = {}
_STEP_START: dict[str, float] = {}

# ANSI 颜色
_CYAN    = "\033[96m"
_GREEN   = "\033[92m"
_YELLOW  = "\033[93m"
_RED     = "\033[91m"
_MAGENTA = "\033[95m"
_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _elapsed(start: float) -> str:
    d = time.time() - start
    if d < 1:
        return f"{d * 1000:.0f}ms"
    return f"{d:.1f}s"


def request_start(req_id: str, filename: str, size_kb: int, extra: str = ""):
    _REQ_START[req_id] = time.time()
    extra_part = f" | 额外提示: {extra[:40]}…" if extra else ""
    print(
        f"\n{_BOLD}{_CYAN}{'━' * 60}\n"
        f"  ▶ 新请求  [{_ts()}]  {req_id[:8]}\n"
        f"    图片: {filename} ({size_kb} KB){extra_part}\n"
        f"{'━' * 60}{_RESET}",
        flush=True,
    )


def step(req_id: str, name: str, detail: str = ""):
    _STEP_START[req_id] = time.time()
    tail = f"  {_DIM}{detail}{_RESET}" if detail else ""
    print(f"  {_YELLOW}⏳ [{_ts()}] {name}{_RESET}{tail}", flush=True)


def step_done(req_id: str, name: str, detail: str = ""):
    cost = ""
    if req_id in _STEP_START:
        cost = f" ({_elapsed(_STEP_START.pop(req_id))})"
    tail = f"  {_DIM}{detail}{_RESET}" if detail else ""
    print(f"  {_GREEN}✔  [{_ts()}] {name}{cost}{_RESET}{tail}", flush=True)


def request_ok(req_id: str, summary: str = ""):
    total = ""
    if req_id in _REQ_START:
        total = f"  总耗时 {_elapsed(_REQ_START.pop(req_id))}"
    tail = f"  {_DIM}{summary}{_RESET}" if summary else ""
    print(
        f"  {_BOLD}{_GREEN}✅ [{_ts()}] 请求完成{total}{_RESET}{tail}\n",
        flush=True,
    )


def request_fail(req_id: str, reason: str):
    total = ""
    if req_id in _REQ_START:
        total = f"  总耗时 {_elapsed(_REQ_START.pop(req_id))}"
    _STEP_START.pop(req_id, None)
    print(
        f"  {_BOLD}{_RED}❌ [{_ts()}] 请求失败{total}{_RESET}\n"
        f"     {_RED}{reason}{_RESET}\n",
        file=sys.stderr,
        flush=True,
    )
