#!/bin/bash
# feishu-bitable-receiver 一键部署脚本
# 服务器信息
SERVER_IP="10.77.79.147"
SERVER_USER="cnooc"
SERVER_PASSWORD="DayDayUp@2024.."
LOCAL_TAR_FILE="/Users/tianzeyuan/Desktop/feishu-bitable-receiver.tar.gz"
REMOTE_DIR="/home/cnooc/python_app"
REMOTE_TAR_FILE="$REMOTE_DIR/feishu-bitable-receiver.tar.gz"
PROJECT_DIR="$REMOTE_DIR/feishu-bitable-receiver"

echo "=========================================="
echo "feishu-bitable-receiver 一键部署脚本"
echo "=========================================="
echo "服务器: $SERVER_USER@$SERVER_IP"
echo ""

# 检查本地压缩包是否存在
if [ ! -f "$LOCAL_TAR_FILE" ]; then
    echo "❌ 错误: 压缩包不存在: $LOCAL_TAR_FILE"
    echo "请先执行打包命令生成压缩包"
    exit 1
fi

echo "✅ 找到压缩包: $LOCAL_TAR_FILE"
echo ""

# 步骤 1: 上传压缩包
echo "【步骤 1】上传压缩包到服务器..."
echo "正在上传: $LOCAL_TAR_FILE -> $SERVER_USER@$SERVER_IP:$REMOTE_TAR_FILE"

# 使用 sshpass 自动输入密码（如果已安装）
if command -v sshpass &> /dev/null; then
    sshpass -p "$SERVER_PASSWORD" scp "$LOCAL_TAR_FILE" "$SERVER_USER@$SERVER_IP:$REMOTE_TAR_FILE"
else
    # 如果没有 sshpass，使用交互式 scp
    echo "提示: 如果未安装 sshpass，将使用交互式上传（需要手动输入密码）"
    echo "密码: $SERVER_PASSWORD"
    scp "$LOCAL_TAR_FILE" "$SERVER_USER@$SERVER_IP:$REMOTE_TAR_FILE"
fi

if [ $? -ne 0 ]; then
    echo "❌ 上传失败"
    exit 1
fi

echo "✅ 上传成功"
echo ""

# 步骤 2: 执行部署命令
echo "【步骤 2】在服务器上执行部署..."
echo "正在连接服务器并执行部署命令..."

# 部署命令
DEPLOY_SCRIPT=$(cat << 'DEPLOY_EOF'
cd /home/cnooc/python_app/feishu-bitable-receiver

# 停止服务
echo "停止服务..."
kill $(cat gunicorn.pid) 2>/dev/null || pkill -f "gunicorn .*wsgi:app" || true
pkill -f "python sankey_service_with_polling.py" || true
sleep 2

# 备份当前版本
echo "备份当前版本..."
BACKUP_DIR="/home/cnooc/python_app/feishu-bitable-receiver.backup.$(date +%Y%m%d_%H%M%S)"
[ -d "/home/cnooc/python_app/feishu-bitable-receiver" ] && mv /home/cnooc/python_app/feishu-bitable-receiver "$BACKUP_DIR" || true

# 解压新版本
echo "解压新版本..."
cd /home/cnooc/python_app
tar xzf feishu-bitable-receiver.tar.gz

# 恢复配置和创建目录
echo "恢复配置..."
cd /home/cnooc/python_app/feishu-bitable-receiver
[ -f "$BACKUP_DIR/.env" ] && cp "$BACKUP_DIR/.env" .env || echo "⚠ 请检查 .env 文件"
mkdir -p logs /home/cnooc/file/excel /home/cnooc/file/sankey

# 安装/更新依赖
echo "安装/更新依赖..."
source /home/cnooc/python_app/venv313/bin/activate
pip install -r requirements.txt --quiet

# 启动服务
echo "启动服务..."
nohup gunicorn -w 3 --threads 2 --timeout 120 -b 0.0.0.0:3000 \
  --access-logfile ./logs/access.log \
  --error-logfile  ./logs/error.log  \
  --log-level info --capture-output \
  wsgi:app >/dev/null 2>&1 &
echo $! > gunicorn.pid

# 验证服务
sleep 3
echo ""
echo "=== 服务状态 ==="
ps -ef | grep 'gunicorn .*wsgi:app' | grep -v grep | head -2
ss -ltnp | grep 3000 || netstat -ltnp | grep 3000
echo ""
echo "=== 健康检查 ==="
curl -s http://10.77.79.147:3000/healthz && echo " - ✓ 通过" || echo " - ⚠ 失败"

echo ""
echo "✅ 部署完成！"
DEPLOY_EOF
)

# 使用 sshpass 执行远程命令（如果已安装）
if command -v sshpass &> /dev/null; then
    sshpass -p "$SERVER_PASSWORD" ssh "$SERVER_USER@$SERVER_IP" "$DEPLOY_SCRIPT"
else
    # 如果没有 sshpass，使用交互式 ssh
    echo "提示: 如果未安装 sshpass，将使用交互式连接（需要手动输入密码）"
    echo "密码: $SERVER_PASSWORD"
    ssh "$SERVER_USER@$SERVER_IP" "$DEPLOY_SCRIPT"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ 部署成功完成！"
    echo "=========================================="
    echo ""
    echo "验证服务:"
    echo "curl http://10.77.79.147:3000/healthz"
    echo ""
else
    echo ""
    echo "❌ 部署过程中出现错误，请检查上面的输出"
    exit 1
fi

