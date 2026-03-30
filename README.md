# AI Agent 微服务平台

多语言 AI Agent 微服务架构，采用 `Nginx -> Spring Cloud Gateway -> Agents` 分层网关模式。

## 架构

```
客户端 → Nginx (80/443) → Java Gateway (8080) ──┬── /api/video-analyze/** → video_analyze Agent (Python, 9001)
                                                └── /api/ui-builder/**    → ui_builder Agent   (Python, 9002)

各 Agent ──→ LLM 服务器
```

- **Nginx**：边缘入口，负责 TLS 终止、入口代理、外网访问控制
- **Java Gateway**：应用网关，负责路由分发、日志、CORS、鉴权、统一错误处理
- **Agent 服务**：各语言独立实现，遵循统一 API 接口契约

## 项目结构

```
AI-Microservice/
├── gateway/                  # Java 网关 (Spring Cloud Gateway)
│   ├── pom.xml
│   └── src/main/
│       ├── java/com/ai/gateway/
│       │   ├── GatewayApplication.java
│       │   ├── config/
│       │   │   ├── CorsConfig.java
│       │   │   ├── HealthEndpoint.java
│       │   │   └── GatewayErrorHandler.java
│       │   └── filter/
│       │       ├── AccessLogFilter.java
│       │       ├── ForwardHeadersFilter.java
│       │       └── AuthFilter.java
│       └── resources/
│           └── application.yml
├── video_analyze/            # 视频分析 Agent (Python FastAPI, 9001)
├── ui_builder/               # UI 构建 Agent (Python FastAPI, 9002)
└── nginx/                    # Nginx 边缘入口配置
    └── nginx.conf
```

## 网关 (Java Gateway)

### 技术栈

- Java 17+
- Spring Boot 3.2.5
- Spring Cloud Gateway 2023.0.1
- Spring Boot Actuator

### 功能

| 功能 | 说明 |
|------|------|
| 路由转发 | 按路径前缀分发到不同 Agent |
| 请求日志 | AccessLogFilter 记录每个请求的方法、路径、耗时 |
| 请求头转发 | X-Real-IP, X-Forwarded-For, X-Forwarded-Proto |
| CORS | 全局跨域支持 |
| 鉴权 | AuthFilter（默认关闭，支持静态 Bearer Token） |
| 错误处理 | 统一 JSON 错误响应，与下游 ApiResult 格式一致 |
| 健康检查 | `/gateway-health` + Actuator `/actuator/health` |
| 大文件上传 | 支持 50MB 请求体 |
| 超时控制 | 连接 10s，响应 600s（适配 LLM 长时间调用） |

### 启动

```bash
cd gateway
mvn spring-boot:run
```

或打包后运行：

```bash
mvn clean package -DskipTests
java -jar target/gateway-1.0.0.jar
```

网关默认监听 **8080** 端口。

### 配置

关键配置在 `gateway/src/main/resources/application.yml`：

```yaml
# 修改网关端口
server.port: 8080

# 通过环境变量覆盖下游服务地址
AGENT_VIDEO_ANALYZE_URL=http://127.0.0.1:9001
AGENT_UI_BUILDER_URL=http://127.0.0.1:9002

# 开启鉴权并配置 Bearer Token
GATEWAY_AUTH_ENABLED=true
GATEWAY_AUTH_ALLOWED_TOKENS=demo-token-1,demo-token-2

# 配置允许跨域的前端来源
GATEWAY_CORS_ALLOWED_ORIGIN_PATTERNS=http://localhost:3000,http://127.0.0.1:5173
```

### API 路由

| 路径 | 转发目标 | 说明 |
|------|---------|------|
| `/api/video-analyze/**` | `http://127.0.0.1:9001` | 视频分析服务 |
| `/api/ui-builder/**` | `http://127.0.0.1:9002` | UI 构建服务 |
| `/gateway-health` | 网关自身 | 网关健康检查 |
| `/actuator/health` | 网关自身 | Actuator 健康检查 |

## Agent 服务

### video_analyze (端口 9001)

| 接口 | 说明 |
|------|------|
| `POST /api/video-analyze/analyze` | 视频分析（传入 video_url） |
| `GET /api/video-analyze/health` | 健康检查 |

### ui_builder (端口 9002)

| 接口 | 说明 |
|------|------|
| `POST /api/ui-builder/analyze` | UI 截图分析（上传图片） |
| `GET /api/ui-builder/health` | 健康检查 |

## 新增 Agent

1. 用任意语言实现 Agent，遵循 `/api/{agentName}/...` 路径格式
2. 在 `gateway/src/main/resources/application.yml` 中添加路由规则
3. 重启网关

## 启用鉴权

1. 设置 `GATEWAY_AUTH_ENABLED=true`
2. 设置 `GATEWAY_AUTH_ALLOWED_TOKENS=token-a,token-b`
3. 客户端使用 `Authorization: Bearer <token>` 调用网关
4. 重启网关

## 运维接口建议

1. `/gateway-health` 可用于对外健康探测
2. `/actuator/health` 建议仅通过内网或运维网访问
3. 若需暴露 `/actuator/gateway`，请先显式设置：

```bash
MANAGEMENT_ENDPOINT_GATEWAY_ENABLED=true
MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE=health,info,gateway
```
