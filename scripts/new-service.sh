#!/bin/bash
# ============================================================
# scripts/new-service.sh — 从 ui_builder 模板快速创建新微服务
#
# 用法:  ./scripts/new-service.sh <service_name> <port>
# 示例:  ./scripts/new-service.sh image_gen 9003
# ============================================================
set -e

NAME=$1
PORT=$2

if [ -z "$NAME" ] || [ -z "$PORT" ]; then
    echo "用法: $0 <service_name> <port>"
    echo "示例: $0 image_gen 9003"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$PROJECT_DIR/ui_builder"
TARGET="$PROJECT_DIR/$NAME"
DISPLAY_NAME=$(echo "$NAME" | tr '_' '-')

if [ -d "$TARGET" ]; then
    echo "错误: 目录 $TARGET 已存在"
    exit 1
fi

echo "========== 创建微服务: $NAME (端口 $PORT) =========="

# 创建目录结构
mkdir -p "$TARGET/app/routers" "$TARGET/app/services" "$TARGET/app/models" "$TARGET/app/utils"

# 复制框架文件
cp "$TEMPLATE/Dockerfile"             "$TARGET/Dockerfile"
cp "$TEMPLATE/.dockerignore"          "$TARGET/.dockerignore"
cp "$TEMPLATE/requirements.txt"       "$TARGET/requirements.txt"
cp "$TEMPLATE/run.py"                 "$TARGET/run.py"
cp "$TEMPLATE/settings.example.yaml"  "$TARGET/settings.example.yaml"
cp "$TEMPLATE/settings.example.yaml"  "$TARGET/settings.yaml"

# 复制 app 框架文件
cp "$TEMPLATE/app/__init__.py"        "$TARGET/app/__init__.py"
cp "$TEMPLATE/app/config.py"          "$TARGET/app/config.py"
cp "$TEMPLATE/app/main.py"            "$TARGET/app/main.py"

# routers
cp "$TEMPLATE/app/routers/__init__.py"  "$TARGET/app/routers/__init__.py"
cp "$TEMPLATE/app/routers/health.py"    "$TARGET/app/routers/health.py"

# 创建空的业务 router 模板
cat > "$TARGET/app/routers/api.py" << 'ROUTER_EOF'
"""业务路由 —— 在此编写你的 API 接口"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
async def hello():
    return {"message": "Hello from new service"}
ROUTER_EOF

# models
cp "$TEMPLATE/app/models/__init__.py"   "$TARGET/app/models/__init__.py"
cp "$TEMPLATE/app/models/response.py"   "$TARGET/app/models/response.py"

# services
cp "$TEMPLATE/app/services/__init__.py" "$TARGET/app/services/__init__.py"

# utils
cp "$TEMPLATE/app/utils/__init__.py"    "$TARGET/app/utils/__init__.py"
cp "$TEMPLATE/app/utils/logger.py"      "$TARGET/app/utils/logger.py"

# 替换端口和服务名
sed -i "s/9002/$PORT/g" "$TARGET/Dockerfile" "$TARGET/settings.example.yaml" "$TARGET/settings.yaml" "$TARGET/run.py"
sed -i "s/ui-builder/$DISPLAY_NAME/g" "$TARGET/Dockerfile" "$TARGET/settings.example.yaml" "$TARGET/settings.yaml"

# 修改 main.py 中的路由前缀和 router include
sed -i "s|/api/ui-builder|/api/$DISPLAY_NAME|g" "$TARGET/app/main.py"
sed -i "s|from app.routers import analyze|from app.routers import api|g" "$TARGET/app/main.py"
sed -i "s|analyze.router|api.router|g" "$TARGET/app/main.py"
sed -i "s|UI Builder|${NAME}|g" "$TARGET/app/main.py"

echo ""
echo "✅ 服务 $NAME 创建完成"
echo ""
echo "目录结构:"
find "$TARGET" -type f | sed "s|$PROJECT_DIR/||" | sort | head -20
echo ""
echo "下一步:"
echo "  1. 编写业务路由: $NAME/app/routers/api.py"
echo "  2. 编写业务逻辑: $NAME/app/services/"
echo "  3. 添加到 docker-compose.yml （参考文档 docs/deployment-guide.md 第 8 节）"
echo "  4. 添加 Gateway 路由"
echo "  5. docker compose up -d --build $DISPLAY_NAME"
