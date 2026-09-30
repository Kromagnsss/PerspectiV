from __future__ import annotations

import asyncio

from mcp import Client

from perspectiv.mcp_server import mcp


def test_mcp_tools_are_discoverable() -> None:
    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.list_tools()
            names = {tool.name for tool in result.tools}
            assert {
                "get_profile",
                "list_projects",
                "list_tasks",
                "list_budgets",
                "list_time_entries",
                "create_project_record",
                "update_project",
                "save_timesheet_week",
                "save_planning_week",
                "list_project_risks",
                "create_risk_analysis",
                "create_project_risk",
                "add_risk_reduction_iteration",
                "verify_risk_reduction",
                "decide_risk",
                "preview_deletion",
                "confirm_deletion",
            } <= names
            result = await client.call_tool("get_profile", {})
            assert not result.is_error

    asyncio.run(run())
