#!/bin/bash
# 一键打包 + 上传 + 服务器部署 + 健康检查

set -e

### 本地配置
LOCAL_PROJECT_DIR="/Users/tianzeyuan/Desktop/开发/feishu-bitable-receiver"
LOCAL_TAR="/Users/tianzeyuan/Desktop/feishu-bitable-receiver.tar.gz"

### 服务器配置（你提供的账号密码）
SERVER_IP="10.77.79.147"
SERVER_USER="cnooc"
SERVER_PASSWORD="DayDayUp@2024.."
REMOTE_BASE="/home/cnooc/python_app"
REMOTE_PROJECT_DIR="$REMOTE_BASE/feishu-bitable-receiver"
REMOTE_TAR="$REMOTE_BASE/feishu-bitable-receiver.tar.gz"
REMOTE_VENV_ACTIVATE="/home/cnooc/python_app/venv313/bin/activate"

echo "=== 1. 本地打包 ==="
cd "$LOCAL_PROJECT_DIR/.."
[ -f "$LOCAL_TAR" ] && rm -f "$LOCAL_TAR"

tar czf "$LOCAL_TAR" \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='logs' \
  --exclude='*.log' \
  --exclude='*.xlsx' \
  --exclude='*.html' \
  --exclude='.DS_Store' \
  --exclude='*.pid' \
  --exclude='.git' \
  --exclude='test_*.py' \
  --exclude='1111.py' \
  --exclude='output' \
  --exclude='.idea' \
  feishu-bitable-receiver/

ls -lh "$LOCAL_TAR"
echo

echo "=== 2. 上传压缩包到服务器 ==="
if command -v sshpass >/dev/null 2>&1; then
  sshpass -p "$SERVER_PASSWORD" scp "$LOCAL_TAR" "$SERVER_USER@$SERVER_IP:$REMOTE_TAR"
else
  echo "提示：未检测到 sshpass，将使用普通 scp，需要手动输入一次密码：$SERVER_PASSWORD"
  scp "$LOCAL_TAR" "$SERVER_USER@$SERVER_IP:$REMOTE_TAR"
fi

echo
echo "=== 3. 服务器上解压 & 部署 ==="

REMOTE_DEPLOY=$(cat << 'REMOTE_EOF'
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

# 恢复配置和目录
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

# 验证
sleep 3
echo "=== 健康检查 ==="
curl -s http://10.77.79.147:3000/healthz && echo " - ✓ 通过" || echo " - ⚠ 失败"
REMOTE_EOF
)

if command -v sshpass >/dev/null 2>&1; then
  sshpass -p "$SERVER_PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER_USER@$SERVER_IP" "$REMOTE_DEPLOY" || {
    echo "❌ 远程部署执行失败"
    exit 1
  }
else
  echo "提示：未检测到 sshpass，将使用普通 ssh，需要手动输入一次密码：$SERVER_PASSWORD"
  ssh -o StrictHostKeyChecking=no "$SERVER_USER@$SERVER_IP" "$REMOTE_DEPLOY" || {
    echo "❌ 远程部署执行失败"
    exit 1
  }
fi

echo
echo "=== 部署完成 ==="
echo "健康检查地址: http://10.77.79.147:3000/healthz"

