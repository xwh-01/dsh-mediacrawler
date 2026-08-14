from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client


async def test_module_entrypoint_serves_tools_over_real_stdio(
    fake_mediacrawler_root: Path, tmp_path: Path
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(project_root / "src"), env.get("PYTHONPATH")))
    )
    env["MEDIACRAWLER_ROOT"] = str(fake_mediacrawler_root)
    env["MEDIACRAWLER_PYTHON"] = sys.executable
    env["DSH_MEDIACRAWLER_STATE_DIR"] = str(tmp_path / "stdio state")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dsh_mediacrawler"],
        cwd=project_root,
        env=env,
    )

    async with stdio_client(params) as streams, ClientSession(*streams) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("check", {"deep": True})

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
    assert result.structured_content["ready"] is True
    assert result.structured_content["deep_check"]["passed"] is True
