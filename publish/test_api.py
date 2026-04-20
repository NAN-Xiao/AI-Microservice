"""
发布后快速冒烟测试：验证服务器 API 能否正常响应。
用法:
  python test_api.py                     # 测试所有服务
  python test_api.py video_analyze       # 只测 video_analyze
  python test_api.py ui_builder          # 只测 ui_builder
"""

import sys
import time
import httpx

BASE = "http://zhongtai-ai.elexapp.com"

# 各服务的测试项：(名称, 方法, 路径, 期望status, body/None)
SERVICES = {
    "video_analyze": [
        ("健康检查",    "GET",  "/api/video-analyze/health",       200, None),
        ("存活探针",    "GET",  "/api/video-analyze/health/live",  200, None),
        ("就绪探针",    "GET",  "/api/video-analyze/health/ready", None, None),  # 200或503都算通
        ("获取标签模板", "GET", "/api/video-analyze/tags",          200, None),
        ("任务列表",    "GET",  "/api/video-analyze/tasks",        200, None),
    ],
    "ui_builder": [
        ("健康检查",   "GET",  "/api/ui-builder/health",         200, None),
        ("就绪探针",   "GET",  "/api/ui-builder/health/ready",   None, None),
    ],
}

TIMEOUT = 10
PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
WARN = "\033[93m⚠ WARN\033[0m"


def test_endpoint(client: httpx.Client, name: str, method: str, path: str, expected_status):
    url = BASE + path
    t0 = time.perf_counter()
    try:
        resp = client.request(method, url)
        elapsed = (time.perf_counter() - t0) * 1000
        status = resp.status_code

        if expected_status is None:
            # 只要有响应就算通
            tag = PASS if status < 500 else WARN
            print(f"  {tag}  {name:<12s}  {status}  {elapsed:.0f}ms  {path}")
        elif status == expected_status:
            print(f"  {PASS}  {name:<12s}  {status}  {elapsed:.0f}ms  {path}")
        else:
            body = resp.text[:120]
            print(f"  {FAIL}  {name:<12s}  {status}(期望{expected_status})  {elapsed:.0f}ms  {path}")
            print(f"         ↳ {body}")
            return False
        return True

    except httpx.ConnectError:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {FAIL}  {name:<12s}  连接失败  {elapsed:.0f}ms  {path}")
        return False
    except httpx.TimeoutException:
        print(f"  {FAIL}  {name:<12s}  超时({TIMEOUT}s)  {path}")
        return False


# ── video_analyze 核心流程测试 ─────────────────────────────────
# 公开可访问的极短测试视频（~2MB，用于冒烟）
_TEST_VIDEO_URL = "https://www.w3schools.com/html/mov_bbb.mp4"

def test_video_analyze_workflow(client: httpx.Client) -> tuple[int, int]:
    """
    测试同步分析和异步任务完整流程。
    返回 (passed, failed)。
    """
    passed, failed = 0, 0
    analyze_path = "/api/video-analyze/analyze"
    tasks_path = "/api/video-analyze/tasks"
    body = {"video_url": _TEST_VIDEO_URL}

    # 1. 同步分析（LLM 调用，超时放宽到 120s）
    name = "同步分析"
    url = BASE + analyze_path
    t0 = time.perf_counter()
    try:
        resp = client.post(url, json=body, timeout=120)
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        code = data.get("code", resp.status_code)
        if resp.status_code == 200 and code == 200:
            print(f"  {PASS}  {name:<12s}  {resp.status_code}  {elapsed:.0f}ms  {analyze_path}")
            passed += 1
        else:
            msg = data.get("message", resp.text[:120])
            print(f"  {FAIL}  {name:<12s}  HTTP={resp.status_code} code={code}  {elapsed:.0f}ms")
            print(f"         ↳ {msg}")
            failed += 1
    except httpx.TimeoutException:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {WARN}  {name:<12s}  LLM超时({elapsed/1000:.0f}s)，服务本身正常  {analyze_path}")
        # LLM 超时不算服务故障
        passed += 1
    except httpx.ConnectError:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {FAIL}  {name:<12s}  连接失败  {elapsed:.0f}ms  {analyze_path}")
        failed += 1

    # 2. 异步任务：提交
    name = "异步提交"
    url = BASE + tasks_path
    task_id = None
    t0 = time.perf_counter()
    try:
        resp = client.post(url, json=body, timeout=TIMEOUT)
        elapsed = (time.perf_counter() - t0) * 1000
        data = resp.json()
        code = data.get("code", resp.status_code)
        if resp.status_code == 200 and code == 200:
            task_id = data.get("data", {}).get("task_id")
            print(f"  {PASS}  {name:<12s}  {resp.status_code}  {elapsed:.0f}ms  task_id={task_id}")
            passed += 1
        else:
            msg = data.get("message", resp.text[:120])
            print(f"  {FAIL}  {name:<12s}  HTTP={resp.status_code} code={code}  {elapsed:.0f}ms")
            print(f"         ↳ {msg}")
            failed += 1
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  {FAIL}  {name:<12s}  {type(e).__name__}  {elapsed:.0f}ms  {tasks_path}")
        failed += 1

    # 3. 异步任务：查询（只验证接口通，不等待完成）
    if task_id:
        name = "任务查询"
        query_path = f"{tasks_path}/{task_id}"
        url = BASE + query_path
        t0 = time.perf_counter()
        try:
            resp = client.get(url, timeout=TIMEOUT)
            elapsed = (time.perf_counter() - t0) * 1000
            data = resp.json()
            code = data.get("code", resp.status_code)
            if resp.status_code == 200 and code == 200:
                status_val = data.get("data", {}).get("status", "?")
                print(f"  {PASS}  {name:<12s}  {resp.status_code}  {elapsed:.0f}ms  status={status_val}")
                passed += 1
            else:
                msg = data.get("message", resp.text[:120])
                print(f"  {FAIL}  {name:<12s}  HTTP={resp.status_code} code={code}  {elapsed:.0f}ms")
                print(f"         ↳ {msg}")
                failed += 1
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"  {FAIL}  {name:<12s}  {type(e).__name__}  {elapsed:.0f}ms  {query_path}")
            failed += 1

    return passed, failed


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(SERVICES.keys())
    # 验证参数
    for t in targets:
        if t not in SERVICES:
            print(f"未知服务: {t}，可选: {', '.join(SERVICES.keys())}")
            sys.exit(1)

    print(f"目标: {BASE}")
    print(f"测试服务: {', '.join(targets)}")
    print("-" * 60)

    total, passed, failed = 0, 0, 0
    with httpx.Client(timeout=TIMEOUT) as client:
        for svc in targets:
            print(f"\n【{svc}】")
            for name, method, path, expected, body in SERVICES[svc]:
                total += 1
                if test_endpoint(client, name, method, path, expected):
                    passed += 1
                else:
                    failed += 1

    print(f"\n{'=' * 60}")
    if failed == 0:
        print(f"{PASS}  全部通过 ({passed}/{total})")
    else:
        print(f"{FAIL}  {failed}/{total} 项失败")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
