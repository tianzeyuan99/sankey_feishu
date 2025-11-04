# Feishu Bitable Receiver (Flask)

私有化飞书应用后端最小示例：接收事件订阅请求、支持 URL 校验（challenge）与签名校验。

## 目录结构

- app/
  - main.py: Flask 应用（/feishu/events, /healthz）
  - security.py: 签名校验
- wsgi.py: WSGI 入口（用于 gunicorn）
- requirements.txt: 依赖
- .env.example: 环境变量示例
- run.sh: 本地启动脚本
- docs/DEPLOYMENT.md: 部署与操作手册

## 快速开始

1. 复制环境变量

```bash
cp .env.example .env
# 按需修改 APP_ID/APP_SECRET/VERIFICATION_TOKEN/ENCRYPT_KEY/PORT
```

2. 安装依赖（建议使用虚拟环境）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. 启动服务

```bash
./run.sh
# 或使用 gunicorn（推荐生产）
# source .venv/bin/activate && gunicorn -w 2 -b 0.0.0.0:${PORT:-3000} wsgi:app
```

4. 自检

```bash
curl -s http://127.0.0.1:${PORT:-3000}/healthz
curl -s -X POST http://127.0.0.1:${PORT:-3000}/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{"type":"url_verification","challenge":"ping"}'
```

## 飞书平台配置要点

- 事件订阅回调 URL：`http(s)://<你的内网域名或IP>:<端口>/feishu/events`
- 必要权限：根据你要读取的 Bitable 能力勾选（如 record:read）
- 安装应用到目标组织，确保对目标表有访问权限
- 回调要求：1 秒内返回 200；challenge 按原样返回

## 签名校验

- 头部：`x-lark-signature`、`x-lark-request-timestamp`、`x-lark-request-nonce`
- 算法：HMAC-SHA256(EncryptKey, timestamp + nonce + rawBody)
- 可通过设置 `.env` 中的 `ENCRYPT_KEY` 开启校验

## 后续扩展

- 在 `app/main.py` 的业务处理处根据事件类型做增量拉取与本地落库
- 私有化环境中，请将开放 API 网关替换为公司内网地址

## 部署与操作

本项目实现：
- 接收飞书事件订阅（im.message.receive_v1），自动识别消息中的多维表格（Bitable）链接
- 支持两类链接：
  - base+table[+view]：按链接中的表/视图拉取
  - 仅 base：自动选择第一张表与其第一个视图拉取
- 将结果保存到“桌面”（JSON/CSV/Excel），并在会话中回复结果

---

### 1. 环境与要求
- macOS，Python ≥ 3.9（已在 3.13 验证）
- 终端中执行依赖安装：
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
- 飞书应用（公网 open.feishu.cn 或私有化），拿到 `APP_ID`、`APP_SECRET`
- 若需公网回调：ngrok 或 Cloudflare Tunnel（任选其一）

### 2. 目录结构
```
feishu-bitable-receiver/
├─ app/
│  ├─ main.py               # Flask 服务：/feishu/events, /healthz
│  ├─ security.py           # 签名校验
│  └─ pull_bitable.py       # 动态桥接，导入根 pull_bitable.py
├─ pull_bitable.py          # 拉取 Bitable（可独立运行 & 被服务调用）
├─ requirements.txt         # Flask/requests/openpyxl 等依赖
├─ run.sh                   # 本地运行脚本
├─ wsgi.py                  # WSGI 入口（gunicorn）
└─ README.md                # 本手册
```

### 3. 配置与本地启动
1）创建 `.env`：
```bash
APP_ID=<你的AppID>
APP_SECRET=<你的AppSecret>
OPEN_BASE=https://open.feishu.cn     # 私有化替换为你们的网关
PORT=3000
HOST=0.0.0.0
# 统一导出配置
# 输出目录：不填默认写入 ~/Desktop（示例：/data/exports）
OUTPUT_DIR=/Users/<you>/Desktop
# 是否导出 CSV/Excel（已废弃，现在只导出 Excel；保留此配置项用于向后兼容）
EXPORT_CSV=false
EXPORT_XLSX=true
# 仅 base 链接时的选择策略：first（第一张表/视图）或 by_name（按名称优先）
BASE_AUTO_PICK=first
# 当 BASE_AUTO_PICK=by_name 时可设置偏好名（示例）：
# BASE_PREFERRED_TABLE=预算明细
# BASE_PREFERRED_VIEW=全部
```
2）启动服务：
```bash
source .venv/bin/activate
python3 -m app.main
```
3）自检：
```bash
curl http://127.0.0.1:3000/healthz      # => {"status":"ok"}
```

