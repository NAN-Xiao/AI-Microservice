#!/bin/bash
# ==============================================================
# AI-Microservice 发布脚本
# 将本地工程发布到远程服务器 10.1.6.76
#
# 用法:
#   ./publish.sh                    # 发布全部服务（交互输入密码）
#   ./publish.sh ui_builder         # 只发布 ui_builder
#   ./publish.sh video_analyze      # 只发布 video_analyze
#   ./publish.sh see_through        # 只发布 see_through
#   ./publish.sh ui_builder video_analyze see_through # 发布多个指定服务
#
# 选项（环境变量）:
#   REMOTE_PASS=xxx ./publish.sh   # 非交互模式（CI/脚本调用）
#   REMOTE_USER=root ./publish.sh  # 指定用户
# ==============================================================

set -euo pipefail

# ── 配置区（按需修改）──────────────────────────────────────────
REMOTE_HOST="10.1.6.76"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_PASS="${REMOTE_PASS:-ELEXtech%0609}"  # 默认密码，可通过环境变量覆盖
REMOTE_BASE="/home/AI-Microservice"         # 服务器上的部署根目录

# 本地项目根目录（脚本的上一级）
LOCAL_BASE="$(cd "$(dirname "$0")/.." && pwd)"
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
REMOTE_PASS="${REMOTE_PASS:-}"   # 可通过环境变量预设，不推荐明文写脚本

setup_auth() {
    # 优先检测 sshpass
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
        # 两种方式都不行
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

    # 获取密码（环境变量优先，否则交互输入）
    if [ -z "${REMOTE_PASS}" ]; then
        echo -n "请输入 ${REMOTE_USER}@${REMOTE_HOST} 的密码: "
        read -rs REMOTE_PASS
        echo ""
    fi
    export SSHPASS="${REMOTE_PASS}"
}

# ── 包装 ssh / scp / rsync 命令，自动注入密码 ─────────────────
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

do_rsync() {
    # Git Bash 下 rsync 不可用，改用 scp 递归上传
    # 用法: do_rsync <本地目录/> <user@host:远程目录/>
    local src="$1"
    local dst="$2"
    if [ -n "${SSHPASS_BIN}" ]; then
        sshpass -e scp -o StrictHostKeyChecking=no -r "${src}" "${dst}"
    else
        scp -o StrictHostKeyChecking=no -r "${src}" "${dst}"
    fi
}

# ── 服务端口映射（用于重启时兜底清理残留进程）───────────────────────
get_service_port() {
    case "$1" in
        ui_builder)    echo "9002" ;;
        video_analyze) echo "9001" ;;
        see_through)   echo "9004" ;;
        *)             echo ""     ;;
    esac
}

