import os
import json
import time
import sys
import urllib.parse
import socket
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from .security import verify_signature

# 北京时间 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))
from . import pull_bitable
from . import cloud_doc_download
import re

# 先加载 .env（如果存在）
load_dotenv()

# 辅助函数
def _get_bool(name: str) -> bool:
    v = os.getenv(name)
    if v is None:
        raise ValueError(f"环境变量 {name} 未配置，请在 .env 文件中设置")
    return v.lower() in ("1", "true", "yes", "on")

def _get_int(name: str) -> int:
    v = os.getenv(name)
    if v is None:
        raise ValueError(f"环境变量 {name} 未配置，请在 .env 文件中设置")
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"环境变量 {name} 的值 '{v}' 不是有效的整数")

# ========= Feishu credentials =========
APP_ID = os.getenv("APP_ID")
if not APP_ID:
    raise ValueError("环境变量 APP_ID 未配置，请在 .env 文件中设置")

APP_SECRET = os.getenv("APP_SECRET")
if not APP_SECRET:
    raise ValueError("环境变量 APP_SECRET 未配置，请在 .env 文件中设置")

VERIFICATION_TOKEN = os.getenv("VERIFICATION_TOKEN")
ENCRYPT_KEY = os.getenv("ENCRYPT_KEY")
OPEN_BASE = os.getenv("OPEN_BASE")
if not OPEN_BASE:
    raise ValueError("环境变量 OPEN_BASE 未配置，请在 .env 文件中设置")

# ========= Service =========
PORT = _get_int("PORT")
HOST = os.getenv("HOST")
if not HOST:
    raise ValueError("环境变量 HOST 未配置，请在 .env 文件中设置")

# ========= 文件导出配置 =========
OUTPUT_DIR = os.getenv("OUTPUT_DIR")
if not OUTPUT_DIR:
    raise ValueError("环境变量 OUTPUT_DIR 未配置，请在 .env 文件中设置")

EXPORT_CSV = _get_bool("EXPORT_CSV")
EXPORT_XLSX = _get_bool("EXPORT_XLSX")
BASE_AUTO_PICK = os.getenv("BASE_AUTO_PICK")
if not BASE_AUTO_PICK:
    raise ValueError("环境变量 BASE_AUTO_PICK 未配置，请在 .env 文件中设置")

BASE_PREFERRED_TABLE = os.getenv("BASE_PREFERRED_TABLE")
BASE_PREFERRED_VIEW = os.getenv("BASE_PREFERRED_VIEW")

# ========= 日志配置 =========
MESSAGES_LOG_PATH = os.getenv("MESSAGES_LOG_PATH")
if not MESSAGES_LOG_PATH:
    raise ValueError("环境变量 MESSAGES_LOG_PATH 未配置，请在 .env 文件中设置")

# ========= 桑基图生成配置 =========
# 改为可选：优先导入项目内置模块，其次再用 SANKEY_SERVICE_PATH 回退
SANKEY_SERVICE_PATH = os.getenv("SANKEY_SERVICE_PATH", "")

SANKEY_OUTPUT_DIR = os.getenv("SANKEY_OUTPUT_DIR")
if not SANKEY_OUTPUT_DIR:
    raise ValueError("环境变量 SANKEY_OUTPUT_DIR 未配置，请在 .env 文件中设置")

SANKEY_WATCH_DIR = os.getenv("SANKEY_WATCH_DIR")
if not SANKEY_WATCH_DIR:
    raise ValueError("环境变量 SANKEY_WATCH_DIR 未配置，请在 .env 文件中设置")

SANKEY_LOG_FILE = os.getenv("SANKEY_LOG_FILE")
if not SANKEY_LOG_FILE:
    raise ValueError("环境变量 SANKEY_LOG_FILE 未配置，请在 .env 文件中设置")

SANKEY_POLL_INTERVAL = _get_int("SANKEY_POLL_INTERVAL")

# 保留但不再使用的配置（兼容性）
SANKEY_WEBHOOK_URL = os.getenv("SANKEY_WEBHOOK_URL", "")
SANKEY_HTML_SERVER_PORT = os.getenv("SANKEY_HTML_SERVER_PORT", "")
SANKEY_HTML_BASE_URL = os.getenv("SANKEY_HTML_BASE_URL", "")

# 确保目录存在
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SANKEY_OUTPUT_DIR, exist_ok=True)
os.makedirs(SANKEY_WATCH_DIR, exist_ok=True)

# 确保日志文件所在目录存在
log_file_dir = os.path.dirname(SANKEY_LOG_FILE)
if log_file_dir:
    os.makedirs(log_file_dir, exist_ok=True)

messages_log_dir = os.path.dirname(MESSAGES_LOG_PATH)
if messages_log_dir:
    os.makedirs(messages_log_dir, exist_ok=True)

# 导入桑基图生成服务（本地优先，失败再用外部路径）
SankeyService = None
try:
    from .sankey_service_with_polling import SankeyService  # 项目内置
    print("[INFO] 桑基图服务(内置)导入成功")
