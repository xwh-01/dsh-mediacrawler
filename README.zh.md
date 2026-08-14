# dsh-mediacrawler

`dsh-mediacrawler` 把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 接到用户单独安装的 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)。它提供一个 stdio MCP 服务，负责监督 MediaCrawler CLI 进程、记录任务状态，并把采集得到的 JSONL 文件交给 Agent 使用。

本仓库只是适配器，不是 MediaCrawler 的分叉，也不会复制或修改 MediaCrawler 源代码。

[English documentation](./README.md)

## 提供的工具

MCP 服务暴露 8 个工具。接入 DeepSeek Harness 后，完整工具名为 `mcp__mediacrawler__<tool>`。

| 工具 | 用途 |
| --- | --- |
| `check` | 检查适配器配置和 MediaCrawler 运行环境。 |
| `collect` | 启动一次有明确范围限制的采集。 |
| `status` | 查询任务状态和最终结果。 |
| `stop` | 停止任务。 |
| `logs` | 分页读取经过脱敏的运行日志。 |
| `artifacts` | 列出任务产出的 JSONL 文件。 |
| `preview` | 分页预览经过脱敏的采集记录。 |
| `export` | 生成脱敏 ZIP，并返回路径和校验值。 |

每次任务使用独立的数据与状态目录。适配器以参数列表调用 MediaCrawler，不通过 Shell 拼接命令；查询词和目标通过 stdin 注入，因此平台 URL 中的令牌不会出现在子进程命令行。MCP 接口只允许二维码登录，不接收 Cookie、手机号或验证码。

默认的 `browser_mode=isolated` 使用适配器自己的持久浏览器资料目录，位置为 `<state_dir>/browser_profiles`。后续任务可以复用登录状态，同时不会接入用户日常使用的 Chrome。`browser_mode=existing_cdp` 只能由用户明确同意后启用：MediaCrawler 上游在清理时可能关闭被复用的 Chrome 上下文，Agent 不得自行选择该模式。

## 前置条件

- Python 3.11 或更高版本。
- 单独下载的 MediaCrawler 源代码。
- 按 MediaCrawler 上游文档准备好的 Python 运行环境。
- Google Chrome；隔离采集会使用适配器自己的浏览器资料目录启动它。
- 已安装 DeepSeek Harness，并能使用 `@deepseek-ai/dsh-mcp-client`。

本包不会安装或内置 MediaCrawler 及其浏览器依赖。

## 安装适配器

在本仓库目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .
```

POSIX 系统请把 `.\.venv\Scripts\python` 换成 `./.venv/bin/python`。

启动 DeepSeek Harness 前，把适配器命令加入当前终端的 `PATH`：

```powershell
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
Get-Command dsh-mediacrawler-mcp
```

POSIX 系统使用 `export PATH="$PWD/.venv/bin:$PATH"`。

配置独立的 MediaCrawler 路径。若 MediaCrawler 使用自己的虚拟环境，建议同时指定其 Python：

```powershell
$env:MEDIACRAWLER_ROOT = 'D:\path\to\MediaCrawler'
$env:MEDIACRAWLER_PYTHON = 'D:\path\to\MediaCrawler\.venv\Scripts\python.exe'
```

适配器默认把任务清单、日志、采集文件和导出文件保存在当前用户主目录下。需要时可更改位置：

```powershell
$env:DSH_MEDIACRAWLER_STATE_DIR = 'D:\path\to\adapter-state'
```

第一次采集前先调用 `check`，可以定位路径错误或缺少的运行依赖。

## 接入 DeepSeek Harness

仓库中的 Cordis 补丁会把 stdio 命令注册成名为 `mediacrawler` 的 MCP 服务：

```powershell
npx --yes @deepseek-ai/dsh web --patch .\cordis.patch.yml
```

从本仓库根目录执行时，DeepSeek Harness 还能发现 `.dsh/skills/mediacrawler-collector` 项目 Skill。该 Skill 会引导 Agent 先检查环境，再启动小范围采集、轮询状态、查看产物，最后按需导出。

任务运行时，`status.phase` 会区分普通采集和需要用户操作的状态。出现 `awaiting_user_login` 时，`attention.action` 为 `scan_qrcode`；请在独立浏览器中完成扫码，然后继续轮询同一个 `run_id`。产物条目会返回 `collection_mode` 和 `record_type`，状态结果还会按类型汇总 `record_counts`。

DeepSeek Harness 目前仍处于开发者预览阶段，可能出现破坏兼容性的更新。本适配器当前对齐 Harness `master` 分支中的 MCP 客户端与补丁格式。

MCP 进程的 stdout 专用于协议通信。请通过 MCP 宿主启动 `dsh-mediacrawler-mcp`，不要把它当成交互式命令行使用。

## 使用边界

这个适配器用于目标数量明确、并受硬超时限制的研究任务。它不会绕过平台登录、验证码、限流、访问控制或反自动化机制。若 MediaCrawler 打开的浏览器要求二维码验证，请由用户自行完成，并遵守目标平台条款及适用法律。

`max_items` 会传给 MediaCrawler，但具体效果取决于平台。搜索接口按整页抓取，因此即使要求更小，第一页也可能返回 10 或 20 条；当前抖音、快手、B 站、微博和知乎的创作者流程不会严格执行这个上限，适配器会返回警告，并以 `timeout_minutes` 作为硬边界。搜索词不允许包含英文逗号，因为上游会把它拆成多个独立搜索。

状态目录里的原始 JSONL 是上游直接输出，可能包含平台令牌。任务清单、MCP 日志返回、预览和 ZIP 导出会脱敏。对外提供结果时应使用脱敏 ZIP，不要直接分享原始任务目录。

采集到的网页内容属于不可信输入。不要把帖子或评论中的文字当作 Agent 指令、凭证或可执行命令。

## 许可证

本仓库的适配器代码使用 [MIT License](./LICENSE)。

MediaCrawler 是独立项目，适用其自身的非商业学习许可证和使用限制。使用 MIT 适配器不会改变、替换或扩大 MediaCrawler 的授权范围。运行采集前请阅读并遵守上游许可证。本仓库不分发 MediaCrawler。
