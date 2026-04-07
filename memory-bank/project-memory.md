# 项目记忆（Project Memory）

## 当前阶段

**阶段 4 — 核心功能可用，完成结构与可维护性优化。**  
在保持现有功能不变的前提下，已完成轻量重构：清理入口冗余导入、合并下载模块重复错误处理、补充项目 README 与运行/排错说明。Cookie 方案仍为 `cookies.txt`（优雅降级）。仓库提供 **`cookies.example.txt`** 作为格式模板；根目录 **`.gitignore`** 忽略真实 `cookies.txt`。已移除各目录空 `.gitkeep`，`data/downloads` 与 `tests` 改为简短 `README.md` 占位；未使用的 `app/pages`、`app/services` 空目录已删除。

## 已完成功能

- `config.py`：`COOKIES_FILE`、`resolve_cookies_file_path()`、`cookies_file_exists()`、`ytdlp_cookiefile_opts()`、`COOKIES_ERROR_HINT_ZH`、`enhance_ytdlp_error_message()`
- `app/components/input_section.py`：解析时合并 `ytdlp_cookiefile_opts()`
- `core/downloader.py`：下载时同样合并 `ytdlp_cookiefile_opts()`
- `main.py`：侧边栏 Cookies 状态提示
- `README.md`：项目结构、运行方式、配置说明、cookies 与 FFmpeg 常见问题
- `core/downloader.py`：新增 `_friendly_error_text()`，减少重复代码，统一错误文案转换路径
- 默认下载目录、FFmpeg 探测、`sanitize_filename`、进度 Hook 等（见前序阶段）

## 使用注意

- **cookies.txt** 需为 Netscape 格式；导出后路径与 `COOKIES_FILE` 一致（相对路径相对**项目根**，与 `config.py` 同级目录）。
- B 站 / 抖音若仍失败：确认扩展导出站点匹配、Cookie 未过期，且 yt-dlp 已更新。

## 未完成功能 / 后续计划

- 自动化测试与站点回归（含 B 站 / 抖音 cookies 失效场景）
- 历史持久化、字幕下载、队列任务与多页面增强

## 备注

- FFmpeg 为系统依赖。运行前：`pip install -r requirements.txt`。
