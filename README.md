# dsh-mediacrawler

[![CI](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml/badge.svg)](https://github.com/xwh-01/dsh-mediacrawler/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/xwh-01/dsh-mediacrawler)](https://github.com/xwh-01/dsh-mediacrawler/releases/latest)

[English](./README.md) | [中文](./README.zh.md)

An installable profile bundle and bounded stdio MCP adapter that connects [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) to a separately installed [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) checkout.

It supports search, post/video detail, creator feeds, and optional comments on Xiaohongshu, Douyin, Kuaishou, Bilibili, Weibo, Tieba, and Zhihu. Each run is supervised, persisted, and exposed through ten MCP tools.

> This is an adapter, not a MediaCrawler fork. It does not copy or modify MediaCrawler source code, and it does not change MediaCrawler's license.

## Quick start

### 1. Prepare the runtimes

Install the following first:

- Python 3.11 or newer.
- Node.js 22.19+ on the 22.x line, or Node.js 24+, with `pnpm` on `PATH`.
- Google Chrome.
- A separate MediaCrawler checkout with its own working Python environment.
- DeepSeek Harness. The commands below pin the tested `0.1.0-rc.6` release through `npx`.

MediaCrawler and its browser dependencies are intentionally not vendored here.

### 2. Install the Python MCP runtime

Keep the adapter in its own virtual environment. In PowerShell:

```powershell
$adapterVenv = Join-Path $HOME '.dsh\runtimes\dsh-mediacrawler'
python -m venv $adapterVenv
$env:DSH_MEDIACRAWLER_PYTHON = Join-Path $adapterVenv 'Scripts\python.exe'
& $env:DSH_MEDIACRAWLER_PYTHON -m pip install --upgrade pip
& $env:DSH_MEDIACRAWLER_PYTHON -m pip install "dsh-mediacrawler @ git+https://github.com/xwh-01/dsh-mediacrawler.git@v0.2.0"
```

On POSIX systems:

```sh
python3 -m venv "$HOME/.dsh/runtimes/dsh-mediacrawler"
export DSH_MEDIACRAWLER_PYTHON="$HOME/.dsh/runtimes/dsh-mediacrawler/bin/python"
"$DSH_MEDIACRAWLER_PYTHON" -m pip install --upgrade pip
"$DSH_MEDIACRAWLER_PYTHON" -m pip install "dsh-mediacrawler @ git+https://github.com/xwh-01/dsh-mediacrawler.git@v0.2.0"
```

### 3. Install the DSH profile bundle

DSH delegates profile package management to `pnpm`. Install it once if needed, then add the pinned bundle release:

```powershell
npm install --global pnpm@11
npx --yes @deepseek-ai/dsh@0.1.0-rc.6 plugin --profile web add "github:xwh-01/dsh-mediacrawler#v0.2.0"
npx --yes @deepseek-ai/dsh@0.1.0-rc.6 --profile web --dump-config
```

The config dump should contain a `# == dsh-mediacrawler` layer. The bundle mounts both the MCP client and its packaged `mediacrawler-collector` Skill; no repository checkout needs to be the current working directory.

### 4. Configure and start DSH

Export the paths in the same shell that starts DSH. Also restore `DSH_MEDIACRAWLER_PYTHON` from step 2 when opening a new shell:

```powershell
$env:MEDIACRAWLER_ROOT = 'D:\path\to\MediaCrawler'
$env:MEDIACRAWLER_PYTHON = 'D:\path\to\MediaCrawler\.venv\Scripts\python.exe'

# Optional; defaults to ~/.dsh-mediacrawler
$env:DSH_MEDIACRAWLER_STATE_DIR = 'D:\path\to\adapter-state'

npx --yes @deepseek-ai/dsh@0.1.0-rc.6 --profile web
```

The packaged Skill then guides the agent through checking the runtime, starting a small collection, polling status, and exporting results. On first use, ask the agent to call `check(deep=true)`.

`.env.example` is a reference only. The adapter does not load dotenv files, and current DSH releases treat `DSH_*` variables as launch settings; export these values in the DSH process environment.

To uninstall the profile bundle:

```powershell
npx --yes @deepseek-ai/dsh@0.1.0-rc.6 plugin --profile web remove dsh-mediacrawler
```

## MCP tools

DeepSeek Harness exposes these as `mcp__mediacrawler__<tool>`:

| Tool | Purpose |
| --- | --- |
| `check` | Check source paths, CLI dependencies, and browser launch readiness. |
| `collect` | Start one bounded collection run. |
| `status` | Read lifecycle state, required user attention, and result counts. |
| `runs` | Recover recent durable runs and their IDs after a restart or context loss. |
| `result` | Read status, artifacts, and a bounded redacted sample in one call. |
| `stop` | Idempotently stop the crawler process tree. |
| `logs` | Read incremental, redacted run logs. |
| `artifacts` | List typed JSONL artifacts using opaque IDs. |
| `preview` | Read a bounded, redacted artifact preview. |
| `export` | Create a sanitized ZIP and return its path and checksum. |

## Runtime behavior

### When this is useful

Use the Harness web-search providers for quick facts and already-indexed pages. Use this adapter when the task needs logged-in platform records, creator feeds, comments or nested replies, or a durable reproducible export. It complements search providers; it is not a replacement for them.

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
node --test tests-node/*.test.js
python -m build
npm pack --dry-run
```

CI runs the Python tests on Linux and Windows, verifies the packaged Skill provider, installs the bundle into a clean DSH profile, and starts its real MCP stdio entry point.

## Compatibility

DeepSeek Harness is a developer preview and may make compatibility-breaking changes. Release `v0.2.0` is tested with:

- `@deepseek-ai/dsh` `0.1.0-rc.6`.
- Node.js 22.19+ on the 22.x line, and Node.js 24+.
- Python 3.11 and 3.13.
- The MediaCrawler command contract at upstream commit [`5665a27`](https://github.com/NanmiCoder/MediaCrawler/commit/5665a271ef15e0ec82b1f48a951b66760e054db9).

Run `check(deep=true)` after changing either DSH or MediaCrawler; it validates the local checkout before collection starts.

## License

Adapter code is released under the [MIT License](./LICENSE). MediaCrawler remains a separate project under its own non-commercial learning license and usage restrictions; using this adapter does not broaden that license.
