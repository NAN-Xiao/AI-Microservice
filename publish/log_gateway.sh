#!/bin/bash
# 实时查看远程 Gateway 日志
# 用法: bash log_gateway.sh

REMOTE_HOST="10.1.6.76"
REMOTE_USER="root"
LOG_DIR="/home/AI-Microservice2/gateway/logs"

echo "══════════════════════════════════════════"
echo "  Gateway 实时日志  ${REMOTE_USER}@${REMOTE_HOST}"
echo "  Ctrl+C 退出"
echo "══════════════════════════════════════════"
echo ""

ssh -t "${REMOTE_USER}@${REMOTE_HOST}" \
    "tail -f ${LOG_DIR}/ai-gateway.log 2>/dev/null || tail -f ${LOG_DIR}/startup.out 2>/dev/null || echo '日志文件不存在，服务可能尚未启动'"
