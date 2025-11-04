import hmac
import hashlib
from typing import Optional


def verify_signature(raw_body: bytes, timestamp: Optional[str], nonce: Optional[str], signature: Optional[str], encrypt_key: Optional[str]) -> bool:
    """校验飞书签名（x-lark-signature）。

    拼接格式：timestamp + nonce + rawBody，然后使用 Encrypt Key 做 HMAC-SHA256。
    任何缺失视为校验失败。
    """
    if not (timestamp and nonce and signature and encrypt_key and raw_body is not None):
        return False
    to_sign = f"{timestamp}{nonce}".encode("utf-8") + raw_body
    calc = hmac.new(encrypt_key.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)
