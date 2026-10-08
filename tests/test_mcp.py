from __future__ import annotations

import asyncio

from mcp import Client
from sqlalchemy import select

from perspectiv.database import SessionLocal, init_db
from perspectiv.mcp_server import mcp
from perspectiv.models import Project, Task


def find_property_schema(schema: object, property_name: str) -> dict:
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and property_name in properties:
            return properties[property_name]
        for value in schema.values():
            found = find_property_schema(value, property_name)
            if found:
                return found
    elif isinstance(schema, list):
        for value in schema:
            found = find_property_schema(value, property_name)
            if found:
                return found
    return {}


def find_schema_value(schema: object, key: str):
    if isinstance(schema, dict):
        if key in schema:
            return schema[key]
        for value in schema.values():
            found = find_schema_value(value, key)
            if found is not None:
                return found
    elif isinstance(schema, list):
        for value in schema:
            found = find_schema_value(value, key)
            if found is not None:
                return found
    return None


def test_mcp_tools_are_discoverable() -> None:
    init_db()

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


def test_mcp_advertises_and_accepts_task_levels_five_and_six() -> None:
    init_db()
    with SessionLocal() as session:
        project_id = session.scalar(select(Project.id).order_by(Project.id))
    assert project_id is not None

    async def run() -> None:
        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            for tool_name in ("create_project_task", "update_task"):
                level_schema = find_property_schema(tools[tool_name].input_schema, "level")
                assert find_schema_value(level_schema, "minimum") == 1
                assert find_schema_value(level_schema, "maximum") == 6
                assert "6" in str(find_schema_value(level_schema, "description"))

            created = await client.call_tool(
                "create_project_task",
                {
                    "project_id": project_id,
                    "payload": {"title": "Test MCP niveau 6", "level": 6},
                },
            )
            assert not created.is_error

            with SessionLocal() as session:
                task = session.scalar(select(Task).where(Task.title == "Test MCP niveau 6"))
                assert task is not None
                assert task.level == 6
                task_id = task.id

            updated = await client.call_tool(
                "update_task",
                {"task_id": task_id, "payload": {"level": 5}},
            )
            assert not updated.is_error

            with SessionLocal() as session:
                task = session.get(Task, task_id)
                assert task is not None
                assert task.level == 5

    asyncio.run(run())
