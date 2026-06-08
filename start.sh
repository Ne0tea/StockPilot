#!/bin/bash
set -e

echo "Starting Stock Analysis Dashboard..."
echo ""

# 清理旧进程
pkill -f "python.*main.py" 2>/dev/null || true
pkill -f "npm.*dev" 2>/dev/null || true
sleep 1

# 启动后端
echo "启动后端..."
cd /mnt/d/Bio_analysis/software/Stock_analysis/backend
/home/ne0tea/miniconda3/envs/stockPanel/bin/python main.py > /tmp/stock_backend.log 2>&1 &
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
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

# 启动前端
echo "启动前端..."
cd /mnt/d/Bio_analysis/software/Stock_analysis/frontend
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
        kill $BACKEND_PID 2>/dev/null || true
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
cleanup() {
    echo ""
    echo "正在停止服务..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    pkill -P $BACKEND_PID 2>/dev/null || true
    pkill -P $FRONTEND_PID 2>/dev/null || true
    echo "服务已停止"
    exit 0
}

trap cleanup EXIT INT TERM

# 保持运行
wait
