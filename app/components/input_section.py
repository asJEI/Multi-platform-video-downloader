"""
输入区 + 平台检测/元数据解析（Streamlit UI 与 yt-dlp 逻辑同文件）。

设计要点：
- UI：链接输入、「解析视频」、卡片式信息展示。
- 逻辑：extract_video_metadata(url) 供 future downloader 等模块直接复用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError

# 与仓库根目录的 config.py 对齐（app 入口已注入根路径；此处兜底）
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config

# ---------------------------------------------------------------------------
# 自定义异常：解析链路内部使用；最终由 extract_video_metadata 统一转成 dict["error"]
# ---------------------------------------------------------------------------


class VideoParseError(Exception):
    """视频元数据解析失败（面向用户的中文提示）。"""


# yt-dlp 提取选项（按需求固定）
_YDL_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "ignoreerrors": False,
}


def _empty_metadata_result(error: str | None = None) -> dict[str, Any]:
    """与 extract_video_metadata 对齐的空结果结构。"""
    return {
        "title": None,
        "thumbnail": None,
        "duration": None,
        "extractor": None,
        "extractor_key": None,
        "formats": [],
        "webpage_url": None,
        "uploader": None,
        "raw_info": None,
        "error": error,
    }


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise VideoParseError("❌ 请先粘贴有效的视频链接")
    if not re.match(r"^https?://", u, re.I):
        raise VideoParseError("❌ 链接无效或平台不支持，请检查后重试")
    return u


def _pick_thumbnail(info: dict[str, Any]) -> str | None:
    t = info.get("thumbnail")
    if isinstance(t, str) and t:
        return t
    thumbs = info.get("thumbnails") or []
    if thumbs and isinstance(thumbs, list):
        last = thumbs[-1]
        if isinstance(last, dict):
            u = last.get("url")
            if isinstance(u, str) and u:
                return u
    return None


def _format_duration_mmss(seconds: float | int | None) -> str:
    """将秒转为 mm:ss（超过 1 小时则 h:mm:ss，避免超长视频显示不清）。"""
    if seconds is None:
        return "未知"
    try:
        s = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "未知"
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _approx_size_mb(fmt: dict[str, Any], video_duration: float | None) -> float | None:
    """估算体积（MB）：优先 filesize / filesize_approx，否则用 tbr * duration 近似。"""
    fs = fmt.get("filesize") or fmt.get("filesize_approx")
    if isinstance(fs, (int, float)) and fs > 0:
        return float(fs) / (1024 * 1024)

    tbr = fmt.get("tbr")  # 总码率 kbps（部分条目存在）
    dur = video_duration if video_duration is not None else fmt.get("duration")
    if tbr and dur:
        try:
            return (float(tbr) * 1000.0 * float(dur)) / 8.0 / (1024 * 1024)
        except (TypeError, ValueError):
            pass
    return None


def _build_format_entries(
    info: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    从 info['formats'] 过滤有效视频轨，按清晰度（height 优先，其次 fps）降序。
    返回供前端/下载器使用的列表。
    """
    duration = info.get("duration")
    if duration is not None:
        try:
            duration_f = float(duration)
        except (TypeError, ValueError):
            duration_f = None
    else:
        duration_f = None

    formats_raw = info.get("formats") or []
    candidates: list[dict[str, Any]] = []
    for f in formats_raw:
        if not isinstance(f, dict):
            continue
        vcodec = f.get("vcodec")
        height = f.get("height")
        if vcodec in (None, "none"):
            continue
        if not height:
            continue
        fid = f.get("format_id")
        if not fid:
            continue
        candidates.append(f)

    def sort_key(fm: dict[str, Any]) -> tuple[int, float]:
        h = int(fm.get("height") or 0)
        fps_v = fm.get("fps")
        try:
            fps = float(fps_v) if fps_v is not None else 0.0
        except (TypeError, ValueError):
            fps = 0.0
        return (h, fps)

    candidates.sort(key=sort_key, reverse=True)

    out: list[dict[str, Any]] = []
    for f in candidates:
        height = int(f.get("height") or 0)
        fps_v = f.get("fps")
        try:
            fps_f = float(fps_v) if fps_v is not None else None
        except (TypeError, ValueError):
            fps_f = None
        ext = (f.get("ext") or "mp4").lower()
        fps_label = f"{int(fps_f)}fps" if fps_f and fps_f > 0 else ""

        mb = _approx_size_mb(f, duration_f)
        if mb is not None and mb > 0:
            size_part = f"约 {mb:.1f} MB"
        else:
            size_part = "大小未知"

        fps_seg = f"{fps_label} " if fps_label else ""
        label = f"{height}p {fps_seg}{ext.upper()} ({size_part})".strip()

        out.append(
            {
                "id": str(f.get("format_id")),
                "label": label,
                "format": f,
            }
        )
    return out


