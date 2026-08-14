from __future__ import annotations

import sys
from pathlib import Path

from mcp import Client

from dsh_mediacrawler.server import create_server
from dsh_mediacrawler.settings import Settings
from dsh_mediacrawler.supervisor import CrawlerService


async def test_mcp_server_exposes_expected_tools(
    fake_mediacrawler_root, tmp_path
) -> None:
    service = CrawlerService(
        Settings(
            mediacrawler_root=fake_mediacrawler_root,
            state_dir=tmp_path / "state",
            python_executable=Path(sys.executable),
        )
    )
    server = create_server(service)
    async with Client(server) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "check",
            "collect",
            "status",
            "runs",
            "result",
            "stop",
            "logs",
            "artifacts",
            "preview",
            "export",
        }

        result = await client.call_tool("check", {"deep": True})
        assert result.structured_content == {
            "ok": True,
            "ready": True,
            "mediacrawler_root": str(service.settings.mediacrawler_root),
            "state_dir": str(service.settings.state_dir),
            "runner": "configured-python",
            "runner_available": True,
            "issues": [],
            "deep_check": {
                "passed": True,
                "cli_passed": True,
                "exit_code": 0,
                "missing_options": [],
                "output_tail": "",
                "browser_probe": {
                    "passed": True,
                    "checks": [
                        {"browser": "system-chrome", "passed": True},
                    ],
                },
            },
            "supported_platforms": [
                "xhs",
                "dy",
                "ks",
                "bili",
                "wb",
                "tieba",
                "zhihu",
            ],
        }
