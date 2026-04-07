"""
Application configuration: default download folder and FFmpeg discovery.

FFmpeg is not installed via pip; this module resolves the system binary or
returns None so the UI can prompt the user to install it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

# 本文件所在目录 = 项目根目录（main.py、core/、app/ 同级）
_PROJECT_ROOT: Path = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Cookies：Netscape 格式的 cookies.txt（B 站 / 抖音等常需要）
# 默认放在项目根目录；可改为绝对路径。文件不存在时不向 yt-dlp 传入 cookiefile（优雅降级）。
# ---------------------------------------------------------------------------
COOKIES_FILE: str = "cookies.txt"


def resolve_cookies_file_path() -> Path:
    """解析 COOKIES_FILE：相对路径相对项目根目录。"""
    p = Path(COOKIES_FILE)
    if p.is_absolute():
        return p.resolve()
    return (_PROJECT_ROOT / p).resolve()


def cookies_file_exists() -> bool:
    return resolve_cookies_file_path().is_file()


def ytdlp_cookiefile_opts() -> dict[str, Any]:
    """
    仅当 cookies 文件存在时返回 {"cookiefile": 绝对路径}；否则返回空 dict（不把 cookiefile 设为 None）。
    """
    path = resolve_cookies_file_path()
    if path.is_file():
        return {"cookiefile": str(path)}
    return {}


# 当 yt-dlp 报 Cookie 相关错误时，在 UI 中展示的友好说明（多行）
COOKIES_ERROR_HINT_ZH: str = (
    "❌ 需要 cookies.txt 文件。\n"
    "请使用 'Get cookies.txt LOCALLY' 扩展从浏览器导出 cookies.txt 并放到项目根目录。"
)


def enhance_ytdlp_error_message(message: str | None) -> str:
    """
    识别 Cookie 相关英文提示，返回 cookies.txt 引导说明；否则原样返回（strip 后）。
    """
    text = (message or "").strip()
    if not text:
        return text
    tl = text.lower()
    if "fresh cookies" in tl or "cookies" in tl:
        return COOKIES_ERROR_HINT_ZH
    return text

# ---------------------------------------------------------------------------
# Default save directory (override with env VIDEO_DOWNLOADER_SAVE_DIR)
# ---------------------------------------------------------------------------
_DEFAULT_RELATIVE = Path("data") / "downloads"


def get_default_download_dir() -> Path:
    """
    Prefer environment variable, then user-facing folder under home, else project data dir.
    """
    env = os.environ.get("VIDEO_DOWNLOADER_SAVE_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    home = Path.home()
    # Common media folder name on Windows/macOS/Linux
    videos = home / "Videos"
    if videos.is_dir():
        return (videos / "StreamlitVideoDownloader").resolve()

    return (Path(__file__).resolve().parent / _DEFAULT_RELATIVE).resolve()


DEFAULT_DOWNLOAD_DIR: Path = get_default_download_dir()


# ---------------------------------------------------------------------------
# FFmpeg: PATH first, then typical Windows install locations
# ---------------------------------------------------------------------------
_FFMPEG_WINDOWS_CANDIDATES = (
    Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin" / "ffmpeg.exe",
    Path(os.environ.get("LocalAppData", "")) / "Programs" / "ffmpeg" / "bin" / "ffmpeg.exe",
)


def detect_ffmpeg_path() -> Path | None:
    """Return absolute path to ffmpeg if found, else None."""
    which = shutil.which("ffmpeg")
    if which:
        return Path(which).resolve()

    if sys.platform == "win32":
        for candidate in _FFMPEG_WINDOWS_CANDIDATES:
            if candidate.is_file():
                return candidate.resolve()

    return None


FFMPEG_PATH: Path | None = detect_ffmpeg_path()

# Short hint for Streamlit / CLI when FFMPEG_PATH is None
FFMPEG_INSTALL_HINT = (
    "未在系统 PATH 或常见目录中找到 FFmpeg。"
    "请从 https://ffmpeg.org/download.html 安装，并将 ffmpeg 所在目录加入 PATH，"
    "或安装到 C:\\ffmpeg\\bin 等常见路径后重新启动应用。"
)
