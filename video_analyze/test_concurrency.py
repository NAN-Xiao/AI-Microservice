"""
LLM 上游 API 并发压测脚本。
逐步增加并发数，测试上游的并发限制。
用法: python test_concurrency.py [最大并发数]  默认 20
"""

import asyncio
import sys
import time

import httpx

API_URL = "https://aikey.elex-tech.com/v1/chat/completions"
API_KEY = "apg_c2a9f12cb04b6db44c905952402619ba39a4eb446185653c"
MODEL = "qwen3.5-plus"

# 极简 prompt，尽量缩短响应时间，只测并发能力
PAYLOAD = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "回复数字1"}],
    "max_tokens": 5,
}

HEADERS = {"Authorization": f"Bearer {API_KEY}"}


async def single_request(client: httpx.AsyncClient, idx: int) -> dict:
    """发送单个请求，返回结果摘要。"""
    t0 = time.perf_counter()
    try:
        resp = await client.post(API_URL, json=PAYLOAD, headers=HEADERS)
        elapsed = time.perf_counter() - t0
        if resp.status_code == 200:
            return {"idx": idx, "status": 200, "time": elapsed}
        else:
            body = resp.text[:120]
            return {"idx": idx, "status": resp.status_code, "time": elapsed, "body": body}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"idx": idx, "status": -1, "time": elapsed, "error": f"{type(e).__name__}: {e}"}


async def test_batch(n: int):
    """并发发送 n 个请求，统计结果。"""
    async with httpx.AsyncClient(timeout=60) as client:
        t0 = time.perf_counter()
        results = await asyncio.gather(*(single_request(client, i) for i in range(n)))
        wall = time.perf_counter() - t0

    ok = [r for r in results if r["status"] == 200]
    rate_limited = [r for r in results if r["status"] == 429]
    errors = [r for r in results if r["status"] not in (200, 429)]

    times = [r["time"] for r in ok]
    avg_t = sum(times) / len(times) if times else 0

    print(f"  并发={n:>3d}  |  成功={len(ok):>3d}  429限流={len(rate_limited):>3d}  "
          f"其他错误={len(errors):>3d}  |  墙钟={wall:.1f}s  平均响应={avg_t:.1f}s")

    if rate_limited:
        print(f"         ↳ 429 示例: {rate_limited[0].get('body', '')[:100]}")
    if errors:
        for e in errors[:2]:
            print(f"         ↳ 错误: status={e['status']} {e.get('error', e.get('body', ''))[:100]}")

    return len(rate_limited), len(errors)


async def main():
    max_conc = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    # 测试梯度
    levels = sorted(set([1, 3, 5, 8, 10, 15, 20, 30, 50]) & set(range(1, max_conc + 1))
                    | {max_conc})
    levels = sorted(levels)

    print(f"目标: 测试上游 LLM API 并发上限 (模型={MODEL})")
    print(f"测试梯度: {levels}")
    print("-" * 72)

    for n in levels:
        rl, err = await test_batch(n)
        # 两批之间间隔 2 秒，避免触发短时限流
        if n != levels[-1]:
            await asyncio.sleep(2)

    print("-" * 72)
    print("测试完成。观察 429 开始出现的并发数即为上游限制。")


if __name__ == "__main__":
    asyncio.run(main())
