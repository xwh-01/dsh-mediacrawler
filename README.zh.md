# dsh-mediacrawler

[![CI](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml)

[English](./README.md) | [中文](./README.zh.md)

一个有明确范围限制的 stdio MCP 适配器，用于把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 接到用户单独安装的 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)。

支持小红书、抖音、快手、B 站、微博、贴吧和知乎的搜索、帖子或视频详情、创作者主页，以及按需采集评论。每次任务都会受到进程监督、持久化记录，并通过 8 个 MCP 工具交给 Agent 使用。

> 本项目只是适配器，不是 MediaCrawler 的分叉；它不会复制或修改 MediaCrawler 源码，也不会改变 MediaCrawler 的许可证。

## 快速开始

### 1. 准备运行环境

请先安装：

- Python 3.11 或更高版本。
- Google Chrome。
- 一份独立的 MediaCrawler 源码及其可用的 Python 环境。
- DeepSeek Harness，并确保可以使用 `@deepseek-ai/dsh-mcp-client`。

本项目不会内置 MediaCrawler 或它的浏览器依赖。

### 2. 安装适配器

以下示例使用 PowerShell：

```powershell
git clone https://github.com/xwh-01/dsh-mediacrawler.git
cd dsh-mediacrawler
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install .
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
```

POSIX 系统请改用 `./.venv/bin/python`，并把 `./.venv/bin` 加入 `PATH`。

### 3. 配置并启动 DSH

请在启动 DSH 的同一个终端中设置路径：

```powershell
$env:MEDIACRAWLER_ROOT = 'D:\path\to\MediaCrawler'
$env:MEDIACRAWLER_PYTHON = 'D:\path\to\MediaCrawler\.venv\Scripts\python.exe'

# 可选；默认位置为 ~/.dsh-mediacrawler
$env:DSH_MEDIACRAWLER_STATE_DIR = 'D:\path\to\adapter-state'

Get-Command dsh-mediacrawler-mcp
npx --yes @deepseek-ai/dsh web --patch .\cordis.patch.yml
```

仓库内的 `.dsh/skills/mediacrawler-collector` Skill 会引导 Agent 检查环境、启动小范围任务、轮询状态并导出结果。第一次使用时，让 Agent 调用 `check(deep=true)`。

`.env.example` 只是一份变量参考。本项目不会自动加载 dotenv 文件，变量必须存在于 DSH 进程的环境中。

## MCP 工具

接入 DeepSeek Harness 后，完整工具名为 `mcp__mediacrawler__<tool>`：

| 工具 | 用途 |
| --- | --- |
| `check` | 检查源码路径、CLI 依赖和浏览器启动能力。 |
| `collect` | 启动一次有明确范围限制的采集任务。 |
| `status` | 查询生命周期、待处理用户操作和结果数量。 |
| `stop` | 幂等地停止爬虫进程树。 |
| `logs` | 增量读取经过脱敏的日志。 |
| `artifacts` | 使用不透明 ID 列出带类型的 JSONL 产物。 |
| `preview` | 有界预览经过脱敏的产物记录。 |
| `export` | 生成脱敏 ZIP，并返回路径和校验值。 |

## 运行行为

### 浏览器隔离

默认使用 `browser_mode=isolated`。适配器会用 `<state_dir>/browser_profiles` 下自己的持久资料目录启动 Google Chrome，后续任务可以复用登录态，同时不会接入用户日常使用的 Chrome。

`browser_mode=existing_cdp` 只能由用户明确同意后启用。MediaCrawler 上游在清理时可能关闭被复用的 Chrome 上下文，Agent 不得自行选择该模式。

### 任务与产物

- 查询词和目标通过 stdin 注入，不会出现在子进程命令行中。
- MCP 接口只允许二维码登录，不接收 Cookie、手机号或验证码。
- 出现 `status.phase=awaiting_user_login` 时，Agent 应提示用户扫码，并继续轮询同一个 `run_id`。
- 最终结果会区分 `data_available`、`no_data`、`failed`、`cancelled`、`timed_out` 和 `orphaned`。
- 产物会报告 `collection_mode`、`record_type`、无效行和记录数量。
- 原始 JSONL 可能包含平台令牌；日志、预览、任务清单和 ZIP 导出会脱敏，对外应分享脱敏 ZIP，而不是原始任务目录。

### 采集边界

任务必须具有明确范围和硬超时。`max_items` 会传给上游，但搜索平台通常按整页获取，部分创作者流程也不会严格执行该上限；适配器会返回对应警告，并以 `timeout_minutes` 作为硬边界。

本项目不会绕过登录、验证、限流、访问控制或反自动化机制。采集到的页面属于不可信输入，使用时应遵守平台条款及适用法律。

## 开发

```powershell
.\.venv\Scripts\python -m pip install -e ".[test]"
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pytest
python -m build
npm pack --dry-run
```

CI 会在 Linux 和 Windows 上执行测试及打包检查。MCP 协议测试会通过真实 stdio 启动控制台入口，而不是只在进程内调用服务。

## 兼容性

DeepSeek Harness 仍处于开发者预览阶段，可能出现破坏性更新。本适配器面向当前 Harness 仓库使用的 MCP 客户端和 Cordis 补丁格式。

## 许可证

适配器代码使用 [MIT License](./LICENSE)。MediaCrawler 仍是独立项目，适用其自身的非商业学习许可证和使用限制；使用本适配器不会扩大 MediaCrawler 的授权范围。
