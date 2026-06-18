"""Tests for IDE bridge protocol - Unix socket client/server communication."""

from __future__ import annotations

import asyncio
import json
import shutil
import stat
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.ide_bridge import (
    DEFAULT_INTELLIJ_PORT,
    DEFAULT_VSCODE_PORT,
    IDEBridgeClient,
    IDEBridgeError,
    remove_port_file,
    write_socket_file,
)


class TestSocketFileManagement:
    """Tests for socket/port file read/write."""

    def test_write_socket_file(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            sock = str(tmp_path / "vscode.sock")
            result = write_socket_file("vscode", sock, "tok123", pid=12345)
            assert result.exists()
            assert result == tmp_path / "vscode-port"
            data = json.loads(result.read_text())
            assert data["socket"] == sock
            assert data["token"] == "tok123"
            assert data["pid"] == 12345
            assert data["ide"] == "vscode"

    def test_write_socket_file_chmods_600(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            result = write_socket_file("vscode", str(tmp_path / "vscode.sock"), "tok")
            mode = stat.S_IMODE(result.stat().st_mode)
            assert mode == 0o600

    def test_write_socket_file_default_pid(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            result = write_socket_file("vscode", str(tmp_path / "vscode.sock"), "tok")
            data = json.loads(result.read_text())
            # When pid not given, falls back to current process pid
            assert isinstance(data["pid"], int)
            assert data["pid"] > 0

    def test_remove_port_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        sock_file = tmp_path / "vscode.sock"
        port_file.write_text('{"socket": "/x.sock", "token": "t"}')
        sock_file.write_text("")
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            remove_port_file("vscode")
            assert not port_file.exists()
            assert not sock_file.exists()

    def test_remove_nonexistent_port_file(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            # Should not raise even if neither file exists
            remove_port_file("vscode")


class TestIDEBridgeClient:
    """Tests for the Unix socket client."""

    def test_default_ports(self) -> None:
        assert DEFAULT_VSCODE_PORT == 46117
        assert DEFAULT_INTELLIJ_PORT == 46118

    def test_client_initialization(self) -> None:
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
        assert client.ide_name == "vscode"
        assert client.default_port == DEFAULT_VSCODE_PORT
        assert not client._connected

    def test_port_file_and_socket_path_props(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            assert client.port_file == tmp_path / "vscode-port"
            assert client.socket_path == tmp_path / "vscode.sock"

    def test_discover_socket_from_json_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text(json.dumps({"socket": "/custom/path.sock"}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            sock, token = client._discover_socket()
            assert sock == "/custom/path.sock"
            assert token is None

    def test_discover_socket_and_token_from_json(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text(json.dumps({"socket": "/custom/path.sock", "token": "abc123"}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            sock, token = client._discover_socket()
            assert sock == "/custom/path.sock"
            assert token == "abc123"

    def test_discover_socket_default_when_no_file(self, tmp_path: Path) -> None:
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            sock, token = client._discover_socket()
            assert sock == str(tmp_path / "vscode.sock")
            assert token is None

    def test_discover_socket_default_when_bad_json(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text("not-json-at-all")

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            sock, token = client._discover_socket()
            assert sock == str(tmp_path / "vscode.sock")
            assert token is None

    def test_discover_socket_falls_back_socket_when_token_absent(
        self,
        tmp_path: Path,
    ) -> None:
        port_file = tmp_path / "vscode-port"
        # JSON dict without a "socket" key -> falls back to socket_path,
        # token absent -> None
        port_file.write_text(json.dumps({"pid": 999}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)
            sock, token = client._discover_socket()
            assert sock == str(tmp_path / "vscode.sock")
            assert token is None

    @pytest.mark.asyncio
    async def test_connect_fails_gracefully(self, tmp_path: Path) -> None:
        """Should return False when no server is listening."""
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            # No port file, no socket file -> nonexistent socket path
            client = IDEBridgeClient("nosuchide", 39173)
            result = await client.connect()
            assert result is False
            assert not client._connected

    @pytest.mark.asyncio
    async def test_ensure_connection_raises_with_instructions(
        self,
        tmp_path: Path,
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
        assert client._writer is None
        assert client._reader is None


class TestIDEBridgeProtocol:
    """Tests for JSON-RPC protocol formatting."""

    @pytest.mark.asyncio
    async def test_call_formats_request_correctly(self) -> None:
        """Should format JSON-RPC 2.0 requests correctly."""
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)

        # Mock the writer; capture what gets written to the socket.
        sent_messages: list[bytes] = []
        mock_writer = AsyncMock()
        mock_writer.write = lambda data: sent_messages.append(data)
        mock_writer.drain = AsyncMock()
        client._writer = mock_writer
        client._connected = True

        # Manually resolve the pending future for request id 1.
        async def respond_after_delay() -> None:
            await asyncio.sleep(0.05)
            if 1 in client._pending and not client._pending[1].done():
                client._pending[1].set_result(["session1", "session2"])

        task = asyncio.create_task(respond_after_delay())

        result = await client.call("list_sessions", timeout=5.0)

        assert result == ["session1", "session2"]
        assert len(sent_messages) == 1

        # Strip trailing newline framing and parse.
        request = json.loads(sent_messages[0].decode().strip())
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "list_sessions"
        assert request["id"] == 1

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_includes_params(self) -> None:
        """Should include params when provided."""
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)

        sent_messages: list[bytes] = []
        mock_writer = AsyncMock()
        mock_writer.write = lambda data: sent_messages.append(data)
        mock_writer.drain = AsyncMock()
        client._writer = mock_writer
        client._connected = True

        async def respond_after_delay() -> None:
            await asyncio.sleep(0.05)
            if 1 in client._pending and not client._pending[1].done():
                client._pending[1].set_result("ok")

        task = asyncio.create_task(respond_after_delay())
        await client.call("read_terminal", {"session_id": "x", "lines": 5}, timeout=5.0)

        request = json.loads(sent_messages[0].decode().strip())
        assert request["params"] == {"session_id": "x", "lines": 5}

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_call_timeout(self) -> None:
        """Should raise IDEBridgeError on timeout."""
        client = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)

        mock_writer = AsyncMock()
        mock_writer.write = lambda data: None
        mock_writer.drain = AsyncMock()
        client._writer = mock_writer
        client._connected = True

        with pytest.raises(IDEBridgeError, match="Timeout"):
            await client.call("slow_method", timeout=0.1)
        # Pending future cleaned up after timeout.
        assert not client._pending


# Routed mock responses shared by the E2E server.
E2E_RESPONSES: dict[str, object] = {
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


class TestIDEBridgeE2E:
    """End-to-end tests with a real asyncio Unix-socket echo server."""

    @pytest.fixture
    def short_dir(self):
        """A short temp dir so AF_UNIX socket paths fit the 104-byte limit.

        pytest's tmp_path can exceed the macOS AF_UNIX path limit, so the
        E2E Unix-socket server needs a shorter base directory.
        """
        path = Path(tempfile.mkdtemp(prefix="ssh_"))
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

    @pytest.fixture
    async def server_socket(self, short_dir: Path):
        """Start a Unix-socket JSON-RPC echo server; yield its socket path."""
        sock_path = short_dir / "test.sock"

        async def handle(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            # First line is the auth handshake: {"type":"auth","token":...}.
            auth_line = await reader.readline()
            if not auth_line:
                writer.close()
                return
            auth = json.loads(auth_line.decode())
            assert auth.get("type") == "auth"
            writer.write(json.dumps({"ok": True}).encode() + b"\n")
            await writer.drain()

            # Then handle JSON-RPC requests line by line.
            while True:
                line = await reader.readline()
                if not line:
                    break
                request = json.loads(line.decode())
                method = request.get("method", "")
                req_id = request.get("id")
                result = E2E_RESPONSES.get(method, f"Unknown: {method}")
                response = {"jsonrpc": "2.0", "id": req_id, "result": result}
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()

        server = await asyncio.start_unix_server(handle, path=str(sock_path))
        try:
            yield sock_path
        finally:
            server.close()
            await server.wait_closed()

    async def _make_client(
        self,
        base_dir: Path,
        sock_path: Path,
    ) -> IDEBridgeClient:
        """Build a client whose discovery points at the running server."""
        port_file = base_dir / "test-port"
        port_file.write_text(json.dumps({"socket": str(sock_path), "token": "secret"}))
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", base_dir):
            client = IDEBridgeClient("test", 39999)
            await client.connect()
        return client

    @pytest.mark.asyncio
    async def test_connect_handshake(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            assert client._connected
            assert client._token == "secret"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_list_sessions(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            sessions = await client.list_sessions()
            assert len(sessions) == 2
            assert sessions[0]["id"] == "term-1"
            assert sessions[1]["name"] == "zsh"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_read_terminal(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            output = await client.read_terminal("term-1", 20)
            assert "hello" in output
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_execute_command(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            result = await client.execute_command("ls -la", "term-1")
            assert "Executed" in result
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_split_pane(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            result = await client.split_pane("v", "term-1")
            assert result["new_session_id"] == "term-3"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_get_active_session(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            result = await client.get_active_session()
            assert result == "term-1"
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_is_ai_session(
        self,
        short_dir: Path,
        server_socket: Path,
    ) -> None:
        client = await self._make_client(short_dir, server_socket)
        try:
            result = await client.is_ai_session("term-1")
            assert result is False
        finally:
            await client.disconnect()
