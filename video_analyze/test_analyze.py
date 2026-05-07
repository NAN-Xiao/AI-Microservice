"""
Video Analyze Clip API 测试脚本

测试接口：
  POST /api/video-analyze/clip
  POST /api/video-analyze/clip/tasks
  GET  /api/video-analyze/clip/tasks/{task_id}
"""

import io
import json
import sys
import time
from typing import Any

# 修复 Windows GBK 控制台编码问题
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

BASE_URL = "http://10.1.6.76:9001"
VIDEO_URL = "https://vidio-1300638412.cos.ap-beijing.myqcloud.com/00cb5464426850d5_17.mp4"
CLIP_PROMPT = "切片尽量控制在 3 到 8 秒"

# 超时（秒）：LLM 处理视频可能耗时较长
SYNC_TIMEOUT = 600
SUBMIT_TIMEOUT = 30
POLL_TIMEOUT = 10
POLL_INTERVAL = 5
POLL_MAX_WAIT = 600
ASYNC_TASK_COUNT = 3


def separator(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def pretty(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def clip_payload() -> dict[str, str]:
    return {
        "video_url": VIDEO_URL,
        "prompt": CLIP_PROMPT,
    }


def validate_clip_result(result: Any) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, f"result 应为 object，实际为 {type(result).__name__}"

    instructions = result.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        return False, "result.instructions 应为非空数组"

    emotion = result.get("emotion")
    if not isinstance(emotion, str) or not emotion.strip():
        return False, "result.emotion 应为非空字符串"

    for idx, item in enumerate(instructions):
        if not isinstance(item, dict):
            return False, f"instructions[{idx}] 应为 object"
        for field in ("start", "end", "time_str", "content"):
            if field not in item:
                return False, f"instructions[{idx}] 缺少字段 {field}"
        if not isinstance(item["start"], int) or not isinstance(item["end"], int):
            return False, f"instructions[{idx}] start/end 应为整数"
        if item["end"] <= item["start"]:
            return False, f"instructions[{idx}] 时间范围非法"
        if not str(item["time_str"]).strip() or not str(item["content"]).strip():
            return False, f"instructions[{idx}] time_str/content 不能为空"

    return True, "ok"


def test_sync_clip() -> bool:
    separator("1. 同步切片分析  POST /api/video-analyze/clip")
    url = f"{BASE_URL}/api/video-analyze/clip"
    payload = clip_payload()

    print(f"请求 URL:  {url}")
    print(f"视频地址:  {VIDEO_URL}")
    print(f"提示词:    {CLIP_PROMPT}")
    print(f"超时设置:  {SYNC_TIMEOUT}s")
    print("请求中（LLM 切片分析可能需要数分钟）...")

    start = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=SYNC_TIMEOUT)
        elapsed = time.time() - start
        print(f"\nStatus: {resp.status_code}  耗时: {elapsed:.1f}s")

        data = resp.json()
        pretty(data)

        if resp.status_code != 200 or data.get("code") != 200:
            print(f"❌ 同步切片接口失败: http={resp.status_code} code={data.get('code')}")
            return False

        ok, message = validate_clip_result(data.get("data"))
        if not ok:
            print(f"❌ 同步切片返回结构错误: {message}")
            return False

        print("✅ 同步切片分析成功")
        return True

    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"❌ 同步切片分析超时 ({elapsed:.1f}s)")
        return False
    except Exception as e:
        print(f"❌ 同步切片分析异常: {e}")
        return False


def test_submit_clip_tasks() -> list[str]:
    separator(f"2. 提交切片任务  POST /api/video-analyze/clip/tasks × {ASYNC_TASK_COUNT}")
    url = f"{BASE_URL}/api/video-analyze/clip/tasks"
    payload = clip_payload()
    task_ids: list[str] = []

    print(f"请求 URL: {url}")
    for idx in range(1, ASYNC_TASK_COUNT + 1):
        print(f"\n--- 提交第 {idx}/{ASYNC_TASK_COUNT} 个切片任务 ---")
        try:
            resp = requests.post(url, json=payload, timeout=SUBMIT_TIMEOUT)
            print(f"Status: {resp.status_code}")

            data = resp.json()
            pretty(data)

            if resp.status_code != 200 or data.get("code") != 200:
                print(f"❌ 提交切片任务失败: http={resp.status_code} code={data.get('code')}")
                return task_ids

            task_id = ((data.get("data") or {}).get("task_id") or "").strip()
            status = (data.get("data") or {}).get("status")
            if not task_id:
                print("❌ 提交切片任务返回缺少 task_id")
                return task_ids
            if status not in ("pending", "processing"):
                print(f"❌ 提交切片任务返回状态异常: {status}")
                return task_ids

            task_ids.append(task_id)
            print(f"✅ 切片任务提交成功: task_id={task_id}")

        except Exception as e:
            print(f"❌ 提交切片任务异常: {e}")
            return task_ids

    return task_ids


