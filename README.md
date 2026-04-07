# 多平台视频下载器（Streamlit + yt-dlp + FFmpeg）

一个干净、模块化的 Streamlit Web 应用：粘贴链接、解析元数据、选择清晰度、下载并自动合并音视频（如需）。

## 功能概览

- 链接解析：自动识别平台并展示标题、封面、时长、上传者等信息
- 清晰度列表：按分辨率和帧率从高到低排序
- 一键下载：支持音视频分离流自动合并（依赖 FFmpeg）
- Cookies 支持：通过 `cookies.txt` 解决 B 站/抖音等平台的访问限制
- 进度展示：下载状态、百分比和结果路径

## 项目结构

```text
.
├── main.py                          # Streamlit 入口（页面与流程编排）
├── config.py                        # 全局配置（下载目录、FFmpeg、cookies）
├── cookies.example.txt              # Cookie 文件格式示例（复制为 cookies.txt 后填入真实导出）
├── cookies.txt                      # 本地使用：Netscape 格式（勿提交，见 .gitignore）
├── app/
│   └── components/
│       └── input_section.py         # 输入 + 解析 + 元数据显示
├── core/
│   ├── downloader.py                # 下载核心、进度 Hook、错误处理
│   └── utils.py                     # 工具函数（如 sanitize_filename）
├── data/
│   └── downloads/                   # 默认下载目录（兜底）
├── memory-bank/
│   └── project-memory.md            # 阶段记录
└── requirements.txt
```

## 快速开始

1. 创建并激活虚拟环境（可选但推荐）
2. 安装依赖：

```bash
pip install -r requirements.txt
```

3. 启动应用：

```bash
streamlit run main.py
```

## 配置说明

请在 `config.py` 中调整：

- `DEFAULT_DOWNLOAD_DIR`：默认下载目录（支持环境变量覆盖）
- `FFMPEG_PATH`：自动检测系统 FFmpeg
- `COOKIES_FILE`：Cookie 文件路径（默认 `cookies.txt`）

## cookies.txt 使用说明（B站 / 抖音）

- 参考仓库中的 **`cookies.example.txt`** 了解字段格式（示例行无效，需整文件替换为扩展导出内容）
- 需为 **Netscape HTTP Cookie File** 格式
- 推荐使用浏览器扩展 **Get cookies.txt LOCALLY** 导出
- 将导出文件保存为项目根目录 **`cookies.txt`**（已在 `.gitignore` 中忽略，避免误提交）
- 文件不存在时会优雅降级（不传 cookiefile），但相关站点可能解析失败

## 常见问题

- 提示未检测到 FFmpeg：
  - 安装 FFmpeg 并加入系统 `PATH`
- 提示需要 cookies：
  - 更新并重新导出 `cookies.txt`
  - 确认导出时包含目标站点域名（如 `bilibili.com`、`douyin.com`）
