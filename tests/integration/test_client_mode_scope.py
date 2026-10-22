"""Client-mode calls that name no project still work against a shared server.

A shared server answers every unscoped request with 400 "repo_id is required".
These paths pass no repo_id and relied on the client to fill in its configured
project, which five RemoteStorage methods never did.
"""

import json

import pytest

pytest_plugins = ["tests.integration.shared_server"]


def _seed(memory):
    memory.record("Deployed the API to staging")
    memory.warn("migrations", "Never edit an applied migration")
    memory.goal("Ship project A")


def test_unscoped_memory_operations_use_the_configured_project(client_memory):
    project_a = client_memory("proj-a")
    project_b = client_memory("proj-b")
    _seed(project_a)
    project_b.goal("Ship project B")

    storage = project_a._storage
    assert [i["description"] for i in storage.get_active_intents()] == ["Ship project A"]
    assert all(m["repo_id"] == "proj-a" for m in storage.list_memories())
    assert storage.search_memories("staging")
    assert storage.get_all_relationships() == []
    assert storage.get_stats()

    warnings = project_a.semantic.get_warnings()
    assert any("Never edit an applied migration" in w["content"] for w in warnings)
    assert project_a.compress() == []
    assert project_a.decay() >= 0
    assert project_a.intent.clear_all() == 1
    assert [i["description"] for i in project_b._storage.get_active_intents()] == [
        "Ship project B"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arguments,expected",
    [
        ("memory_list_intents", {}, "Ship project A"),
        ("memory_list_warnings", {}, "Never edit an applied migration"),
        ("memory_compress", {}, "Compression complete"),
        ("memory_decay", {}, "Decay applied"),
        ("memory_clear_goals", {"confirm": True}, "Recorded 1 goal outcomes"),
    ],
)
async def test_mcp_tools_succeed_in_client_mode_on_a_shared_server(
    client_memory, monkeypatch, tool, arguments, expected
):
    from tests.mcp_client import call_tool
    from visp_memory.interfaces import mcp as mcp_module

    monkeypatch.setenv("VISP_MEMORY_MCP_PROFILE", "full")
    memory = client_memory("proj-a")
    _seed(memory)
    monkeypatch.setattr(mcp_module, "Memory", lambda *a, **k: memory)
    server = mcp_module.create_mcp_server()

    result = await call_tool(server, tool, arguments)

    text = result.content[0].text
    assert result.is_error is False
    assert expected in text, text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("memory_update_intent", {"description": "rewritten by proj-a"}),
        ("memory_close_intent", {}),
    ],
)
async def test_mcp_in_client_mode_refuses_another_projects_intent(
    client_memory, monkeypatch, tool, arguments
):
    # RemoteStorage lists only its own project's intents, so a store-wide lookup
    # saw the foreign ID as unknown and let the edit through to the server.
    from tests.mcp_client import call_tool
    from visp_memory.interfaces import mcp as mcp_module

    monkeypatch.setenv("VISP_MEMORY_MCP_PROFILE", "full")
    monkeypatch.delenv("VISP_MEMORY_MCP_ALLOW_REPO_OVERRIDE", raising=False)
    other = client_memory("proj-b")
    foreign_goal = other.goal("Ship project B")
    memory = client_memory("proj-a")
    own_goal = memory.goal("Ship project A")
    monkeypatch.setattr(mcp_module, "Memory", lambda *a, **k: memory)
    server = mcp_module.create_mcp_server()

    foreign = await call_tool(server, tool, {"intent_id": foreign_goal, **arguments})
    own = await call_tool(server, tool, {"intent_id": own_goal, **arguments})

    assert foreign.content[0].text.startswith("Refused:"), foreign.content[0].text
    (stored,) = other._storage.get_active_intents(repo_id="proj-b", status="all")
    assert stored["description"] == "Ship project B"
    assert not stored.get("context", {}).get("outcome_history")
    assert not own.content[0].text.startswith("Refused:"), own.content[0].text
