"""maquake backend implementation.

maquake is a macOS drop-down terminal with a Unix domain socket API.
Socket path: /tmp/maquake.sock
Protocol: JSON request/response over Unix socket.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket

from .base import (
    ControlKey,
    SessionInfo,
    SplitDirection,
    TerminalBackend,
)

logger = logging.getLogger(__name__)

MAQUAKE_SOCKET = "/tmp/maquake.sock"


class MaQuakeBackend(TerminalBackend):
    """maquake backend using Unix domain socket API.

    maquake is a drop-down terminal (Quake-style) for macOS.
    It supports tabs but not splits.

    Session IDs are UUIDs assigned by maquake to each tab.
    """

    def __init__(self) -> None:
        self._connected = False

    @property
    def name(self) -> str:
        return "maquake"

    @property
    def is_available(self) -> bool:
        return os.path.exists(MAQUAKE_SOCKET)

    async def _send(self, payload: dict) -> dict:
        """Send JSON request to maquake socket and return response.

        maquake uses a request-response protocol: connect, send JSON,
        read response, server closes connection. Uses blocking socket
        in a thread to match nc behavior exactly.
        """
        data = json.dumps(payload).encode() + b"\n"

        def _socket_rpc() -> bytes:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(MAQUAKE_SOCKET)
            sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            sock.close()
            return b"".join(chunks)

        try:
            response = await asyncio.get_running_loop().run_in_executor(None, _socket_rpc)
            return json.loads(response.decode())
        except json.JSONDecodeError as e:
            logger.error(f"maquake invalid JSON response: {e}")
            return {"ok": False, "error": f"Invalid JSON: {e}"}
        except Exception as e:
            logger.error(f"maquake socket error: {e}")
            return {"ok": False, "error": str(e)}

    async def connect(self) -> bool:
        resp = await self._send({"action": "state"})
        if resp.get("ok"):
            self._connected = True
            logger.info("Connected to maquake")
            return True
        logger.error(f"Failed to connect to maquake: {resp.get('error')}")
        return False

    async def ensure_connection(self) -> None:
        if not self._connected:
            await self.connect()

    async def disconnect(self) -> None:
        self._connected = False

    # --- Session Management ---

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        if session_id:
            # Find specific tab
            resp = await self._send({"action": "list"})
            if not resp.get("ok"):
                return None
            for tab in resp.get("tabs", []):
                if tab["session_id"] == session_id:
                    return self._tab_to_session(tab)
            return None

        # Get active session
        resp = await self._send({"action": "state"})
        if not resp.get("ok"):
            return None
        active_id = resp.get("active_session_id")
        if not active_id:
            return None
        return await self.get_session(active_id)

    def _tab_to_session(self, tab: dict) -> SessionInfo:
        return SessionInfo(
            session_id=tab["session_id"],
            name=tab.get("title", "maquake"),
            path=tab.get("cwd", "~"),
            job=tab.get("title", "shell"),
            at_prompt=True,  # maquake doesn't expose running command info
        )

    async def list_sessions(self) -> str:
        resp = await self._send({"action": "list"})
        if not resp.get("ok"):
            return f"Error: {resp.get('error', 'unknown')}"

        tabs = resp.get("tabs", [])
        result = [f"Total: {len(tabs)} tabs\n"]
        for tab in tabs:
            indicator = "●" if tab.get("active") else "○"
            title = tab.get("title", "untitled")
            cwd = tab.get("cwd", "~")
            sid = tab["session_id"]
            result.append(f"  {indicator} {title} @ {cwd} [{sid}]")
        return "\n".join(result)

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        if session_id:
            info = await self.get_session(session_id)
            if not info:
                return "Session not found"
            return json.dumps({
                "session_id": info.session_id,
                "name": info.name,
                "path": info.path,
                "job": info.job,
                "at_prompt": info.at_prompt,
            }, indent=2)

        state_resp = await self._send({"action": "state"})
        list_resp = await self._send({"action": "list"})

        state = {
            "visible": state_resp.get("visible"),
            "pinned": state_resp.get("pinned"),
            "tab_count": state_resp.get("tab_count", 0),
            "active_session": state_resp.get("active_session_id"),
            "width_percent": state_resp.get("width_percent"),
            "height_percent": state_resp.get("height_percent"),
            "tabs": list_resp.get("tabs", []),
        }
        return json.dumps(state, indent=2)

    async def is_ai_session(self, session_id: str) -> bool:
        # maquake doesn't expose running command, so we can't detect AI sessions
        return False

    async def get_current_active_session_id(self) -> str | None:
        resp = await self._send({"action": "state"})
        return resp.get("active_session_id") if resp.get("ok") else None

    # --- Command Execution ---

    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,  # noqa: ASYNC109
        watch_for: str = "prompt",
    ) -> str:
        payload: dict = {"action": "execute", "command": command}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._send(payload)
        if not resp.get("ok"):
            return f"Error: {resp.get('error', 'unknown')}"

        if not wait:
            return f"Sent: {command}"

        return await self._wait_for_completion(
            session_id or resp.get("session_id"),
            timeout,
            watch_for,
        )

    async def _wait_for_completion(
        self,
        session_id: str | None,
        timeout: int,  # noqa: ASYNC109
        watch_for: str,
    ) -> str:
        start = asyncio.get_running_loop().time()
        last_output = ""
        last_change = start
        poll_interval = 0.2

        while True:
            elapsed = asyncio.get_running_loop().time() - start
            if elapsed >= timeout:
                return f"Timed out after {timeout}s"

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 1.0)

            payload: dict = {"action": "read", "lines": 50}
            if session_id:
                payload["session_id"] = session_id
            resp = await self._send(payload)

            current = "\n".join(resp.get("lines", []))

            if watch_for == "output":
                if current and current != last_output:
                    return f"Output detected in {elapsed:.1f}s"

            elif watch_for == "silence":
                if current != last_output:
                    last_output = current
                    last_change = asyncio.get_running_loop().time()
                    poll_interval = 0.2
                elif asyncio.get_running_loop().time() - last_change >= 2.0:
                    return f"Completed (silence) in {elapsed:.1f}s:\n{current[-2000:]}"

            else:  # prompt
                if current != last_output:
                    last_output = current
                    last_change = asyncio.get_running_loop().time()
                    poll_interval = 0.2
                elif asyncio.get_running_loop().time() - last_change >= 2.0:
                    return f"Completed (stability) in {elapsed:.1f}s:\n{current[-2000:]}"

    async def send_text(self, text: str, session_id: str | None = None) -> str:
        payload: dict = {"action": "paste", "text": text}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._send(payload)
        if resp.get("ok"):
            return f"Pasted {len(text)} characters"
        return f"Error: {resp.get('error', 'unknown')}"

    async def send_control(self, key: ControlKey, session_id: str | None = None) -> str:
        # maquake supports: c, d, z, a, e, k, l, u, w, enter, esc, tab
        supported = {
            ControlKey.C, ControlKey.D, ControlKey.Z,
            ControlKey.A, ControlKey.E, ControlKey.K,
            ControlKey.L, ControlKey.U, ControlKey.W,
            ControlKey.ENTER, ControlKey.ESC, ControlKey.TAB,
        }
        if key not in supported:
            keys = ", ".join(k.value for k in supported)
            return f"Key '{key.value}' not supported by maquake ({keys})"

        payload: dict = {"action": "control-char", "key": key.value}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._send(payload)
        if not resp.get("ok"):
            return f"Error: {resp.get('error', 'unknown')}"

        if key == ControlKey.ENTER:
            return "Sent Enter key"
        elif key == ControlKey.ESC:
            return "Sent Escape key"
        return f"Sent Ctrl+{key.value.upper()}"

    # --- Terminal Reading ---

    async def read_terminal(self, lines: int = 20, session_id: str | None = None) -> str:
        payload: dict = {"action": "read", "lines": lines}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._send(payload)
        if not resp.get("ok"):
            return f"Error: {resp.get('error', 'unknown')}"

        content = "\n".join(resp.get("lines", []))
        rows = resp.get("rows", 0)
        cols = resp.get("cols", 0)

        return f"Last {lines} lines ({cols}x{rows}):\n{content}"

    async def clear_terminal(self, session_id: str | None = None) -> str:
        # Send Ctrl+L to clear
        return await self.send_control(ControlKey.L, session_id)

    # --- Session Creation ---

    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        # maquake is a drop-down terminal — no split support, create a new tab instead
        return await self.create_tab()

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        # maquake show + new tab
        await self._send({"action": "show"})
        result = await self.create_tab(command=command)
        return result

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        resp = await self._send({"action": "new-tab"})
        if not resp.get("ok"):
            return f"Error: {resp.get('error', 'unknown')}"

        new_id = resp.get("session_id", "unknown")
        result = f"New tab created: {new_id}"

        if command:
            await asyncio.sleep(0.3)
            await self._send({"action": "execute", "command": command, "session_id": new_id})
            result += f" (ran: {command})"

        return result

    async def create_session(self, profile: str | None = None) -> str:
        return await self.create_tab(profile=profile)

    # --- Focus Management ---

    async def focus_session(self, session_id: str) -> str:
        resp = await self._send({"action": "focus", "session_id": session_id})
        if resp.get("ok"):
            return f"Focused tab {session_id}"
        return f"Error: {resp.get('error', 'unknown')}"

    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        payload: dict = {"action": "close-session"}
        if session_id:
            payload["session_id"] = session_id

        resp = await self._send(payload)
        if resp.get("ok"):
            return f"Closed tab {session_id or '(active)'}"
        return f"Error: {resp.get('error', 'unknown')}"

    # --- Appearance ---

    async def set_appearance(
        self,
        session_id: str | None = None,
        title: str | None = None,
        color: str | None = None,
        badge: str | None = None,
    ) -> str:
        return "Appearance settings not supported by maquake"

    async def show_alert(self, title: str, message: str) -> str:
        return "Alerts not supported by maquake"

    # --- maquake-specific: Window Control ---

    async def toggle(self) -> str:
        resp = await self._send({"action": "toggle"})
        return "Toggled" if resp.get("ok") else f"Error: {resp.get('error')}"

    async def show(self) -> str:
        resp = await self._send({"action": "show"})
        return "Shown" if resp.get("ok") else f"Error: {resp.get('error')}"

    async def hide(self) -> str:
        resp = await self._send({"action": "hide"})
        return "Hidden" if resp.get("ok") else f"Error: {resp.get('error')}"

    async def pin(self) -> str:
        resp = await self._send({"action": "pin"})
        return "Pinned" if resp.get("ok") else f"Error: {resp.get('error')}"

    async def unpin(self) -> str:
        resp = await self._send({"action": "unpin"})
        return "Unpinned" if resp.get("ok") else f"Error: {resp.get('error')}"
