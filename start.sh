#!/bin/bash
###
 # @Descripttion: 
 # @Author: Ne0tea
 # @version: 
 # @Date: 2026-06-30 21:08:54
 # @LastEditors: Ne0tea
 # @LastEditTime: 2026-06-30 21:08:54
### 
set -e

echo "Starting Stock Analysis Dashboard..."
echo ""

# 优雅停止进程：先发送 SIGTERM，最多等待 120 秒，再发送 SIGKILL。
stop_process_until() {
    local pid="$1"
    local label="$2"
    local deadline="$3"

    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    echo "发送 SIGTERM 到 $label (PID: $pid)"
    kill -TERM "$pid" 2>/dev/null || true
    while kill -0 "$pid" 2>/dev/null; do
        process_state=$(ps -o stat= -p "$pid" 2>/dev/null || true)
        case "$process_state" in
            Z*) break ;;
        esac
        if [ "$SECONDS" -ge "$deadline" ]; then
            echo "$label 未在 120 秒内退出，发送 SIGKILL"
            kill -KILL "$pid" 2>/dev/null || true
            break
        fi
        sleep 1
    done
    wait "$pid" 2>/dev/null || true
}

stop_matching() {
    local pattern="$1"
    local label="$2"
    local pid
    local deadline=$((SECONDS + 120))

    for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
        [ "$pid" = "$$" ] && continue
        stop_process_until "$pid" "$label" "$deadline"
    done
}

stop_matching "python.*main.py" "旧后端"
stop_matching "npm.*dev" "旧前端"

# 启动后端
echo "启动后端..."
cd ./backend
python main.py > /tmp/stock_backend.log 2>&1 &
BACKEND_PID=$!

# 等待后端启动
echo "等待后端启动..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/watchlist > /dev/null 2>&1; then
        echo "✓ 后端启动成功 (PID: $BACKEND_PID)"
        break
    fi
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo "✗ 后端启动失败，查看日志："
        tail -50 /tmp/stock_backend.log
        exit 1
    fi
    sleep 1
done

if ! curl -s http://localhost:8000/api/watchlist > /dev/null 2>&1; then
    echo "✗ 后端启动超时，查看日志："
    tail -50 /tmp/stock_backend.log
    stop_process_until "$BACKEND_PID" "后端" "$((SECONDS + 120))"
    exit 1
fi

# 启动前端
echo "启动前端..."
cd ../frontend
npm run dev > /tmp/stock_frontend.log 2>&1 &
FRONTEND_PID=$!

# 等待前端启动
echo "等待前端启动..."
for i in {1..20}; do
    if curl -s http://localhost:5173 > /dev/null 2>&1; then
        echo "✓ 前端启动成功 (PID: $FRONTEND_PID)"
        break
    fi
    if ! kill -0 $FRONTEND_PID 2>/dev/null; then
        echo "✗ 前端启动失败，查看日志："
        tail -50 /tmp/stock_frontend.log
        stop_process_until "$BACKEND_PID" "后端" "$((SECONDS + 120))"
        exit 1
    fi
    sleep 1
done

echo ""
echo "=========================================="
echo "✓ 所有服务启动成功！"
echo ""
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"
echo "  API文档: http://localhost:8000/docs"
echo ""
echo "  后端日志: tail -f /tmp/stock_backend.log"
echo "  前端日志: tail -f /tmp/stock_frontend.log"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo "=========================================="
echo ""

# 清理函数
cleanup_done=0
cleanup() {
    if [ "$cleanup_done" -eq 1 ]; then
        return
    fi
    cleanup_done=1
    echo ""
    echo "正在停止服务..."
    local deadline=$((SECONDS + 120))
    stop_process_until "$BACKEND_PID" "后端" "$deadline"
    stop_process_until "$FRONTEND_PID" "前端" "$deadline"
    echo "服务已停止"
}

trap cleanup EXIT INT TERM

# 保持运行
wait || true
