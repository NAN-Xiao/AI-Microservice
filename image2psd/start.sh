#!/bin/bash
#############################################
# image2psd 启动/停止/重启脚本
# 用法：./start.sh {start|stop|restart|status}
#############################################

APP_NAME="image2psd"
APP_HOME=$(cd "$(dirname "$0")" && pwd)
PID_FILE="$APP_HOME/$APP_NAME.pid"
LOG_DIR="$APP_HOME/logs"
VENV_DIR="$APP_HOME/venv"
PYTHON="${VENV_DIR}/bin/python"

check_venv() {
    if [ ! -f "$PYTHON" ]; then
        echo "[ERROR] 虚拟环境不存在: $VENV_DIR"
        echo "[提示]  请先执行:"
        echo "  python3.11 -m venv venv"
        echo "  source venv/bin/activate"
        echo "  pip install -r requirements.txt"
        exit 1
    fi
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    return 1
}

start() {
    local pid
    if pid=$(get_pid); then
        echo "[$APP_NAME] 已在运行中, PID=$pid"
        return 0
    fi

    check_venv
    mkdir -p "$LOG_DIR"

    echo "[$APP_NAME] 启动中..."
    echo "  目录: $APP_HOME"
    echo "  Python: $PYTHON"
    echo "  日志: $LOG_DIR/"

    cd "$APP_HOME"
    nohup "$PYTHON" run.py > "$LOG_DIR/startup.out" 2>&1 &

    local new_pid=$!
    echo $new_pid > "$PID_FILE"
    sleep 3

    if kill -0 "$new_pid" 2>/dev/null; then
        echo "[$APP_NAME] 启动成功, PID=$new_pid"
        echo "[$APP_NAME] 查看日志: tail -f $LOG_DIR/startup.out"
    else
        echo "[$APP_NAME] 启动失败，请检查日志: $LOG_DIR/startup.out"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop() {
    local pid
    if ! pid=$(get_pid); then
        echo "[$APP_NAME] 未在运行"
        return 0
    fi

    echo "[$APP_NAME] 停止中, PID=$pid..."
    kill "$pid"
    local count=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        count=$((count + 1))
        if [ $count -ge 15 ]; then
            echo "[$APP_NAME] 强制终止..."
            kill -9 "$pid" 2>/dev/null
            break
        fi
    done

    rm -f "$PID_FILE"
    echo "[$APP_NAME] 已停止"
}

restart() {
    stop
    sleep 2
    start
}

status() {
    local pid
    if pid=$(get_pid); then
        echo "[$APP_NAME] 运行中, PID=$pid"
        ps -p "$pid" -o pid,user,%cpu,%mem,etime,cmd --no-headers 2>/dev/null
    else
        echo "[$APP_NAME] 未运行"
    fi
}

case "$1" in
    start)   start   ;;
    stop)    stop    ;;
    restart) restart ;;
    status)  status  ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
