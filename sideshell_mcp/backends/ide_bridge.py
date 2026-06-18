"""IDE Bridge Protocol - Unix socket client for VSCode/IntelliJ backends.

Both IDE backends (VSCode extension, IntelliJ plugin) run a Unix socket server.
This module provides the client-side protocol implementation.

Discovery: extensions write socket info to ~/.sideshell/<ide>-port
Protocol: JSON-RPC 2.0 over Unix socket (newline-delimited JSON)

Methods:
  - list_sessions -> [{id, name, path, job, at_prompt}]
  - read_terminal(session_id, lines) -> str
  - send_text(session_id, text) -> str
  - execute_command(session_id, command, wait, timeout, watch_for) -> str
  - send_control(session_id, key) -> str
  - split_pane(session_id, direction) -> {new_session_id}
  - create_tab(profile, command) -> {new_session_id}
  - create_window(profile, command) -> {new_session_id}
  - focus_session(session_id) -> str
  - close_session(session_id) -> str
  - clear_terminal(session_id) -> str
  - get_terminal_state(session_id?) -> json
  - set_appearance(session_id, title, color, badge) -> str
  - get_active_session() -> {session_id}
  - is_ai_session(session_id) -> bool
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Socket directory
SIDESHELL_DIR = Path.home() / ".sideshell"

# Default socket paths
DEFAULT_VSCODE_PORT = 46117  # kept for backward compat with port file parsing
DEFAULT_INTELLIJ_PORT = 46118


class IDEBridgeError(Exception):
    """Error communicating with IDE bridge."""


class IDEBridgeClient:
    """Unix socket client for communicating with IDE terminal extensions.

    The IDE extension/plugin runs a Unix socket server.
    This client connects to it and sends JSON-RPC 2.0 requests
    as newline-delimited JSON.
    """

    def __init__(self, ide_name: str, default_port: int) -> None:
        self.ide_name = ide_name
        self.default_port = default_port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = False
        self._token: str | None = None

    @property
    def port_file(self) -> Path:
        return SIDESHELL_DIR / f"{self.ide_name}-port"

    @property
    def socket_path(self) -> Path:
        return SIDESHELL_DIR / f"{self.ide_name}.sock"

    def _discover_socket(self) -> tuple[str, str | None]:
        """Discover the socket path and auth token.

        Reads port file for socket path and token.
        Falls back to well-known socket path.

        Returns:
            (socket_path, token) tuple. Token may be None.
        """
        if self.port_file.exists():
            try:
                content = self.port_file.read_text().strip()
                data = json.loads(content)
                if isinstance(data, dict):
                    sock = data.get("socket", str(self.socket_path))
                    token = data.get("token")
                    logger.debug(f"Discovered {self.ide_name} socket: {sock}")
                    return sock, token
            except (json.JSONDecodeError, ValueError):
                pass
        return str(self.socket_path), None

    async def connect(self) -> bool:
        """Connect to the IDE Unix socket server."""
        try:
            sock_path, self._token = self._discover_socket()
            logger.info(f"Connecting to {self.ide_name} at {sock_path}")

            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(sock_path),
                timeout=5.0,
            )

            # Send token handshake as first message
            handshake = {"type": "auth", "token": self._token or ""}
            self._writer.write(json.dumps(handshake).encode() + b"\n")
            await self._writer.drain()

            # Read auth response
            line = await asyncio.wait_for(self._reader.readline(), timeout=5.0)
            resp = json.loads(line.decode())
            if not resp.get("ok"):
                err = resp.get("error", "auth failed")
                logger.warning(f"Auth rejected by {self.ide_name}: {err}")
                self._writer.close()
                return False

            self._connected = True
            self._reader_task = asyncio.create_task(self._read_loop())
            logger.info(f"Connected to {self.ide_name}")
            return True
        except (OSError, TimeoutError) as e:
            logger.warning(f"Cannot connect to {self.ide_name}: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the IDE socket."""
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
        # Cancel pending futures
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def ensure_connection(self) -> None:
        """Ensure we're connected, reconnect if needed."""
        if not self._connected or self._writer is None:
            success = await self.connect()
            if not success:
                raise IDEBridgeError(
                    f"Cannot connect to {self.ide_name} extension. "
                    f"Make sure the sideshell extension is installed "
                    f"and running in {self.ide_name}."
                )

    async def _read_loop(self) -> None:
        """Read responses from the Unix socket (newline-delimited JSON)."""
        try:
            while self._reader and not self._reader.at_eof():
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode())
                    req_id = data.get("id")
                    if req_id is not None and req_id in self._pending:
                        future = self._pending.pop(req_id)
                        if not future.done():
                            if "error" in data:
                                future.set_exception(IDEBridgeError(data["error"].get("message", "Unknown error")))
                            else:
                                future.set_result(data.get("result"))
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from {self.ide_name}")
        except Exception as e:
            logger.debug(f"Socket read loop ended: {e}")
            self._connected = False

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Send a JSON-RPC request and wait for response."""
        await self.ensure_connection()

        self._request_id += 1
        req_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            self._writer.write(json.dumps(request).encode() + b"\n")  # type: ignore[union-attr]
            await self._writer.drain()  # type: ignore[union-attr]
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except TimeoutError:
            self._pending.pop(req_id, None)
            raise IDEBridgeError(f"Timeout waiting for {method} response from {self.ide_name}") from None
        except Exception:
            self._pending.pop(req_id, None)
            raise

    # === High-level methods matching TerminalBackend API ===

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await self.call("list_sessions")

    async def read_terminal(self, session_id: str | None = None, lines: int = 20) -> str:
        return await self.call("read_terminal", {"session_id": session_id, "lines": lines})

    async def send_text(self, session_id: str | None = None, text: str = "") -> str:
        return await self.call("send_text", {"session_id": session_id, "text": text})

    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,
        watch_for: str = "prompt",
    ) -> str:
        return await self.call(
            "execute_command",
            {
                "command": command,
                "session_id": session_id,
                "wait": wait,
                "timeout": timeout,
                "watch_for": watch_for,
            },
            timeout=float(timeout) + 5.0,
        )

    async def send_control(self, key: str, session_id: str | None = None) -> str:
        return await self.call("send_control", {"session_id": session_id, "key": key})

    async def split_pane(
        self,
        direction: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.call(
            "split_pane",
            {"session_id": session_id, "direction": direction},
        )

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> dict[str, Any]:
        return await self.call("create_tab", {"profile": profile, "command": command})

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> dict[str, Any]:
        return await self.call("create_window", {"profile": profile, "command": command})

    async def focus_session(self, session_id: str) -> str:
        return await self.call("focus_session", {"session_id": session_id})

    async def close_session(self, session_id: str | None = None) -> str:
        return await self.call("close_session", {"session_id": session_id})

    async def clear_terminal(self, session_id: str | None = None) -> str:
        return await self.call("clear_terminal", {"session_id": session_id})

    async def get_terminal_state(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.call("get_terminal_state", {"session_id": session_id})

    async def set_appearance(
        self,
        session_id: str | None = None,
        title: str | None = None,
        color: str | None = None,
        badge: str | None = None,
    ) -> str:
        return await self.call(
            "set_appearance",
            {"session_id": session_id, "title": title, "color": color, "badge": badge},
        )

    async def get_active_session(self) -> str | None:
        result = await self.call("get_active_session")
        if isinstance(result, dict):
            return result.get("session_id")
        return result

    async def is_ai_session(self, session_id: str) -> bool:
        return await self.call("is_ai_session", {"session_id": session_id})

    async def return_focus(self, session_id: str | None = None) -> str:
        return await self.call("return_focus", {"session_id": session_id})


def write_socket_file(
    ide_name: str,
    socket_path: str,
    token: str,
    pid: int | None = None,
) -> Path:
    """Write socket info file for client discovery.

    Args:
        ide_name: IDE name (vscode, intellij).
        socket_path: Path to the Unix socket.
        token: Auth token.
        pid: Optional PID of the IDE process.

    Returns:
        Path to the info file.
    """
    SIDESHELL_DIR.mkdir(parents=True, exist_ok=True)
    port_file = SIDESHELL_DIR / f"{ide_name}-port"
    data = {
        "socket": socket_path,
        "token": token,
        "pid": pid or os.getpid(),
        "ide": ide_name,
    }
    port_file.write_text(json.dumps(data))
    port_file.chmod(0o600)
    return port_file


def remove_port_file(ide_name: str) -> None:
    """Remove port/socket file on extension shutdown."""
    port_file = SIDESHELL_DIR / f"{ide_name}-port"
    port_file.unlink(missing_ok=True)
    # Also remove socket file
    sock_file = SIDESHELL_DIR / f"{ide_name}.sock"
    sock_file.unlink(missing_ok=True)
