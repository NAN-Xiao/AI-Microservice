# AI-Microservice 部署指南

> 适用于 Linux 服务器（CentOS 7+ / Ubuntu 20.04+），涵盖 Nginx + Nacos + Docker 全栈部署。

---

## 目录

1. [整体架构](#1-整体架构)
2. [服务器环境准备](#2-服务器环境准备)
3. [安装 Docker & Docker Compose](#3-安装-docker--docker-compose)
4. [部署微服务（Docker Compose）](#4-部署微服务docker-compose)
5. [安装并配置 Nginx（反向代理 & SSL）](#5-安装并配置-nginx反向代理--ssl)
6. [API 鉴权](#6-api-鉴权)
7. [Nacos 服务发现与配置管理](#7-nacos-服务发现与配置管理)
8. [新增微服务指南](#8-新增微服务指南)
9. [自动化部署（CI/CD）](#9-自动化部署cicd)
10. [运维速查](#10-运维速查)

---

## 1. 整体架构

```
            客户端 (Unity / Web / curl)
            Authorization: Bearer <token>
                        │
                        ▼
            ┌──────────────────────────────┐
            │       Nginx  (端口 80/443)    │
            │   SSL 卸载 + 按路径分发        │
            └──────────┬───────────────────┘
                       │  透传 Authorization 头
          ┌────────────┼────────────────┐
          │            │                │
 ┌────────▼────────┐ ┌▼──────────────┐ ┌▼──────────────┐
 │  video-analyze  │ │  ui-builder   │ │ 未来新服务 ... │
 │  (Docker:9001)  │ │ (Docker:9002) │ │ (Docker:900x) │
 │  FastAPI 鉴权   │ │  FastAPI 鉴权 │ │  FastAPI 鉴权  │
 └────────┬────────┘ └──────┬────────┘ └──────┬────────┘
          │                 │                  │
          └─────────────────┼──────────────────┘
                            │  启动时自动注册 / 关闭时注销
                 ┌──────────▼──────────┐
                 │  Nacos (8848/9848)  │
                 │  服务注册 + 配置管理  │
                 └─────────────────────┘
```

**请求链路：** 客户端 → Nginx(80/443) → 各微服务(900x)

**鉴权方式：** 与调用 OpenAI / 通义千问 API 一致 —— 请求头 `Authorization: Bearer <token>`

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
# 80/443  - Nginx（外部唯一入口）
# 8848    - Nacos 控制台（限内网）
# 9001    - video-analyze（内部，Nginx 转发）
# 9002    - ui-builder（内部，Nginx 转发）
# 9848    - Nacos gRPC

# Ubuntu (ufw)
sudo ufw allow 80,443/tcp
sudo ufw allow from 10.0.0.0/8 to any port 8848,9001,9002,9848 proto tcp
sudo ufw enable

# CentOS (firewalld)
sudo firewall-cmd --permanent --add-port={80,443}/tcp
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="8848" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="9001" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="9002" protocol="tcp" accept'
sudo firewall-cmd --reload
```

> **安全建议：** 9001/9002 端口不对公网开放，只允许 Nginx 本机（127.0.0.1）或内网访问。

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

## 4. 部署微服务（Docker Compose）

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

> 项目根目录的 `docker-compose.yml` 已包含完整配置（Nacos + 两个微服务）。
> 核心设计：所有服务共享 `AUTH_TOKENS` 环境变量，启动时自动注册到 Nacos。

```bash
# 构建并后台启动所有服务
docker compose up -d --build

# 查看状态
docker compose ps

# 查看某服务日志
docker compose logs -f ui-builder
docker compose logs -f video-analyze
docker compose logs -f nacos

# 重启单个服务
docker compose restart ui-builder

# 停止所有服务
docker compose down

# 停止并清除数据卷（慎用）
docker compose down -v
```

### 4.4 验证服务

```bash
# 健康检查（不需要 token）
curl http://localhost:9001/api/video-analyze/health
curl http://localhost:9002/api/ui-builder/health

# 如果开启了鉴权，业务接口需要 Bearer Token
curl -H "Authorization: Bearer your-secure-api-token-here" \
     http://localhost:9002/api/ui-builder/analyze

# 不带 token 调用业务接口 → 401
curl http://localhost:9002/api/ui-builder/analyze
# {"code": 401, "message": "Unauthorized: invalid or missing token"}

# Nacos 控制台
curl http://localhost:8848/nacos/
# 浏览器访问 http://<服务器IP>:8848/nacos
# 默认账号密码: nacos / nacos（务必修改）
```

---

## 5. 安装并配置 Nginx（反向代理 & SSL）

### 5.1 安装 Nginx

```bash
# ========== Ubuntu ==========
sudo apt install -y nginx
sudo systemctl enable nginx --now

# ========== CentOS ==========
sudo yum install -y epel-release
sudo yum install -y nginx
sudo systemctl enable nginx --now
```

### 5.2 申请 SSL 证书

**公网域名（Let's Encrypt 免费证书）：**
```bash
sudo apt install -y certbot python3-certbot-nginx   # Ubuntu
sudo yum install -y certbot python3-certbot-nginx    # CentOS

sudo certbot --nginx -d your-domain.com
sudo certbot renew --dry-run   # 验证自动续期
```

**内网部署（自签证书）：**
```bash
sudo mkdir -p /etc/nginx/certs
sudo openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout /etc/nginx/certs/key.pem \
  -out /etc/nginx/certs/cert.pem \
  -subj "/CN=ai-microservice" \
  -addext "subjectAltName=IP:10.1.73.202,IP:127.0.0.1,DNS:localhost"
```

### 5.3 Nginx 配置

```bash
sudo vim /etc/nginx/conf.d/ai-microservice.conf
```

```nginx
# ============================================================
#  AI-Microservice Nginx 配置
#  请求链路: 客户端 → Nginx(80/443) → 各微服务
#  鉴权: Nginx 透传 Authorization 头，FastAPI 中间件校验
# ============================================================

upstream video_analyze {
    server 127.0.0.1:9001;
    keepalive 16;
}

upstream ui_builder {
    server 127.0.0.1:9002;
    keepalive 16;
}

# ===== HTTP → HTTPS 重定向 =====
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

# ===== HTTPS 主配置 =====
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    # 内网自签证书:
    # ssl_certificate     /etc/nginx/certs/cert.pem;
    # ssl_certificate_key /etc/nginx/certs/key.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;

    client_max_body_size 50m;

    # --- video-analyze ---
    location /api/video-analyze/ {
        proxy_pass http://video_analyze;
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

    # --- ui-builder ---
    location /api/ui-builder/ {
        proxy_pass http://ui_builder;
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

    # --- Nacos 控制台（限内网）---
    location /nacos/ {
        proxy_pass http://127.0.0.1:8848/nacos/;
        proxy_set_header Host $host;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        deny all;
    }

    # --- 健康检查 ---
    location /nginx-health {
        return 200 "OK";
        add_header Content-Type text/plain;
    }
}
```

```bash
sudo nginx -t
sudo systemctl reload nginx

# 验证
curl -k https://localhost/api/ui-builder/health
curl -k -H "Authorization: Bearer your-token" https://localhost/api/ui-builder/analyze
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

## 7. Nacos 服务发现与配置管理

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

### 7.3 在 Nacos 中管理配置（可选）

登录 Nacos 控制台 → 配置管理 → 配置列表 → 新建配置：

| Data ID | Group | 格式 | 用途 |
|---------|-------|------|------|
| `ui-builder.yaml` | `AI_MICROSERVICE` | YAML | ui-builder 配置 |
| `video-analyze.yaml` | `AI_MICROSERVICE` | YAML | video-analyze 配置 |

> 当前配置优先级：环境变量 > settings.yaml。Nacos 配置推送（热更新）需额外集成 nacos-sdk-python，当前版本暂未实现。

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

```nginx
upstream image_gen {
    server 127.0.0.1:9003;
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
docker compose up -d --build image-gen
sudo nginx -t && sudo systemctl reload nginx
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

for svc in "9001/api/video-analyze/health/live" "9002/api/ui-builder/health/live" "8848/nacos/"; do
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

# Nginx
sudo nginx -t                                  # 测试配置
sudo systemctl reload nginx                    # 重载

# 鉴权测试
curl http://localhost:9002/api/ui-builder/health                                    # 不需要 token
curl -H "Authorization: Bearer your-token" http://localhost:9002/api/ui-builder/submit  # 需要 token
curl http://localhost:9002/api/ui-builder/submit                                    # → 401
```

### 端口列表

| 服务 | 端口 | 说明 |
|------|------|------|
| Nginx | 80 / 443 | 外部唯一入口 |
| Nacos | 8848 / 9848 | 服务注册 & 配置（限内网） |
| video-analyze | 9001 | 视频分析 |
| ui-builder | 9002 | UI 构建 |
| 新服务 | 9003+ | 按需分配 |

### 日志位置

| 位置 | 说明 |
|------|------|
| `./ui_builder/logs/` | ui-builder 业务日志 |
| `./video_analyze/logs/` | video-analyze 业务日志 |
| `docker compose logs <服务名>` | 容器标准输出 |
| `/var/log/nginx/` | Nginx 日志 |