except Exception as inner_err:
    try:
        if SANKEY_SERVICE_PATH and os.path.exists(SANKEY_SERVICE_PATH):
            sys.path.insert(0, SANKEY_SERVICE_PATH)
            from sankey_service_with_polling import SankeyService  # 外部路径
            print("[INFO] 桑基图服务(外部)导入成功")
        else:
            print(f"[WARNING] 未配置有效的 SANKEY_SERVICE_PATH，且内置导入失败: {inner_err}")
            SankeyService = None
    except Exception as outer_err:
        print(f"[ERROR] 桑基图服务导入失败: {outer_err}")
        import traceback
        traceback.print_exc()
        SankeyService = None


def get_local_ip():
    """动态获取本机IP地址"""
    try:
        # 方法1: 连接外部地址获取本机IP（推荐）
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            # 方法2: 通过主机名获取
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip.startswith("127."):
                # 如果返回的是127.x.x.x，尝试获取实际IP
                import subprocess
                result = subprocess.run(['ipconfig', 'getifaddr', 'en0'], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
                return "127.0.0.1"
            return ip
        except Exception:
            return "127.0.0.1"


def get_sankey_html_base_url():
    """获取桑基图HTML访问的基础URL
    如果.env中配置了SANKEY_HTML_BASE_URL，则使用配置的值
    否则动态获取本机IP和端口生成URL
    """
    # 1) 若显式配置了 BASE_URL，则优先使用（例如 Nginx 静态服务）
    if SANKEY_HTML_BASE_URL:
        return SANKEY_HTML_BASE_URL.rstrip("/")
    # 2) 否则使用当前服务 (HOST, PORT) 暴露的 /sankey 路由
    server_ip = get_local_ip() if HOST in ("0.0.0.0", "", None) else HOST
    return f"http://{server_ip}:{PORT}/sankey"

# 简单的 tenant_access_token 内存缓存
TENANT_TOKEN_CACHE = {"token": None, "expire_at": 0.0}

def get_tenant_access_token() -> str:
    now = time.time()
    if TENANT_TOKEN_CACHE["token"] and TENANT_TOKEN_CACHE["expire_at"] - now > 60:
        return TENANT_TOKEN_CACHE["token"]
    url = f"{OPEN_BASE}/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=5)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get_tenant_access_token failed: {data}")
    TENANT_TOKEN_CACHE["token"] = data["tenant_access_token"]
    TENANT_TOKEN_CACHE["expire_at"] = now + float(data.get("expire", 7000))
    return TENANT_TOKEN_CACHE["token"]

def reply_message(message_id: str, text: str) -> dict:
    token = get_tenant_access_token()
    url = f"{OPEN_BASE}/open-apis/im/v1/messages/{message_id}/reply"
    payload = {
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False)
    }
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=5)
    try:
        return r.json()
    except Exception:
        return {"status_code": r.status_code, "text": r.text}


def get_table_name(open_base: str, app_token: str, table_id: str, tenant_token: str) -> str:
    """获取表格名称"""
    headers = {"Authorization": f"Bearer {tenant_token}"}
    url = f"{open_base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}"
    r = requests.get(url, headers=headers, timeout=10).json()
    if r.get("code") != 0:
        return f"table_{table_id}"
    return r.get("data", {}).get("table", {}).get("name", f"table_{table_id}")


def get_base_name(open_base: str, app_token: str, tenant_token: str) -> str:
    """获取多维表格（base/app）的名称"""
    headers = {"Authorization": f"Bearer {tenant_token}"}
    url = f"{open_base}/open-apis/bitable/v1/apps/{app_token}"
    r = requests.get(url, headers=headers, timeout=10).json()
    if r.get("code") != 0:
        return f"base_{app_token}"
    # API 返回结构可能是 data.app.name 或 data.name
    app_data = r.get("data", {})
    base_name = app_data.get("app", {}).get("name") or app_data.get("name") or f"base_{app_token}"
    return base_name


def get_beijing_timestamp() -> str:
    """获取当前北京时间，格式：YYYYMMDD_HHMMSS"""
    return datetime.now(BEIJING_TZ).strftime("%Y%m%d_%H%M%S")


