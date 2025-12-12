#!/bin/bash
# 服务诊断命令

echo "=== 1. 检查进程 ==="
ps -ef | grep 'gunicorn .*wsgi:app' | grep -v grep
echo ""

echo "=== 2. 检查端口 ==="
ss -ltnp | grep 3000 || netstat -ltnp | grep 3000
echo ""

echo "=== 3. 检查PID文件 ==="
if [ -f /home/cnooc/python_app/feishu-bitable-receiver/gunicorn.pid ]; then
    PID=$(cat /home/cnooc/python_app/feishu-bitable-receiver/gunicorn.pid)
    echo "PID文件中的PID: $PID"
    if ps -p $PID > /dev/null 2>&1; then
        echo "✅ 进程存在"
    else
        echo "❌ 进程不存在"
    fi
else
    echo "❌ PID文件不存在"
fi
echo ""

echo "=== 4. 检查错误日志（最后50行）==="
if [ -f /home/cnooc/python_app/feishu-bitable-receiver/logs/error.log ]; then
    tail -50 /home/cnooc/python_app/feishu-bitable-receiver/logs/error.log
else
    echo "❌ 错误日志文件不存在"
fi
echo ""

echo "=== 5. 检查访问日志（最后20行）==="
if [ -f /home/cnooc/python_app/feishu-bitable-receiver/logs/access.log ]; then
    tail -20 /home/cnooc/python_app/feishu-bitable-receiver/logs/access.log
else
    echo "⚠ 访问日志文件不存在"
fi
echo ""

echo "=== 6. 测试本地连接 ==="
curl -v http://127.0.0.1:3000/healthz 2>&1 | head -20
echo ""

echo "=== 7. 检查项目目录和文件 ==="
cd /home/cnooc/python_app/feishu-bitable-receiver
pwd
ls -la wsgi.py app/main.py 2>&1
echo ""

echo "=== 8. 检查Python环境 ==="
which python3
python3 --version
echo ""

echo "=== 9. 尝试手动启动（测试）==="
echo "执行: cd /home/cnooc/python_app/feishu-bitable-receiver && source /home/cnooc/python_app/venv313/bin/activate && python3 -c 'from app.main import app; print(\"导入成功\")'"
cd /home/cnooc/python_app/feishu-bitable-receiver
source /home/cnooc/python_app/venv313/bin/activate
python3 -c 'from app.main import app; print("✅ 导入成功")' 2>&1

