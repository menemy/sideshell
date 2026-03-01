"""Tests for IDE bridge protocol - WebSocket client/server communication."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.ide_bridge import (
    DEFAULT_INTELLIJ_PORT,
    DEFAULT_VSCODE_PORT,
    IDEBridgeClient,
    IDEBridgeError,
    remove_port_file,
    write_port_file,
)


class TestPortFileManagement:
    """Tests for port file read/write."""

    def test_write_port_file(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            result = write_port_file("vscode", 46117, pid=12345)
            assert result.exists()
            data = json.loads(result.read_text())
            assert data["port"] == 46117
            assert data["pid"] == 12345

    def test_remove_port_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text('{"port": 46117}')
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            remove_port_file("vscode")
            assert not port_file.exists()

    def test_remove_nonexistent_port_file(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            # Should not raise
            remove_port_file("vscode")


class TestIDEBridgeClient:
    """Tests for the WebSocket client."""

    def test_default_ports(self) -> None:
        assert DEFAULT_VSCODE_PORT == 46117
        assert DEFAULT_INTELLIJ_PORT == 46118

    def test_client_initialization(self) -> None:
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
        assert client.ide_name == "vscode"
        assert client.default_port == DEFAULT_VSCODE_PORT
        assert not client._connected

    def test_discover_port_from_json_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text(json.dumps({"port": 55555}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            port, token = client._discover_port_and_token()
            assert port == 55555
            assert token is None

    def test_discover_port_and_token_from_json(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text(json.dumps({"port": 55555, "token": "abc123"}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            port, token = client._discover_port_and_token()
            assert port == 55555
            assert token == "abc123"

    def test_discover_port_from_plain_text(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text("55555")

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            port, token = client._discover_port_and_token()
            assert port == 55555
            assert token is None

    def test_discover_port_default_when_no_file(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            port, token = client._discover_port_and_token()
            assert port == DEFAULT_VSCODE_PORT
            assert token is None

    @pytest.mark.asyncio
    async def test_connect_raises_without_websockets(self) -> None:
        """Should raise clear error if websockets not installed."""
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
        with patch.dict("sys.modules", {"websockets": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                # connect() catches ImportError and raises IDEBridgeError
                with pytest.raises(IDEBridgeError, match="websockets"):
                    await client.connect()

    @pytest.mark.asyncio
    async def test_connect_fails_gracefully(self, tmp_path: Path) -> None:
        """Should return False when server is not available."""
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("nosuchide", 39173)  # Non-existent port
            result = await client.connect()
            assert result is False
            assert not client._connected

    @pytest.mark.asyncio
    async def test_ensure_connection_raises_with_instructions(
        self, tmp_path: Path,
    ) -> None:
        """Should raise with install instructions when can't connect."""
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("nosuchide", 39173)
            with pytest.raises(IDEBridgeError, match="extension"):
                await client.ensure_connection()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self) -> None:
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
        client._connected = False
        await client.disconnect()
        assert not client._connected
        assert client._ws is None


class TestIDEBridgeProtocol:
    """Tests for JSON-RPC protocol formatting."""

    @pytest.mark.asyncio
    async def test_call_formats_request_correctly(self) -> None:
        """Should format JSON-RPC 2.0 requests correctly."""
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)

        # Mock the WebSocket
        mock_ws = AsyncMock()
        sent_messages: list[str] = []

        async def capture_send(msg: str) -> None:
            sent_messages.append(msg)

        mock_ws.send = capture_send
        client._ws = mock_ws
        client._connected = True

        # Create a task that simulates a response
        async def respond_after_delay() -> None:
            await asyncio.sleep(0.1)
            # Simulate response
            if 1 in client._pending:
                client._pending[1].set_result(["session1", "session2"])

        task = asyncio.create_task(respond_after_delay())

        result = await client.call("list_sessions", timeout=5.0)

        assert result == ["session1", "session2"]
        assert len(sent_messages) == 1

        request = json.loads(sent_messages[0])
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "list_sessions"
        assert "id" in request

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_timeout(self) -> None:
        """Should raise on timeout."""
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._ws = mock_ws
        client._connected = True

        with pytest.raises(IDEBridgeError, match="Timeout"):
            await client.call("slow_method", timeout=0.1)


class TestIDEBridgeE2E:
    """End-to-end tests with a mock WebSocket server."""

    @pytest.fixture
    async def mock_server(self) -> asyncio.AbstractServer:
        """Create a mock WebSocket server that echoes requests."""
        try:
            import websockets
        except ImportError:
            pytest.skip("websockets not installed")

        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            async for message in websocket:
                request = json.loads(message)
                method = request.get("method", "")
                req_id = request.get("id")

                # Route methods to mock responses
                responses = {
                    "list_sessions": [
                        {"id": "term-1", "name": "bash", "path": "/home", "active": True},
                        {"id": "term-2", "name": "zsh", "path": "/tmp", "active": False},
                    ],
                    "read_terminal": "Last 20 lines:\n$ echo hello\nhello\n$",
                    "get_active_session": {"session_id": "term-1"},
                    "is_ai_session": False,
                    "execute_command": "Executed: ls -la",
                    "send_text": "Sent text to terminal",
                    "send_control": "Sent control key: c",
                    "split_pane": {"new_session_id": "term-3"},
                    "create_tab": {"new_session_id": "term-4"},
                    "create_window": {"new_session_id": "term-5"},
                    "focus_session": "Focused term-1",
                    "close_session": "Closed term-1",
                    "clear_terminal": "Cleared",
                    "get_terminal_state": {"terminals": [], "total": 2},
                    "set_appearance": "Set title: test",
                }

                result = responses.get(method, f"Unknown: {method}")

                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
                await websocket.send(json.dumps(response))

        server = await websockets.serve(handler, "127.0.0.1", 0)
        yield server
        server.close()
        await server.wait_closed()

    @pytest.fixture
    def server_port(self, mock_server: asyncio.AbstractServer) -> int:
        """Get the port of the mock server."""
        for socket in mock_server.sockets:
            return socket.getsockname()[1]
        raise RuntimeError("No sockets")

    @pytest.mark.asyncio
    async def test_list_sessions(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            sessions = await client.list_sessions()
            assert len(sessions) == 2
            assert sessions[0]["id"] == "term-1"
            assert sessions[1]["name"] == "zsh"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_read_terminal(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            output = await client.read_terminal("term-1", 20)
            assert "hello" in output
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_execute_command(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.execute_command("ls -la", "term-1")
            assert "Executed" in result
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_split_pane(self, mock_server: asyncio.AbstractServer, server_port: int) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.split_pane("v", "term-1")
            assert result["new_session_id"] == "term-3"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_send_control(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.send_control("c", "term-1")
            assert "control key" in result
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_get_active_session(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.get_active_session()
            assert result == "term-1"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_is_ai_session(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.is_ai_session("term-1")
            assert result is False
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_create_tab(self, mock_server: asyncio.AbstractServer, server_port: int) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.create_tab()
            assert result["new_session_id"] == "term-4"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_set_appearance(
        self, mock_server: asyncio.AbstractServer, server_port: int,
    ) -> None:
        client = IDEBridgeClient("test", server_port)
        await client.connect()
        try:
            result = await client.set_appearance(title="test")
            assert "title" in result
        finally:
            await client.disconnect()
