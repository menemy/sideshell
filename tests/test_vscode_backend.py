"""Tests for VSCode terminal backend."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.base import ControlKey, SplitDirection
from sideshell_mcp.backends.ide_bridge import IDEBridgeError
from sideshell_mcp.backends.vscode_backend import INSTALL_INSTRUCTIONS, VSCodeBackend


class TestVSCodeBackendInit:
    """Tests for VSCode backend initialization."""

    def test_name(self) -> None:
        backend = VSCodeBackend()
        assert backend.name == "vscode"

    def test_is_available_with_code_binary(self) -> None:
        backend = VSCodeBackend()
        with patch("shutil.which", return_value="/usr/bin/code"):
            assert backend.is_available is True

    def test_is_available_with_port_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text(json.dumps({"port": 46117}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            backend = VSCodeBackend()
            assert backend.is_available is True

    def test_not_available_without_anything(self) -> None:
        with patch("shutil.which", return_value=None):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                backend = VSCodeBackend()
                assert backend.is_available is False

    def test_install_instructions_contain_port(self) -> None:
        formatted = INSTALL_INSTRUCTIONS.format(port=46117)
        assert "46117" in formatted
        assert "code --install-extension" in formatted


class TestVSCodeBackendConnection:
    """Tests for VSCode backend connection management."""

    @pytest.mark.asyncio
    async def test_connect_delegates_to_bridge(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.connect = AsyncMock(return_value=True)
        result = await backend.connect()
        assert result is True
        backend._bridge.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_returns_false_on_error(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.connect = AsyncMock(side_effect=IDEBridgeError("fail"))
        result = await backend.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_connection_shows_install_instructions(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.ensure_connection = AsyncMock(side_effect=IDEBridgeError("no connection"))
        with pytest.raises(IDEBridgeError, match="code --install-extension"):
            await backend.ensure_connection()

    @pytest.mark.asyncio
    async def test_disconnect_delegates(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.disconnect = AsyncMock()
        await backend.disconnect()
        backend._bridge.disconnect.assert_called_once()


class TestVSCodeBackendSessions:
    """Tests for session listing and management."""

    @pytest.mark.asyncio
    async def test_list_sessions_formats_output(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-1", "name": "bash", "path": "/home", "active": True},
                {"id": "term-2", "name": "zsh", "path": "/tmp", "active": False},
            ]
        )
        result = await backend.list_sessions()
        assert "Total: 2 terminals" in result
        assert "bash" in result
        assert "zsh" in result
        assert "term-1" in result
        assert "term-2" in result
        assert "●" in result  # active marker
        assert "○" in result  # inactive marker

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(return_value=[])
        result = await backend.list_sessions()
        assert "No terminal sessions" in result

    @pytest.mark.asyncio
    async def test_get_session_by_id(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-1", "name": "bash", "path": "/home"},
                {"id": "term-2", "name": "zsh", "path": "/tmp"},
            ]
        )
        session = await backend.get_session("term-2")
        assert session is not None
        assert session.session_id == "term-2"
        assert session.name == "zsh"

    @pytest.mark.asyncio
    async def test_get_session_returns_none_for_missing(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-1", "name": "bash", "path": "/home"},
            ]
        )
        session = await backend.get_session("nonexistent")
        assert session is None

    @pytest.mark.asyncio
    async def test_get_session_returns_active(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-1", "name": "bash", "path": "/home"},
                {"id": "term-2", "name": "zsh", "path": "/tmp"},
            ]
        )
        backend._bridge.get_active_session = AsyncMock(return_value="term-2")
        session = await backend.get_session()
        assert session is not None
        assert session.session_id == "term-2"

    @pytest.mark.asyncio
    async def test_get_session_fallback_to_first(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-1", "name": "bash", "path": "/home"},
            ]
        )
        backend._bridge.get_active_session = AsyncMock(return_value=None)
        session = await backend.get_session()
        assert session is not None
        assert session.session_id == "term-1"

    @pytest.mark.asyncio
    async def test_get_session_returns_none_when_empty(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.list_sessions = AsyncMock(return_value=[])
        session = await backend.get_session()
        assert session is None

    @pytest.mark.asyncio
    async def test_get_current_active_session_id(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.get_active_session = AsyncMock(return_value="term-1")
        result = await backend.get_current_active_session_id()
        assert result == "term-1"

    @pytest.mark.asyncio
    async def test_is_ai_session(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.is_ai_session = AsyncMock(return_value=True)
        result = await backend.is_ai_session("term-1")
        assert result is True


class TestVSCodeBackendOperations:
    """Tests for terminal operations."""

    @pytest.mark.asyncio
    async def test_execute_command(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.execute_command = AsyncMock(return_value="output here")
        result = await backend.execute_command("ls -la", "term-1", wait=True, timeout=10)
        assert result == "output here"
        backend._bridge.execute_command.assert_called_once_with(
            command="ls -la", session_id="term-1", wait=True, timeout=10, watch_for="prompt"
        )

    @pytest.mark.asyncio
    async def test_send_text(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.send_text = AsyncMock(return_value="sent")
        result = await backend.send_text("hello", "term-1")
        assert result == "sent"

    @pytest.mark.asyncio
    async def test_send_control(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.send_control = AsyncMock(return_value="sent ctrl+c")
        result = await backend.send_control(ControlKey.C, "term-1")
        assert "ctrl+c" in result
        backend._bridge.send_control.assert_called_once_with(key="c", session_id="term-1")

    @pytest.mark.asyncio
    async def test_read_terminal(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.read_terminal = AsyncMock(return_value="$ echo hello\nhello\n$")
        result = await backend.read_terminal(lines=20, session_id="term-1")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_clear_terminal(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.clear_terminal = AsyncMock(return_value="cleared")
        result = await backend.clear_terminal("term-1")
        assert result == "cleared"

    @pytest.mark.asyncio
    async def test_split_pane_vertical(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.split_pane = AsyncMock(return_value={"new_session_id": "term-3"})
        result = await backend.split_pane(SplitDirection.VERTICAL, "term-1")
        assert "vertically" in result
        assert "term-3" in result

    @pytest.mark.asyncio
    async def test_split_pane_horizontal(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.split_pane = AsyncMock(return_value={"new_session_id": "term-4"})
        result = await backend.split_pane(SplitDirection.HORIZONTAL, "term-1")
        assert "horizontally" in result
        assert "term-4" in result

    @pytest.mark.asyncio
    async def test_create_tab(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.create_tab = AsyncMock(return_value={"new_session_id": "term-5"})
        result = await backend.create_tab()
        assert "tab" in result.lower()
        assert "term-5" in result

    @pytest.mark.asyncio
    async def test_create_window(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.create_window = AsyncMock(return_value={"new_session_id": "term-6"})
        result = await backend.create_window()
        assert "window" in result.lower()
        assert "term-6" in result

    @pytest.mark.asyncio
    async def test_create_session_delegates_to_create_tab(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.create_tab = AsyncMock(return_value={"new_session_id": "term-7"})
        result = await backend.create_session()
        assert "term-7" in result

    @pytest.mark.asyncio
    async def test_focus_session(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.focus_session = AsyncMock(return_value="focused")
        result = await backend.focus_session("term-1")
        assert result == "focused"

    @pytest.mark.asyncio
    async def test_close_session(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.close_session = AsyncMock(return_value="closed")
        result = await backend.close_session("term-1")
        assert result == "closed"

    @pytest.mark.asyncio
    async def test_set_appearance(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.set_appearance = AsyncMock(return_value="appearance set")
        result = await backend.set_appearance(title="Test", color="#FF0000")
        assert result == "appearance set"
        backend._bridge.set_appearance.assert_called_once_with(
            session_id=None, title="Test", color="#FF0000", badge=None
        )

    @pytest.mark.asyncio
    async def test_get_terminal_state_dict(self) -> None:
        backend = VSCodeBackend()
        state = {"terminals": [{"id": "t1"}], "total": 1}
        backend._bridge.get_terminal_state = AsyncMock(return_value=state)
        result = await backend.get_terminal_state()
        parsed = json.loads(result)
        assert parsed["total"] == 1

    @pytest.mark.asyncio
    async def test_get_terminal_state_string(self) -> None:
        backend = VSCodeBackend()
        backend._bridge.get_terminal_state = AsyncMock(return_value="some state")
        result = await backend.get_terminal_state()
        assert result == "some state"
