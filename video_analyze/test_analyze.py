"""
Video Analyze API 测试脚本
测试内容：
  仅执行异步任务并发测试：
  POST /api/video-analyze/tasks → GET /api/video-analyze/tasks/{task_id}
"""

import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 修复 Windows GBK 控制台编码问题
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

BASE_URL = "http://10.1.6.76:9001"
VIDEO_URL = "https://vidio-1300638412.cos.ap-beijing.myqcloud.com/00cb5464426850d5_17.mp4"

# 超时（秒）：同步分析可能耗时较长，LLM 处理视频需要时间
SYNC_TIMEOUT = 600
POLL_INTERVAL = 5
POLL_MAX_WAIT = 600
ASYNC_TASK_COUNT = 15


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def pretty(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ─── 1. 健康检查 ────────────────────────────────────────
def test_health():
    separator("1. 健康检查  GET /api/video-analyze/health")
    url = f"{BASE_URL}/api/video-analyze/health"
    try:
        resp = requests.get(url, timeout=10)
        print(f"Status: {resp.status_code}")
        pretty(resp.json())
        assert resp.status_code == 200, f"健康检查失败: HTTP {resp.status_code}"
        print("✅ 健康检查通过")
        return True
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return False


# ─── 2. 同步分析 ────────────────────────────────────────
def test_sync_analyze():
    separator("2. 同步分析  POST /api/video-analyze/analyze")
    url = f"{BASE_URL}/api/video-analyze/analyze"
    payload = {
        "video_url": VIDEO_URL,
        # tags 不传，使用服务端默认标签体系
    }
    print(f"请求 URL:  {url}")
    print(f"视频地址:  {VIDEO_URL}")
    print(f"超时设置:  {SYNC_TIMEOUT}s")
    print("请求中（LLM 分析视频可能需要数分钟）...")

    start = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=SYNC_TIMEOUT)
        elapsed = time.time() - start
        print(f"\nStatus: {resp.status_code}  耗时: {elapsed:.1f}s")
        data = resp.json()
        pretty(data)

        if data.get("code") == 200:
            print("✅ 同步分析成功")
            return True
        else:
            print(f"⚠️  返回业务错误码: {data.get('code')}")
            return False
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"❌ 同步分析超时 ({elapsed:.1f}s)")
        return False
    except Exception as e:
        print(f"❌ 同步分析异常: {e}")
        return False


# ─── 3. 异步任务提交 + 轮询（10 次） ─────────────────────
def _submit_async_task(submit_url: str, payload: dict, idx: int) -> dict:
    """提交单个异步任务，返回统一结果结构。"""
    try:
        resp = requests.post(submit_url, json=payload, timeout=30)
        data = resp.json()
        if resp.status_code != 200 or data.get("code") != 200:
            return {
                "idx": idx,
                "ok": False,
                "http_status": resp.status_code,
                "code": data.get("code"),
                "message": data.get("message"),
                "task_id": None,
                "response_json": data,
            }
        return {
            "idx": idx,
            "ok": True,
            "http_status": resp.status_code,
            "code": data.get("code"),
            "message": data.get("message"),
            "task_id": data["data"]["task_id"],
            "response_json": data,
        }
    except Exception as e:
        return {
            "idx": idx,
            "ok": False,
            "http_status": None,
            "code": None,
            "message": str(e),
            "task_id": None,
            "response_json": None,
        }


