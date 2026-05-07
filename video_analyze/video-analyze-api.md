# Video Analyze API

基础地址：

- 线上：`http://zhongtai-ai.elexapp.com`
- 直连服务：`http://10.1.6.76:9001`
- 本地：`http://localhost:9001`

所有业务接口使用 JSON 请求体和 JSON 响应。若服务端配置了鉴权 Token，请在请求头中传：

```http
Authorization: Bearer <token>
Content-Type: application/json
```

## 通用响应格式

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "request_id": "a1b2c3d4e5f6"
}
```

说明：

- `code`：业务状态码，`200` 表示成功。
- `message`：错误或成功信息。
- `data`：接口数据。
- `request_id`：同步分析类接口会返回，便于排查日志。

任务状态：

| status | 含义 |
| --- | --- |
| `pending` | 已提交，排队中 |
| `processing` | 分析中 |
| `completed` | 已完成，`result` 字段包含结果 |
| `failed` | 已失败，`error` / `error_code` 字段包含原因 |

## 1. 视频标签分析

### 1.1 同步分析

```http
POST /api/video-analyze/analyze
```

同步阻塞等待 LLM 分析完成，适合调用方可接受较长 HTTP 等待时间的场景。

请求体：

```json
{
  "video_url": "https://example.com/video.mp4",
  "tags": null,
  "prompt": "请重点关注广告创意和转化引导"
}
```

参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `video_url` | string | 是 | 视频地址，仅支持 `http` / `https` |
| `tags` | object | 否 | 自定义标签体系；不传或传 `null` 使用服务端默认标签 |
| `prompt` | string | 否 | 额外提示词，会追加到系统提示词末尾 |

成功响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "视频类型": {
      "内容类型": ["游戏实况"]
    }
  },
  "request_id": "a1b2c3d4e5f6"
}
```

### 1.2 提交异步任务

```http
POST /api/video-analyze/tasks
```

立即返回 `task_id`，调用方通过查询接口轮询结果。

请求体同同步分析：

```json
{
  "video_url": "https://example.com/video.mp4",
  "tags": null,
  "prompt": "请重点关注广告创意和转化引导"
}
```

成功响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "task_id": "7f8e9d6c5b4a3210",
    "status": "pending",
    "message": "任务已提交，请通过 GET /api/video-analyze/tasks/{task_id} 轮询结果"
  },
  "request_id": null
}
```

### 1.3 查询异步任务

```http
GET /api/video-analyze/tasks/{task_id}
```

成功响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "task_id": "7f8e9d6c5b4a3210",
    "task_type": "analyze",
    "video_url": "https://example.com/video.mp4",
    "status": "completed",
    "created_at": 1778120000.123,
    "started_at": 1778120001.456,
    "finished_at": 1778120030.789,
    "duration_seconds": 29.33,
    "result": {
      "视频类型": {
        "内容类型": ["游戏实况"]
      }
    }
  },
  "request_id": null
}
```

失败任务会返回：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "task_id": "7f8e9d6c5b4a3210",
    "task_type": "analyze",
    "video_url": "https://example.com/video.mp4",
    "status": "failed",
    "created_at": 1778120000.123,
    "started_at": 1778120001.456,
    "finished_at": 1778120010.789,
    "duration_seconds": 9.33,
    "error": "分析超时，LLM 服务响应过慢",
    "error_code": 504
  },
  "request_id": null
}
```

### 1.4 标签任务列表

```http
GET /api/video-analyze/tasks?status=completed&limit=50
```

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 否 | 按状态筛选：`pending` / `processing` / `completed` / `failed` |
| `limit` | int | 否 | 返回数量，默认 `50`，范围 `1-200` |

响应的 `data` 是任务数组，按创建时间倒序返回，只包含 `task_type=analyze` 的任务。

### 1.5 获取标签模板

```http
GET /api/video-analyze/tags
```

返回当前服务端默认标签体系。

### 1.6 替换标签模板

```http
PUT /api/video-analyze/tags
```

请求体就是完整标签 JSON，格式需与 `resources/video_tags.json` 一致。更新后立即生效，后续未传 `tags` 的分析请求会使用新模板。

```json
{
  "视频类型": {
    "内容类型": ["游戏实况", "剧情剪辑"]
  }
}
```

## 2. 视频切片分析

### 2.1 同步切片分析

```http
POST /api/video-analyze/clip
```

同步阻塞等待 LLM 输出视频分段指令和整体情绪曲线。

请求体：

```json
{
  "video_url": "https://example.com/video.mp4",
  "prompt": "切片尽量控制在 3 到 8 秒"
}
```

参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `video_url` | string | 是 | 视频地址，仅支持 `http` / `https` |
| `prompt` | string | 否 | 额外提示词，会追加到切片规则后 |

成功响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "instructions": [
      {
        "start": 0,
        "end": 5,
        "time_str": "00:00-00:05",
        "content": "画面内容 + 镜头描述 + 创作寓意 + 情绪作用"
      }
    ],
    "emotion": "从平静铺垫逐步转向紧张，结尾释放爽感"
  },
  "request_id": "b2c3d4e5f6a7"
}
```

### 2.2 提交切片异步任务

```http
POST /api/video-analyze/clip/tasks
```

请求体同同步切片分析：

```json
{
  "video_url": "https://example.com/video.mp4",
  "prompt": "切片尽量控制在 3 到 8 秒"
}
```

