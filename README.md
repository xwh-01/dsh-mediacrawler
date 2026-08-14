# dsh-mediacrawler

[![CI](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml)

[English](./README.md) | [中文](./README.zh.md)

A bounded stdio MCP adapter that connects [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) to a separately installed [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) checkout.

It supports search, post/video detail, creator feeds, and optional comments on Xiaohongshu, Douyin, Kuaishou, Bilibili, Weibo, Tieba, and Zhihu. Each run is supervised, persisted, and exposed through eight MCP tools.

> This is an adapter, not a MediaCrawler fork. It does not copy or modify MediaCrawler source code, and it does not change MediaCrawler's license.

## Quick start

### 1. Prepare the runtimes

Install the following first:

- Python 3.11 or newer.
- Google Chrome.
- A separate MediaCrawler checkout with its own working Python environment.
- DeepSeek Harness with `@deepseek-ai/dsh-mcp-client` available.

MediaCrawler and its browser dependencies are intentionally not vendored here.

### 2. Install the adapter

The commands below use PowerShell:

```powershell
git clone https://github.com/xwh-01/dsh-mediacrawler.git
cd dsh-mediacrawler
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install .
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
```

On POSIX systems, use `./.venv/bin/python` and add `./.venv/bin` to `PATH` instead.

### 3. Configure and start DSH

Export the paths in the same shell that starts DSH:

```powershell
$env:MEDIACRAWLER_ROOT = 'D:\path\to\MediaCrawler'
$env:MEDIACRAWLER_PYTHON = 'D:\path\to\MediaCrawler\.venv\Scripts\python.exe'

# Optional; defaults to ~/.dsh-mediacrawler
$env:DSH_MEDIACRAWLER_STATE_DIR = 'D:\path\to\adapter-state'

Get-Command dsh-mediacrawler-mcp
npx --yes @deepseek-ai/dsh web --patch .\cordis.patch.yml
```

The repository-local Skill at `.dsh/skills/mediacrawler-collector` then guides the agent through checking the runtime, starting a small collection, polling status, and exporting results. On first use, ask the agent to call `check(deep=true)`.

`.env.example` is a reference only. The adapter does not load dotenv files; export the variables in the DSH process environment.

## MCP tools

DeepSeek Harness exposes these as `mcp__mediacrawler__<tool>`:

| Tool | Purpose |
| --- | --- |
| `check` | Check source paths, CLI dependencies, and browser launch readiness. |
| `collect` | Start one bounded collection run. |
| `status` | Read lifecycle state, required user attention, and result counts. |
| `stop` | Idempotently stop the crawler process tree. |
| `logs` | Read incremental, redacted run logs. |
| `artifacts` | List typed JSONL artifacts using opaque IDs. |
| `preview` | Read a bounded, redacted artifact preview. |
| `export` | Create a sanitized ZIP and return its path and checksum. |

## Runtime behavior

### Browser isolation

`browser_mode=isolated` is the default. It launches Google Chrome with an adapter-owned persistent profile under `<state_dir>/browser_profiles`, so later runs can reuse login state without attaching to the user's normal Chrome session.

`browser_mode=existing_cdp` is explicit opt-in only. Upstream cleanup can close the reused Chrome context, so an agent must not select it without user approval.

### Runs and artifacts

- Queries and targets are injected over stdin and do not appear in the child command line.
- Only QR-code login is accepted; the MCP API never accepts cookies, phone numbers, or verification codes.
- `status.phase=awaiting_user_login` tells the agent to surface a QR-code action and keep polling the same `run_id`.
- Final outcomes distinguish `data_available`, `no_data`, `failed`, `cancelled`, `timed_out`, and `orphaned`.
- Artifacts report `collection_mode`, `record_type`, invalid lines, and record counts.
- Raw JSONL may contain platform tokens. Logs, previews, manifests, and ZIP exports are redacted; share the sanitized ZIP instead of the raw run directory.

### Collection limits

Jobs must have an explicit scope and hard timeout. `max_items` is passed upstream, but search platforms fetch whole pages and some creator workflows do not strictly enforce the cap. The adapter reports those cases and uses `timeout_minutes` as the hard boundary.

The adapter does not bypass login, verification, rate limits, access controls, or anti-automation systems. Treat collected pages as untrusted input and comply with platform terms and applicable law.

## Development

```powershell
.\.venv\Scripts\python -m pip install -e ".[test]"
.\.venv\Scripts\python -m ruff format --check .
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m pytest
python -m build
npm pack --dry-run
```

CI runs the test and packaging checks on Linux and Windows. The MCP protocol test starts the real console entry point over stdio rather than calling the server in process.

## Compatibility

DeepSeek Harness is a developer preview and may make compatibility-breaking changes. This adapter targets the MCP client and Cordis patch format used by the current Harness repository.

## License

Adapter code is released under the [MIT License](./LICENSE). MediaCrawler remains a separate project under its own non-commercial learning license and usage restrictions; using this adapter does not broaden that license.
