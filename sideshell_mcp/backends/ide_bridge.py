"""IDE Bridge Protocol - shared WebSocket client for VSCode/IntelliJ backends.

Both IDE backends (VSCode extension, IntelliJ plugin) run a WebSocket server
on localhost. This module provides the client-side protocol implementation.

Discovery: extensions write their port to ~/.sideshell/<ide>-port
Protocol: JSON-RPC 2.0 over WebSocket

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

# Port file directory
SIDESHELL_DIR = Path.home() / ".sideshell"

# Default ports
DEFAULT_VSCODE_PORT = 46117
DEFAULT_INTELLIJ_PORT = 46118


class IDEBridgeError(Exception):
    """Error communicating with IDE bridge."""


class IDEBridgeClient:
    """WebSocket client for communicating with IDE terminal extensions.

    The IDE extension/plugin runs a WebSocket server on localhost.
    This client connects to it and sends JSON-RPC 2.0 requests.
    """

    def __init__(self, ide_name: str, default_port: int) -> None:
        self.ide_name = ide_name
        self.default_port = default_port
        self._ws: Any = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = False
        self._port: int | None = None
        self._token: str | None = None

    @property
    def port_file(self) -> Path:
        return SIDESHELL_DIR / f"{self.ide_name}-port"

    def _discover_port_and_token(self) -> tuple[int, str | None]:
        """Discover the port and auth token from the port file.

        Returns:
            (port, token) tuple. Token may be None if not present.
        """
        if self.port_file.exists():
            try:
                content = self.port_file.read_text().strip()
                data = json.loads(content)
                if isinstance(data, dict):
                    port = int(data.get("port", self.default_port))
                    token = data.get("token")
                    logger.debug(f"Discovered {self.ide_name} port: {port}")
                    return port, token
                else:
                    return int(data), None
            except (json.JSONDecodeError, ValueError):
                try:
                    return int(content), None
                except ValueError:
                    pass
        return self.default_port, None

    async def connect(self) -> bool:
        """Connect to the IDE WebSocket server."""
        try:
            import websockets

            self._port, self._token = self._discover_port_and_token()
            uri = f"ws://127.0.0.1:{self._port}"
            if self._token:
                uri += f"?token={self._token}"
            logger.info(f"Connecting to {self.ide_name} at ws://127.0.0.1:{self._port}")

            self._ws = await asyncio.wait_for(
                websockets.connect(uri),
                timeout=5.0,
            )
            self._connected = True
            self._reader_task = asyncio.create_task(self._read_loop())
            logger.info(f"Connected to {self.ide_name}")
            return True
        except ImportError:
            raise IDEBridgeError(
                "websockets package required for IDE backends. "
                "Install with: pip install websockets"
            ) from None
        except (OSError, TimeoutError) as e:
            logger.warning(f"Cannot connect to {self.ide_name}: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the IDE WebSocket server."""
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        # Cancel pending futures
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def ensure_connection(self) -> None:
        """Ensure we're connected, reconnect if needed."""
        if not self._connected or self._ws is None:
            success = await self.connect()
            if not success:
                raise IDEBridgeError(
                    f"Cannot connect to {self.ide_name} extension. "
                    f"Make sure the sideshell extension is installed "
                    f"and running in {self.ide_name}."
                )

    async def _read_loop(self) -> None:
        """Read responses from the WebSocket."""
        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    req_id = data.get("id")
                    if req_id is not None and req_id in self._pending:
                        future = self._pending.pop(req_id)
                        if not future.done():
                            if "error" in data:
                                future.set_exception(
                                    IDEBridgeError(data["error"].get("message", "Unknown error"))
                                )
                            else:
                                future.set_result(data.get("result"))
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from {self.ide_name}: {message[:200]}")
        except Exception as e:
            logger.debug(f"WebSocket read loop ended: {e}")
            self._connected = False

    async def call(self, method: str, params: dict[str, Any] | None = None,
                   timeout: float = 30.0) -> Any:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: RPC method name.
            params: Method parameters.
            timeout: Response timeout in seconds.

        Returns:
            Response result.
        """
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
            await self._ws.send(json.dumps(request))
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except TimeoutError:
            self._pending.pop(req_id, None)
            raise IDEBridgeError(
                f"Timeout waiting for {method} response "
                f"from {self.ide_name}"
            ) from None
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

    async def split_pane(self, direction: str, session_id: str | None = None) -> dict[str, Any]:
        return await self.call("split_pane", {"session_id": session_id, "direction": direction})

    async def create_tab(
        self, profile: str | None = None, command: str | None = None
    ) -> dict[str, Any]:
        return await self.call("create_tab", {"profile": profile, "command": command})

    async def create_window(
        self, profile: str | None = None, command: str | None = None
    ) -> dict[str, Any]:
        return await self.call("create_window", {"profile": profile, "command": command})

    async def focus_session(self, session_id: str) -> str:
        return await self.call("focus_session", {"session_id": session_id})

    async def close_session(self, session_id: str | None = None) -> str:
        return await self.call("close_session", {"session_id": session_id})

    async def clear_terminal(self, session_id: str | None = None) -> str:
        return await self.call("clear_terminal", {"session_id": session_id})

    async def get_terminal_state(self, session_id: str | None = None) -> dict[str, Any]:
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


def write_port_file(ide_name: str, port: int, pid: int | None = None) -> Path:
    """Write port file for IDE extension discovery (called by extensions).

    Args:
        ide_name: IDE name (vscode, intellij).
        port: WebSocket server port.
        pid: Optional PID of the IDE process.

    Returns:
        Path to the port file.
    """
    SIDESHELL_DIR.mkdir(parents=True, exist_ok=True)
    port_file = SIDESHELL_DIR / f"{ide_name}-port"
    data = {"port": port, "pid": pid or os.getpid()}
    port_file.write_text(json.dumps(data))
    return port_file


def remove_port_file(ide_name: str) -> None:
    """Remove port file on extension shutdown."""
    port_file = SIDESHELL_DIR / f"{ide_name}-port"
    port_file.unlink(missing_ok=True)
