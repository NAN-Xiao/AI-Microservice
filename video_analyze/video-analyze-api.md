# Video Analyze API

基础地址：`http://zhongtai-ai.elexapp.com`

```
# 同步分析（阻塞等待结果）
POST /api/video-analyze/analyze
  Body: { "video_url": "http://xxx/video.mp4", "tags": {} }
  # video_url - 必填，http/https 视频地址
  # tags      - 选填，自定义标签体系，不传用服务端默认

# 异步提交任务（立即返回 task_id）
POST /api/video-analyze/tasks
  Body: { "video_url": "http://xxx/video.mp4", "tags": {} }
  # 参数同上

# 查询任务结果（轮询）
GET /api/video-analyze/tasks/{task_id}
  # status: pending → processing → completed / failed

# 任务列表
GET /api/video-analyze/tasks?status=completed&limit=50
  # status - 选填，筛选状态
  # limit  - 选填，返回数量，默认50，最大200

# 获取标签模板
GET /api/video-analyze/tags

# 替换标签模板
PUT /api/video-analyze/tags
  Body: 完整标签 JSON

# 健康检查
GET /api/video-analyze/health
```

## 完整请求示例

```python
import requests

resp = requests.post(
    "http://zhongtai-ai.elexapp.com/api/video-analyze/analyze",
    json={"video_url": "https://example.com/path/to/video.mp4"},
)
print(resp.json())
# {"code": 200, "message": "success", "data": {"视频类型": "游戏实况", ...}, "request_id": "a1b2c3d4e5f6"}
```


```java
# 1. 提交任务
resp = requests.post(
    "http://zhongtai-ai.elexapp.com/api/video-analyze/tasks",
    json={"video_url": "https://example.com/path/to/video.mp4"},
)
task_id = resp.json()["data"]["task_id"]

# 2. 轮询结果
import time
while True:
    r = requests.get(f"http://zhongtai-ai.elexapp.com/api/video-analyze/tasks/{task_id}")
    status = r.json()["data"]["status"]
    if status == "completed":
        tags = r.json()["data"]["result"]  # 分析结果
        break
    elif status == "failed":
        print("分析失败:", r.json()["data"].get("error"))
        break
    time.sleep(3)  # 每3秒查一次
```

**错误码：**

| code | 含义               |
| ---- | ------------------ |
| 200  | 成功               |
| 400  | 请求参数错误       |
| 404  | 任务不存在或已过期 |
| 500  | 服务内部错误       |
| 502  | LLM 上游服务错误   |
| 503  | 无法连接 LLM 服务  |
| 504  | LLM 分析超时       |
