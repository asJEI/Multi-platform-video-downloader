"""
下载核心：yt-dlp + FFmpeg 合并、进度回调、可选封面保存。

与 `app/components/input_section.py` 的配合方式：
- `metadata`：直接使用 `extract_video_metadata()` 的返回（需 `error is None`）
- `selected_format`：通常取 `st.session_state["last_video_metadata"]["formats"][i]`，
  或手写包含 `id` / `format_id` 与可选 `format` 的字典
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# 确保可导入仓库根目录下的 config.py（例如 streamlit 以 app/main.py 启动时）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config
from core.utils import sanitize_filename

# ---------------------------------------------------------------------------
# 可选依赖：封面下载
# ---------------------------------------------------------------------------

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]


def _yt_dlp_ffmpeg_location(path: Path | None) -> str | None:
    """yt-dlp 的 ffmpeg_location：传可执行文件所在目录更稳。"""
    if path is None:
        return None
    p = path.resolve()
    if p.is_file():
        return str(p.parent)
    return str(p)


def _resolve_video_url(metadata: dict[str, Any]) -> str | None:
    u = metadata.get("webpage_url")
    if isinstance(u, str) and u.strip():
        return u.strip()
    raw = metadata.get("raw_info") or {}
    if isinstance(raw, dict):
        for k in ("webpage_url", "original_url", "url"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _resolve_format_dict(
    metadata: dict[str, Any], selected_format: dict[str, Any]
) -> dict[str, Any]:
    """尽量拿到完整的 yt-dlp format 字典（用于判断音轨分离）。"""
    fmt = selected_format.get("format")
    if isinstance(fmt, dict) and fmt:
        return fmt

    fid = selected_format.get("id") or selected_format.get("format_id")
    if not fid:
        return {}

    raw = metadata.get("raw_info") or {}
    for f in raw.get("formats") or []:
        if not isinstance(f, dict):
            continue
        if str(f.get("format_id")) == str(fid):
            return f
    return {}


def _format_id_from_selection(selected_format: dict[str, Any], fmt: dict[str, Any]) -> str | None:
    v = selected_format.get("id") or selected_format.get("format_id") or fmt.get("format_id")
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _needs_video_audio_merge(fmt: dict[str, Any]) -> bool:
    """
    判断是否为「纯视频轨」：需要再拉一条音频并由 FFmpeg 合并。

    规则：有有效 vcodec 且无有效 acodec（none/缺失）。
    """
    vcodec = fmt.get("vcodec")
    if vcodec in (None, "none"):
        return False
    acodec = fmt.get("acodec")
    return acodec in (None, "none")


def _build_format_selection(fid: str, fmt: dict[str, Any]) -> str:
    """
    构造 yt-dlp 的 format 字符串。
    分离格式：video_id + bestaudio（ba 为 bestaudio 简写，兼容用户要求）。
    """
    if _needs_video_audio_merge(fmt):
        # ba = bestaudio；加 /b 作为退路；merge_output_format 会再统一封装为 mp4
        return f"{fid}+ba/b"
    return fid


def progress_dict_to_percent_and_message(d: dict[str, Any]) -> tuple[float | None, str]:
    """
    将 yt-dlp progress_hook 的 dict 转为 (0~1 的百分比, 状态文案)。

    无总量时 percentage 为 None，仅展示文案（适合配合 st.text / caption）。
    """
    status = d.get("status")
    if status == "downloading":
        downloaded = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        try:
            downloaded = float(downloaded)
            if total:
                total_f = float(total)
                pct = downloaded / total_f if total_f > 0 else None
            else:
                pct = None
        except (TypeError, ValueError):
            pct = None

        fname = os.path.basename(str(d.get("filename") or ""))
        frag = d.get("fragment_index")
        frags = d.get("fragment_count")
        frag_txt = ""
        if frag is not None and frags:
            frag_txt = f" 分片 {frag}/{frags}"
        spd = d.get("_speed_str") or d.get("speed")
        eta = d.get("_eta_str") or d.get("eta")
        tail = " ".join(x for x in (spd, eta) if x)
        label = fname or "下载中"
        msg = f"正在下载：{label}{frag_txt}"
        if tail:
            msg += f" · {tail}"
        return pct, msg

    if status == "finished":
        fn = d.get("filename")
        base = os.path.basename(str(fn)) if fn else ""
        return 1.0, f"片段完成：{base}" if base else "片段完成"

    if status == "error":
        return None, "下载过程出错，请查看控制台或日志。"

    # postprocessing / starting / etc.
    post = d.get("postprocessor")
    if status == "postprocessing" and post:
        return None, f"后处理：{post}"
    return None, f"状态：{status or '处理中'}"


def create_streamlit_progress_hook(
    progress_bar: Any | None,
    status_text: Any | None,
) -> Callable[[dict[str, Any]], None]:
    """
    生成可放入 yt-dlp `progress_hooks` 的回调，驱动 Streamlit 控件。

    Parameters
    ----------
    progress_bar :
        一般为 `st.progress(0)` 的返回值；若 None 则跳过进度条更新。
    status_text :
        一般为 `st.empty()`，对其 `.text(...)` 更新文案；若 None 则跳过。
    """

    def hook(d: dict[str, Any]) -> None:
        pct, msg = progress_dict_to_percent_and_message(d)
        if status_text is not None:
            status_text.text(msg)
        if progress_bar is not None and pct is not None:
            progress_bar.progress(min(1.0, max(0.0, float(pct))))

    return hook


def _make_path_capture_hook(state: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    """记录每次 finished 的文件路径（合并后最后一次通常为目标文件）。"""

    def hook(d: dict[str, Any]) -> None:
        if d.get("status") == "finished":
            fn = d.get("filename")
            if isinstance(fn, str) and fn:
                state.setdefault("finished_paths", []).append(fn)

    return hook


def download_thumbnail(
    metadata: dict[str, Any],
    download_dir: str | Path,
    *,
    filename_prefix: str | None = None,
    timeout: int = 30,
) -> str | None:
    """
    可选：下载封面到本地（requests + PIL；无 PIL 时按原样写入图片字节）。

    Returns
    -------
    str | None
        已保存的本地路径；失败或缺少依赖则 None。
    """
    url = metadata.get("thumbnail")
    if not isinstance(url, str) or not url.strip():
        return None
    if requests is None:
        return None

    raw_info = metadata.get("raw_info") or {}
    title = (
        metadata.get("title")
        or (raw_info.get("title") if isinstance(raw_info, dict) else None)
        or "cover"
    )
    prefix = filename_prefix or sanitize_filename(str(title))

    dest_dir = Path(download_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{prefix}_cover.jpg"

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url.strip(), headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.content
    except Exception:  # noqa: BLE001
        return None

    try:
        if Image is not None:
            im = Image.open(BytesIO(data)).convert("RGB")
            im.save(dest, format="JPEG", quality=92, optimize=True)
        else:
            dest.write_bytes(data)
        return str(dest.resolve())
    except Exception:  # noqa: BLE001
        return None


def save_to_history(entry: dict[str, Any]) -> None:
    """
    预留：将一次下载结果写入历史记录（JSON/SQLite 等）。

    当前为空实现，避免影响主流程；扩展时在此集中持久化逻辑即可。
    """
    _ = entry
    return


def _empty_result(
    success: bool,
    *,
    file_path: str | None = None,
    error: str | None = None,
    thumbnail_path: str | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "file_path": file_path or "",
        "error": error or "",
        "thumbnail_path": thumbnail_path or "",
    }


def _friendly_error_text(exc: Exception) -> str:
    """
    将异常统一转换为对用户更友好的中文文案。

    - Cookie 相关报错：返回 config 中的固定引导语
    - 其他报错：返回增强后的原始文本
    """
    raw = str(exc).strip() or repr(exc)
    return config.enhance_ytdlp_error_message(raw)


def download_video(
    metadata: dict[str, Any],
    selected_format: dict[str, Any],
    download_dir: str | None = None,
    *,
    download_cover: bool = False,
    progress_hooks: list[Callable[[dict[str, Any]], None]] | None = None,
) -> dict[str, Any]:
    """
    使用 yt-dlp 下载视频；必要时自动合并音视频为 mp4（依赖 FFmpeg）。

    Parameters
    ----------
    metadata :
        extract_video_metadata 的返回值（需已成功，`error` 为 None）。
    selected_format :
        至少包含所选 `id` / `format_id`；若含 `format` 字典可更准确判断是否缺音轨。
    download_dir :
        保存目录；None 时使用 config.DEFAULT_DOWNLOAD_DIR。
    download_cover :
        是否在成功后尝试下载封面到同一目录（失败不视为整次下载失败）。
    progress_hooks :
        额外进度回调（如 create_streamlit_progress_hook(...)），与内部路径采集钩子合并。

    Returns
    -------
    dict
        {"success": bool, "file_path": str, "error": str, "thumbnail_path": str}
    """
    if metadata.get("error"):
        return _empty_result(
            False, error=f"元数据无效：{metadata.get('error')}"
        )

    url = _resolve_video_url(metadata)
    if not url:
        return _empty_result(False, error="❌ 缺少可下载的视频 URL，请先重新解析。")

    fmt = _resolve_format_dict(metadata, selected_format)
    fid = _format_id_from_selection(selected_format, fmt)
    if not fid:
        return _empty_result(
            False, error="❌ 未指定有效的 format_id，请重新选择清晰度。"
        )

    needs_merge = _needs_video_audio_merge(fmt)
    ffmpeg_loc = _yt_dlp_ffmpeg_location(config.FFMPEG_PATH)

    if needs_merge and not ffmpeg_loc:
        return _empty_result(
            False,
            error=(
                "❌ 当前清晰度仅含视频轨，需要 FFmpeg 与音频合并为完整文件。"
                "请安装 FFmpeg 并添加到系统 PATH，然后重启应用。"
                f"（详情：{config.FFMPEG_INSTALL_HINT}）"
            ),
        )

    root = Path(
        download_dir
        if download_dir is not None
        else str(config.DEFAULT_DOWNLOAD_DIR)
    ).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _empty_result(
            False,
            error=f"❌ 无法创建或使用下载目录（权限或路径问题）：{e}",
        )

    outtmpl = os.path.join(str(root), "%(title)s [%(id)s].%(ext)s")
    format_sel = _build_format_selection(fid, fmt)

    hook_state: dict[str, Any] = {}
    hooks: list[Callable[[dict[str, Any]], None]] = [_make_path_capture_hook(hook_state)]
    if progress_hooks:
        hooks.extend(progress_hooks)

    postprocessors: list[dict[str, Any]] = []
    if needs_merge:
        # 显式指定 FFmpeg 合并器（与 merge_output_format 配合）
        postprocessors.append({"key": "FFmpegMerger"})

    ydl_opts: dict[str, Any] = {
        "format": format_sel,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "postprocessors": postprocessors,
        "progress_hooks": hooks,
        "quiet": False,
        "no_warnings": False,
        "ffmpeg_location": ffmpeg_loc,
        # 与 yt-dlp CLI dest 一致：windowsfilenames / restrictfilenames
        "windowsfilenames": True,
        "restrictfilenames": False,
        "retries": 10,
        "fragment_retries": 10,
        **config.ytdlp_cookiefile_opts(),
    }

    thumbnail_path = ""

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ret = ydl.download([url])
    except DownloadError as e:
        friendly = _friendly_error_text(e)
        if friendly == config.COOKIES_ERROR_HINT_ZH:
            return _empty_result(False, error=friendly)
        return _empty_result(False, error=f"❌ 下载失败（网络或站点限制）：{friendly}")
    except OSError as e:
        return _empty_result(
            False,
            error=f"❌ 写入文件失败（磁盘空间、权限或路径问题）：{e}",
        )
    except Exception as e:  # noqa: BLE001
        friendly = _friendly_error_text(e)
        if friendly == config.COOKIES_ERROR_HINT_ZH:
            return _empty_result(False, error=friendly)
        return _empty_result(False, error=f"❌ 下载过程发生异常：{friendly}")

    if ret != 0:
        return _empty_result(
            False,
            error="❌ 下载未完全成功（yt-dlp 返回错误码），请检查链接或稍后重试。",
        )

    paths = hook_state.get("finished_paths") or []
    file_path = str(Path(paths[-1]).resolve()) if paths else ""
    if not file_path:
        return _empty_result(
            False,
            error="❌ 下载已完成但未能解析输出文件路径，请检查下载目录中的文件。",
        )

    if download_cover:
        thumbnail_path = download_thumbnail(metadata, root) or ""

    save_to_history(
        {
            "url": url,
            "file_path": file_path,
            "format_id": fid,
            "extractor": metadata.get("extractor"),
            "title": metadata.get("title"),
        }
    )

    return _empty_result(True, file_path=file_path, thumbnail_path=thumbnail_path)
