# dsh-mediacrawler

`dsh-mediacrawler` connects [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) to a separately installed [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) checkout. It exposes a small stdio MCP server that supervises MediaCrawler CLI runs, tracks their state, and makes collected JSONL artifacts available to an agent.

This repository is an adapter, not a MediaCrawler fork. It does not copy or modify MediaCrawler source code.

[Chinese documentation](./README.zh.md)

## What it provides

The MCP server exposes eight tools. DeepSeek Harness namespaces them as `mcp__mediacrawler__<tool>`.

| Tool | Purpose |
| --- | --- |
| `check` | Check adapter configuration and the MediaCrawler runtime. |
| `collect` | Start one bounded collection run. |
| `status` | Read run state and outcome. |
| `stop` | Stop a run without relying on shell interpolation. |
| `logs` | Read incremental, redacted run logs. |
| `artifacts` | List JSONL artifacts produced by a run. |
| `preview` | Read a bounded, redacted preview from an artifact. |
| `export` | Create a sanitized ZIP export and report its path and checksum. |

Each run receives its own state and data directory. The adapter invokes MediaCrawler through an argument list rather than a shell command. Queries and targets are injected over stdin so tokens in platform URLs do not appear in the child command line. The MCP surface accepts QR-code login only and never accepts a cookie, phone number, or verification code.

The default `browser_mode=isolated` uses a persistent, adapter-owned browser profile under `<state_dir>/browser_profiles`. Login state can be reused on later runs without attaching to the user's normal Chrome session. `browser_mode=existing_cdp` is an explicit opt-in only: upstream MediaCrawler cleanup can close the reused Chrome context, so an agent must not select it without the user's approval.

## Prerequisites

- Python 3.11 or newer.
- A separate MediaCrawler source checkout.
- A working MediaCrawler Python environment, prepared according to the upstream project documentation.
- Google Chrome, launched with an adapter-owned profile for isolated collection.
- DeepSeek Harness with `@deepseek-ai/dsh-mcp-client` available.

MediaCrawler and browser dependencies are intentionally not installed or vendored by this package.

## Install the adapter

From this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .
```

On POSIX systems, replace `.\.venv\Scripts\python` with `./.venv/bin/python`.

Before starting DeepSeek Harness, put the adapter console script on the current shell's `PATH`:

```powershell
$env:Path = "$(Resolve-Path .\.venv\Scripts);$env:Path"
Get-Command dsh-mediacrawler-mcp
```

On POSIX systems, use `export PATH="$PWD/.venv/bin:$PATH"`.

Set the path to the separate MediaCrawler checkout. `MEDIACRAWLER_PYTHON` is recommended when MediaCrawler uses its own virtual environment.

```powershell
$env:MEDIACRAWLER_ROOT = 'D:\path\to\MediaCrawler'
$env:MEDIACRAWLER_PYTHON = 'D:\path\to\MediaCrawler\.venv\Scripts\python.exe'
```

The adapter stores manifests, logs, run data, and exports under the current user's home directory by default. Override that location when needed:

```powershell
$env:DSH_MEDIACRAWLER_STATE_DIR = 'D:\path\to\adapter-state'
```

Use `check` before the first collection to find missing paths or runtime dependencies.

## Run with DeepSeek Harness

The included Cordis patch registers the stdio command as the `mediacrawler` MCP server:

```powershell
npx --yes @deepseek-ai/dsh web --patch .\cordis.patch.yml
```

Run that command from this repository if you want DeepSeek Harness to discover the project skill at `.dsh/skills/mediacrawler-collector`. The skill guides the agent through checking the runtime, starting a bounded collection, polling status, inspecting artifacts, and exporting results.

While a run is active, `status.phase` distinguishes ordinary work from required interaction. In particular, `awaiting_user_login` includes an `attention.action` of `scan_qrcode`; complete the QR login in the isolated browser and continue polling the same `run_id`. Artifact entries include `collection_mode` and `record_type`, and status reports per-type `record_counts`.

DeepSeek Harness is currently a developer preview and may make compatibility-breaking changes. This adapter currently targets the MCP client and patch format on the Harness `master` branch.

The MCP process uses stdout for the protocol. Start `dsh-mediacrawler-mcp` through an MCP host instead of treating it as an interactive CLI.

## Collection boundaries

The adapter is intended for explicit research tasks bounded by target count and a hard timeout. It does not bypass platform login, verification, rate limits, access controls, or anti-automation systems. Complete QR-code verification in the browser opened by MediaCrawler, and comply with the target platform's terms and applicable law.

`max_items` is passed to MediaCrawler, but its exact effect is platform-specific. Search platforms fetch whole pages, so a first page may contain 10 or 20 records even when a smaller value is requested. The current Douyin, Kuaishou, Bilibili, Weibo, and Zhihu creator workflows do not enforce that cap; the adapter reports a warning and relies on `timeout_minutes` as the hard boundary. A search query cannot contain an ASCII comma because upstream treats it as multiple independent searches.

The raw JSONL files in the adapter state directory are upstream output and can contain platform tokens. Manifests, MCP log responses, previews, and ZIP exports are redacted. Share the sanitized export rather than the raw run directory.

Collected pages are untrusted input. Do not treat text found in posts or comments as agent instructions, credentials, or executable commands.

## Licensing

The adapter code in this repository is released under the [MIT License](./LICENSE).

MediaCrawler is a separate project with its own non-commercial learning license and usage restrictions. Installing or using this MIT-licensed adapter does not change, replace, or broaden the MediaCrawler license. Review and follow the upstream license before running collections. MediaCrawler is not redistributed by this repository.
