"""Tests for ITermMCPServer."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from native_iterm2_mcp.server import ControlKey, ITermMCPServer, SessionInfo, SplitDirection


class TestITermMCPServer:
    """Test ITermMCPServer functionality."""

    @pytest.mark.asyncio
    async def test_server_initialization(self) -> None:
        """Test server initialization."""
        server = ITermMCPServer()
        assert server.server.name == "native-iterm2-mcp"
        assert server.connection is None
        assert server.app is None

    @pytest.mark.asyncio
    async def test_connect_to_iterm_success(self) -> None:
        """Test successful connection to iTerm2."""
        server = ITermMCPServer()

        with patch("native_iterm2_mcp.server.iterm2.Connection.async_create") as mock_create:
            with patch("native_iterm2_mcp.server.iterm2.async_get_app") as mock_get_app:
                mock_connection = AsyncMock()
                mock_app = AsyncMock()
                mock_create.return_value = mock_connection
                mock_get_app.return_value = mock_app

                result = await server.connect_to_iterm()

                assert result is True
                assert server.connection == mock_connection
                assert server.app == mock_app

    @pytest.mark.asyncio
    async def test_connect_to_iterm_failure(self) -> None:
        """Test failed connection to iTerm2."""
        server = ITermMCPServer()

        with patch(
            "native_iterm2_mcp.server.iterm2.Connection.async_create",
            side_effect=Exception("Connection failed"),
        ):
            result = await server.connect_to_iterm()
            assert result is False
            assert server.connection is None

    @pytest.mark.asyncio
    async def test_execute_command(self, mcp_server: ITermMCPServer) -> None:
        """Test command execution."""
        args = {"command": "ls -la"}

        result = await mcp_server._execute_command(args)

        assert "✓ Sent to focused terminal: ls -la" in result
        mcp_server.app.current_terminal_window.current_tab.current_session.async_send_text.assert_called_once_with(
            "ls -la\n"
        )

    @pytest.mark.asyncio
    async def test_execute_command_with_session_id(
        self, mcp_server: ITermMCPServer, mock_iterm_app: AsyncMock
    ) -> None:
        """Test command execution with specific session ID."""
        args = {"command": "pwd", "session_id": "test_session_123"}

        result = await mcp_server._execute_command(args)

        assert "✓ Sent to session test_session_123: pwd" in result
        mock_iterm_app.current_terminal_window.current_tab.current_session.async_send_text.assert_called_with(
            "pwd\n"
        )

    @pytest.mark.asyncio
    async def test_read_terminal(self, mcp_server: ITermMCPServer) -> None:
        """Test reading terminal output."""
        args = {"lines": 3}

        result = await mcp_server._read_terminal(args)

        assert "Last 3 lines:" in result
        assert "test output line" in result
        assert "At prompt: True" in result

    @pytest.mark.asyncio
    async def test_send_control_character(self, mcp_server: ITermMCPServer) -> None:
        """Test sending control character."""
        args = {"key": "c"}

        result = await mcp_server._send_control(args)

        assert result == "✓ Sent Ctrl+C"
        mcp_server.app.current_terminal_window.current_tab.current_session.async_send_text.assert_called_once_with(
            "\x03"
        )

    @pytest.mark.asyncio
    async def test_list_sessions(self, mcp_server: ITermMCPServer) -> None:
        """Test listing sessions."""
        result = await mcp_server._list_sessions()

        assert "Window: test_window_123" in result
        assert "Tab:" in result
        assert "[test_session_123]" in result

    @pytest.mark.asyncio
    async def test_split_pane_horizontal(self, mcp_server: ITermMCPServer) -> None:
        """Test horizontal pane split."""
        args = {"direction": "h"}

        # Mock the new session
        new_session = AsyncMock()
        new_session.session_id = "new_session_456"
        mcp_server.app.current_terminal_window.current_tab.current_session.async_split_pane.return_value = (
            new_session
        )

        result = await mcp_server._split_pane(args)

        assert "✓ Split horizontally" in result
        assert "new_session_456" in result
        mcp_server.app.current_terminal_window.current_tab.current_session.async_split_pane.assert_called_once_with(
            vertical=False
        )

    @pytest.mark.asyncio
    async def test_split_pane_vertical(self, mcp_server: ITermMCPServer) -> None:
        """Test vertical pane split."""
        args = {"direction": "v"}

        new_session = AsyncMock()
        new_session.session_id = "new_session_789"
        mcp_server.app.current_terminal_window.current_tab.current_session.async_split_pane.return_value = (
            new_session
        )

        result = await mcp_server._split_pane(args)

        assert "✓ Split vertically" in result
        assert "new_session_789" in result
        mcp_server.app.current_terminal_window.current_tab.current_session.async_split_pane.assert_called_once_with(
            vertical=True
        )

    @pytest.mark.asyncio
    async def test_set_tab_color(self, mcp_server: ITermMCPServer) -> None:
        """Test setting tab color."""
        args = {"color": "red"}

        result = await mcp_server._set_tab_color(args)

        assert result == "✓ Tab color set to red"
        mcp_server.app.current_terminal_window.current_tab.current_session.async_set_profile_properties.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_tab_color_hex(self, mcp_server: ITermMCPServer) -> None:
        """Test setting tab color with hex value."""
        args = {"color": "#FF0000"}

        result = await mcp_server._set_tab_color(args)

        assert result == "✓ Tab color set to #FF0000"

    @pytest.mark.asyncio
    async def test_set_tab_title(self, mcp_server: ITermMCPServer) -> None:
        """Test setting tab title."""
        args = {"title": "My Custom Tab"}

        result = await mcp_server._set_tab_title(args)

        assert result == "✓ Tab title set to 'My Custom Tab'"
        mcp_server.app.current_terminal_window.current_tab.async_set_title.assert_called_once_with(
            "My Custom Tab"
        )

    @pytest.mark.asyncio
    async def test_create_window(self, mcp_server: ITermMCPServer) -> None:
        """Test creating new window."""
        args: dict[str, Any] = {}

        with patch("native_iterm2_mcp.server.iterm2.Window.async_create") as mock_create:
            mock_window = AsyncMock()
            mock_window.window_id = "new_window_123"
            mock_session = AsyncMock()
            mock_tab = AsyncMock()
            mock_tab.current_session = mock_session
            mock_window.current_tab = mock_tab
            mock_create.return_value = mock_window

            result = await mcp_server._create_window(args)

            assert result == "✓ New window created: new_window_123"
            mock_create.assert_called_once_with(mcp_server.connection)

    @pytest.mark.asyncio
    async def test_create_tab(self, mcp_server: ITermMCPServer) -> None:
        """Test creating new tab."""
        args: dict[str, Any] = {}

        result = await mcp_server._create_tab(args)

        assert "✓ New tab created: test_tab_123" in result
        mcp_server.app.current_terminal_window.async_create_tab.assert_called_once()

    @pytest.mark.asyncio
    async def test_focus_session(self, mcp_server: ITermMCPServer) -> None:
        """Test focusing a session."""
        args = {"session_id": "test_session_123"}

        result = await mcp_server._focus_session(args)

        assert result == "✓ Focused session test_session_123"
        mcp_server.app.current_terminal_window.current_tab.current_session.async_activate.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_command(self, mcp_server: ITermMCPServer) -> None:
        """Test broadcasting command to all sessions."""
        args = {"command": "echo 'Hello World'"}

        result = await mcp_server._broadcast_command(args)

        assert "✓ Broadcasted to 1 sessions: echo 'Hello World'" in result
        mcp_server.app.current_terminal_window.current_tab.current_session.async_send_text.assert_called_with(
            "echo 'Hello World'\n"
        )

    @pytest.mark.asyncio
    async def test_get_session_info(self, mcp_server: ITermMCPServer) -> None:
        """Test getting session info."""
        mock_session = AsyncMock()
        mock_session.session_id = "test_123"
        mock_session.async_get_variable = AsyncMock(
            side_effect=[
                "Test Session",  # name
                "/home/user",  # path
                "vim",  # job
                True,  # at_prompt
            ]
        )

        info = await mcp_server._get_session_info(mock_session)

        assert isinstance(info, SessionInfo)
        assert info.session_id == "test_123"
        assert info.name == "Test Session"
        assert info.path == "/home/user"
        assert info.job == "vim"
        assert info.at_prompt is True

    @pytest.mark.asyncio
    async def test_parse_color_named(self, mcp_server: ITermMCPServer) -> None:
        """Test parsing named colors."""
        # Test known color
        color = mcp_server._parse_color("red")
        assert color.red == 255
        assert color.green == 0
        assert color.blue == 0

        # Test unknown color (defaults to gray)
        color = mcp_server._parse_color("unknown")
        assert color.red == 128
        assert color.green == 128
        assert color.blue == 128

    @pytest.mark.asyncio
    async def test_parse_color_hex(self, mcp_server: ITermMCPServer) -> None:
        """Test parsing hex colors."""
        color = mcp_server._parse_color("#FF00FF")
        assert color.red == 255
        assert color.green == 0
        assert color.blue == 255

    @pytest.mark.asyncio
    async def test_route_tool_call(self, mcp_server: ITermMCPServer) -> None:
        """Test routing tool calls."""
        # Mock the execute method
        with patch.object(mcp_server, "_execute_command", return_value="executed"):
            result = await mcp_server._route_tool_call("execute", {"command": "test"})
            assert result == "executed"

        # Test unknown tool
        result = await mcp_server._route_tool_call("unknown_tool", {})
        assert result == "Unknown tool: unknown_tool"

    def test_control_key_enum(self) -> None:
        """Test ControlKey enumeration."""
        assert ControlKey.C.value == "c"
        assert ControlKey.D.value == "d"
        assert ControlKey.Z.value == "z"

    def test_split_direction_enum(self) -> None:
        """Test SplitDirection enumeration."""
        assert SplitDirection.HORIZONTAL.value == "h"
        assert SplitDirection.VERTICAL.value == "v"