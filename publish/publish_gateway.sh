#!/bin/bash
# ==============================================================
# Gateway 构建 & 发布脚本
# 将本地 gateway（Spring Cloud Gateway）打包并发布到远程服务器
#
# 用法:
#   ./publish_gateway.sh                          # 构建并发布（交互输入密码）
#   RESTART=true ./publish_gateway.sh             # 发布后自动重启
#   REMOTE_PASS=xxx RESTART=true ./publish_gateway.sh  # 非交互模式
#
# 选项（环境变量）:
#   REMOTE_HOST    远程服务器地址（默认 10.1.6.76）
#   REMOTE_USER    远程用户名（默认 root）
#   REMOTE_PASS    远程密码（默认 ELEXtech%0609）
#   REMOTE_BASE    远程部署根目录（默认 /home/AI-Microservice2）
#   RESTART        发布后是否自动重启（默认 false）
#   JAVA_HOME      JDK 路径（默认 C:/Program Files/Java/jdk-17.0.18）
# ==============================================================

set -euo pipefail

# ── 配置区（按需修改）──────────────────────────────────────────
REMOTE_HOST="${REMOTE_HOST:-10.1.6.76}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PASS="${REMOTE_PASS:-ELEXtech%0609}"
REMOTE_BASE="${REMOTE_BASE:-/home/AI-Microservice2}"
RESTART="${RESTART:-false}"
JAVA_HOME="${JAVA_HOME:-C:/Program Files/Java/jdk-17.0.18}"

# 本地项目根目录（脚本的上一级）
LOCAL_BASE="$(cd "$(dirname "$0")/.." && pwd)"
GATEWAY_DIR="${LOCAL_BASE}/gateway"
REMOTE_GATEWAY="${REMOTE_BASE}/gateway"
# ──────────────────────────────────────────────────────────────

# 颜色输出
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

# ── sshpass 检测 & 密码处理 ───────────────────────────────────
SSHPASS_BIN=""

setup_auth() {
    if command -v sshpass &>/dev/null; then
        SSHPASS_BIN="sshpass"
        yellow "检测到 sshpass，将使用账号密码认证"
    else
        yellow "未检测到 sshpass，尝试测试 SSH Key 免密登录..."
        if ssh -o BatchMode=yes -o ConnectTimeout=5 \
               "${REMOTE_USER}@${REMOTE_HOST}" "echo ok" &>/dev/null; then
            green "SSH Key 免密登录可用，无需 sshpass"
            return 0
        fi
        red "需要 sshpass 才能使用密码登录"
        echo ""
        echo "  安装方式："
        echo "    Rocky Linux / CentOS:  sudo yum install -y sshpass"
        echo "    Ubuntu / Debian:       sudo apt install -y sshpass"
        echo "    macOS (Homebrew):      brew install hudochenkov/sshpass/sshpass"
        echo "    Git Bash (Windows):    不支持，请在 WSL 中安装"
        echo ""
        echo "  或者配置 SSH Key 免密登录（推荐）："
        echo "    ssh-copy-id ${REMOTE_USER}@${REMOTE_HOST}"
        exit 1
    fi

    if [ -z "${REMOTE_PASS}" ]; then
        echo -n "请输入 ${REMOTE_USER}@${REMOTE_HOST} 的密码: "
        read -rs REMOTE_PASS
        echo ""
    fi
    export SSHPASS="${REMOTE_PASS}"
}

# ── 包装 ssh / scp 命令 ───────────────────────────────────────
do_ssh() {
    if [ -n "${SSHPASS_BIN}" ]; then
        sshpass -e ssh -o StrictHostKeyChecking=no \
                -o ConnectTimeout=10 \
                "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    else
        ssh -o ConnectTimeout=10 \
            "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    fi
}

do_scp() {
    if [ -n "${SSHPASS_BIN}" ]; then
        sshpass -e scp -o StrictHostKeyChecking=no -r "$@"
    else
        scp -r "$@"
    fi
}

# ── 校验 SSH 连通性 ────────────────────────────────────────────
check_connection() {
    blue "测试连接 ${REMOTE_USER}@${REMOTE_HOST}..."
    if ! do_ssh "echo '连接成功'" 2>/dev/null; then
        red "无法连接到 ${REMOTE_HOST}，请检查网络、用户名或密码"
        exit 1
    fi
    green "连接正常"
}

