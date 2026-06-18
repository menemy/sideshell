"""Unit tests for VibeSideshellServer with mock backend.

Tests the MCP server routing, execute logic, return_focus behavior,
error handling, and tool definitions.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from sideshell_mcp.backends.base import ControlKey, SplitDirection, TerminalBackend
from sideshell_mcp.server import VibeSideshellServer


class MockBackend(TerminalBackend):
    """Minimal mock backend for testing server logic."""

    def __init__(self):
        self._connected = False

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_available(self) -> bool:
        return True

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def ensure_connection(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_session(self, session_id=None):
        return None

    async def list_sessions(self) -> str:
        return "Total: 2 panes\n  pane1\n  pane2"

    async def get_terminal_state(self, session_id=None) -> str:
        if session_id:
            return json.dumps({"session_id": session_id, "job": "zsh"})
        return json.dumps({"total_panes": 2})

    async def is_ai_session(self, session_id: str) -> bool:
        return session_id == "ai-session"

    async def get_current_active_session_id(self) -> str | None:
        return "active-pane"

    async def execute_command(self, command, session_id=None, wait=False, timeout=30, watch_for="prompt") -> str:
        if session_id == "ai-session":
            return "Cannot execute in AI pane."
        if wait:
            return f"Completed: {command}"
        return f"Sent: {command}"

    async def send_text(self, text, session_id=None) -> str:
        return f"Pasted {len(text)} characters"

    async def send_control(self, key, session_id=None) -> str:
        return f"Sent Ctrl+{key.value.upper()}"

    async def read_terminal(self, lines=20, session_id=None) -> str:
        return f"Last {lines} lines:\n$ echo hello\nhello\n$\n\nAt prompt: True"

    async def clear_terminal(self, session_id=None) -> str:
        return "Terminal cleared"

    async def split_pane(self, direction, session_id=None) -> str:
        d = "horizontally" if direction == SplitDirection.HORIZONTAL else "vertically"
        return f"Split {d}. New session: %42"

    async def create_window(self, profile=None, command=None) -> str:
        return "New session created with pane_id: %10"

    async def create_tab(self, profile=None, command=None) -> str:
        return "New window created with pane_id: %11"

    async def create_session(self, profile=None) -> str:
        return "Split horizontally. New session: %12"

    async def focus_session(self, session_id) -> str:
        return f"Focused pane {session_id}"

    async def close_session(self, session_id=None, force=False) -> str:
        return f"Closed pane {session_id}"


@pytest.fixture
def backend():
    return MockBackend()


@pytest.fixture
def server(backend):
    return VibeSideshellServer(backend)


# =============================================================================
# Tool Definitions
# =============================================================================


class TestToolDefinitions:
    def test_all_tools_defined(self, server):
        tools = server._get_tool_definitions()
        names = [t.name for t in tools]
        expected = [
            "execute",
            "read",
            "control-char",
            "list",
            "split",
            "new-window",
            "new-tab",
            "focus",
            "new-session",
            "clear",
            "paste",
            "set-appearance",
            "get-terminal-state",
            "show-alert",
            "set-color-preset",
            "list-color-presets",
            "close-session",
        ]
        for name in expected:
            assert name in names, f"Missing tool: {name}"

    def test_tool_count(self, server):
        tools = server._get_tool_definitions()
        assert len(tools) == 17

    def test_execute_tool_has_wait_schema(self, server):
        tools = server._get_tool_definitions()
        execute = next(t for t in tools if t.name == "execute")
        props = execute.inputSchema["properties"]
        assert "wait" in props
        assert "timeout" in props
        assert "watch_for" in props
        assert "targets" in props
        assert "return_focus" in props

    def test_control_char_enums_match(self, server):
        tools = server._get_tool_definitions()
        ctrl = next(t for t in tools if t.name == "control-char")
        enum_values = ctrl.inputSchema["properties"]["key"]["enum"]
        expected = [k.value for k in ControlKey]
        assert enum_values == expected

    def test_split_direction_enums(self, server):
        tools = server._get_tool_definitions()
        split = next(t for t in tools if t.name == "split")
        enum_values = split.inputSchema["properties"]["direction"]["enum"]
        assert "h" in enum_values
        assert "v" in enum_values

    def test_backend_name_in_descriptions(self, server):
        tools = server._get_tool_definitions()
        execute = next(t for t in tools if t.name == "execute")
        assert "mock" in execute.description

        list_tool = next(t for t in tools if t.name == "list")
        assert "mock" in list_tool.description


# =============================================================================
# Tool Routing
# =============================================================================


class TestToolRouting:
    @pytest.mark.asyncio
    async def test_route_execute(self, server):
        result = await server._route_tool_call("execute", {"command": "ls"})
        assert "Sent: ls" in result

    @pytest.mark.asyncio
    async def test_route_read(self, server):
        result = await server._route_tool_call("read", {"lines": 10})
        assert "Last 10 lines" in result

    @pytest.mark.asyncio
    async def test_route_read_default_lines(self, server):
        result = await server._route_tool_call("read", {})
        assert "Last 20 lines" in result

    @pytest.mark.asyncio
    async def test_route_control_char(self, server):
        result = await server._route_tool_call("control-char", {"key": "c"})
        assert "Ctrl+C" in result

    @pytest.mark.asyncio
    async def test_route_control_char_invalid(self, server):
        result = await server._route_tool_call("control-char", {"key": "invalid_key"})
        assert "Invalid control key" in result

    @pytest.mark.asyncio
    async def test_route_list(self, server):
        result = await server._route_tool_call("list", {})
        assert "pane" in result.lower()

    @pytest.mark.asyncio
    async def test_route_split_horizontal(self, server):
        result = await server._route_tool_call("split", {"direction": "h"})
        assert "horizontally" in result

    @pytest.mark.asyncio
    async def test_route_split_vertical(self, server):
        result = await server._route_tool_call("split", {"direction": "v"})
        assert "vertically" in result

    @pytest.mark.asyncio
    async def test_route_split_invalid_direction(self, server):
        result = await server._route_tool_call("split", {"direction": "x"})
        assert "Invalid direction" in result

    @pytest.mark.asyncio
    async def test_route_new_window(self, server):
        result = await server._route_tool_call("new-window", {})
        assert "pane_id" in result

    @pytest.mark.asyncio
    async def test_route_new_tab(self, server):
        result = await server._route_tool_call("new-tab", {})
        assert "pane_id" in result

    @pytest.mark.asyncio
    async def test_route_focus(self, server):
        result = await server._route_tool_call("focus", {"session_id": "%1"})
        assert "Focused" in result

    @pytest.mark.asyncio
    async def test_route_new_session(self, server):
        result = await server._route_tool_call("new-session", {})
        assert "session" in result.lower() or "Split" in result

    @pytest.mark.asyncio
    async def test_route_clear(self, server):
        result = await server._route_tool_call("clear", {})
        assert "cleared" in result.lower()

    @pytest.mark.asyncio
    async def test_route_paste(self, server):
        result = await server._route_tool_call("paste", {"text": "hello world"})
        assert "11 characters" in result

    @pytest.mark.asyncio
    async def test_route_set_appearance(self, server):
        result = await server._route_tool_call("set-appearance", {"title": "Test"})
        assert "not supported" in result.lower() or "appearance" in result.lower()

    @pytest.mark.asyncio
    async def test_route_get_terminal_state(self, server):
        result = await server._route_tool_call("get-terminal-state", {})
        assert "total_panes" in result

    @pytest.mark.asyncio
    async def test_route_get_terminal_state_with_session(self, server):
        result = await server._route_tool_call("get-terminal-state", {"session_id": "%1"})
        assert "%1" in result

    @pytest.mark.asyncio
    async def test_route_show_alert(self, server):
        result = await server._route_tool_call("show-alert", {"title": "Hi", "message": "Test"})
        assert "not supported" in result.lower() or "alert" in result.lower()

    @pytest.mark.asyncio
    async def test_route_set_color_preset(self, server):
        result = await server._route_tool_call("set-color-preset", {"preset": "red"})
        assert "not supported" in result.lower() or "color" in result.lower()

    @pytest.mark.asyncio
    async def test_route_list_color_presets(self, server):
        result = await server._route_tool_call("list-color-presets", {})
        assert "not supported" in result.lower() or "color" in result.lower()

    @pytest.mark.asyncio
    async def test_route_close_session(self, server):
        result = await server._route_tool_call("close-session", {"session_id": "%1"})
        assert "Closed" in result

    @pytest.mark.asyncio
    async def test_route_unknown_tool(self, server):
        result = await server._route_tool_call("nonexistent", {})
        assert "Unknown tool: nonexistent" == result


# =============================================================================
# Execute Logic
# =============================================================================


class TestExecuteLogic:
    @pytest.mark.asyncio
    async def test_execute_fire_and_forget(self, server):
        result = await server._execute({"command": "echo hello", "wait": False})
        assert "Sent: echo hello" in result

    @pytest.mark.asyncio
    async def test_execute_with_wait(self, server):
        result = await server._execute({"command": "echo hello", "wait": True, "timeout": 5})
        assert "Completed" in result

    @pytest.mark.asyncio
    async def test_execute_monitor_mode(self, server):
        result = await server._execute({"wait": True, "timeout": 5})
        assert "Completed" in result

    @pytest.mark.asyncio
    async def test_execute_no_command_no_wait(self, server):
        result = await server._execute({})
        assert "Error" in result
        assert "command is required" in result

    @pytest.mark.asyncio
    async def test_execute_broadcast(self, server):
        result = await server._execute(
            {
                "command": "echo hi",
                "targets": ["%1", "%2", "%3"],
            }
        )
        assert "Sent to 3 sessions" in result

    @pytest.mark.asyncio
    async def test_execute_broadcast_skips_ai_sessions(self, server):
        result = await server._execute(
            {
                "command": "echo hi",
                "targets": ["%1", "ai-session", "%3"],
            }
        )
        assert "Sent to 2 sessions" in result
        assert "Skipped 1 AI session" in result

    @pytest.mark.asyncio
    async def test_execute_with_session_id(self, server):
        result = await server._execute({"command": "pwd", "session_id": "%5"})
        assert "Sent: pwd" in result

    @pytest.mark.asyncio
    async def test_execute_with_watch_for(self, server):
        result = await server._execute(
            {
                "command": "ls",
                "wait": True,
                "watch_for": "silence",
            }
        )
        assert "Completed" in result


# =============================================================================
# Return Focus
# =============================================================================


class TestReturnFocus:
    @pytest.mark.asyncio
    async def test_return_focus_default_true(self, server, backend):
        """return_focus defaults to True — focus should be restored."""
        # Mock backend to simulate focus change
        focus_calls = []
        original_focus = backend.focus_session

        async def track_focus(session_id):
            focus_calls.append(session_id)
            return await original_focus(session_id)

        backend.focus_session = track_focus

        call_count = 0

        async def changing_active():
            nonlocal call_count
            call_count += 1
            # First call returns original, after execute it changes
            if call_count <= 1:
                return "active-pane"
            return "other-pane"

        backend.get_current_active_session_id = changing_active

        result = await server._route_tool_call("execute", {"command": "ls"})
        # Focus should have been returned
        assert "active-pane" in focus_calls or "focus returned" in result

    @pytest.mark.asyncio
    async def test_return_focus_false(self, server, backend):
        """return_focus=False — focus should NOT be restored."""
        focus_calls = []
        original_focus = backend.focus_session

        async def track_focus(session_id):
            focus_calls.append(session_id)
            return await original_focus(session_id)

        backend.focus_session = track_focus

        result = await server._route_tool_call(
            "execute",
            {
                "command": "ls",
                "return_focus": False,
            },
        )
        # No focus restoration should happen
        assert len(focus_calls) == 0
        assert "focus returned" not in result

    @pytest.mark.asyncio
    async def test_return_focus_no_change(self, server, backend):
        """If focus hasn't changed, don't call focus_session."""
        focus_calls = []
        original_focus = backend.focus_session

        async def track_focus(session_id):
            focus_calls.append(session_id)
            return await original_focus(session_id)

        backend.focus_session = track_focus
        # Active session stays the same
        backend.get_current_active_session_id = AsyncMock(return_value="active-pane")

        result = await server._route_tool_call("execute", {"command": "ls"})
        assert len(focus_calls) == 0

    @pytest.mark.asyncio
    async def test_return_focus_on_split(self, server, backend):
        """Split with return_focus should restore focus."""
        call_count = 0

        async def changing_active():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return "active-pane"
            return "new-split-pane"

        backend.get_current_active_session_id = changing_active
        backend.focus_session = AsyncMock(return_value="Focused")

        result = await server._route_tool_call("split", {"direction": "h"})
        backend.focus_session.assert_called_once_with("active-pane")

    @pytest.mark.asyncio
    async def test_return_focus_on_clear(self, server, backend):
        """Clear with return_focus should restore focus."""
        call_count = 0

        async def changing_active():
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return "active-pane"
            return "other-pane"

        backend.get_current_active_session_id = changing_active
        backend.focus_session = AsyncMock(return_value="Focused")

        result = await server._route_tool_call("clear", {})
        backend.focus_session.assert_called_once_with("active-pane")


# =============================================================================
# MCP Resources (via request_handlers)
# =============================================================================


class TestResources:
    @pytest.mark.asyncio
    async def test_list_resources(self, server):
        from mcp.types import ListResourcesRequest

        handler = server.server.request_handlers[ListResourcesRequest]
        result = await handler(ListResourcesRequest(method="resources/list"))
        resources = result.root.resources
        uris = [str(r.uri) for r in resources]
        assert "sideshell://sessions" in uris
        assert "sideshell://capabilities" in uris

    @pytest.mark.asyncio
    async def test_list_resource_templates(self, server):
        from mcp.types import ListResourceTemplatesRequest

        handler = server.server.request_handlers[ListResourceTemplatesRequest]
        result = await handler(ListResourceTemplatesRequest(method="resources/templates/list"))
        templates = result.root.resourceTemplates
        uris = [t.uriTemplate for t in templates]
        assert any("{session_id}" in u for u in uris)
        assert any("screen" in u for u in uris)

    @pytest.mark.asyncio
    async def test_read_sessions_resource(self, server):
        from mcp.types import ReadResourceRequest

        handler = server.server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(method="resources/read", params={"uri": "sideshell://sessions"}))
        content = result.root.contents[0].text
        assert "pane" in content.lower()

    @pytest.mark.asyncio
    async def test_read_capabilities_resource(self, server):
        from mcp.types import ReadResourceRequest

        handler = server.server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(method="resources/read", params={"uri": "sideshell://capabilities"}))
        data = json.loads(result.root.contents[0].text)
        assert data["backend"] == "mock"
        assert "features" in data
        assert "control_keys" in data

    @pytest.mark.asyncio
    async def test_read_session_detail_resource(self, server):
        from mcp.types import ReadResourceRequest

        handler = server.server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(method="resources/read", params={"uri": "sideshell://sessions/%1"}))
        assert len(result.root.contents) >= 1

    @pytest.mark.asyncio
    async def test_read_session_screen_resource(self, server):
        from mcp.types import ReadResourceRequest

        handler = server.server.request_handlers[ReadResourceRequest]
        result = await handler(
            ReadResourceRequest(method="resources/read", params={"uri": "sideshell://sessions/%1/screen"})
        )
        content = result.root.contents[0].text
        assert "lines" in content.lower()

    @pytest.mark.asyncio
    async def test_read_unknown_resource(self, server):
        from mcp.types import ReadResourceRequest

        handler = server.server.request_handlers[ReadResourceRequest]
        result = await handler(ReadResourceRequest(method="resources/read", params={"uri": "sideshell://unknown"}))
        assert "Unknown resource" in result.root.contents[0].text


# =============================================================================
# MCP call_tool handler (via request_handlers)
# =============================================================================


class TestCallToolHandler:
    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self, server):
        from mcp.types import CallToolRequest

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(method="tools/call", params={"name": "list", "arguments": {}}))
        contents = result.root.content
        assert len(contents) >= 1
        assert contents[0].type == "text"
        assert "pane" in contents[0].text.lower()

    @pytest.mark.asyncio
    async def test_call_tool_error_returns_text(self, server, backend):
        """Errors in tools should be caught and returned as text."""

        async def broken_list():
            raise RuntimeError("Connection lost")

        backend.list_sessions = broken_list

        from mcp.types import CallToolRequest

        handler = server.server.request_handlers[CallToolRequest]
        result = await handler(CallToolRequest(method="tools/call", params={"name": "list", "arguments": {}}))
        contents = result.root.content
        assert len(contents) >= 1
        assert "Error" in contents[0].text