成功响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "task_id": "9a8b7c6d5e4f3210",
    "status": "pending",
    "message": "切片任务已提交，请通过 GET /api/video-analyze/clip/tasks/{task_id} 轮询结果"
  },
  "request_id": null
}
```

### 2.3 查询切片任务

```http
GET /api/video-analyze/clip/tasks/{task_id}
```

响应结构与标签分析任务一致，但 `task_type` 为 `clip`，完成后 `result` 为切片结果：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "task_id": "9a8b7c6d5e4f3210",
    "task_type": "clip",
    "video_url": "https://example.com/video.mp4",
    "status": "completed",
    "created_at": 1778120000.123,
    "started_at": 1778120001.456,
    "finished_at": 1778120030.789,
    "duration_seconds": 29.33,
    "result": {
      "instructions": [
        {
          "start": 0,
          "end": 5,
          "time_str": "00:00-00:05",
          "content": "画面内容 + 镜头描述 + 创作寓意 + 情绪作用"
        }
      ],
      "emotion": "从平静铺垫逐步转向紧张，结尾释放爽感"
    }
  },
  "request_id": null
}
```

### 2.4 切片任务列表

```http
GET /api/video-analyze/clip/tasks?status=completed&limit=50
```

查询参数同标签任务列表。响应的 `data` 是任务数组，按创建时间倒序返回，只包含 `task_type=clip` 的任务。

## 3. 健康检查

### 3.1 完整健康信息

```http
GET /api/video-analyze/health
```

响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "service": "video-analyze",
    "status": "UP",
    "ready": true,
    "model": "your-model-name",
    "llm_configured": true,
    "tasks": {
      "total": 3,
      "completed": 2,
      "processing": 1
    }
  },
  "request_id": null
}
```

### 3.2 存活探针

```http
GET /api/video-analyze/health/live
```

响应：

```json
{
  "status": "UP"
}
```

### 3.3 就绪探针

```http
GET /api/video-analyze/health/ready
```

就绪时返回 HTTP `200`：

```json
{
  "status": "READY"
}
```

尚未就绪时返回 HTTP `503`：

```json
{
  "status": "NOT_READY"
}
```

## 4. 调用示例

### 4.1 同步标签分析

```python
import requests

BASE_URL = "http://zhongtai-ai.elexapp.com"

resp = requests.post(
    f"{BASE_URL}/api/video-analyze/analyze",
    headers={"Authorization": "Bearer <token>"},
    json={
        "video_url": "https://example.com/path/to/video.mp4",
        "prompt": "请重点关注广告创意和转化引导",
    },
    timeout=600,
)

print(resp.json())
```

### 4.2 异步标签分析

```python
import time
import requests

BASE_URL = "http://zhongtai-ai.elexapp.com"
HEADERS = {"Authorization": "Bearer <token>"}

submit_resp = requests.post(
    f"{BASE_URL}/api/video-analyze/tasks",
    headers=HEADERS,
    json={"video_url": "https://example.com/path/to/video.mp4"},
    timeout=30,
)
task_id = submit_resp.json()["data"]["task_id"]

while True:
    poll_resp = requests.get(
        f"{BASE_URL}/api/video-analyze/tasks/{task_id}",
        headers=HEADERS,
        timeout=10,
    )
    task = poll_resp.json()["data"]
    status = task["status"]

    if status == "completed":
        print("分析结果:", task["result"])
        break
    if status == "failed":
        print("分析失败:", task.get("error"))
        break

    time.sleep(3)
```

### 4.3 同步切片分析

```python
import requests

BASE_URL = "http://zhongtai-ai.elexapp.com"

resp = requests.post(
    f"{BASE_URL}/api/video-analyze/clip",
    headers={"Authorization": "Bearer <token>"},
    json={
        "video_url": "https://example.com/path/to/video.mp4",
        "prompt": "切片尽量控制在 3 到 8 秒",
    },
    timeout=600,
)

print(resp.json())
```

## 5. 错误码

| code | 含义 |
| --- | --- |
| `200` | 成功 |
| `400` | 请求参数错误，例如 `video_url` 或 `tags` 格式不合法 |
| `401` | 鉴权失败，缺少或传入了错误的 Bearer Token |
| `404` | 任务不存在、已过期，或使用了错误的任务类型查询接口 |
| `500` | 服务内部错误，或服务未配置 LLM 密钥 |
| `502` | LLM 上游服务错误，或 LLM 响应格式异常 |
| `503` | 无法连接 LLM 服务；`/health/ready` 未就绪也会返回 HTTP 503 |
| `504` | LLM 分析超时 |

## 6. 接口清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/video-analyze/analyze` | 同步标签分析 |
| `POST` | `/api/video-analyze/tasks` | 提交标签分析任务 |
| `GET` | `/api/video-analyze/tasks/{task_id}` | 查询标签分析任务 |
| `GET` | `/api/video-analyze/tasks` | 标签分析任务列表 |
| `GET` | `/api/video-analyze/tags` | 获取标签模板 |
| `PUT` | `/api/video-analyze/tags` | 替换标签模板 |
| `POST` | `/api/video-analyze/clip` | 同步切片分析 |
| `POST` | `/api/video-analyze/clip/tasks` | 提交切片任务 |
| `GET` | `/api/video-analyze/clip/tasks/{task_id}` | 查询切片任务 |
| `GET` | `/api/video-analyze/clip/tasks` | 切片任务列表 |
| `GET` | `/api/video-analyze/health` | 完整健康信息 |
| `GET` | `/api/video-analyze/health/live` | 存活探针 |
| `GET` | `/api/video-analyze/health/ready` | 就绪探针 |