def test_async_task():
    separator(f"3. 异步任务并发测试  POST /api/video-analyze/tasks × {ASYNC_TASK_COUNT}")
    submit_url = f"{BASE_URL}/api/video-analyze/tasks"
    payload = {
        "video_url": VIDEO_URL,
        # tags 不传，使用服务端默认标签体系
    }
    print(f"并发提交任务数: {ASYNC_TASK_COUNT}")
    try:
        submit_results: list[dict] = []
        submit_start = time.time()
        with ThreadPoolExecutor(max_workers=ASYNC_TASK_COUNT) as ex:
            futures = [
                ex.submit(_submit_async_task, submit_url, payload, i + 1)
                for i in range(ASYNC_TASK_COUNT)
            ]
            for f in as_completed(futures):
                submit_results.append(f.result())

        submit_elapsed = time.time() - submit_start
        submit_results.sort(key=lambda x: x["idx"])

        print(f"提交完成，耗时: {submit_elapsed:.2f}s")
        for r in submit_results:
            icon = "✅" if r["ok"] else "❌"
            print(
                f"  {icon} #{r['idx']:02d} "
                f"http={r['http_status']} code={r['code']} "
                f"task_id={r['task_id']}"
            )
            print("    提交接口完整返回参数:")
            pretty(r.get("response_json"))

        failed_submit = [r for r in submit_results if not r["ok"]]
        if failed_submit:
            print(f"\n❌ 存在提交失败任务: {len(failed_submit)}/{ASYNC_TASK_COUNT}")
            for r in failed_submit:
                print(f"  - #{r['idx']:02d}: {r['message']}")
            return False

        task_ids = [r["task_id"] for r in submit_results if r["task_id"]]
        print(f"\n开始轮询 {len(task_ids)} 个任务（间隔 {POLL_INTERVAL}s，最多等待 {POLL_MAX_WAIT}s）...\n")

        task_status: dict[str, str] = {tid: "pending" for tid in task_ids}
        task_result: dict[str, dict] = {}
        start = time.time()

        while time.time() - start < POLL_MAX_WAIT:
            cycle_start = time.time()
            elapsed = time.time() - start
            done = 0
            failed = 0

            for tid in task_ids:
                if task_status.get(tid) in ("completed", "failed"):
                    if task_status[tid] == "completed":
                        done += 1
                    else:
                        failed += 1
                    continue

                poll_url = f"{BASE_URL}/api/video-analyze/tasks/{tid}"
                r = requests.get(poll_url, timeout=10)
                resp_json = r.json()
                task_data = resp_json.get("data", {})
                status = task_data.get("status", "unknown")
                task_status[tid] = status

                # 每次轮询都输出接口返回参数，便于排查任务状态变化
                print(f"    轮询接口完整返回参数（task_id={tid}）:")
                pretty(resp_json)

                if status in ("completed", "failed"):
                    task_result[tid] = task_data
                if status == "completed":
                    done += 1
                elif status == "failed":
                    failed += 1

            print(
                f"  [{elapsed:5.1f}s] completed={done}/{len(task_ids)} "
                f"failed={failed}/{len(task_ids)}"
            )

            if done + failed == len(task_ids):
                print("\n全部任务进入最终态。")
                print(f"  完成: {done}")
                print(f"  失败: {failed}")

                if failed > 0:
                    print("❌ 异步任务并发测试失败（存在 failed）")
                    for tid, data in task_result.items():
                        if data.get("status") == "failed":
                            print(f"  - {tid}: {data.get('error')}")
                    return False

                # 打印一个样例结果，避免日志过长
                first_tid = task_ids[0]
                sample = task_result.get(first_tid, {})
                print(f"\n样例任务结果（task_id={first_tid}）:")
                pretty(sample.get("result", {}))
                print("✅ 异步任务并发测试成功")
                return True

            # 严格按 POLL_INTERVAL 节奏轮询：本轮耗时会被扣除
            spent = time.time() - cycle_start
            sleep_for = max(0.0, POLL_INTERVAL - spent)
            time.sleep(sleep_for)

        unfinished = [tid for tid in task_ids if task_status.get(tid) not in ("completed", "failed")]
        print(f"❌ 轮询超时（等待 {POLL_MAX_WAIT}s），未完成任务数: {len(unfinished)}")
        for tid in unfinished:
            print(f"  - {tid}: {task_status.get(tid)}")
        return False

    except Exception as e:
        print(f"❌ 异步任务异常: {e}")
        return False


# ─── 4. 参数校验 ────────────────────────────────────────
def test_validation():
    separator("4. 参数校验")
    url = f"{BASE_URL}/api/video-analyze/analyze"
    results = []

    # 4a. 空 URL
    print("\n--- 4a. 空 video_url ---")
    try:
        resp = requests.post(url, json={"video_url": ""}, timeout=10)
        print(f"Status: {resp.status_code}")
        pretty(resp.json())
        if resp.status_code == 422:
            print("✅ 空 URL 校验通过（返回 422）")
            results.append(True)
        else:
            print(f"⚠️  预期 422, 实际 {resp.status_code}")
            results.append(False)
    except Exception as e:
        print(f"❌ 异常: {e}")
        results.append(False)

    # 4b. 非 http(s) URL
    print("\n--- 4b. 非 http(s) URL ---")
    try:
        resp = requests.post(url, json={"video_url": "ftp://example.com/video.mp4"}, timeout=10)
        print(f"Status: {resp.status_code}")
        pretty(resp.json())
        if resp.status_code == 422:
            print("✅ 非 http(s) URL 校验通过（返回 422）")
            results.append(True)
        else:
            print(f"⚠️  预期 422, 实际 {resp.status_code}")
            results.append(False)
    except Exception as e:
        print(f"❌ 异常: {e}")
        results.append(False)

    # 4c. 缺少 video_url 字段
    print("\n--- 4c. 缺少 video_url ---")
    try:
        resp = requests.post(url, json={}, timeout=10)
        print(f"Status: {resp.status_code}")
        pretty(resp.json())
        if resp.status_code == 422:
            print("✅ 缺少字段校验通过（返回 422）")
            results.append(True)
        else:
            print(f"⚠️  预期 422, 实际 {resp.status_code}")
            results.append(False)
    except Exception as e:
        print(f"❌ 异常: {e}")
        results.append(False)

    return all(results)


# ─── 运行 ──────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Video Analyze API 测试")
    print(f"  Base URL: {BASE_URL}")
    print(f"  Video:    {VIDEO_URL}")
    print(f"  Async:    {ASYNC_TASK_COUNT} 并发，每 {POLL_INTERVAL}s 轮询")
    print("=" * 60)

    results = {}

    # 只执行异步任务并发测试
    results["异步任务"] = test_async_task()

    # ─── 汇总 ──────────────────────────────────────────
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
