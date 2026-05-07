#!/bin/bash
# ==============================================================
# msg_queue 独立发布脚本
# 将本地 msg_queue 发布到远程服务器并重启
#
# 用法:
#   ./publish_msg_queue.sh
#
# 选项（环境变量）:
#   REMOTE_PASS=xxx ./publish_msg_queue.sh
#   REMOTE_USER=root ./publish_msg_queue.sh
#   REMOTE_HOST=10.1.6.76 ./publish_msg_queue.sh
#   REMOTE_BASE=/home/AI-Microservice/msg_queue ./publish_msg_queue.sh
# ==============================================================

set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-10.1.6.76}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PASS="${REMOTE_PASS:-ELEXtech%0609}"
REMOTE_BASE="${REMOTE_BASE:-/home/AI-Microservice/msg_queue}"

LOCAL_BASE="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DIR="${LOCAL_BASE}/msg_queue"
REMOTE_DIR="${REMOTE_BASE}"
JAR_PREFIX="http-message-queue"
SERVICE_PORT="8090"

green()  { echo -e "\033[32m[✓] $*\033[0m"; }
red()    { echo -e "\033[31m[✗] $*\033[0m"; }
yellow() { echo -e "\033[33m[→] $*\033[0m"; }
blue()   { echo -e "\033[34m[…] $*\033[0m"; }
banner() {
    echo ""
    echo "══════════════════════════════════════════════"
    echo "  $*"
    echo "══════════════════════════════════════════════"
}

SSHPASS_BIN=""

setup_auth() {
    if command -v sshpass >/dev/null 2>&1; then
        SSHPASS_BIN="sshpass"
        yellow "检测到 sshpass，将使用账号密码认证"
        if [ -z "${REMOTE_PASS}" ]; then
            echo -n "请输入 ${REMOTE_USER}@${REMOTE_HOST} 的密码: "
            read -rs REMOTE_PASS
            echo ""
        fi
        export SSHPASS="${REMOTE_PASS}"
    else
        yellow "未检测到 sshpass，默认使用当前 SSH 配置"
    fi
}

do_ssh() {
    if [ -n "${SSHPASS_BIN}" ]; then
        sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
            "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    else
        ssh -o ConnectTimeout=10 "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    fi
}

do_scp() {
    if [ -n "${SSHPASS_BIN}" ]; then
        sshpass -e scp -o StrictHostKeyChecking=no "$@"
    else
        scp "$@"
    fi
}

check_connection() {
    blue "测试连接 ${REMOTE_USER}@${REMOTE_HOST}..."
    if ! do_ssh "echo '连接成功'" >/dev/null 2>&1; then
        red "无法连接到 ${REMOTE_HOST}"
        exit 1
    fi
    green "连接正常"
}

build_local_jar() {
    banner "本地构建 msg_queue"
    if [ ! -d "${LOCAL_DIR}" ]; then
        red "本地目录不存在: ${LOCAL_DIR}"
        exit 1
    fi

    cd "${LOCAL_DIR}"
    mvn clean package
}

find_local_jar() {
    find "${LOCAL_DIR}/target" -maxdepth 1 -type f \
        -name "${JAR_PREFIX}-*.jar" ! -name "*.original" \
        -print | sort | tail -n 1
}

upload_artifacts() {
    local jar_file="$1"
    banner "上传 msg_queue"

    blue "创建远程目录 ${REMOTE_DIR}..."
    do_ssh "mkdir -p ${REMOTE_DIR}/target ${REMOTE_DIR}/logs"

    blue "清理远程旧包..."
    do_ssh "find ${REMOTE_DIR}/target -maxdepth 1 -type f -name '${JAR_PREFIX}-*.jar' -delete 2>/dev/null || true"

    blue "上传 jar 与启动脚本..."
    do_scp "${jar_file}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/target/"
    do_scp "${LOCAL_DIR}/start.sh" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/start.sh"

    blue "修复行尾并赋权..."
    do_ssh "bash -lc '
        sed -i \"s/\\r//\" ${REMOTE_DIR}/start.sh
        chmod +x ${REMOTE_DIR}/start.sh
    '"
}

restart_remote_service() {
    banner "重启 msg_queue"
    do_ssh "bash ${REMOTE_DIR}/start.sh restart"
}

health_check() {
    banner "健康检查"
    sleep 5
    if do_ssh "curl -sf --connect-timeout 5 'http://127.0.0.1:${SERVICE_PORT}/health' >/dev/null 2>&1"; then
        green "msg_queue (端口 ${SERVICE_PORT}) — 正常"
    else
        yellow "msg_queue (端口 ${SERVICE_PORT}) — 未响应（可能仍在启动中）"
    fi
}

print_summary() {
    banner "发布完成"
    echo "  目标服务器:  ${REMOTE_USER}@${REMOTE_HOST}"
    echo "  部署目录:    ${REMOTE_DIR}"
    echo "  健康检查:    http://127.0.0.1:${SERVICE_PORT}/health"
    echo ""
    echo "  远程查看状态:"
    echo "    ssh ${REMOTE_USER}@${REMOTE_HOST}"
    echo "    bash ${REMOTE_DIR}/start.sh status"
}

main() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║        msg_queue 独立发布脚本               ║"
    echo "║        目标: ${REMOTE_USER}@${REMOTE_HOST}             ║"
    echo "╚══════════════════════════════════════════════╝"

    setup_auth
    check_connection
    build_local_jar

    local jar_file
    jar_file="$(find_local_jar)"
    if [ -z "${jar_file}" ]; then
        red "未找到打包产物: ${LOCAL_DIR}/target/${JAR_PREFIX}-*.jar"
        exit 1
    fi

    upload_artifacts "${jar_file}"
    restart_remote_service
    health_check
    print_summary
}

main "$@"
