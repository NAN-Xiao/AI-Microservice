# AI-Microservice 部署指南

> 适用于 Linux 服务器（CentOS 7+ / Ubuntu 20.04+），单机 Docker Compose 一键拉起全部服务（Nginx + Nacos + 微服务）。

---

## 目录

1. [整体架构](#1-整体架构)
2. [服务器环境准备](#2-服务器环境准备)
3. [安装 Docker & Docker Compose](#3-安装-docker--docker-compose)
4. [部署全部服务（一键启动）](#4-部署全部服务一键启动)
5. [SSL 证书配置](#5-ssl-证书配置)
6. [API 鉴权](#6-api-鉴权)
7. [Nacos 服务发现与 Token 热管理](#7-nacos-服务发现与-token-热管理)
8. [新增微服务指南](#8-新增微服务指南)
9. [自动化部署（CI/CD）](#9-自动化部署cicd)
10. [运维速查](#10-运维速查)

---

## 1. 整体架构

```
            客户端 (Unity / Web / curl)
            Authorization: Bearer <token>
                        │
        ═════════════════════════════ Docker Compose ══════════════════════════════
        │                       ▼                                          │
        │           ┌──────────────────────────────┐                      │
        │           │     Nginx  (端口 80/443)      │                      │
        │           │   SSL 卸载 + 按路径分发          │                      │
        │           └──────────┬───────────────────┘                      │
        │                      │  Docker 内部网络 (ai-net)                   │
        │         ┌────────────┼────────────────┐                     │
        │         │            │                │                     │
        │┌────────▼────────┐ ┌▼──────────────┐ ┌▼──────────────┐│
        ││  video-analyze  │ │  ui-builder   │ │ 未来新服务 ... ││
        ││  (Docker:9001)  │ │ (Docker:9002) │ │ (Docker:900x) ││
        ││  FastAPI 鉴权   │ │  FastAPI 鉴权 │ │  FastAPI 鉴权  ││
        │└────────┬────────┘ └──────┬────────┘ └──────┬────────┘│
        │         │                 │                  │                    │
        │         └─────────────────┼──────────────────┘                    │
        │                            │  启动时自动注册 / 关闭时注销                 │
        │                 ┌──────────▼──────────┐                               │
        │                 │  Nacos (8848/9848)  │                               │
        │                 │  服务注册 + Token 热管理│                               │
        │                 └─────────────────────┘                               │
        ═════════════════════════════════════════════════════════════════════
```

**单机部署：** 所有服务都在同一台机器的 Docker Compose 中，`docker compose up -d` 一键拉起。

**请求链路：** 客户端 → Nginx(80/443) → Docker 内网 → 各微服务

**鉴权方式：** 与调用 OpenAI / 通义千问 API 一致 —— 请求头 `Authorization: Bearer <token>`

**Token 热管理：** 在 Nacos 控制台修改配置，30秒内自动生效，无需重启服务

**为什么不需要 Spring Cloud Gateway：**
- 所有服务都是 Python（FastAPI），不需要 Java 生态的路由/熔断
- 服务间不互调，Nginx 按路径分发即可
- 鉴权由 FastAPI 中间件统一处理，每个服务自己校验 token
- 少一层 = 更低延迟、更少故障点、更简单运维

---

## 2. 服务器环境准备

```bash
# ========== 系统更新 ==========
# Ubuntu
sudo apt update && sudo apt upgrade -y

# CentOS
sudo yum update -y

# ========== 安装常用工具 ==========
# Ubuntu
sudo apt install -y curl wget git vim net-tools lsof

# CentOS
sudo yum install -y curl wget git vim net-tools lsof

# ========== 开放防火墙端口 ==========
# 80/443  - Nginx（外部唯一入口，Docker 容器映射到宿主机）
# 8848    - Nacos 控制台（限内网，可选——已通过 Nginx /nacos/ 代理）
# 9848    - Nacos gRPC（限内网）
# 9001/9002 不需要开放 —— 仅 Docker 内部网络通信

# Ubuntu (ufw)
sudo ufw allow 80,443/tcp
sudo ufw allow from 10.0.0.0/8 to any port 8848,9848 proto tcp
sudo ufw enable

# CentOS (firewalld)
sudo firewall-cmd --permanent --add-port={80,443}/tcp
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="8848" protocol="tcp" accept'
sudo firewall-cmd --reload
```

> **安全建议：** 9001/9002 端口无需对外开放，仅在 Docker 内部网络 (ai-net) 中通信。外部请求统一走 Nginx(80/443)。

---

## 3. 安装 Docker & Docker Compose

```bash
# ========== 安装 Docker ==========
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable docker --now

# 把当前用户加入 docker 组（免 sudo）
sudo usermod -aG docker $USER
newgrp docker

# 验证
docker --version
docker compose version

# ========== 如果 docker compose 版本过低 ==========
# Docker Compose V2 通常随 Docker 一起安装
# 如需手动安装:
sudo apt install docker-compose-plugin   # Ubuntu
sudo yum install docker-compose-plugin   # CentOS
```

---

## 4. 部署全部服务（一键启动）

### 4.1 上传代码到服务器

```bash
# 方式一：git clone
cd /opt
git clone <仓库地址> AI-Microservice
cd AI-Microservice

# 方式二：本地打包上传
# 本地：
tar czf ai-micro.tar.gz --exclude='venv' --exclude='node_modules' --exclude='__pycache__' AI-Microservice/
scp ai-micro.tar.gz user@server:/opt/
# 服务器：
cd /opt && tar xzf ai-micro.tar.gz && cd AI-Microservice
```

### 4.2 配置环境变量

```bash
cp .env.example .env
vim .env
```

填写真实值：
```bash
# LLM API Key
UI_BUILDER_LLM_KEY=apg_xxxxxxxxxxxxxxxxxxxx
VIDEO_ANALYZE_LLM_KEY=apg_xxxxxxxxxxxxxxxxxxxx

# API 鉴权 Token（客户端调用 API 时需携带 Bearer Token）
# 多个 token 逗号分隔；留空则关闭鉴权
AUTH_TOKENS=your-secure-api-token-here

# Nacos
NACOS_AUTH_TOKEN=your-nacos-secret-at-least-32-chars
NACOS_IDENTITY_VALUE=your-nacos-identity
```

### 4.3 docker-compose.yml

> 项目根目录的 `docker-compose.yml` 已包含完整配置（Nginx + Nacos + 两个微服务）。
> **单机部署：** 所有服务都在同一个 Docker Compose 中，一条命令全部拉起。
> Nginx 通过 Docker 内部网络 (ai-net) 直接连接微服务，无需暴露 9001/9002 端口到宿主机。

```bash
# 构建并后台启动所有服务
docker compose up -d --build

# 查看状态
docker compose ps

# 查看某服务日志
docker compose logs -f ui-builder
docker compose logs -f video-analyze
docker compose logs -f nacos
docker compose logs -f nginx

# 重启单个服务
docker compose restart ui-builder

# 停止所有服务
docker compose down

# 停止并清除数据卷（慎用）
docker compose down -v
```

### 4.4 验证服务

```bash
# 通过 Nginx 统一入口访问（建议）
curl http://localhost/api/video-analyze/health
curl http://localhost/api/ui-builder/health

# 也可以直接访问容器端口（调试用）
curl http://localhost:9001/api/video-analyze/health
curl http://localhost:9002/api/ui-builder/health

# 带鉴权的业务接口
curl -H "Authorization: Bearer your-secure-api-token-here" \
     http://localhost/api/ui-builder/analyze

# 不带 token 调用业务接口 → 401
curl http://localhost/api/ui-builder/analyze
# {"code": 401, "message": "Unauthorized: invalid or missing token"}

# Nacos 控制台（通过 Nginx 代理，限内网）
curl http://localhost/nacos/
# 浏览器访问 http://<服务器IP>/nacos 或 http://<服务器IP>:8848/nacos
# 默认账号密码: nacos / nacos（务必修改）
```

---

## 5. SSL 证书配置

Nginx 已包含在 Docker Compose 中，无需单独安装。只需配置 SSL 证书即可开启 HTTPS。

### 5.1 申请 SSL 证书

**公网域名（Let's Encrypt 免费证书）：**
```bash
sudo apt install -y certbot python3-certbot-nginx   # Ubuntu
sudo yum install -y certbot python3-certbot-nginx    # CentOS

sudo certbot --nginx -d your-domain.com
sudo certbot renew --dry-run   # 验证自动续期
```

**内网部署（自签证书）：**
```bash
mkdir -p ./nginx/certs
openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout ./nginx/certs/key.pem \
  -out ./nginx/certs/cert.pem \
  -subj "/CN=ai-microservice" \
  -addext "subjectAltName=IP:10.1.73.202,IP:127.0.0.1,DNS:localhost"
```

### 5.2 启用 HTTPS

编辑 `nginx/nginx.conf`，取消 SSL 相关注释：

```nginx
server {
    listen 443 ssl http2;
    ssl_certificate     /etc/nginx/certs/cert.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    # ... 其余 location 配置不变
}
```

然后取消 `docker-compose.yml` 中 nginx 服务的证书挂载注释：

```yaml
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro    # 取消此行注释
```

重启 Nginx 容器：

```bash
docker compose restart nginx

# 验证
curl -k https://localhost/api/ui-builder/health
```

---

## 6. API 鉴权

### 6.1 机制说明

鉴权方式与调用 OpenAI / 通义千问等 LLM API **完全一致**：

```bash
# 调 LLM API
curl https://aikey.elex-tech.com/v1/chat/completions \
  -H "Authorization: Bearer apg_xxxx"

# 调我们的 API（同样的方式）
curl https://your-domain.com/api/ui-builder/submit \
  -H "Authorization: Bearer your-api-token" \
  -F "file=@screenshot.png"
```

### 6.2 鉴权规则

| 场景 | 行为 |
|------|------|
| `AUTH_TOKENS` 环境变量为空 | 鉴权关闭，所有请求放行（本地开发） |
| `AUTH_TOKENS=token-a,token-b` | 请求头必须携带 `Authorization: Bearer token-a` 或 `Bearer token-b` |
| 路径含 `/health` | 始终放行（Docker 健康检查 / Nginx 探针） |
| 路径含 `/docs` 或 `/openapi.json` | 始终放行（Swagger 文档） |
| Token 错误或缺失 | 返回 `401 Unauthorized` |

### 6.3 配置

在 `.env` 中设置（所有服务共享同一组 token）：

```bash
# 单个 token
AUTH_TOKENS=my-secure-api-token-2026

# 多个 token（逗号分隔，按团队/项目分发）
AUTH_TOKENS=unity-client-token,web-dashboard-token,ci-test-token
```

### 6.4 客户端集成示例

**Unity C#：**
```csharp
var request = new UnityWebRequest(url, "POST");
request.SetRequestHeader("Authorization", "Bearer " + apiToken);
```

**Python：**
```python
import httpx
resp = await client.post(url, headers={"Authorization": f"Bearer {token}"})
```

**curl：**
```bash
curl -H "Authorization: Bearer your-token" https://your-domain.com/api/ui-builder/submit
```

---

## 7. Nacos 服务发现与 Token 热管理

### 7.1 自动注册机制

每个 Python 微服务在启动时**自动向 Nacos 注册**，关闭时**自动注销**，无需手动操作。

注册逻辑在 `app/main.py` 的 lifespan 中：

```
服务启动 → 注册到 Nacos → set_ready(True) → 接受请求
   ↕
服务关闭 → set_ready(False) → 从 Nacos 注销 → 关闭连接
```

**环境变量：** `NACOS_ADDR=nacos:8848`（docker-compose.yml 已配置）

**注册参数：**
- serviceName: 来自 `settings.yaml` 中的 `service.name`
- groupName: `AI_MICROSERVICE`
- ip / port: 服务监听地址

### 7.2 在 Nacos 中查看注册的服务

浏览器访问 `http://<服务器IP>:8848/nacos` → 服务管理 → 服务列表

应能看到：
- `ui-builder` (AI_MICROSERVICE 组)
- `video-analyze` (AI_MICROSERVICE 组)

### 7.3 Nacos Token 热管理（已实现）

每个微服务启动时会自动从 Nacos 配置中心拉取 token，并每 **30 秒轮询**检查变更。修改 Nacos 配置后自动生效，无需重启服务。

**Token 来源优先级：** Nacos 配置 + 环境变量 `AUTH_TOKENS` 取并集（两边的 token 都生效）

**配置方法：** 登录 Nacos 控制台 → 配置管理 → 配置列表 → 新建配置：

| Data ID | Group | 内容 | 说明 |
|---------|-------|------|------|
| `ui-builder` | `AI_MICROSERVICE` | `auth_tokens: unity-token,web-token` | ui-builder 专用 token |
| `video-analyze` | `AI_MICROSERVICE` | `auth_tokens: internal-token,ci-token` | video-analyze 专用 token |

**支持不同服务不同 token：** 每个服务用自己的 service name 作为 Data ID，可以给不同服务配不同的 token 列表。

**配置格式示例：**
```yaml
# YAML 格式
auth_tokens: token-a,token-b,token-c
```
或纯文本（逗号分隔）：
```
token-a,token-b,token-c
```

> 编辑并发布后，30 秒内对应服务自动加载新 token，无需任何重启操作。

---

## 8. 新增微服务指南

以新增 `image-gen`（图片生成）服务为例，总共 **4 步**：

### 8.1 创建服务目录

```
AI-Microservice/
└── image_gen/
    ├── app/
    │   ├── __init__.py
    │   ├── config.py          # 复制 ui_builder 的，改端口和服务名
    │   ├── main.py            # 复制 ui_builder 的，改服务名
    │   ├── middleware/
    │   │   ├── __init__.py
    │   │   └── auth.py        # 直接复制，不用改
    │   ├── routers/
    │   │   ├── __init__.py
    │   │   ├── health.py      # 直接复制，改路由前缀
    │   │   └── generate.py    # 你的业务路由
    │   ├── services/
    │   ├── models/
    │   └── utils/
    ├── Dockerfile             # 复制 ui_builder 的，改端口
    ├── .dockerignore
    ├── requirements.txt
    ├── run.py
    └── settings.yaml
```

**核心要改的地方：**

| 文件 | 改什么 |
|------|--------|
| `settings.yaml` | `port: 9003`, `name: "image-gen"` |
| `Dockerfile` | `PORT=9003`, `EXPOSE 9003`, HEALTHCHECK 路径 |
| `app/main.py` | 路由前缀改为 `/api/image-gen`，include 业务 router |
| `app/routers/health.py` | prefix 改为 `/api/image-gen` |

### 8.2 添加到 docker-compose.yml

```yaml
  image-gen:
    build:
      context: ./image_gen
      dockerfile: Dockerfile
    container_name: image-gen
    restart: unless-stopped
    ports:
      - "9003:9003"
    environment:
      - HOST=0.0.0.0
      - PORT=9003
      - DEBUG=false
      - LOG_TO_FILE=true
      - LLM_API_KEY=${IMAGE_GEN_LLM_KEY}
      - AUTH_TOKENS=${AUTH_TOKENS:-}
      - NACOS_ADDR=nacos:8848
    volumes:
      - ./image_gen/logs:/app/logs
    depends_on:
      nacos:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c",
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9003/api/image-gen/health/live')"]
      interval: 10s
      timeout: 5s
      start_period: 15s
      retries: 3
    networks:
      - ai-net
```

### 8.3 Nginx 添加路由

编辑 `nginx/nginx.conf`，添加 upstream 和 location：

```nginx
upstream image_gen {
    server image-gen:9003;
    keepalive 16;
}

location /api/image-gen/ {
    proxy_pass http://image_gen;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization $http_authorization;
    proxy_connect_timeout 10s;
    proxy_read_timeout 600s;
    proxy_send_timeout 60s;
}
```

### 8.4 一键部署

```bash
# 重建并启动新服务 + 重启 Nginx 加载新配置
docker compose up -d --build image-gen
docker compose restart nginx
```

---

## 9. 自动化部署（CI/CD）

### 9.1 部署脚本

```bash
#!/bin/bash
# scripts/deploy.sh
set -e

DEPLOY_DIR="/opt/AI-Microservice"
BRANCH="${1:-main}"

cd $DEPLOY_DIR
git fetch origin && git checkout $BRANCH && git pull origin $BRANCH

[ ! -f .env ] && echo "缺少 .env，请先 cp .env.example .env && vim .env" && exit 1

docker compose up -d --build
sleep 10

for svc in "80/nginx-health" "80/api/video-analyze/health/live" "80/api/ui-builder/health/live" "8848/nacos/"; do
    curl -sf "http://localhost:$svc" > /dev/null 2>&1 && echo "✅ $svc" || echo "❌ $svc"
done

docker image prune -f
docker compose ps
```

### 9.2 GitHub Actions 示例

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SERVER_IP }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/AI-Microservice
            git pull origin main
            docker compose up -d --build
            docker image prune -f
```

---

## 10. 运维速查

### 常用命令

```bash
# Docker Compose
docker compose ps                              # 状态
docker compose logs -f --tail=100 ui-builder   # 日志
docker compose restart ui-builder              # 重启
docker compose up -d --build ui-builder        # 重建
docker compose down                            # 停止

# Nginx（也在 Docker 中）
docker compose logs -f nginx                   # Nginx 日志
docker compose restart nginx                   # 重载 Nginx 配置
docker compose exec nginx nginx -t             # 测试配置语法

# 鉴权测试（通过 Nginx 统一入口）
curl http://localhost/api/ui-builder/health                                    # 不需要 token
curl -H "Authorization: Bearer your-token" http://localhost/api/ui-builder/submit  # 需要 token
curl http://localhost/api/ui-builder/submit                                    # → 401
```

### 端口列表

| 服务 | 端口 | 说明 |
|------|------|------|
| Nginx | 80 / 443 | 外部唯一入口（Docker） |
| Nacos | 8848 / 9848 | 服务注册 & Token 热管理（限内网） |
| video-analyze | 9001 | 视频分析（Docker 内部） |
| ui-builder | 9002 | UI 构建（Docker 内部） |
| 新服务 | 9003+ | 按需分配 |

### 日志位置

| 位置 | 说明 |
|------|------|
| `./ui_builder/logs/` | ui-builder 业务日志 |
| `./video_analyze/logs/` | video-analyze 业务日志 |
| `docker compose logs <服务名>` | 容器标准输出 |
| `docker compose logs nginx` | Nginx 访问/错误日志 |
