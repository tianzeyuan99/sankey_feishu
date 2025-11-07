#!/bin/bash
# 本地打包脚本
# 用于生成 feishu-bitable-receiver.tar.gz

cd /Users/tianzeyuan/Desktop

echo "=== 开始打包 feishu-bitable-receiver ==="

# 删除旧压缩包
[ -f feishu-bitable-receiver.tar.gz ] && rm feishu-bitable-receiver.tar.gz

# 打包（排除不必要的文件）
tar czf feishu-bitable-receiver.tar.gz \
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
  --exclude='1111.py' \
  --exclude='test_sheets_download.py' \
  --exclude='output' \
  feishu-bitable-receiver/

if [ $? -eq 0 ]; then
    echo "✅ 打包成功: feishu-bitable-receiver.tar.gz"
    ls -lh feishu-bitable-receiver.tar.gz
else
    echo "❌ 打包失败"
    exit 1
fi

echo ""
echo "=== 打包内容检查 ==="
tar tzf feishu-bitable-receiver.tar.gz | head -20
echo "..."
echo "总计文件数: $(tar tzf feishu-bitable-receiver.tar.gz | wc -l)"

