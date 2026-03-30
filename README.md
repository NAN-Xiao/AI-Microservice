# UI Builder - AI Agent 微服务平台

Nginx 统一路由的多语言 AI Agent 微服务架构。每个关注点（路由、鉴权、日志、Agent）都是独立服务。

## 架构

```
客户端 → Nginx (80) ──┬── auth_request ──→ 鉴权服务 (9100)
                      ├── /api/ui-builder/ → ui-builder Agent (Python, 9001)
                      ├── /api/vision/     → vision Agent (任意语言, 9002)
                      └── /api/codegen/    → codegen Agent (Go, 9003)

各 Agent ──→ LLM 服务器
各服务   ──→ 日志收集 (ELK / Loki)
```

- **Nginx**：统一入口，路由分发，auth_request 鉴权委托，限流
- **鉴权服务**：独立微服务，Nginx 通过 auth_request 子请求调用
- **Agent 服务**：各语言独立实现，遵循 `api-spec/openapi.yml` 接口契约
- **日志/监控**：各服务独立推送日志，Prometheus 拉取指标

## 项目结构

```
ui_builder/
├── api-spec/
│   └── openapi.yml      # 跨语言 API 契约（所有 Agent 遵循）
├── nginx/
│   └── nginx.conf       # Nginx 路由 + 鉴权 + 限流配置
└── README.md
```

各 Agent 为独立项目，可用任意语言实现，独立仓库或子目录均可。

## API 契约

所有 Agent 统一遵循 `api-spec/openapi.yml`，路径格式：`/api/{agentName}/...`

| 接口 | 说明 |
|------|------|
| `POST /api/{agent}/chat` | 同步聊天 |
| `POST /api/{agent}/chat/upload` | 带图片上传的同步聊天 |
| `POST /api/{agent}/chat/stream` | SSE 流式聊天 |
| `POST /api/{agent}/chat/stream/upload` | 带图片上传的流式聊天 |
| `GET /api/{agent}/health` | Agent 健康检查 |

## 新增 Agent

1. 用任意语言实现 Agent，遵循 `api-spec/openapi.yml`
2. 在 `nginx/nginx.conf` 中添加 upstream + location 路由
3. `nginx -t && nginx -s reload`

## 启用鉴权

1. 部署鉴权服务（任意语言），提供 `GET /auth/verify` 接口
   - 返回 200：放行
   - 返回 401/403：拒绝
   - Nginx 传入 `X-Original-URI`、`Authorization` 等头
2. 在 `nginx.conf` 中取消 `auth_service` upstream 和 `auth_request` 的注释
3. reload Nginx

## 部署

### 内网

各服务独立进程，Nginx 在 conf 中写死 IP 和端口。

### 上云（K8s）

K8s Ingress 替代 Nginx，各 Agent 为独立 Deployment + Service。