def _extract_with_ytdlp(url: str) -> dict[str, Any]:
    """
    使用 YoutubeDL 拉取元数据；失败抛 VideoParseError（中文提示）。

    若项目根目录存在 config.COOKIES_FILE（默认 cookies.txt），则通过 cookiefile 传入 yt-dlp。
    """
    # 仅当 cookies 文件存在时合并 cookiefile（见 config.ytdlp_cookiefile_opts）
    ydl_opts: dict[str, Any] = {**_YDL_OPTS, **config.ytdlp_cookiefile_opts()}

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except (DownloadError, ExtractorError) as e:
        raw = str(e).strip() or repr(e)
        friendly = config.enhance_ytdlp_error_message(raw)
        if friendly == config.COOKIES_ERROR_HINT_ZH:
            raise VideoParseError(friendly) from e
        raise VideoParseError(
            f"❌ 无法解析该链接（网络或平台限制）：{friendly}"
        ) from e
    except VideoParseError:
        raise
    except Exception as e:  # noqa: BLE001 — 统一转为可展示错误
        raw_exc = str(e).strip()
        friendly_exc = config.enhance_ytdlp_error_message(raw_exc)
        if friendly_exc == config.COOKIES_ERROR_HINT_ZH:
            raise VideoParseError(friendly_exc) from e
        raise VideoParseError(
            "❌ 链接无效或平台不支持，请检查后重试"
        ) from e

    if not isinstance(info, dict):
        raise VideoParseError("❌ 未获取到有效的视频信息，请更换链接后重试")

    if info.get("_type") == "playlist":
        raise VideoParseError("❌ 暂不支持播放列表，请粘贴单个视频链接")

    extractor_key = info.get("extractor_key") or info.get("ie_key")
    extractor_human = info.get("extractor") or extractor_key

    title = info.get("title")
    webpage_url = info.get("webpage_url") or info.get("original_url") or url

    return {
        "title": title,
        "thumbnail": _pick_thumbnail(info),
        "duration": info.get("duration"),
        "extractor": extractor_human,
        "extractor_key": extractor_key,
        "formats": _build_format_entries(info),
        "webpage_url": webpage_url,
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        "raw_info": info,
        "error": None,
    }


# ---------------------------------------------------------------------------
# 对外纯函数：供 future downloader.py 等复用
# ---------------------------------------------------------------------------


def extract_video_metadata(url: str) -> dict[str, Any]:
    """
    解析视频元数据，返回结构化字典。

    Returns
    -------
    dict
        包含 title、thumbnail、duration、extractor、extractor_key、formats、
        webpage_url、uploader、raw_info（完整 info 供下载器使用）、
        error（成功为 None，失败为中文错误文案）。
    """
    try:
        normalized = _normalize_url(url)
        return _extract_with_ytdlp(normalized)
    except VideoParseError as e:
        return _empty_metadata_result(str(e))


# ---------------------------------------------------------------------------
# Streamlit：输入 + 解析 + 卡片展示
# ---------------------------------------------------------------------------


def render_input_section() -> None:
    """
    渲染「粘贴链接 → 解析视频 → 卡片展示」整块区域。

    成功时在 st.session_state 中写入：
    - last_video_metadata : extract_video_metadata 的完整返回（error 为 None）
    """
    st.subheader("视频链接")
    url = st.text_input(
        label="视频地址",
        label_visibility="collapsed",
        placeholder="粘贴视频链接（支持 YouTube、Bilibili、Twitter 等）",
        key="video_url_input",
    )

    col_a, col_b = st.columns([1, 4])
    with col_a:
        parse_clicked = st.button("解析视频", type="primary", use_container_width=True)

    if not parse_clicked:
        return

    if not url or not url.strip():
        st.warning("请先粘贴视频链接")
        return

    try:
        with st.spinner("正在解析..."):
            result = extract_video_metadata(url)
    except Exception as e:  # noqa: BLE001 — 防御性：理论上 extract 已吞掉；避免页面崩溃
        st.error(str(e))
        return

    if result.get("error"):
        st.error(result["error"])
        return

    st.session_state["last_video_metadata"] = result

    # ---------- 卡片式主信息 ----------
    with st.container(border=True):
        c_thumb, c_main = st.columns([1, 2])
        with c_thumb:
            thumb = result.get("thumbnail")
            if thumb:
                st.image(thumb, use_container_width=True)
            else:
                st.caption("无封面")
        with c_main:
            title = result.get("title") or "（无标题）"
            st.markdown(f"### {title}")
            platform = result.get("extractor") or result.get("extractor_key") or "未知平台"
            dur = _format_duration_mmss(result.get("duration"))
            st.markdown(f"**平台：** `{platform}`")
            st.markdown(f"**时长：** `{dur}`")

    # ---------- 其他元数据 ----------
    with st.expander("更多元数据", expanded=False):
        m1, m2 = st.columns(2)
        with m1:
            st.text_input("上传者", value=result.get("uploader") or "—", disabled=True)
            st.text_input("页面 URL", value=result.get("webpage_url") or "—", disabled=True)
        with m2:
            ek = result.get("extractor_key") or "—"
            st.text_input("extractor_key / ie_key", value=str(ek), disabled=True)
            raw_info = result.get("raw_info") or {}
            vc = raw_info.get("view_count") if isinstance(raw_info, dict) else None
            st.text_input(
                "播放量（若平台提供）",
                value=str(vc) if vc is not None else "—",
                disabled=True,
            )

    # ---------- 清晰度列表预览（供后续下载器接选中的 format_id） ----------
    fmt_entries: list[dict[str, Any]] = result.get("formats") or []
    if fmt_entries:
        st.markdown("**可用清晰度（已按高度/帧率排序）**")
        for i, item in enumerate(fmt_entries):
            st.caption(f"{i + 1}. `{item['label']}` · format_id=`{item['id']}`")
    else:
        st.info("未解析到带分辨率的视频格式条目（可能为纯音频或特殊流）。")
