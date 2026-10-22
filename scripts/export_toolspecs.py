"""Write each MCP server's tools/list response to infra/gateway/toolspecs/<server>.json.

Agent Registry stores this as the server's tool spec, so gateway policies can refer to
tools and their annotations (readOnlyHint and so on). A unit test checks the files
match the servers; re-run this after changing a tool:
  uv run python scripts/export_toolspecs.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_servers.compensation import server as compensation  # noqa: E402
from mcp_servers.hris import server as hris  # noqa: E402
from mcp_servers.ticketing import server as ticketing  # noqa: E402

SERVERS = {
    "hris": hris.mcp,
    "ticketing": ticketing.mcp,
    "compensation": compensation.mcp,
}
OUT = ROOT / "infra" / "gateway" / "toolspecs"


async def toolspec(server) -> dict:
    async with Client(server) as client:
        tools = await client.list_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
                "annotations": t.annotations.model_dump(
                    by_alias=True, exclude_none=True
                ),
            }
            for t in tools
        ]
    }


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, server in SERVERS.items():
        text = json.dumps(await toolspec(server), indent=1, ensure_ascii=False) + "\n"
        (OUT / f"{name}.json").write_text(text, encoding="utf-8")
        print(f"{name}: {len(text.encode())} bytes (Agent Registry limit: 10 KB)")


if __name__ == "__main__":
    asyncio.run(main())
