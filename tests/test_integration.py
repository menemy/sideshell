"""Integration tests for native-iterm2-mcp."""

from unittest.mock import AsyncMock, patch

import pytest

from native_iterm2_mcp.server import ITermMCPServer


class TestIntegration:
    """Integration tests for the MCP server."""

    @pytest.mark.asyncio
    async def test_tool_list(self, mcp_server: ITermMCPServer) -> None:
        """Test that all tools are listed correctly."""
        tools = mcp_server._get_tool_definitions()

        tool_names = [tool.name for tool in tools]
        expected_tools = [
            "execute",
            "read",
            "ctrl",
            "list",
            "split",
            "tab-color",
            "tab-title",
            "new-window",
            "new-tab",
            "focus",
            "broadcast",
        ]

        for expected in expected_tools:
            assert expected in tool_names

    @pytest.mark.asyncio
    async def test_tool_call_execute(self, mcp_server: ITermMCPServer) -> None:
        """Test calling the execute tool through the route."""
        result = await mcp_server._route_tool_call("execute", {"command": "echo test"})
        assert "✓ Sent to focused terminal: echo test" in result

    @pytest.mark.asyncio
    async def test_tool_call_read(self, mcp_server: ITermMCPServer) -> None:
        """Test calling the read tool through the route."""
        result = await mcp_server._route_tool_call("read", {"lines": 5})
        assert "Last 5 lines:" in result

    @pytest.mark.asyncio
    async def test_tool_call_error_handling(self, mcp_server: ITermMCPServer) -> None:
        """Test error handling in tool calls."""
        result = await mcp_server._route_tool_call("unknown_tool", {})
        assert "Unknown tool: unknown_tool" in result

    @pytest.mark.asyncio
    async def test_ensure_connection_reconnect(self) -> None:
        """Test that ensure_connection reconnects when connection is lost."""
        server = ITermMCPServer()

        # First, set up a working connection
        mock_app = AsyncMock()
        server.app = mock_app
        server.connection = AsyncMock()

        # Make the first call fail (simulating lost connection)
        with patch("native_iterm2_mcp.server.iterm2.async_get_app") as mock_get_app:
            mock_get_app.side_effect = [Exception("Connection lost"), mock_app]

            with patch.object(server, "connect_to_iterm", return_value=True) as mock_connect:
                await server.ensure_connection()
                mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_workflow_create_and_split(
        self, mcp_server: ITermMCPServer, mock_iterm_app: AsyncMock
    ) -> None:
        """Test a workflow of creating a new tab and splitting it."""
        # Create new tab
        result = await mcp_server._route_tool_call("new-tab", {"command": "cd /tmp"})
        assert "✓ New tab created" in result

        # Split the tab
        new_session = AsyncMock()
        new_session.session_id = "split_session"
        mock_iterm_app.current_terminal_window.current_tab.current_session.async_split_pane.return_value = (
            new_session
        )

        result = await mcp_server._route_tool_call("split", {"direction": "v"})
        assert "✓ Split vertically" in result

    @pytest.mark.asyncio
    async def test_workflow_multiple_commands(self, mcp_server: ITermMCPServer) -> None:
        """Test executing multiple commands in sequence."""
        commands = ["cd /tmp", "ls -la", "pwd"]

        for cmd in commands:
            result = await mcp_server._route_tool_call("execute", {"command": cmd})
            assert "✓ Sent to focused terminal:" in result
            assert cmd in result

    @pytest.mark.asyncio
    async def test_session_not_found(self, mcp_server: ITermMCPServer) -> None:
        """Test handling when session is not found."""
        with patch.object(mcp_server, "_find_session", return_value=None):
            result = await mcp_server._route_tool_call("focus", {"session_id": "non_existent"})
            assert "Session non_existent not found" in result

    @pytest.mark.asyncio
    async def test_no_window_in_focus(self, mcp_server: ITermMCPServer) -> None:
        """Test handling when no window is in focus - should fallback to first available."""
        mcp_server.app.current_terminal_window = None

        result = await mcp_server._route_tool_call("execute", {"command": "test"})
        # With fallback logic, command should succeed even without focused window
        assert "✓ Sent to focused terminal: test" in result