# ── 构建 Gateway（Maven 打包）──────────────────────────────────
build_gateway() {
    banner "构建 Gateway"

    if [ ! -d "${GATEWAY_DIR}" ]; then
        red "Gateway 项目目录不存在: ${GATEWAY_DIR}"
        exit 1
    fi

    blue "执行 Maven 打包 (-DskipTests)..."
    cd "${GATEWAY_DIR}"
    export JAVA_HOME
    export PATH="${JAVA_HOME}/bin:${PATH}"

    if ! mvn clean package -DskipTests --no-transfer-progress; then
        red "Maven 打包失败，请检查本地编译错误"
        exit 1
    fi

    # 找到打好的 jar
    JAR_FILE=$(find "${GATEWAY_DIR}/target" -maxdepth 1 -name "*.jar" ! -name "*sources*" | head -1)
    if [ -z "${JAR_FILE}" ]; then
        red "未找到 target/*.jar，打包可能失败"
        exit 1
    fi
    JAR_NAME=$(basename "${JAR_FILE}")
    green "打包完成: ${JAR_NAME}"
}

# ── 发布 Gateway ───────────────────────────────────────────────
publish_gateway() {
    banner "发布 Gateway"

    # 1. 创建远程目录
    blue "创建远程目录 ${REMOTE_GATEWAY}..."
    do_ssh "mkdir -p ${REMOTE_GATEWAY}/logs"

    # 2. 停止远程服务（如果在运行）
    if [ "${RESTART}" = "true" ]; then
        blue "停止远程 gateway..."
        do_ssh "[ -f ${REMOTE_GATEWAY}/start.sh ] && bash ${REMOTE_GATEWAY}/start.sh stop || true"
        sleep 2
    fi

    # 3. 上传 JAR
    blue "上传 ${JAR_NAME}..."
    do_scp "${JAR_FILE}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_GATEWAY}/${JAR_NAME}"

    # 4. 上传 start.sh（如果存在）
    if [ -f "${GATEWAY_DIR}/start.sh" ]; then
        blue "上传 start.sh..."
        do_scp "${GATEWAY_DIR}/start.sh" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_GATEWAY}/start.sh"
        do_ssh "chmod +x ${REMOTE_GATEWAY}/start.sh"
    fi

    # 5. 上传 docs（如果存在）
    if [ -d "${GATEWAY_DIR}/docs" ]; then
        blue "上传 docs/..."
        do_scp "${GATEWAY_DIR}/docs" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_GATEWAY}/"
    fi

    # 6. 上传配置文件（如果存在 application*.yml / application*.properties）
    for cfg in "${GATEWAY_DIR}"/src/main/resources/application*.yml \
               "${GATEWAY_DIR}"/src/main/resources/application*.properties \
               "${GATEWAY_DIR}"/src/main/resources/bootstrap*.yml; do
        if [ -f "${cfg}" ]; then
            blue "上传配置: $(basename "${cfg}")..."
            do_scp "${cfg}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_GATEWAY}/"
        fi
    done

    # 7. 重启
    if [ "${RESTART}" = "true" ]; then
        blue "启动远程 gateway..."
        do_ssh "bash ${REMOTE_GATEWAY}/start.sh start"
    fi

    green "Gateway 发布完成 → ${REMOTE_HOST}:${REMOTE_GATEWAY}/${JAR_NAME}"
}

# ── 健康检查 ───────────────────────────────────────────────────
health_check() {
    [ "${RESTART}" != "true" ] && return
    banner "健康检查"
    sleep 5
    if do_ssh "curl -sf --connect-timeout 5 'http://127.0.0.1:8081/gateway-health' > /dev/null 2>&1"; then
        green "gateway (端口 8081) — 正常"
    else
        yellow "gateway (端口 8081) — 未响应（可能仍在启动中）"
    fi
}

# ── 完成摘要 ───────────────────────────────────────────────────
print_summary() {
    banner "发布完成"
    echo "  目标服务器:  ${REMOTE_USER}@${REMOTE_HOST}"
    echo "  部署目录:    ${REMOTE_GATEWAY}"
    echo "  JAR 文件:    ${JAR_NAME}"
    echo "  自动重启:    ${RESTART}"
    echo ""
    if [ "${RESTART}" = "false" ]; then
        yellow "提示: 加 RESTART=true 可在发布后自动重启 → RESTART=true ./publish_gateway.sh"
    fi
}

# ── 入口 ───────────────────────────────────────────────────────
main() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║     Gateway 构建 & 发布脚本                  ║"
    echo "║     目标: ${REMOTE_USER}@${REMOTE_HOST}             ║"
    echo "╚══════════════════════════════════════════════╝"

    setup_auth
    check_connection
    build_gateway
    publish_gateway
    health_check
    print_summary
}

main "$@"