def generate_sankey_and_notify(excel_file_path: str, base_name: str) -> tuple[bool, str]:
    """生成桑基图
    返回: (是否成功, HTML文件路径或错误类型)
    错误类型: "format_error" 表示 Excel 格式不符合要求
    """
    app.logger.info(f"[桑基图生成] 开始处理，Excel文件: {excel_file_path}, Base名称: {base_name}")
    
    if SankeyService is None:
        app.logger.error("[桑基图生成] 失败：SankeyService 未初始化，可能是导入失败")
        return False, "service_error"
    
    # 检查 Excel 文件是否存在
    if not os.path.exists(excel_file_path):
        app.logger.error(f"[桑基图生成] 失败：Excel文件不存在 - {excel_file_path}")
        return False, "file_not_found"
    
    app.logger.info(f"[桑基图生成] Excel文件验证通过，文件大小: {os.path.getsize(excel_file_path)} bytes")
    
    edges_file_path = None
    try:
        # 创建桑基图服务实例（不启动轮询，只用于单次生成）
        app.logger.info(f"[桑基图生成] 创建服务实例，watch_dir={SANKEY_WATCH_DIR}, output_dir={SANKEY_OUTPUT_DIR}")
        sankey_service = SankeyService(
            watch_dir=SANKEY_WATCH_DIR,
            output_dir=SANKEY_OUTPUT_DIR,
            log_file=SANKEY_LOG_FILE,
            poll_interval=SANKEY_POLL_INTERVAL
        )
        app.logger.info("[桑基图生成] 服务实例创建成功")
        
        # 步骤1: 将预算文件转换为边表文件
        app.logger.info(f"[桑基图生成] 步骤1：开始转换预算文件为边表 - {os.path.basename(excel_file_path)}")
        try:
            edges_file_path = sankey_service.convert_budget_to_edges(excel_file_path)
        except KeyError as e:
            app.logger.exception(f"[桑基图生成] 步骤1失败：缺少必要的列 - {e}")
            return False, "format_error"
        except IndexError as e:
            app.logger.exception(f"[桑基图生成] 步骤1失败：数据行不完整 - {e}")
            return False, "format_error"
        except Exception as convert_err:
            app.logger.exception(f"[桑基图生成] 步骤1失败：转换预算文件时出错 - {convert_err}")
            return False, "format_error"
        
        if not edges_file_path:
            app.logger.error("[桑基图生成] 步骤1失败：convert_budget_to_edges 返回 None")
            return False, "format_error"
        
        if not os.path.exists(edges_file_path):
            app.logger.error(f"[桑基图生成] 步骤1失败：边表文件不存在 - {edges_file_path}")
            return False, "桑基图生成失败"
        
        app.logger.info(f"[桑基图生成] 步骤1成功：边表文件已生成 - {os.path.basename(edges_file_path)}, 文件大小: {os.path.getsize(edges_file_path)} bytes")
        
        # 步骤2: 生成HTML文件名
        excel_basename = os.path.splitext(os.path.basename(excel_file_path))[0]
        html_filename = f"{excel_basename}_桑基图.html"
        html_output_path = os.path.join(SANKEY_OUTPUT_DIR, html_filename)
        app.logger.info(f"[桑基图生成] 步骤2：HTML输出路径 - {html_output_path}")
        
        # 步骤3: 生成桑基图
        app.logger.info(f"[桑基图生成] 步骤3：开始生成桑基图HTML，边表文件: {edges_file_path}, 预算文件: {excel_file_path}")
        try:
            success = sankey_service.generate_sankey_chart(
                edges_path=edges_file_path,           # 转换后的边表文件
                output_html_path=html_output_path,
                budget_path=excel_file_path            # 原始预算文件（用于加载节点描述）
            )
        except Exception as chart_err:
            app.logger.exception(f"[桑基图生成] 步骤3失败：生成桑基图时出错 - {chart_err}")
            # 清理临时文件
            try:
                if edges_file_path and os.path.exists(edges_file_path):
                    os.remove(edges_file_path)
                    app.logger.info(f"[桑基图生成] 已清理临时边表文件: {os.path.basename(edges_file_path)}")
            except Exception as cleanup_err:
                app.logger.warning(f"[桑基图生成] 清理临时文件失败: {cleanup_err}")
            return False, "桑基图生成失败"
        
        # 步骤4: 生成完成后清理临时边表文件
        if success:
            app.logger.info(f"[桑基图生成] 步骤3成功：桑基图HTML已生成 - {html_output_path}")
            
            # 验证HTML文件是否存在
            if not os.path.exists(html_output_path):
                app.logger.error(f"[桑基图生成] 失败：HTML文件未生成 - {html_output_path}")
                # 清理临时文件
                try:
                    if edges_file_path and os.path.exists(edges_file_path):
                        os.remove(edges_file_path)
                except Exception:
                    pass
                return False, "桑基图生成失败"
            
            app.logger.info(f"[桑基图生成] HTML文件验证通过，文件大小: {os.path.getsize(html_output_path)} bytes")
            
            # 清理临时边表文件
            try:
                if edges_file_path and os.path.exists(edges_file_path):
                    os.remove(edges_file_path)
                    app.logger.info(f"[桑基图生成] 已删除临时边表文件: {os.path.basename(edges_file_path)}")
            except Exception as e:
                app.logger.warning(f"[桑基图生成] 删除临时边表文件失败: {e}")
            
            # 返回可访问的 HTTP URL
            base_url = get_sankey_html_base_url()
            html_url = f"{base_url}/{urllib.parse.quote(html_filename)}"
            app.logger.info(f"[桑基图生成] 生成成功，返回URL: {html_url}")
            return True, html_url
        else:
            app.logger.error(f"[桑基图生成] 步骤3失败：generate_sankey_chart 返回 False，HTML文件可能未生成 - {html_output_path}")
            # 即使生成失败，也尝试清理临时文件
            try:
                if edges_file_path and os.path.exists(edges_file_path):
                    os.remove(edges_file_path)
                    app.logger.info(f"[桑基图生成] 已删除临时边表文件: {os.path.basename(edges_file_path)}")
            except Exception as e:
                app.logger.warning(f"[桑基图生成] 删除临时边表文件失败: {e}")
            
            return False, "桑基图生成失败"
            
    except Exception as e:
        app.logger.exception(f"[桑基图生成] 异常：生成桑基图时发生未捕获的异常 - {e}")
        import traceback
        app.logger.error(f"[桑基图生成] 异常堆栈：\n{traceback.format_exc()}")
        # 出错时也尝试清理临时文件
        try:
            if edges_file_path and os.path.exists(edges_file_path):
                os.remove(edges_file_path)
                app.logger.info(f"[桑基图生成] 已删除临时边表文件: {os.path.basename(edges_file_path)}")
        except Exception as cleanup_error:
            app.logger.warning(f"[桑基图生成] 清理临时文件时出错: {cleanup_error}")
        return False, "桑基图生成失败"