### 4. 飞书控制台配置（事件订阅）
1）开启机器人能力并安装应用到租户

2）订阅事件：接收消息 v2.0（`im.message.receive_v1`）

3）权限（最小集，按需开启）：
- `bitable:app:read`
- `bitable:table:read`
- `bitable:record:read`

4）回调 URL：
- 内网：`http://<host>:3000/feishu/events`
- 公网：`https://<隧道域名>/feishu/events`

5）点击“验证请求地址”，成功后“保存”

### 5. 公网暴露（任选其一）
#### A）ngrok
```bash
ngrok config add-authtoken <你的authtoken>
ngrok http 3000
# Forwarding: https://xxxxx.ngrok-free.dev -> http://localhost:3000
```
回调设置：`https://xxxxx.ngrok-free.dev/feishu/events`
> 若提示 endpoint 已在线：`pkill -f ngrok` 再启动，或直接复用该地址。

#### B）Cloudflare Tunnel
```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:3000
# 显示 https://xxxxx.trycloudflare.com
```
回调设置：`https://xxxxx.trycloudflare.com/feishu/events`

### 6. 使用方式
#### A）通过机器人触发拉取
- 向机器人发送多维表格链接：
  - 仅 base：`https://.../base/<app_token>` → 自动选择第一张表与第一个视图
  - base+table[+view]：`https://.../base/<app_token>?table=tbl...&view=vew...`
- 输出目录会生成 Excel 文件；机器人回复“已拉取 N 条记录 + Excel 路径”。

**文件命名格式：** `{多维表格名称}-{发送者ID}-{北京时间}.xlsx`
- 多维表格名称：来自飞书多维表格（base/app）的实际名称
- 发送者ID：发送消息的用户 ID（open_id/union_id/user_id）
- 北京时间：格式 YYYYMMDD_HHMMSS（UTC+8）

说明：
- 行顺序：按视图返回；仅 base 时自动取第一视图以保证一致性。
- 列顺序：Excel 与视图列顺序严格一致；列表/对象做了可读性转换。
- 同一用户多次拉取同一多维表格会生成不同时间戳的文件，不会覆盖。

#### B）独立脚本本地拉取
```bash
# 默认参数已内置
python3 pull_bitable.py --csv --xlsx

# 或自定义参数
python3 pull_bitable.py \
  --app-id <APP_ID> --app-secret <APP_SECRET> \
  --app-token <base_token> --table-id <tbl> --view-id <vew> \
  --open-base https://open.feishu.cn \
  --outfile /Users/<you>/Desktop/export.json --csv --xlsx
```

### 7. 故障排查
- challenge 失败：检查回调路径/Content-Type，确保 1s 内返回
- 401/403/invalid param：核对 APP_ID/APP_SECRET、权限是否已开通并“重新安装授权”
- 顺序不一致：带上 `view_id`；仅 base 时项目会自动取首个视图；CSV/Excel 与视图列顺序一致
- ngrok reconnecting：公司网络限制；可改用 Cloudflare Tunnel

### 8. 安全与生产化建议
- 开启签名校验（`ENCRYPT_KEY`）与 Verification Token 校验
- 限制来源 IP/域名；日志脱敏
- 使用 `gunicorn + Nginx` 或容器化；输出目录可配置
- 记录 `event_id/message_id` 做幂等与重放保护

### 9. 变更摘要
- 支持“仅 base 链接自动拉取第一张表与第一个视图”
- **只导出 Excel 格式**（不再生成 JSON/CSV）
- **文件命名：** `多维表格名称-发送者ID-北京时间.xlsx`（便于区分不同用户和时间）
- `pull_bitable.py` 既可独立运行，也可在服务中调用

