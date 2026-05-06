#!/bin/bash
#############################################
# msg_queue 启动/停止/重启脚本
# 用法：./start.sh {start|stop|restart|status|build}
#############################################

set -e

APP_NAME="msg_queue"
APP_HOME=$(cd "$(dirname "$0")" && pwd)
PID_FILE="$APP_HOME/$APP_NAME.pid"
LOG_DIR="$APP_HOME/logs"
STARTUP_LOG="$LOG_DIR/startup.out"
JAR_PREFIX="http-message-queue"
APP_PORT="${APP_PORT:-8090}"

JAVA_CMD="${JAVA_CMD:-java}"
MAVEN_CMD="${MAVEN_CMD:-mvn}"
JAVA_OPTS="${JAVA_OPTS:-}"
APP_ARGS="${APP_ARGS:-}"
BUILD_BEFORE_START="${BUILD_BEFORE_START:-false}"

find_jar() {
    find "$APP_HOME/target" -maxdepth 1 -type f \
        -name "${JAR_PREFIX}-*.jar" ! -name "*.original" \
        -print 2>/dev/null | sort | tail -n 1
}

check_java() {
    if ! command -v "$JAVA_CMD" >/dev/null 2>&1; then
        echo "[ERROR] 未找到 Java: $JAVA_CMD"
        echo "[提示] 请安装 JDK 17+，或通过 JAVA_CMD 指定 Java 可执行文件"
        exit 1
    fi
}

check_maven() {
    if ! command -v "$MAVEN_CMD" >/dev/null 2>&1; then
        echo "[ERROR] 未找到 Maven: $MAVEN_CMD"
        echo "[提示] 请安装 Maven 3.6+，或通过 MAVEN_CMD 指定 Maven 可执行文件"
        exit 1
    fi
}

build() {
    check_maven
    echo "[$APP_NAME] 构建中..."
    cd "$APP_HOME"
    "$MAVEN_CMD" -DskipTests package
    echo "[$APP_NAME] 构建完成"
}

ensure_jar() {
    local jar
    jar=$(find_jar)

    if [ "$BUILD_BEFORE_START" = "true" ] || [ -z "$jar" ]; then
        build
        jar=$(find_jar)
    fi

    if [ -z "$jar" ]; then
        echo "[ERROR] 未找到可启动 jar: $APP_HOME/target/${JAR_PREFIX}-*.jar"
        exit 1
    fi

    echo "$jar"
}

find_port_pid() {
    if command -v ss >/dev/null 2>&1; then
        ss -lntp 2>/dev/null | sed -n "s/.*:${APP_PORT} .*pid=\([0-9]\+\).*/\1/p" | head -n 1
        return 0
    fi

    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$APP_PORT" -sTCP:LISTEN 2>/dev/null | head -n 1
        return 0
    fi

    if command -v netstat >/dev/null 2>&1; then
        netstat -lntp 2>/dev/null | sed -n "s/.*:${APP_PORT} .* \([0-9]\+\)\/.*/\1/p" | head -n 1
        return 0
    fi

    return 1
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        rm -f "$PID_FILE"
    fi

    local port_pid
    port_pid=$(find_port_pid || true)
    if [ -n "$port_pid" ] && kill -0 "$port_pid" 2>/dev/null; then
        echo "$port_pid" > "$PID_FILE"
        echo "$port_pid"
        return 0
    fi

    return 1
}

start() {
    local pid
    if pid=$(get_pid); then
        echo "[$APP_NAME] 已在运行中, PID=$pid"
        return 0
    fi

    check_java
    mkdir -p "$LOG_DIR"

    local jar
    jar=$(ensure_jar)

    echo "[$APP_NAME] 启动中..."
    echo "  目录: $APP_HOME"
    echo "  Java: $JAVA_CMD"
    echo "  Jar: $jar"
    echo "  Port: $APP_PORT"
    echo "  日志: $STARTUP_LOG"

    cd "$APP_HOME"
    nohup "$JAVA_CMD" $JAVA_OPTS -jar "$jar" $APP_ARGS > "$STARTUP_LOG" 2>&1 &

    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"
    sleep 3

    if kill -0 "$new_pid" 2>/dev/null; then
        echo "[$APP_NAME] 启动成功, PID=$new_pid"
        echo "[$APP_NAME] 查看日志: tail -f $STARTUP_LOG"
    else
        local recovered_pid
        recovered_pid=$(get_pid || true)
        if [ -n "$recovered_pid" ]; then
            echo "[$APP_NAME] 端口 ${APP_PORT} 已由 PID=$recovered_pid 接管"
            echo "[$APP_NAME] 查看日志: tail -f $STARTUP_LOG"
            return 0
        fi
        echo "[$APP_NAME] 启动失败，请检查日志: $STARTUP_LOG"
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
        if [ "$count" -ge 30 ]; then
            echo "[$APP_NAME] 强制终止..."
            kill -9 "$pid" 2>/dev/null || true
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
        ps -p "$pid" -o pid,user,%cpu,%mem,etime,cmd --no-headers 2>/dev/null || true
    else
        echo "[$APP_NAME] 未运行"
    fi
}

case "$1" in
    start)   start   ;;
    stop)    stop    ;;
    restart) restart ;;
    status)  status  ;;
    build)   build   ;;
    *)
        echo "用法: $0 {start|stop|restart|status|build}"
        echo "可选环境变量:"
        echo "  JAVA_CMD=/path/to/java"
        echo "  MAVEN_CMD=/path/to/mvn"
        echo "  JAVA_OPTS='-Xms256m -Xmx512m'"
        echo "  APP_ARGS='--server.port=8090'"
        echo "  BUILD_BEFORE_START=true"
        exit 1
        ;;
esac
