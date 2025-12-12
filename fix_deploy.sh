#!/bin/bash
# 修复部署 - 检查并重新部署

echo "=== 1. 检查压缩包 ==="
cd /home/cnooc/python_app
ls -lh feishu-bitable-receiver.tar.gz
echo ""

echo "=== 2. 检查当前目录内容 ==="
ls -la | grep feishu
echo ""

echo "=== 3. 检查备份目录 ==="
ls -d /home/cnooc/python_app/feishu-bitable-receiver.backup.* 2>/dev/null | tail -3
echo ""

echo "=== 4. 重新解压（如果压缩包存在）==="
if [ -f /home/cnooc/python_app/feishu-bitable-receiver.tar.gz ]; then
    cd /home/cnooc/python_app
    # 删除可能存在的旧目录
    [ -d feishu-bitable-receiver ] && rm -rf feishu-bitable-receiver
    # 解压
    tar xzf feishu-bitable-receiver.tar.gz
    echo "解压完成"
    ls -la feishu-bitable-receiver/ | head -10
else
    echo "❌ 压缩包不存在"
fi
echo ""

echo "=== 5. 检查项目目录 ==="
if [ -d /home/cnooc/python_app/feishu-bitable-receiver ]; then
    cd /home/cnooc/python_app/feishu-bitable-receiver
    echo "当前目录: $(pwd)"
    echo "关键文件:"
    ls -la wsgi.py app/main.py requirements.txt 2>&1
else
    echo "❌ 项目目录不存在"
fi