# ── 重启前停止旧进程（先优雅停止，再按端口兜底强杀）─────────────────
stop_remote_service() {
    local svc_name="$1"
    local remote_dir="$2"
    local svc_port
    svc_port="$(get_service_port "$svc_name")"

    blue "停止远程 ${svc_name}..."
    do_ssh "bash -lc '
        set +e
        if [ -f ${remote_dir}/start.sh ]; then
            bash ${remote_dir}/start.sh stop
        fi
        if [ -n \"${svc_port}\" ]; then
            pid=\$(ss -lntp 2>/dev/null | sed -n \"s/.*:${svc_port} .*pid=\\([0-9]\\+\\).*/\\1/p\" | head -n 1)
            if [ -n \"\$pid\" ]; then
                echo \"[提示] 检测到端口 ${svc_port} 仍被 PID=\$pid 占用，执行强制停止...\"
                kill \"\$pid\" 2>/dev/null || true
                sleep 1
                kill -9 \"\$pid\" 2>/dev/null || true
            fi
        fi
        exit 0
    '"
    sleep 1
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

# ── 发布 Python 服务通用函数 ───────────────────────────────────
publish_python_service() {
    local svc_name="$1"
    banner "发布 ${svc_name}"

    local local_dir="${LOCAL_BASE}/${svc_name}"
    local remote_dir="${REMOTE_BASE}/${svc_name}"

    if [ ! -d "${local_dir}" ]; then
        red "本地目录不存在: ${local_dir}"
        exit 1
    fi

    # 1. 创建远程目录
    blue "创建远程目录 ${remote_dir}..."
    do_ssh "mkdir -p ${remote_dir}/logs"

    # 2. 停止远程服务（每次发布都先停后启）
    stop_remote_service "${svc_name}" "${remote_dir}"

    # 3. scp 上传源码（先清除旧文件，保留 venv 和 logs）
    blue "同步源码到 ${REMOTE_HOST}:${remote_dir}..."
    # 删除远程旧文件（保留 venv/ 和 logs/）
    do_ssh "find ${remote_dir} -maxdepth 1 -not -name 'venv' -not -name 'logs' -not -path '${remote_dir}' -exec rm -rf {} + 2>/dev/null; true"
    # 整体上传（scp 会把本地目录内容传过去）
    do_scp "${local_dir}/." "${REMOTE_USER}@${REMOTE_HOST}:${remote_dir}/"

    # 4. 修复行尾（Windows \r\n → Unix \n）+ 赋予执行权限
    do_ssh "bash -lc '
        cd ${remote_dir}
        for f in start.sh *.sh; do
            [ -f \"\$f\" ] && sed -i \"s/\\r//\" \"\$f\" && chmod +x \"\$f\"
        done
    '"

    # 5. 安装/更新 Python 依赖
    blue "更新远程 Python 依赖..."
    do_ssh "bash -lc '
        cd ${remote_dir}
        # 若 venv 不存在或不是 Python 3.11，则重建，避免旧环境(如 3.9)导致语法不兼容
        if [ ! -x venv/bin/python ] || ! venv/bin/python -c \"import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)\"; then
            echo \"[提示] 创建/重建 Python 3.11 虚拟环境...\"
            rm -rf venv
            python3.11 -m venv venv
        fi
        source venv/bin/activate
        pip install -q --upgrade pip
        pip install -q -r requirements.txt
        deactivate
        echo \"依赖更新完成\"
    '"

    # 6. 启动服务
    blue "启动远程 ${svc_name}..."
    do_ssh "bash ${remote_dir}/start.sh start"

    green "${svc_name} 发布完成 → ${REMOTE_HOST}:${remote_dir}"
}

publish_ui_builder()    { publish_python_service "ui_builder";    }
publish_video_analyze() { publish_python_service "video_analyze"; }
publish_see_through()   { publish_python_service "see_through";   }

# ── 健康检查 ───────────────────────────────────────────────────
health_check() {
    banner "健康检查"
    sleep 5
    local checks=(
        "ui_builder|9002|http://127.0.0.1:9002/api/ui-builder/health"
        "video_analyze|9001|http://127.0.0.1:9001/api/video-analyze/health"
        "see_through|9004|http://127.0.0.1:9004/api/see-through/health"
    )
    for check in "${checks[@]}"; do
        IFS='|' read -r name port url <<< "${check}"
        if do_ssh "curl -sf --connect-timeout 5 '${url}' > /dev/null 2>&1"; then
            green "${name} (端口 ${port}) — 正常"
        else
            yellow "${name} (端口 ${port}) — 未响应（可能仍在启动中）"
        fi
    done
}

# ── 完成摘要 ───────────────────────────────────────────────────
print_summary() {
    banner "发布完成"
    echo "  目标服务器:  ${REMOTE_USER}@${REMOTE_HOST}"
    echo "  部署根目录:  ${REMOTE_BASE}"
    echo ""
    echo "  登录服务器查看服务状态:"
    echo "    ssh ${REMOTE_USER}@${REMOTE_HOST}"
    echo "    bash ${REMOTE_BASE}/deploy.sh status"
}

# ── 入口 ───────────────────────────────────────────────────────
main() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║       AI-Microservice 发布脚本               ║"
    echo "║       目标: ${REMOTE_USER}@${REMOTE_HOST}             ║"
    echo "╚══════════════════════════════════════════════╝"

    setup_auth      # 确定认证方式（Key 或 sshpass+密码）
    check_connection

    local targets=("$@")
    if [ ${#targets[@]} -eq 0 ]; then
        targets=("ui_builder" "video_analyze" "see_through")
    fi

    for target in "${targets[@]}"; do
        case "${target}" in
            ui_builder)    publish_ui_builder    ;;
            video_analyze) publish_video_analyze ;;
            see_through)   publish_see_through   ;;
            *)
                red "未知服务: ${target}（可选: ui_builder / video_analyze / see_through）"
                exit 1
                ;;
        esac
    done

    health_check
    print_summary
}

main "$@"
