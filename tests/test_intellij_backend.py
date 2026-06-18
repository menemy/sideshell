"""Tests for IntelliJ terminal backend."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.base import ControlKey, SplitDirection
from sideshell_mcp.backends.ide_bridge import IDEBridgeError
from sideshell_mcp.backends.intellij_backend import INSTALL_INSTRUCTIONS, IntelliJBackend


class TestIntelliJBackendInit:
    """Tests for IntelliJ backend initialization."""

    def test_name(self) -> None:
        backend = IntelliJBackend()
        assert backend.name == "intellij"

    def test_is_available_with_port_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "intellij-port"
        port_file.write_text(json.dumps({"port": 46118}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            backend = IntelliJBackend()
            assert backend.is_available is True

    def test_is_available_with_jetbrains_ide_env(self) -> None:
        with patch.dict(os.environ, {"JETBRAINS_IDE": "PyCharm"}, clear=False):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                backend = IntelliJBackend()
                assert backend.is_available is True

    def test_is_available_with_terminal_emulator_env(self) -> None:
        with patch.dict(os.environ, {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}, clear=False):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                backend = IntelliJBackend()
                assert backend.is_available is True

    def test_not_available_without_anything(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("JETBRAINS_IDE", "TERMINAL_EMULATOR")}
        with patch.dict(os.environ, env, clear=True):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                backend = IntelliJBackend()
                assert backend.is_available is False

    def test_install_instructions_contain_port(self) -> None:
        formatted = INSTALL_INSTRUCTIONS.format(port=46118)
        assert "46118" in formatted
        assert "JetBrains" in formatted

    def test_install_instructions_list_all_ides(self) -> None:
        assert "IntelliJ IDEA" in INSTALL_INSTRUCTIONS
        assert "PyCharm" in INSTALL_INSTRUCTIONS
        assert "WebStorm" in INSTALL_INSTRUCTIONS
        assert "GoLand" in INSTALL_INSTRUCTIONS


class TestIntelliJBackendConnection:
    """Tests for IntelliJ backend connection management."""

    @pytest.mark.asyncio
    async def test_connect_delegates_to_bridge(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.connect = AsyncMock(return_value=True)
        result = await backend.connect()
        assert result is True

    @pytest.mark.asyncio
    async def test_connect_returns_false_on_error(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.connect = AsyncMock(side_effect=IDEBridgeError("fail"))
        result = await backend.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_connection_shows_install_instructions(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.ensure_connection = AsyncMock(side_effect=IDEBridgeError("no conn"))
        with pytest.raises(IDEBridgeError, match="Plugins"):
            await backend.ensure_connection()

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.disconnect = AsyncMock()
        await backend.disconnect()
        backend._bridge.disconnect.assert_called_once()


class TestIntelliJBackendSessions:
    """Tests for session management."""

    @pytest.mark.asyncio
    async def test_list_sessions_formats_output(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-proj-0", "name": "Local", "path": "/project", "active": True},
                {"id": "term-proj-1", "name": "Build", "path": "/project", "active": False},
            ]
        )
        result = await backend.list_sessions()
        assert "Total: 2" in result
        assert "Local" in result
        assert "Build" in result

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.list_sessions = AsyncMock(return_value=[])
        result = await backend.list_sessions()
        assert "No terminal sessions" in result
        assert "IntelliJ" in result

    @pytest.mark.asyncio
    async def test_get_session_by_id(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-proj-0", "name": "Local", "path": "/project"},
            ]
        )
        session = await backend.get_session("term-proj-0")
        assert session is not None
        assert session.session_id == "term-proj-0"

    @pytest.mark.asyncio
    async def test_get_session_returns_active(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.list_sessions = AsyncMock(
            return_value=[
                {"id": "term-0", "name": "A", "path": "/"},
                {"id": "term-1", "name": "B", "path": "/"},
            ]
        )
        backend._bridge.get_active_session = AsyncMock(return_value="term-1")
        session = await backend.get_session()
        assert session is not None
        assert session.session_id == "term-1"

    @pytest.mark.asyncio
    async def test_get_session_returns_none_when_empty(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.list_sessions = AsyncMock(return_value=[])
        assert await backend.get_session() is None

    @pytest.mark.asyncio
    async def test_is_ai_session(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.is_ai_session = AsyncMock(return_value=False)
        assert await backend.is_ai_session("term-0") is False

    @pytest.mark.asyncio
    async def test_get_current_active_session_id(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.get_active_session = AsyncMock(return_value="term-0")
        assert await backend.get_current_active_session_id() == "term-0"


class TestIntelliJBackendOperations:
    """Tests for terminal operations."""

    @pytest.mark.asyncio
    async def test_execute_command(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.execute_command = AsyncMock(return_value="output")
        result = await backend.execute_command("ls", "term-0", wait=True, timeout=5)
        assert result == "output"
        backend._bridge.execute_command.assert_called_once_with(
            command="ls", session_id="term-0", wait=True, timeout=5, watch_for="prompt"
        )

    @pytest.mark.asyncio
    async def test_send_text(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.send_text = AsyncMock(return_value="ok")
        result = await backend.send_text("echo test", "term-0")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_send_control(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.send_control = AsyncMock(return_value="ctrl+d sent")
        result = await backend.send_control(ControlKey.D, "term-0")
        assert "ctrl+d" in result
        backend._bridge.send_control.assert_called_once_with(key="d", session_id="term-0")

    @pytest.mark.asyncio
    async def test_read_terminal(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.read_terminal = AsyncMock(return_value="$ pwd\n/home\n$")
        result = await backend.read_terminal(lines=10, session_id="term-0")
        assert "/home" in result

    @pytest.mark.asyncio
    async def test_clear_terminal(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.clear_terminal = AsyncMock(return_value="cleared")
        assert await backend.clear_terminal("term-0") == "cleared"

    @pytest.mark.asyncio
    async def test_split_pane(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.split_pane = AsyncMock(return_value={"new_session_id": "term-2"})
        result = await backend.split_pane(SplitDirection.VERTICAL, "term-0")
        assert "vertically" in result
        assert "term-2" in result

    @pytest.mark.asyncio
    async def test_split_pane_string_result(self) -> None:
        """Handle case where bridge returns string instead of dict."""
        backend = IntelliJBackend()
        backend._bridge.split_pane = AsyncMock(return_value="Not supported in IntelliJ")
        result = await backend.split_pane(SplitDirection.HORIZONTAL, "term-0")
        assert "horizontally" in result

    @pytest.mark.asyncio
    async def test_create_tab(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.create_tab = AsyncMock(return_value={"new_session_id": "term-3"})
        result = await backend.create_tab()
        assert "tab" in result.lower()
        assert "term-3" in result

    @pytest.mark.asyncio
    async def test_create_window(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.create_window = AsyncMock(return_value={"new_session_id": "term-4"})
        result = await backend.create_window()
        assert "window" in result.lower()

    @pytest.mark.asyncio
    async def test_create_session_is_create_tab(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.create_tab = AsyncMock(return_value={"new_session_id": "term-5"})
        result = await backend.create_session()
        assert "term-5" in result

    @pytest.mark.asyncio
    async def test_focus_session(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.focus_session = AsyncMock(return_value="focused")
        assert await backend.focus_session("term-0") == "focused"

    @pytest.mark.asyncio
    async def test_close_session(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.close_session = AsyncMock(return_value="closed")
        assert await backend.close_session("term-0") == "closed"

    @pytest.mark.asyncio
    async def test_set_appearance(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.set_appearance = AsyncMock(return_value="title set")
        result = await backend.set_appearance(title="Build", badge="!")
        assert result == "title set"
        backend._bridge.set_appearance.assert_called_once_with(session_id=None, title="Build", color=None, badge="!")

    @pytest.mark.asyncio
    async def test_get_terminal_state_dict(self) -> None:
        backend = IntelliJBackend()
        state = {"terminals": [], "total": 0}
        backend._bridge.get_terminal_state = AsyncMock(return_value=state)
        result = await backend.get_terminal_state()
        parsed = json.loads(result)
        assert parsed["total"] == 0

    @pytest.mark.asyncio
    async def test_get_terminal_state_string(self) -> None:
        backend = IntelliJBackend()
        backend._bridge.get_terminal_state = AsyncMock(return_value="state info")
        result = await backend.get_terminal_state()
        assert result == "state info"
