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


def download_cloud_doc_to_excel(file_token: str, output_path: str, tenant_token: str, open_base: str) -> tuple[bool, Optional[str]]:
    """下载飞书云文档为 Excel 文件

    Args:
        file_token: 云文档的 file_token
        output_path: 输出文件路径
        tenant_token: tenant_access_token
        open_base: 飞书 API 基础 URL

    Returns:
        tuple[bool, Optional[str]]: (是否成功, 错误信息或 None)
    """
    headers = {
        "Authorization": f"Bearer {tenant_token}",
        "Content-Type": "application/json"
    }

    # 优先尝试：直接下载接口（官方标准接口）
    download_url = f"{open_base}/open-apis/drive/v1/files/{file_token}/download"
    
    try:
        resp = requests.get(download_url, headers=headers, timeout=30, stream=True)
        
        # 处理 403 权限错误
        if resp.status_code == 403:
            return False, "permission_denied"
        
        # 处理 404 文件不存在
        if resp.status_code == 404:
            return False, "file_not_found"
        
        # 处理 200 成功
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '')
            
            # 排除 HTML 页面
            if 'text/html' in content_type:
                return False, "invalid_response"
            
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
                        return True, None
                    else:
                        # 文件头验证失败，删除无效文件
                        os.remove(output_path)
                        return False, "invalid_file_format"
        
        # 其他状态码
        return False, "download_failed"
        
    except requests.exceptions.RequestException as e:
        return False, f"network_error: {str(e)}"
    except Exception as e:
        return False, f"unknown_error: {str(e)}"


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

