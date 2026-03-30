# AI Agent 微服务平台

多语言 AI Agent 微服务架构，支持 Nginx 或 Spring Cloud Gateway 统一路由。

## 架构

```
客户端 → Java Gateway (8080) ──┬── /api/video-analyze/** → video_analyze Agent (Python, 9001)
         或 Nginx (80)         └── /api/ui-builder/**    → ui_builder Agent   (Python, 9002)

各 Agent ──→ LLM 服务器
```

- **Java Gateway**：Spring Cloud Gateway 统一入口，路由分发、日志、CORS、鉴权（可选）
- **Nginx**：备用方案，配置在 `nginx/nginx.conf`
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
└── nginx/                    # Nginx 配置（备用）
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
| 鉴权 | AuthFilter（默认关闭，可配置开启） |
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

# 修改下游服务地址（也可通过环境变量覆盖）
spring.cloud.gateway.routes[0].uri: http://127.0.0.1:9001
spring.cloud.gateway.routes[1].uri: http://127.0.0.1:9002

# 开启鉴权
gateway.auth.enabled: true
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

1. 部署鉴权服务，提供 Token 验证接口
2. 在 `application.yml` 中设置 `gateway.auth.enabled: true`
3. 在 `AuthFilter.java` 中实现具体验证逻辑（JWT / 远程调用）
4. 重启网关
