"""
通用小工具：文件名清理等。

保留中文等非 ASCII 字符，仅移除 Windows / 跨平台非法字符。
"""

from __future__ import annotations

import re
import unicodedata


def sanitize_filename(name: str, max_length: int = 180) -> str:
    """
    将字符串整理为更安全的单段文件名（不含路径分隔符）。

    - 去除控制字符、规范化 Unicode
    - 替换 Windows 非法字符 `\\ / : * ? \" < > |`
    - 首尾空格与末尾句点（Windows）去掉
    - 过长时截断
    """
    if not name:
        return "unnamed"

    s = unicodedata.normalize("NFKC", str(name))
    # 控制字符
    s = "".join(ch for ch in s if ord(ch) >= 32 or ch in "\t\n\r")
    # Windows 保留名、非法符号
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = s.strip().rstrip(".")

    # Windows 设备名（简化处理）
    if s.upper() in {"CON", "PRN", "AUX", "NUL"} or re.match(
        r"^(COM|LPT)\d$", s.upper()
    ):
        s = f"_{s}_"

    if len(s) > max_length:
        s = s[: max(1, max_length - 3)].rstrip() + "..."

    return s or "unnamed"
