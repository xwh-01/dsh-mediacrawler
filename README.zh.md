# dsh-mediacrawler

[![CI](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xwh-01/dsh-mediacrawler)](https://github.com/xwh-01/dsh-mediacrawler/releases/latest)

[English](./README.md) | [中文](./README.zh.md)

一个可安装的 profile bundle 和有明确范围限制的 stdio MCP 适配器，用于把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 接到用户单独安装的 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)。

支持小红书、抖音、快手、B 站、微博、贴吧和知乎的搜索、帖子或视频详情、创作者主页，以及按需采集评论。每次任务都会受到进程监督、持久化记录，并通过 10 个 MCP 工具交给 Agent 使用。

> 本项目只是适配器，不是 MediaCrawler 的分叉；它不会复制或修改 MediaCrawler 源码，也不会改变 MediaCrawler 的许可证。

## 快速开始

### 1. 准备运行环境

请先安装：

- Python 3.11 或更高版本。
- Node.js 22.x 系列中的 22.19+，或 Node.js 24+，并确保 `pnpm` 位于 `PATH`。
- Google Chrome。
- 一份独立的 MediaCrawler 源码及其可用的 Python 环境。
- DeepSeek Harness。下方命令通过 `npx` 固定使用已测试的 `0.1.0-rc.6`。

本项目不会内置 MediaCrawler 或它的浏览器依赖。

### 2. 安装 Python MCP 运行时

请为适配器使用独立虚拟环境。PowerShell：

```powershell
$adapterVenv = Join-Path $HOME '.dsh\runtimes\dsh-mediacrawler'
python -m venv $adapterVenv
$env:DSH_MEDIACRAWLER_PYTHON = Join-Path $adapterVenv 'Scripts\python.exe'
& $env:DSH_MEDIACRAWLER_PYTHON -m pip install --upgrade pip
& $env:DSH_MEDIACRAWLER_PYTHON -m pip install "dsh-mediacrawler @ git+https://github.com/xwh-01/dsh-mediacrawler.git@v0.2.0"
```

POSIX 系统：

```sh
python3 -m venv "$HOME/.dsh/runtimes/dsh-mediacrawler"
export DSH_MEDIACRAWLER_PYTHON="$HOME/.dsh/runtimes/dsh-mediacrawler/bin/python"
"$DSH_MEDIACRAWLER_PYTHON" -m pip install --upgrade pip
"$DSH_MEDIACRAWLER_PYTHON" -m pip install "dsh-mediacrawler @ git+https://github.com/xwh-01/dsh-mediacrawler.git@v0.2.0"
```

### 3. 安装 DSH profile bundle

DSH 会把 profile 包管理交给 `pnpm`。如有需要请先安装一次，然后加入固定版本的 bundle：

```powershell
npm install --global pnpm@11
npx --yes @deepseek-ai/dsh@0.1.0-rc.6 plugin --profile web add "github:xwh-01/dsh-mediacrawler#v0.2.0"
npx --yes @deepseek-ai/dsh@0.1.0-rc.6 --profile web --dump-config
```

配置输出中应出现 `# == dsh-mediacrawler` 层。bundle 会同时挂载 MCP 客户端和随包提供的 `mediacrawler-collector` Skill，不要求从本仓库目录启动 DSH。

### 4. 配置并启动 DSH

请在启动 DSH 的同一个终端中设置路径。新开终端时，也要恢复第 2 步中的 `DSH_MEDIACRAWLER_PYTHON`：

```powershell
$env:MEDIACRAWLER_ROOT = 'D:\path\to\MediaCrawler'
$env:MEDIACRAWLER_PYTHON = 'D:\path\to\MediaCrawler\.venv\Scripts\python.exe'

# 可选；默认位置为 ~/.dsh-mediacrawler
$env:DSH_MEDIACRAWLER_STATE_DIR = 'D:\path\to\adapter-state'

npx --yes @deepseek-ai/dsh@0.1.0-rc.6 --profile web
```

随包提供的 Skill 会引导 Agent 检查环境、启动小范围任务、轮询状态并导出结果。第一次使用时，让 Agent 调用 `check(deep=true)`。

`.env.example` 只是一份变量参考。本项目不会自动加载 dotenv 文件，且当前 DSH 会把 `DSH_*` 变量视为启动配置；这些变量必须导出到 DSH 进程环境中。

卸载 profile bundle：

```powershell
npx --yes @deepseek-ai/dsh@0.1.0-rc.6 plugin --profile web remove dsh-mediacrawler
```

## MCP 工具

接入 DeepSeek Harness 后，完整工具名为 `mcp__mediacrawler__<tool>`：

| 工具 | 用途 |
| --- | --- |
| `check` | 检查源码路径、CLI 依赖和浏览器启动能力。 |
| `collect` | 启动一次有明确范围限制的采集任务。 |
| `status` | 查询生命周期、待处理用户操作和结果数量。 |
| `runs` | 在重启或上下文丢失后找回近期持久化任务及其 ID。 |
| `result` | 一次读取任务状态、产物列表和有界脱敏样本。 |
| `stop` | 幂等地停止爬虫进程树。 |
| `logs` | 增量读取经过脱敏的日志。 |
| `artifacts` | 使用不透明 ID 列出带类型的 JSONL 产物。 |
| `preview` | 有界预览经过脱敏的产物记录。 |
| `export` | 生成脱敏 ZIP，并返回路径和校验值。 |

## 运行行为

### 什么时候值得用

查询即时事实或已经被索引的网页时，应优先使用 Harness 的网页搜索 provider。需要登录后的平台原始记录、创作者内容流、评论或楼中楼，或者需要可复现的持久化导出时，再使用本适配器。它补充网页搜索，而不是替代网页搜索。

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
node --test tests-node/*.test.js
python -m build
npm pack --dry-run
```

CI 会在 Linux 和 Windows 上执行 Python 测试、验证随包 Skill provider、把 bundle 安装进全新的 DSH profile，并启动真实的 MCP stdio 入口。

## 兼容性

DeepSeek Harness 仍处于开发者预览阶段，可能出现破坏性更新。`v0.2.0` 已测试：

- `@deepseek-ai/dsh` `0.1.0-rc.6`。
- Node.js 22.x 系列中的 22.19+，以及 Node.js 24+。
- Python 3.11 和 3.13。
- MediaCrawler 上游提交 [`5665a27`](https://github.com/NanmiCoder/MediaCrawler/commit/5665a271ef15e0ec82b1f48a951b66760e054db9) 对应的命令接口。

升级 DSH 或 MediaCrawler 后请运行 `check(deep=true)`；它会在采集前验证本地环境。

## 许可证

适配器代码使用 [MIT License](./LICENSE)。MediaCrawler 仍是独立项目，适用其自身的非商业学习许可证和使用限制；使用本适配器不会扩大 MediaCrawler 的授权范围。