def test_query_clip_tasks(task_ids: list[str]) -> bool:
    separator("3. 查询切片任务  GET /api/video-analyze/clip/tasks/{task_id}")
    if not task_ids:
        print("❌ 没有可查询的 task_id")
        return False

    print(f"任务数量: {len(task_ids)}")
    print(f"轮询间隔: {POLL_INTERVAL}s，最多等待: {POLL_MAX_WAIT}s")

    task_status: dict[str, str] = {task_id: "pending" for task_id in task_ids}
    start = time.time()
    while time.time() - start < POLL_MAX_WAIT:
        elapsed = time.time() - start
        completed = 0
        failed = 0

        for task_id in task_ids:
            if task_status.get(task_id) in ("completed", "failed"):
                if task_status[task_id] == "completed":
                    completed += 1
                else:
                    failed += 1
                continue

            url = f"{BASE_URL}/api/video-analyze/clip/tasks/{task_id}"
            try:
                resp = requests.get(url, timeout=POLL_TIMEOUT)
                data = resp.json()
                task_data = data.get("data") or {}
                status = task_data.get("status")
                task_status[task_id] = status

                print(f"\n[{elapsed:5.1f}s] task_id={task_id}  http={resp.status_code}  task_status={status}")
                pretty(data)

                if resp.status_code != 200 or data.get("code") != 200:
                    print(f"❌ 查询切片任务失败: http={resp.status_code} code={data.get('code')}")
                    return False

                if task_data.get("task_type") != "clip":
                    print(f"❌ task_type 异常: {task_data.get('task_type')}")
                    return False

                if status == "completed":
                    ok, message = validate_clip_result(task_data.get("result"))
                    if not ok:
                        print(f"❌ 切片任务结果结构错误: {message}")
                        return False
                    completed += 1
                elif status == "failed":
                    failed += 1
                    print(f"❌ 切片任务失败: {task_data.get('error')}")
                elif status not in ("pending", "processing"):
                    print(f"❌ 未知任务状态: {status}")
                    return False

            except requests.exceptions.Timeout:
                print(f"⚠️  查询超时，继续轮询: task_id={task_id}")
            except Exception as e:
                print(f"❌ 查询切片任务异常: {e}")
                return False

        print(f"\n[{elapsed:5.1f}s] completed={completed}/{len(task_ids)} failed={failed}/{len(task_ids)}")
        if completed + failed == len(task_ids):
            if failed:
                print("❌ 切片任务查询失败，存在 failed 任务")
                return False
            print("✅ 切片任务查询成功，全部任务已完成")
            return True

        time.sleep(POLL_INTERVAL)

    unfinished = [task_id for task_id, status in task_status.items() if status not in ("completed", "failed")]
    print(f"❌ 轮询超时（等待 {POLL_MAX_WAIT}s），未完成任务数: {len(unfinished)}")
    for task_id in unfinished:
        print(f"  - {task_id}: {task_status.get(task_id)}")
    return False


def main() -> None:
    print("=" * 60)
    print("  Video Analyze Clip API 测试")
    print(f"  Base URL: {BASE_URL}")
    print(f"  Video:    {VIDEO_URL}")
    print(f"  Prompt:   {CLIP_PROMPT}")
    print(f"  Async:    {ASYNC_TASK_COUNT} 个切片任务，每 {POLL_INTERVAL}s 轮询")
    print("=" * 60)

    results: dict[str, bool] = {}

    results["同步切片分析"] = test_sync_clip()

    task_ids = test_submit_clip_tasks()
    results["提交切片任务"] = len(task_ids) == ASYNC_TASK_COUNT
    results["查询切片任务"] = test_query_clip_tasks(task_ids) if task_ids else False

    separator("测试结果汇总")
    for name, passed in results.items():
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  总计: {passed}/{total} 通过")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