app = Flask(__name__)

# 幂等性检查：记录已处理的消息 ID（内存中，重启后清空）
PROCESSED_MESSAGE_IDS = set()


@app.get("/sankey/<path:filename>")
def serve_sankey_html(filename: str):
    """提供桑基图 HTML 的只读访问。"""
    try:
        decoded = urllib.parse.unquote(filename)
        file_path = os.path.join(SANKEY_OUTPUT_DIR, decoded)
        # 目录越界防护
        if not os.path.abspath(file_path).startswith(os.path.abspath(SANKEY_OUTPUT_DIR)):
            return jsonify({"error": "无效的文件路径"}), 403
        if not os.path.exists(file_path):
            return jsonify({"error": "文件不存在"}), 404
        return send_from_directory(SANKEY_OUTPUT_DIR, decoded, mimetype="text/html")
    except Exception as e:
        app.logger.exception(f"serve sankey html error: {e}")
        return jsonify({"error": str(e)}), 500


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.post("/feishu/events")
def feishu_events():
    # 原始数据用于签名校验
    raw = request.get_data(cache=False, as_text=False)
    
    # 手动解析 JSON（因为 get_json() 可能在某些情况下失败）
    try:
        if raw:
            body = json.loads(raw.decode('utf-8'))
        else:
            body = request.get_json(silent=True) or {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}
    
    # 调试输出（统一写入应用日志）
    try:
        app.logger.info(f"[DEBUG] Content-Type: {request.headers.get('Content-Type')}")
        app.logger.info(f"[DEBUG] Headers: {dict(request.headers)}")
        app.logger.info(f"[DEBUG] Query Args: {request.args.to_dict(flat=True)}")
    except Exception:
        pass
    try:
        # 避免日志过大，仅截取原始体前8KB
        raw_preview = raw[:8192] if isinstance(raw, (bytes, bytearray)) else raw
        app.logger.info(f"[DEBUG] Raw body: {raw_preview}")
    except Exception:
        pass
    app.logger.info(f"[DEBUG] Parsed body: {body}")
    app.logger.info(f"[DEBUG] body.get('challenge'): {body.get('challenge')}")

    # 1) URL 验证（challenge）
    # 兼容：有的平台仅传 challenge；标准为 type=url_verification 且带 challenge
    challenge = body.get("challenge")
    if challenge:
        print(f"[DEBUG] ✓ hit challenge branch, returning challenge: {challenge}")
        # 标准回包为 JSON: {"challenge": "..."}
        return jsonify({"challenge": challenge})
    
    print(f"[DEBUG] ✗ no challenge found, continuing with event handling")

    # 2) Verification Token 基础校验（如平台提供）
    header = body.get("header", {})
    token = header.get("token")
    if VERIFICATION_TOKEN and token and token != VERIFICATION_TOKEN:
        return ("invalid verification token", 401)

    # 3) 签名校验（推荐）
    ts = request.headers.get("x-lark-request-timestamp")
    nonce = request.headers.get("x-lark-request-nonce")
    sig = request.headers.get("x-lark-signature")
    if ENCRYPT_KEY:
        ok = verify_signature(raw, ts, nonce, sig, ENCRYPT_KEY)
        if not ok:
            return ("invalid signature", 401)

    # 4) 业务处理（尽快 200；耗时逻辑异步）
    event = body.get("event") or {}
    event_type = header.get("event_type") or event.get("type")
    app.logger.info(f"Received event: {event_type}")

    # 如果是“接收消息”事件，打印并落盘
    # 常见事件名：im.message.receive_v1（不同版本命名可能略有差异）
    try:
        if event_type and "im.message" in event_type:
            message = (event or {}).get("message") or {}
            content_raw = message.get("content")  # 通常是 JSON 字符串，如 '{"text":"hi"}'
            content = None
            if isinstance(content_raw, str):
                try:
                    content = json.loads(content_raw)
                except json.JSONDecodeError:
                    content = {"text": content_raw}
            elif isinstance(content_raw, dict):
                content = content_raw
            else:
                content = {"unknown": content_raw}

            text = content.get("text") if isinstance(content, dict) else str(content)
            message_id = message.get("message_id")
            print(f"[MESSAGE] id={message_id} text={text}")

            # 幂等性检查：如果该消息已处理过，直接返回 200（避免飞书重试）
            if message_id and message_id in PROCESSED_MESSAGE_IDS:
                app.logger.info(f"Message {message_id} already processed, skipping")
                return jsonify({"ok": "already processed"}), 200

            # 立即记录 message_id，防止重复处理（在处理开始前）
            # 这样可以避免飞书重试时重复处理同一消息
            if message_id:
                PROCESSED_MESSAGE_IDS.add(message_id)
                app.logger.info(f"Marking message {message_id} as processed")

            # 提取发送者与会话信息，并记录详细ID到日志
            sender = event.get("sender", {})
            sender_id_obj = sender.get("sender_id", {})
            open_id = sender_id_obj.get("open_id")
            union_id = sender_id_obj.get("union_id")
            user_id_legacy = sender_id_obj.get("user_id")
            sender_id = open_id or union_id or user_id_legacy or "unknown"
            chat_id = message.get("chat_id")
            chat_type = message.get("chat_type")
            tenant_key = header.get("tenant_key") or body.get("header", {}).get("tenant_key")
            event_id = header.get("event_id") or body.get("header", {}).get("event_id")
            app.logger.info(
                f"[参与者] event_id={event_id}, tenant_key={tenant_key}, chat_id={chat_id}, chat_type={chat_type}, "
                f"open_id={open_id}, union_id={union_id}, user_id={user_id_legacy}, sender_id_used={sender_id}"
            )

            # 追加写入消息日志（含关键ID）
            with open(MESSAGES_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(
                    f"{datetime.now().isoformat()}\t{event_type}\t{message_id}\t"
                    f"open_id={open_id}\tunion_id={union_id}\tuser_id={user_id_legacy}\t"
                    f"chat_id={chat_id}\tchat_type={chat_type}\t"
                    f"{json.dumps(content, ensure_ascii=False)}\n"
                )

            # 检查链接类型
            is_bitable_link = isinstance(text, str) and "/base/" in text
            is_cloud_doc_link = isinstance(text, str) and (
                "/file/" in text or "/docs/" in text or "/sheets/" in text
            )
            is_link = isinstance(text, str) and (
                text.startswith("http://") or text.startswith("https://")
            )
            
            app.logger.info(f"[消息处理] 链接类型检查: is_bitable={is_bitable_link}, is_cloud_doc={is_cloud_doc_link}, is_link={is_link}, text={text[:100]}")
            
            # 场景 1 和 2：不支持的链接类型或非链接消息
            if not is_bitable_link and not is_cloud_doc_link:
                if message_id:
                    try:
                        if not is_link:
                            # 场景 2：非链接消息
                            reply_message(message_id, "该内容不能进行桑基图生成，\n\n请发送多维表格链接或云文档链接")
                            app.logger.info(f"[消息处理] 场景2：非链接消息，已回复，message_id: {message_id}")
                        else:
                            # 场景 1：不支持的链接类型
                            reply_message(message_id, "该内容不能进行桑基图生成，\n\n请发送多维表格链接（/base/）或云文档链接（/file/、/docs/、/sheets/）")
                            app.logger.info(f"[消息处理] 场景1：不支持的链接类型，已回复，message_id: {message_id}")
                    except Exception as e:
                        app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {e}")
                return jsonify({"ok": "received"}), 200
            
            # 处理云文档链接
            if is_cloud_doc_link:
                app.logger.info(f"[消息处理] 检测到云文档链接，开始处理，message_id: {message_id}")
                try:
                    token = get_tenant_access_token()
                    
                    # 提取 file_token
                    try:
                        file_token = cloud_doc_download.extract_file_token_from_link(text)
                        app.logger.info(f"[消息处理] 提取到 file_token: {file_token}")
                    except ValueError as e:
                        app.logger.error(f"[消息处理] 云文档链接格式错误，message_id: {message_id}, 错误: {e}")
                        reply_message(message_id, "云文档链接格式错误，请检查链接是否正确")
                        return jsonify({"ok": "received"}), 200
                    
                    # 下载云文档（先下载，获取文件名后再重命名）
                    ts = get_beijing_timestamp()
                    temp_outfile = os.path.join(OUTPUT_DIR, f"temp-{sender_id}-{ts}.xlsx")
                    
                    app.logger.info(f"[消息处理] 开始下载云文档，file_token: {file_token}, 临时文件: {temp_outfile}")
                    download_success, download_error, file_title = cloud_doc_download.download_cloud_doc_to_excel(
                        file_token, temp_outfile, token, OPEN_BASE, doc_link=text
                    )
                    
                    if not download_success:
                        # 场景 3：下载失败（权限错误）
                        app.logger.error(f"[消息处理] 场景3：云文档下载失败，message_id: {message_id}, 错误类型: {download_error}")
                        if download_error == "permission_denied" or download_error == "file_not_found":
                            reply_message(message_id, "文档访问失败，请检查：\n\n1. 链接是否正确\n\n2. 应用是否有访问权限\n\n3. 文件是否已分享给应用")
                        else:
                            reply_message(message_id, "云文档下载失败，请检查链接是否正确")
                        return jsonify({"ok": "received"}), 200
                    
                    # 生成最终文件名（使用实际文件名或默认名称）
                    if file_title:
                        # 清理文件名（去除特殊字符）
                        safe_name = re.sub(r'[<>:"/\\|?*]', '_', file_title)
                        outfile = os.path.join(OUTPUT_DIR, f"{safe_name}-{sender_id}-{ts}.xlsx")
                        base_name = file_title
                    else:
                        # 如果没有获取到文件名，使用默认名称
                        outfile = os.path.join(OUTPUT_DIR, f"云文档-{sender_id}-{ts}.xlsx")
                        base_name = "云文档"
                    
                    # 如果文件名不同，重命名文件
                    if temp_outfile != outfile:
                        try:
                            os.rename(temp_outfile, outfile)
                            app.logger.info(f"[消息处理] 文件已重命名: {temp_outfile} -> {outfile}")
                        except Exception as e:
                            app.logger.warning(f"[消息处理] 文件重命名失败，使用临时文件名: {e}")
                            outfile = temp_outfile
                    
                    app.logger.info(f"[消息处理] 云文档下载成功，文件: {outfile}, 文件名: {base_name}")
                    
                    # 生成桑基图
                    app.logger.info(f"[消息处理] 开始生成桑基图，Excel文件: {outfile}, Base名称: {base_name}")
                    sankey_success, sankey_result = generate_sankey_and_notify(outfile, base_name)
                    
                    # 只返回一次消息
                    if sankey_success:
                        app.logger.info(f"[消息处理] 桑基图生成成功，回复链接给用户，message_id: {message_id}")
                        reply_message(message_id, f"桑基图链接：{sankey_result}")
                    else:
                        # 场景 4：Excel 格式不对
                        if sankey_result == "format_error":
                            app.logger.error(f"[消息处理] 场景4：Excel格式不符合要求，message_id: {message_id}")
                            reply_message(message_id, "Excel 文件格式不符合要求，请确保文件包含：\n\n1. 第一列为时间列\n\n2. 后续列为成对的项目列和描述列\n\n3. 最后一列为总预算\n\n4. 数据行完整")
                        else:
                            app.logger.error(f"[消息处理] 桑基图生成失败，回复错误消息给用户，message_id: {message_id}, 结果: {sankey_result}")
                            reply_message(message_id, "桑基图生成失败，请联系服务管理员")
                    
                    return jsonify({"ok": "received"}), 200
                    
                except ValueError as e:
                    # 链接格式错误
                    app.logger.error(f"[消息处理] 云文档链接格式错误，message_id: {message_id}, 错误: {e}")
                    reply_message(message_id, "云文档链接格式错误，请检查链接是否正确")
                    return jsonify({"ok": "received"}), 200
                except Exception as e:
                    # 其他异常
                    app.logger.exception(f"[消息处理] 处理云文档失败，message_id: {message_id}, 错误: {e}")
                    reply_message(message_id, "桑基图生成失败，请联系服务管理员")
                    return jsonify({"ok": "received"}), 200
            
            # 是多维表格链接，进行处理
            app.logger.info(f"[消息处理] 检测到多维表格链接，开始处理，message_id: {message_id}")
            try:
                # 带 table 参数的链接
                if "?table=" in text:
                    # 解析 app_token / table_id / view_id
                    app_token = None
                    table_id = None
                    view_id = None
                    # app_token：位于 /base/<token>
                    m = re.search(r"/base/([A-Za-z0-9]+)", text)
                    if m:
                        app_token = m.group(1)
                    m = re.search(r"[?&]table=([A-Za-z0-9]+)", text)
                    if m:
                        table_id = m.group(1)
                    m = re.search(r"[?&]view=([A-Za-z0-9]+)", text)
                    if m:
                        view_id = m.group(1)

                    if app_token and table_id:
                        try:
                            token = get_tenant_access_token()
                            # 获取多维表格（base）名称
                            base_name = get_base_name(OPEN_BASE, app_token, token)
                            # 清理文件名（去除特殊字符）
                            safe_name = re.sub(r'[<>:"/\\|?*]', '_', base_name)
                            # 生成北京时间戳
                            ts = get_beijing_timestamp()
                            # 文件命名：多维表格名-发送者ID-时间戳.xlsx
                            outfile = os.path.join(OUTPUT_DIR, f"{safe_name}-{sender_id}-{ts}.xlsx")
                            result = pull_bitable.pull_to_files(
                                OPEN_BASE, APP_ID, APP_SECRET, app_token, table_id, view_id, outfile
                            )
                            
                            # 生成桑基图
                            app.logger.info(f"[消息处理] 开始生成桑基图，Excel文件: {result.get('xlsx')}, Base名称: {base_name}")
                            sankey_success, sankey_result = generate_sankey_and_notify(result['xlsx'], base_name)
                            
                            # 只返回一次消息
                            if sankey_success:
                                app.logger.info(f"[消息处理] 桑基图生成成功，回复链接给用户，message_id: {message_id}")
                                reply_message(message_id, f"桑基图链接：{sankey_result}")  # 成功：返回标注后的链接
                            else:
                                # 场景 4：Excel 格式不对
                                if sankey_result == "format_error":
                                    app.logger.error(f"[消息处理] 场景4：Excel格式不符合要求，message_id: {message_id}")
                                    reply_message(message_id, "Excel 文件格式不符合要求，请确保文件包含：\n\n1. 第一列为时间列\n\n2. 后续列为成对的项目列和描述列\n\n3. 最后一列为总预算\n\n4. 数据行完整")
                                else:
                                    app.logger.error(f"[消息处理] 桑基图生成失败，回复错误消息给用户，message_id: {message_id}, 结果: {sankey_result}")
                                    reply_message(message_id, "桑基图生成失败，请联系服务管理员")
                        except RuntimeError as e:
                            # 场景 3：权限错误或 API 错误
                            error_msg = str(e)
                            app.logger.exception(f"[消息处理] 场景3：多维表格访问失败，message_id: {message_id}, 错误: {e}")
                            try:
                                if "code" in error_msg or "permission" in error_msg.lower() or "access" in error_msg.lower():
                                    reply_message(message_id, "文档访问失败，请检查：\n\n1. 链接是否正确\n\n2. 应用是否有访问权限\n\n3. 文件是否已分享给应用")
                                else:
                                    reply_message(message_id, "多维表格拉取失败，请检查链接是否正确")
                                app.logger.info(f"[消息处理] 已发送错误消息给用户，message_id: {message_id}")
                            except Exception as reply_err:
                                app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                        except Exception as e:
                            # 其他异常
                            app.logger.exception(f"[消息处理] 拉取多维表格失败，message_id: {message_id}, 错误: {e}")
                            try:
                                reply_message(message_id, "桑基图生成失败，请联系服务管理员")
                                app.logger.info(f"[消息处理] 已发送错误消息给用户，message_id: {message_id}")
                            except Exception as reply_err:
                                app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                    else:
                        # app_token 或 table_id 解析失败
                        app.logger.warning(f"[消息处理] app_token 或 table_id 解析失败，message_id: {message_id}, text: {text}")
                        if message_id:
                            try:
                                reply_message(message_id, "多维表格链接格式错误，请检查链接是否正确")
                                app.logger.info(f"[消息处理] 已发送错误消息（解析失败），message_id: {message_id}")
                            except Exception as reply_err:
                                app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                    return jsonify({"ok": "received"}), 200

                # 仅 base 链接：自动取第一张表与第一视图
                else:
                    print("[INFO] 处理仅 base 链接（无 table 参数）")
                    m = re.search(r"/base/([A-Za-z0-9]+)", text)
                    app_token = m.group(1) if m else None
                    print(f"[INFO] 解析得到 app_token: {app_token}")
                    if app_token:
                        try:
                            token = get_tenant_access_token()
                            headers = {"Authorization": f"Bearer {token}"}
                            # 列表表
                            url_tables = f"{OPEN_BASE}/open-apis/bitable/v1/apps/{app_token}/tables"
                            params = {"page_size": 200}
                            rt = requests.get(url_tables, headers=headers, params=params, timeout=10).json()
                            if rt.get("code") != 0:
                                # 场景 3：权限错误
                                error_code = rt.get("code")
                                error_msg = rt.get("msg", "")
                                app.logger.error(f"[消息处理] 场景3：多维表格API错误，code: {error_code}, msg: {error_msg}")
                                if error_code in [99991672, 99992354] or "permission" in error_msg.lower() or "access" in error_msg.lower():
                                    reply_message(message_id, "文档访问失败，请检查：\n\n1. 链接是否正确\n\n2. 应用是否有访问权限\n\n3. 文件是否已分享给应用")
                                else:
                                    reply_message(message_id, "多维表格拉取失败，请检查链接是否正确")
                                return jsonify({"ok": "received"}), 200
                            
                            if not rt.get("data", {}).get("items"):
                                app.logger.error(f"[消息处理] 多维表格中没有表，message_id: {message_id}")
                                reply_message(message_id, "多维表格中没有可用的表，请检查链接是否正确")
                                return jsonify({"ok": "received"}), 200
                            tables = rt["data"]["items"]
                            table_id = None
                            if BASE_AUTO_PICK == "first" or not BASE_PREFERRED_TABLE:
                                table_id = tables[0]["table_id"]
                            else:
                                for t in tables:
                                    if t.get("name") == BASE_PREFERRED_TABLE:
                                        table_id = t["table_id"]
                                        break
                                if not table_id:
                                    table_id = tables[0]["table_id"]

                            # 尝试第一视图（可选）
                            view_id = None
                            try:
                                url_views = f"{OPEN_BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views"
                                rv = requests.get(url_views, headers=headers, params={"page_size": 200}, timeout=10).json()
                                if rv.get("code") == 0 and rv.get("data", {}).get("items"):
                                    views = rv["data"]["items"]
                                    if BASE_AUTO_PICK == "first" or not BASE_PREFERRED_VIEW:
                                        view_id = views[0]["view_id"]
                                    else:
                                        for v in views:
                                            if v.get("name") == BASE_PREFERRED_VIEW:
                                                view_id = v["view_id"]
                                                break
                                        if not view_id:
                                            view_id = views[0]["view_id"]
                            except Exception:
                                pass

                            # 获取多维表格（base）名称
                            base_name = get_base_name(OPEN_BASE, app_token, token)
                            # 清理文件名（去除特殊字符）
                            safe_name = re.sub(r'[<>:"/\\|?*]', '_', base_name)
                            # 生成北京时间戳
                            ts = get_beijing_timestamp()
                            # 文件命名：多维表格名-发送者ID-时间戳.xlsx
                            outfile = os.path.join(OUTPUT_DIR, f"{safe_name}-{sender_id}-{ts}.xlsx")
                            print(f"[INFO] 开始拉取Excel: table_id={table_id}, view_id={view_id}, outfile={outfile}")
                            result = pull_bitable.pull_to_files(
                                OPEN_BASE, APP_ID, APP_SECRET, app_token, table_id, view_id, outfile
                            )
                            print(f"[INFO] Excel拉取完成: count={result.get('count')}, file={result.get('xlsx')}")
                            
                            # 生成桑基图
                            app.logger.info(f"[消息处理] 开始生成桑基图，Excel文件: {result.get('xlsx')}, Base名称: {base_name}")
                            sankey_success, sankey_result = generate_sankey_and_notify(result['xlsx'], base_name)
                            app.logger.info(f"[消息处理] 桑基图生成结果: success={sankey_success}, result={sankey_result}")
                            
                            # 只返回一次消息
                            if sankey_success:
                                app.logger.info(f"[消息处理] 桑基图生成成功，回复链接给用户，message_id: {message_id}")
                                reply_message(message_id, f"桑基图链接：{sankey_result}")  # 成功：返回标注后的链接
                            else:
                                # 场景 4：Excel 格式不对
                                if sankey_result == "format_error":
                                    app.logger.error(f"[消息处理] 场景4：Excel格式不符合要求，message_id: {message_id}")
                                    reply_message(message_id, "Excel 文件格式不符合要求，请确保文件包含：\n\n1. 第一列为时间列\n\n2. 后续列为成对的项目列和描述列\n\n3. 最后一列为总预算\n\n4. 数据行完整")
                                else:
                                    app.logger.error(f"[消息处理] 桑基图生成失败，回复错误消息给用户，message_id: {message_id}, 结果: {sankey_result}")
                                    reply_message(message_id, "桑基图生成失败，请联系服务管理员")
                        except RuntimeError as e:
                            # 场景 3：权限错误或 API 错误
                            error_msg = str(e)
                            app.logger.exception(f"[消息处理] 场景3：多维表格访问失败，message_id: {message_id}, 错误: {e}")
                            try:
                                if "code" in error_msg or "permission" in error_msg.lower() or "access" in error_msg.lower():
                                    reply_message(message_id, "文档访问失败，请检查：\n\n1. 链接是否正确\n\n2. 应用是否有访问权限\n\n3. 文件是否已分享给应用")
                                else:
                                    reply_message(message_id, "多维表格拉取失败，请检查链接是否正确")
                                app.logger.info(f"[消息处理] 已发送错误消息给用户，message_id: {message_id}")
                            except Exception as reply_err:
                                app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                        except Exception as e:
                            # 其他异常
                            app.logger.exception(f"[消息处理] 自动拉取多维表格失败，message_id: {message_id}, 错误: {e}")
                            try:
                                reply_message(message_id, "桑基图生成失败，请联系服务管理员")
                                app.logger.info(f"[消息处理] 已发送错误消息给用户，message_id: {message_id}")
                            except Exception as reply_err:
                                app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                    else:
                        # app_token 解析失败
                        app.logger.warning(f"[消息处理] app_token 解析失败，message_id: {message_id}, text: {text}")
                        if message_id:
                            try:
                                reply_message(message_id, "多维表格链接格式错误，请检查链接是否正确")
                                app.logger.info(f"[消息处理] 已发送错误消息（解析失败），message_id: {message_id}")
                            except Exception as reply_err:
                                app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                    return jsonify({"ok": "received"}), 200

            except Exception as e:
                app.logger.exception(f"[消息处理] 解析多维表格链接失败，message_id: {message_id}, 错误: {e}")
                # 解析链接失败，也要返回错误消息
                if message_id:
                    try:
                        reply_message(message_id, "多维表格链接格式错误，请检查链接是否正确")
                        app.logger.info(f"[消息处理] 已发送错误消息（解析链接失败），message_id: {message_id}")
                    except Exception as reply_err:
                        app.logger.exception(f"[消息处理] 发送错误消息失败，message_id: {message_id}, 错误: {reply_err}")
                return jsonify({"ok": "received"}), 200
    except Exception as e:
        app.logger.exception(f"log message error: {e}")
        # 即使出错也要返回 200，避免飞书重试
        return jsonify({"ok": "received"}), 200

    # 默认返回 200（确保飞书不会重试）
    return jsonify({"ok": "received"}), 200


def create_app() -> Flask:
    return app


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
