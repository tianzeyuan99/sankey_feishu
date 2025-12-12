#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云文档下载模块
从飞书云文档链接下载 Excel 文件
"""

import os
import re
import json
import requests
import pandas as pd
from typing import Optional


def extract_file_token_from_link(doc_link: str) -> str:
    """从云文档链接中提取 file_token

    支持的链接格式：
    - https://xxx.feishu.cn/docs/xxx
    - https://xxx.feishu.cn/sheets/xxx
    - https://xxx.feishu.cn/file/xxx  (文件链接格式)
    - https://xxx.w.cnooc.com.cn/file/xxx
    """
    # 匹配多种格式
    patterns = [
        r'/(?:docs|sheets|file)/([A-Za-z0-9]+)',  # 标准格式：/docs/、/sheets/、/file/
        r'/(?:docs|sheets|file)/([A-Za-z0-9]+)\?',  # 带查询参数
        r'/(?:docs|sheets|file)/([A-Za-z0-9]+)#',  # 带锚点
    ]

    for pattern in patterns:
        m = re.search(pattern, doc_link)
        if m:
            file_token = m.group(1)
            return file_token

    raise ValueError(
        f"无法从链接中提取 file_token: {doc_link}\n支持的链接格式示例：\n  - https://xxx.feishu.cn/docs/xxx\n  - https://xxx.feishu.cn/sheets/xxx\n  - https://xxx.feishu.cn/file/xxx")


def download_sheets_via_read(file_token: str, output_path: str, tenant_token: str, open_base: str) -> tuple[bool, Optional[str], Optional[str]]:
    """通过读取接口获取 sheets 数据并转换为 Excel（支持多sheet）
    
    使用 v2/spreadsheets/{token}/metainfo 接口获取所有 sheet_id，
    然后使用 v2/spreadsheets/{token}/values/{sheet_id} 读取每个sheet的数据。
    
    Args:
        file_token: Sheets 的 file_token
        output_path: 输出文件路径
        tenant_token: tenant_access_token
        open_base: 飞书 API 基础 URL
    
    Returns:
        tuple[bool, Optional[str], Optional[str]]: (是否成功, 错误信息或 None, 文件名或 None)
    """
    headers = {
        "Authorization": f"Bearer {tenant_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    try:
        # 步骤1: 使用 v2/metainfo 接口获取表格元数据，获取所有 sheet
        metadata_url = f"{open_base}/open-apis/sheets/v2/spreadsheets/{file_token}/metainfo"
        resp = requests.get(metadata_url, headers=headers, timeout=30)
        
        if resp.status_code == 403:
            return False, "permission_denied", None
        if resp.status_code == 404:
            return False, "file_not_found", None
        if resp.status_code != 200:
            return False, f"api_error: status_code={resp.status_code}", None
        
        metadata = resp.json()
        if metadata.get("code") != 0:
            error_msg = metadata.get("msg", "unknown")
            if "permission" in error_msg.lower() or "access" in error_msg.lower():
                return False, "permission_denied", None
            if "not found" in error_msg.lower():
                return False, "file_not_found", None
            return False, f"api_error: {error_msg}", None
        
        # 获取文件名（title）
        data = metadata.get("data", {})
        properties = data.get("properties", {})
        file_title = properties.get("title", "")
        
        # 获取所有 sheet
        sheets = data.get("sheets", [])
        if not sheets:
            return False, "no_sheets", None
        
        # 步骤2: 读取所有sheet的数据
        all_sheets_data = {}
        for sheet in sheets:
            sheet_id = sheet.get("sheetId")
            sheet_title = sheet.get("title", f"Sheet{sheet_id}")
            
            if not sheet_id:
                continue
            
            # 读取每个sheet的数据
            read_url = f"{open_base}/open-apis/sheets/v2/spreadsheets/{file_token}/values/{sheet_id}"
            resp = requests.get(read_url, headers=headers, timeout=30)
            
            if resp.status_code == 403:
                return False, "permission_denied", None
            if resp.status_code == 404:
                return False, "file_not_found", None
            if resp.status_code != 200:
                # 某个sheet读取失败，跳过
                continue
            
            read_data = resp.json()
            if read_data.get("code") != 0:
                # 某个sheet读取失败，跳过
                continue
            
            # 步骤3: 解析数据
            value_range = read_data.get("data", {}).get("valueRange", {})
            values = value_range.get("values", [])
            
            if values:
                # 转换为 DataFrame（第一行作为表头）
                if len(values) > 0:
                    df = pd.DataFrame(values[1:], columns=values[0] if len(values) > 0 else None)
                    all_sheets_data[sheet_title] = df
        
        if not all_sheets_data:
            return False, "empty_data", None
        
        # 步骤4: 保存为Excel
        # 如果只有一个sheet，保持原有行为（无表头，兼容旧格式）
        # 如果有多个sheet，保存为多sheet Excel（有表头）
        if len(all_sheets_data) == 1:
            # 单sheet：保持原有格式（无表头）
            df = list(all_sheets_data.values())[0]
            # 如果没有表头，使用原有逻辑：直接使用values
            # 这里我们需要重新读取一次，因为DataFrame可能已经丢失了原始数据
            first_sheet = sheets[0]
            sheet_id = first_sheet.get("sheetId")
            read_url = f"{open_base}/open-apis/sheets/v2/spreadsheets/{file_token}/values/{sheet_id}"
            resp = requests.get(read_url, headers=headers, timeout=30)
            read_data = resp.json()
            value_range = read_data.get("data", {}).get("valueRange", {})
            values = value_range.get("values", [])
            df = pd.DataFrame(values)
            df.to_excel(output_path, index=False, header=False, engine='openpyxl')
        else:
            # 多sheet：保存为多sheet Excel（有表头）
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                for sheet_name, df in all_sheets_data.items():
                    # 清理sheet名称（Excel sheet名称限制）
                    safe_sheet_name = sheet_name[:31]  # Excel sheet名称最长31字符
                    df.to_excel(writer, sheet_name=safe_sheet_name, index=False, header=True)
        
        # 验证文件是否生成成功
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True, None, file_title
        else:
            return False, "file_write_failed", None
            
    except requests.exceptions.RequestException as e:
        return False, f"network_error: {str(e)}", None
    except Exception as e:
        return False, f"unknown_error: {str(e)}", None


def download_cloud_doc_to_excel(file_token: str, output_path: str, tenant_token: str, open_base: str, doc_link: str = "") -> tuple[bool, Optional[str], Optional[str]]:
    """下载飞书云文档为 Excel 文件

    Args:
        file_token: 云文档的 file_token
        output_path: 输出文件路径
        tenant_token: tenant_access_token
        open_base: 飞书 API 基础 URL
        doc_link: 原始文档链接（用于判断类型）

    Returns:
        tuple[bool, Optional[str], Optional[str]]: (是否成功, 错误信息或 None, 文件名或 None)
    """
    headers = {
        "Authorization": f"Bearer {tenant_token}",
        "Content-Type": "application/json"
    }
    
    # 判断是否为 sheets 类型
    is_sheets = "/sheets/" in doc_link if doc_link else False
    
    # 如果是 sheets 类型，优先尝试读取接口
    if is_sheets:
        try:
            success, error, file_title = download_sheets_via_read(file_token, output_path, tenant_token, open_base)
            if success:
                return True, None, file_title
            # 如果是权限或文件不存在错误，直接返回
            if error in ["permission_denied", "file_not_found"]:
                return False, error, None
            # 其他错误，继续尝试直接下载接口
        except Exception:
            # 读取接口异常，继续尝试直接下载接口
            pass

    # 直接下载接口（官方标准接口）
    download_url = f"{open_base}/open-apis/drive/v1/files/{file_token}/download"
    
    try:
        resp = requests.get(download_url, headers=headers, timeout=30, stream=True)
        
        # 处理 403 权限错误
        if resp.status_code == 403:
            return False, "permission_denied", None
        
        # 处理 404 文件不存在
        if resp.status_code == 404:
            return False, "file_not_found", None
        
        # 处理 200 成功
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '')
            
            # 排除 HTML 页面
            if 'text/html' in content_type:
                return False, "invalid_response", None
            
            # 检查是否是文件流（排除 JSON）
            if 'text/html' not in content_type and 'application/json' not in content_type:
                # 保存文件
                with open(output_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = os.path.getsize(output_path)
                
                # 验证文件确实是 Excel（检查文件头）
                with open(output_path, 'rb') as f:
                    file_header = f.read(4)
                    if file_header == b'PK\x03\x04':
                        # Excel 文件头验证通过
                        # 对于非 Sheets 类型的云文档，无法获取文件名，返回 None
                        return True, None, None
                    else:
                        # 文件头验证失败，删除无效文件
                        os.remove(output_path)
                        return False, "invalid_file_format", None
        
        # 其他状态码
        return False, "download_failed", None
        
    except requests.exceptions.RequestException as e:
        return False, f"network_error: {str(e)}", None
    except Exception as e:
        return False, f"unknown_error: {str(e)}", None


def download_file(download_url: str, output_path: str, headers: dict = None) -> bool:
    """下载文件到本地（用于下载链接方式）

    Args:
        download_url: 下载链接
        output_path: 输出路径
        headers: 请求头（可选）

    Returns:
        bool: 是否成功
    """
    try:
        resp = requests.get(download_url, headers=headers, timeout=30, stream=True)
        if resp.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            # 验证文件头
            with open(output_path, 'rb') as f:
                file_header = f.read(4)
                if file_header == b'PK\x03\x04':
                    return True
                else:
                    os.remove(output_path)
                    return False
        return False
    except Exception:
        return False

