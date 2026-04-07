"""
多平台视频下载器 — Streamlit 主入口

运行（请在仓库根目录执行，确保已安装依赖）：
    streamlit run main.py

注意事项：
    1. 先安装 Python 依赖：pip install -r requirements.txt
    2. 分离视频流合并为 MP4 需要系统已安装 FFmpeg，并可在 PATH 中被检测到
       （或与 config.py 中的探测路径一致）
    3. 首次运行若提示找不到模块，请确认本文件位于项目根目录，且存在 app/components 与 core 目录
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# 导入路径：支持「根目录 main.py」且保持 from components / from core / import config
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
_APP = _ROOT / "app"
for p in (_ROOT, _APP):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

# 渲染输入与解析区（解析结果写入 st.session_state["last_video_metadata"]）
from components.input_section import render_input_section
from config import COOKIES_FILE
from config import DEFAULT_DOWNLOAD_DIR as DOWNLOAD_DIR
from config import FFMPEG_INSTALL_HINT
from config import FFMPEG_PATH
from config import cookies_file_exists
from config import resolve_cookies_file_path
from core.downloader import create_streamlit_progress_hook, download_video, save_to_history


def _open_folder(path: str) -> None:
    """在系统文件管理器中打开目录（若为文件则打开其所在文件夹）。"""
    target = Path(path).expanduser().resolve()
    folder = target if target.is_dir() else target.parent
    folder_str = str(folder)
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(folder_str)  # noqa: S606
        elif system == "Darwin":
            subprocess.run(["open", folder_str], check=False)
        else:
            subprocess.run(["xdg-open", folder_str], check=False)
    except Exception as e:  # noqa: BLE001
        st.warning(f"无法打开文件夹：{e}，请手动前往：{folder_str}")


def _maybe_download_button(local_path: str, max_bytes: int = 200 * 1024 * 1024) -> None:
    """若文件体积适中，提供浏览器内下载按钮（过大则跳过以免占满内存）。"""
    p = Path(local_path)
    if not p.is_file():
        return
    try:
        size = p.stat().st_size
    except OSError:
        return
    if size > max_bytes:
        st.caption("文件较大，已省略页面内「重新下载」按钮，请使用下方路径或打开文件夹。")
        return
    try:
        data = p.read_bytes()
    except OSError as e:
        st.caption(f"无法读取文件以供下载：{e}")
        return
    st.download_button(
        label="将已下载文件保存到…",
        data=data,
        file_name=p.name,
        mime="application/octet-stream",
        use_container_width=True,
    )


def _render_sidebar() -> None:
    st.sidebar.header("信息与设置")
    st.sidebar.markdown("**默认下载目录**")
    st.sidebar.code(str(DOWNLOAD_DIR), language="text")

    st.sidebar.markdown("**Cookies（B站 / 抖音）**")
    _cook_path = resolve_cookies_file_path()
    if cookies_file_exists():
        st.sidebar.info("cookies.txt 已加载 ✓")
    else:
        st.sidebar.warning(
            "未找到 cookies.txt，B站/抖音可能解析失败。"
            f"\n请将导出的文件放到：`{COOKIES_FILE}`（当前解析路径：`{_cook_path}`）"
        )

    st.sidebar.markdown("**FFmpeg**")
    if FFMPEG_PATH is not None:
        st.sidebar.success(f"已检测到： `{FFMPEG_PATH}`")
    else:
        st.sidebar.error("未检测到 FFmpeg")
        st.sidebar.caption(FFMPEG_INSTALL_HINT)

    st.sidebar.markdown("---")
    st.sidebar.markdown("**后续可扩展**")
    st.sidebar.caption("· 下载历史持久化与搜索\n· 字幕下载与封装\n· 队列与后台任务")


def main() -> None:
    st.set_page_config(
        page_title="多平台视频下载器",
        page_icon="🎥",
        layout="wide",
    )

    _render_sidebar()

    st.title("🎥 多平台视频下载器")
    st.markdown(
        "粘贴各平台视频链接，一键解析清晰度后下载到本地。"
        "支持 **YouTube**、**Bilibili**、**Twitter / X** 等（具体以 yt-dlp 为准）。"
    )

    left, right = st.columns([1, 1], gap="large")

    with left:
        st.markdown("##### 1 · 链接与解析")
        render_input_section()

    meta = st.session_state.get("last_video_metadata")

    with right:
        st.markdown("##### 2 · 清晰度与下载")
        if not meta or meta.get("error"):
            st.info("解析成功后，将在此选择清晰度并开始下载。")
        else:
            # 简要摘要（与左侧卡片互补，便于一眼确认）
            with st.container(border=True):
                t = meta.get("title") or "—"
                plat = meta.get("extractor") or meta.get("extractor_key") or "—"
                st.caption("当前已解析")
                st.markdown(f"**{t}**")
                c1, c2 = st.columns(2)
                with c1:
                    st.metric("平台", str(plat)[:24] + ("…" if len(str(plat)) > 24 else ""))
                with c2:
                    dur = meta.get("duration")
                    dlabel = f"{int(dur)} s" if dur is not None else "—"
                    st.metric("时长", dlabel)

            formats_list = meta.get("formats") or []
            if not formats_list:
                st.warning("当前视频没有可用的带分辨率格式列表，无法按清晰度下载。")
            else:
                raw = meta.get("raw_info") or {}
                fp = str(raw.get("id") or meta.get("webpage_url") or "unknown")

                options = list(range(len(formats_list)))
                idx = st.selectbox(
                    "选择清晰度（已按高度 / 帧率从高到低）",
                    options=options,
                    format_func=lambda i: formats_list[i]["label"],
                    key=f"selected_format_{fp}",
                )
                selected = formats_list[int(idx)]

                dl_clicked = st.button("开始下载", type="primary", use_container_width=True)

                if dl_clicked:
                    try:
                        with st.status("正在下载…", expanded=True) as status_area:
                            prog = st.progress(0)
                            status_txt = st.empty()
                            hook = create_streamlit_progress_hook(prog, status_txt)

                            result = download_video(
                                meta,
                                selected,
                                download_dir=str(DOWNLOAD_DIR),
                                download_cover=True,
                                progress_hooks=[hook],
                            )

                            if result.get("success"):
                                status_area.update(
                                    label="下载完成",
                                    state="complete",
                                )
                            else:
                                status_area.update(
                                    label="下载失败",
                                    state="error",
                                )

                        if result.get("success"):
                            out = result.get("file_path") or ""
                            st.success("下载成功")
                            st.text_input("完整文件路径", value=out, disabled=True)

                            if result.get("thumbnail_path"):
                                st.caption(f"封面已保存：{result['thumbnail_path']}")

                            _maybe_download_button(out)

                            if st.button("打开下载文件夹", use_container_width=True):
                                _open_folder(out)

                            # 预留：业务侧可在此追加历史字段（download_video 内已有一次 save_to_history）
                            try:
                                save_to_history(
                                    {
                                        "source": "main.py",
                                        "file_path": out,
                                        "title": meta.get("title"),
                                        "format_id": selected.get("id"),
                                    }
                                )
                            except Exception as hist_e:  # noqa: BLE001
                                st.caption(f"历史记录扩展写入跳过：{hist_e}")
                        else:
                            st.error(result.get("error") or "下载失败，原因未知。")

                    except Exception as e:  # noqa: BLE001
                        st.error(f"下载过程出现异常：{e}")


# Streamlit 会从头到尾执行本脚本，需直接调用 main（不要仅放在 __main__ 守卫内）
main()