### 10. 内网服务器部署（示例：10.77.79.147）

#### A）传输代码到服务器
```bash
# 在本机打包项目（排除虚拟环境）
cd /Users/tianzeyuan/Desktop
tar czf feishu-bitable-receiver.tar.gz \
  --exclude='.venv' --exclude='*.pyc' --exclude='__pycache__' \
  --exclude='.git' --exclude='messages.log' \
  feishu-bitable-receiver/

# 传输到服务器（替换 <user> 为服务器用户名）
scp feishu-bitable-receiver.tar.gz <user>@10.77.79.147:/opt/

# SSH 登录服务器
ssh <user>@10.77.79.147
```

#### B）在服务器上解压并安装
```bash
cd /opt
tar xzf feishu-bitable-receiver.tar.gz
cd feishu-bitable-receiver

# 创建虚拟环境并安装依赖（确保 Python 3.9+）
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### C）配置 .env（关键：内网网关与输出目录）
```bash
# 编辑 .env，重点修改：
# - OPEN_BASE: 改为你们的私有化网关，例如 https://open.w.cnooc.com.cn
# - OUTPUT_DIR: 改为服务器上的目录，例如 /data/feishu-exports
# - PORT/HOST: 根据需要调整

vim .env
```

示例内网 .env：
```bash
APP_ID=cli_a989be153375d013
APP_SECRET=uCVV1EC9At8CqyZbHpp3cdmIaCgXRqtB
OPEN_BASE=https://open.w.cnooc.com.cn    # 改为你们私有化网关

PORT=3000
HOST=0.0.0.0

OUTPUT_DIR=/data/feishu-exports          # 改为服务器目录
EXPORT_CSV=true
EXPORT_XLSX=true
BASE_AUTO_PICK=first
```

创建输出目录并设置权限：
```bash
sudo mkdir -p /data/feishu-exports
sudo chown $(whoami):$(whoami) /data/feishu-exports
```

#### D）使用 systemd 管理服务（推荐）
```bash
# 创建 systemd 服务文件
sudo tee /etc/systemd/system/feishu-bitable.service > /dev/null <<EOF
[Unit]
Description=Feishu Bitable Receiver Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=/opt/feishu-bitable-receiver
Environment="PATH=/opt/feishu-bitable-receiver/.venv/bin"
ExecStart=/opt/feishu-bitable-receiver/.venv/bin/gunicorn \
  -w 2 \
  -b 0.0.0.0:3000 \
  --access-logfile /opt/feishu-bitable-receiver/logs/access.log \
  --error-logfile /opt/feishu-bitable-receiver/logs/error.log \
  wsgi:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 创建日志目录
mkdir -p /opt/feishu-bitable-receiver/logs

# 重载 systemd 并启动
sudo systemctl daemon-reload
sudo systemctl enable feishu-bitable
sudo systemctl start feishu-bitable

# 查看状态
sudo systemctl status feishu-bitable
# 查看日志
sudo journalctl -u feishu-bitable -f
```

#### E）配置防火墙与测试
```bash
# 开放端口（如使用 firewalld）
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload

# 测试健康检查
curl http://10.77.79.147:3000/healthz

# 测试 challenge
curl -X POST http://10.77.79.147:3000/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{"type":"url_verification","challenge":"test123"}'
```

#### F）在飞书控制台配置回调
- 回调 URL：`http://10.77.79.147:3000/feishu/events`
- 点击“验证请求地址”并保存

注意事项：
- 确保服务器 Python 版本 ≥ 3.9
- 输出目录权限：确保运行用户有写权限
- 防火墙：开放端口 3000（或你配置的 PORT）
- 日志查看：`sudo journalctl -u feishu-bitable -f` 或查看 `/opt/feishu-bitable-receiver/logs/`
- 重启服务：`sudo systemctl restart feishu-bitable`
- 停止服务：`sudo systemctl stop feishu-bitable`

---
> 可扩展：按“表名/视图名”选择、增量同步（last_update 游标）、将结果上传为飞书临时文件并返回下载链接。
