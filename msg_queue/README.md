# HTTP Message Queue (Java)

一个基于 `Spring Boot` 的 HTTP 队列工程：
- `GET/POST /messages/**` 接收 HTTP 消息并按路径规则决定是否入队
- 后台消费者线程消费（`worker-count=1` 时顺序消费，`>1` 时并发消费）
- `GET /health` 健康检查
- `GET /queue/stats` 查看队列和消费统计
- `POST /api/see-through/convert` 接收图片，作为队列任务串行调用 `see_through` 服务并返回 PSD
- `POST /api/see-through/cleanup` 代理清理 `see_through` 临时文件
- `GET /api/see-through/health` 代理 `see_through` 健康检查
- `POST /api/see-through/cancel` 取消仍在 `msg_queue` 中排队的 SeeThrough 任务
- 任务过滤规则（按 URL 路径）：
  - `/messages/query/**` 查询任务不入队，直接处理
  - 只有 `queue.long-task-path-prefixes` 白名单路径入队
  - 其他路径直接处理

## 环境要求

- JDK 17+
- Maven 3.6+

## 启动

```powershell
mvn spring-boot:run
```

默认端口：`8090`

## 接口示例

1. 入队（命中耗时路径白名单，POST）

```bash
curl -X POST "http://127.0.0.1:8090/messages/report/generate" \
  -H "Content-Type: application/json" \
  -d "{\"topic\":\"order.create\",\"payload\":{\"orderId\":1001,\"userId\":99}}"
```

返回示例：

```json
{
  "messageId": "d2ec12bc-3f99-45a7-93df-2a9f6a6f6f11",
  "status": "queued",
  "queueSize": 1
}
```

队列已满（超过 200 任务）返回示例：

```json
{
  "code": "TASK_BUSY",
  "message": "任务繁忙，请稍后重试"
}
```
HTTP 状态码：`503 Service Unavailable`

2. 查看队列统计

```bash
curl "http://127.0.0.1:8090/queue/stats"
```

3. 健康检查

```bash
curl "http://127.0.0.1:8090/health"
```

4. 查询任务（不入队）

```bash
curl -X POST "http://127.0.0.1:8090/messages/query/order/detail" \
  -H "Content-Type: application/json" \
  -d "{\"topic\":\"query.order.detail\",\"payload\":{\"orderId\":1001}}"
```

5. 入队（命中耗时路径白名单，GET）

```bash
curl "http://127.0.0.1:8090/messages/report/generate?topic=report.generate&reportDate=2026-04-24&userId=99"
```

## 配置项

配置文件：`src/main/resources/application.yml`

- `queue.max-size`：队列最大容量（默认 `200`）
- `queue.worker-count`：消费者线程数（默认 `1`，即消费完一个再消费下一个）
- `queue.worker-delay-ms`：每条消息模拟处理延迟（毫秒，默认 `0`）
- `queue.long-task-path-prefixes`：允许入队的耗时任务 URL 路径前缀白名单（相对 `/messages`）
- `see-through.base-url`：后端 Gateway 地址，默认 `http://127.0.0.1:8081`，实际调用会拼接 `/api/see-through/...`
- `see-through.auth-token`：调用后端 `see_through` 时使用的 Bearer token；若客户端请求带 `Authorization`，优先透传客户端 token
- `see-through.max-size`：SeeThrough 转换等待队列容量，默认 `200`
- `see-through.request-timeout-seconds`：同步等待 SeeThrough 转换结果的超时时间，默认 `600`

## SeeThrough 串行任务

`msg_queue` 会把 `/api/see-through/convert` 的 multipart 图片请求封装为队列任务，由单 worker 串行通过 Gateway 调用后端 `see_through` 的 `/api/see-through/convert`。调用方仍同步拿到 PSD 文件；队列满时返回 `503` 和 `TASK_BUSY`。

```bash
curl -X POST "http://127.0.0.1:8090/api/see-through/convert" \
  -F "image=@input.png" \
  -o output.psd
```

查看 SeeThrough 队列状态：

```bash
curl "http://127.0.0.1:8090/api/see-through/queue/stats"
```

取消排队中的 SeeThrough 任务：

```bash
curl -X POST "http://127.0.0.1:8090/api/see-through/cancel" \
  -H "Content-Type: application/json" \
  -d "{\"taskId\":\"your-client-generated-task-id\"}"
```

前端可以在上传时把自生成的 `taskId` 作为 query 参数传给转换接口：

```bash
curl -X POST "http://127.0.0.1:8090/api/see-through/convert?taskId=your-client-generated-task-id" \
  -F "image=@input.png" \
  -o output.psd
```

页面关闭或请求断开时，`msg_queue` 会尝试取消任务。仍在队列里等待的任务会被移除；已经开始调用 `see_through` 的任务只能标记为取消并丢弃结果，不能保证中断下游已经开始的 ComfyUI 转换。

## 日志配置

- 使用 `log4j2`（配置文件：`src/main/resources/log4j2-spring.xml`）
- 主日志文件：`./logs/queueServer.log`
- 按日期滚动压缩：`./logs/queueServer-YYYY-MM-DD.log.gz`

## 说明

当前是内存队列（`LinkedBlockingQueue`），适合开发和联调。
如果你要上生产，可以把 `MessageQueueService` 替换为 Redis、RabbitMQ、Kafka 的实现。
