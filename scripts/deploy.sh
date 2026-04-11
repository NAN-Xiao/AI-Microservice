#!/bin/bash
# ============================================================
# scripts/deploy.sh — AI-Microservice 一键部署/更新
#
# 用法:
#   ./scripts/deploy.sh              # 部署全部服务
#   ./scripts/deploy.sh ui-builder   # 只部署指定服务
# ============================================================
set -e

DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="$1"

cd "$DEPLOY_DIR"

echo "========== 检查 .env =========="
if [ ! -f .env ]; then
    echo "错误: 缺少 .env 文件"
    echo "  cp .env.example .env && vim .env"
    exit 1
fi

echo "========== 构建并启动 =========="
if [ -n "$SERVICE" ]; then
    echo "目标服务: $SERVICE"
    docker compose up -d --build "$SERVICE"
else
    echo "目标: 全部服务"
    docker compose up -d --build
fi

echo "========== 等待服务就绪 =========="
sleep 10

echo "========== 健康检查 =========="
check_health() {
    local name=$1 port=$2 path=$3
    if curl -sf "http://localhost:${port}${path}" > /dev/null 2>&1; then
        echo "  ✅ $name (port $port)"
    else
        echo "  ❌ $name (port $port)"
    fi
}

check_health "video-analyze" 9001 "/api/video-analyze/health/live"
check_health "ui-builder"    9002 "/api/ui-builder/health/live"
check_health "gateway"       8080 "/actuator/health"
check_health "nacos"         8848 "/nacos/"

echo "========== 清理旧镜像 =========="
docker image prune -f

echo "========== 当前状态 =========="
docker compose ps
