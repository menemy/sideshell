"""VSCode terminal backend via WebSocket bridge.

This backend connects to the sideshell VSCode extension which runs
a WebSocket server inside VSCode, exposing terminal control APIs.

Install the extension:
  code --install-extension sideshell.sideshell-terminal

Or from VS Code Marketplace: search for "sideshell"
"""

from __future__ import annotations

import json
import logging
import shutil

from .base import ControlKey, SessionInfo, SplitDirection, TerminalBackend
from .ide_bridge import DEFAULT_VSCODE_PORT, IDEBridgeClient, IDEBridgeError

logger = logging.getLogger(__name__)

INSTALL_INSTRUCTIONS = """
sideshell VSCode extension is not running.

To install:
  1. Install from VS Code Marketplace:
     code --install-extension sideshell.sideshell-terminal

  2. Or install from .vsix file:
     code --install-extension sideshell-terminal-0.1.0.vsix

  3. Restart VS Code or reload the window (Cmd+Shift+P -> "Reload Window")

The extension starts automatically and listens on localhost:{port}.
""".strip()


class VSCodeBackend(TerminalBackend):
    """VSCode terminal backend using WebSocket bridge to the extension."""

    def __init__(self) -> None:
        self._bridge = IDEBridgeClient("vscode", DEFAULT_VSCODE_PORT)

    @property
    def name(self) -> str:
        return "vscode"

    @property
    def is_available(self) -> bool:
        """Check if VSCode is likely available."""
        # Check if 'code' command exists
        if shutil.which("code"):
            return True
        # Check port file
        if self._bridge.port_file.exists():
            return True
        return False

    async def connect(self) -> bool:
        try:
            return await self._bridge.connect()
        except IDEBridgeError:
            return False

    async def ensure_connection(self) -> None:
        try:
            await self._bridge.ensure_connection()
        except IDEBridgeError:
            raise IDEBridgeError(
                INSTALL_INSTRUCTIONS.format(port=self._bridge.default_port)
            )

    async def disconnect(self) -> None:
        await self._bridge.disconnect()

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        sessions = await self._bridge.list_sessions()
        if not sessions:
            return None
        if session_id:
            for s in sessions:
                if s.get("id") == session_id:
                    return SessionInfo(
                        session_id=s["id"],
                        name=s.get("name", ""),
                        path=s.get("path", ""),
                        job=s.get("job", ""),
                        at_prompt=s.get("at_prompt", False),
                    )
            return None
        # Return first/active session
        active = await self._bridge.get_active_session()
        if active:
            for s in sessions:
                if s.get("id") == active:
                    return SessionInfo(
                        session_id=s["id"],
                        name=s.get("name", ""),
                        path=s.get("path", ""),
                        job=s.get("job", ""),
                        at_prompt=s.get("at_prompt", False),
                    )
        # Fallback to first
        s = sessions[0]
        return SessionInfo(
            session_id=s["id"],
            name=s.get("name", ""),
            path=s.get("path", ""),
            job=s.get("job", ""),
            at_prompt=s.get("at_prompt", False),
        )

    async def list_sessions(self) -> str:
        sessions = await self._bridge.list_sessions()
        if not sessions:
            return "No terminal sessions found in VS Code"

        lines = [f"Total: {len(sessions)} terminals\n"]
        for s in sessions:
            status = "●" if s.get("active") else "○"
            name = s.get("name", "unnamed")
            sid = s.get("id", "?")
            path = s.get("path", "")
            lines.append(f"  {status} {name}: {path} [{sid}]")
        return "\n".join(lines)

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        state = await self._bridge.get_terminal_state(session_id)
        return json.dumps(state, indent=2) if isinstance(state, dict) else str(state)

    async def is_ai_session(self, session_id: str) -> bool:
        return await self._bridge.is_ai_session(session_id)

    async def get_current_active_session_id(self) -> str | None:
        return await self._bridge.get_active_session()

    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,
        watch_for: str = "prompt",
    ) -> str:
        return await self._bridge.execute_command(
            command=command,
            session_id=session_id,
            wait=wait,
            timeout=timeout,
            watch_for=watch_for,
        )

    async def send_text(self, text: str, session_id: str | None = None) -> str:
        return await self._bridge.send_text(session_id=session_id, text=text)

    async def send_control(self, key: ControlKey, session_id: str | None = None) -> str:
        return await self._bridge.send_control(key=key.value, session_id=session_id)

    async def read_terminal(self, lines: int = 20, session_id: str | None = None) -> str:
        return await self._bridge.read_terminal(session_id=session_id, lines=lines)

    async def clear_terminal(self, session_id: str | None = None) -> str:
        return await self._bridge.clear_terminal(session_id=session_id)

    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        result = await self._bridge.split_pane(direction=direction.value, session_id=session_id)
        new_id = result.get("new_session_id", "?") if isinstance(result, dict) else result
        return f"Split {'vertically' if direction == SplitDirection.VERTICAL else 'horizontally'}. New session: {new_id}"

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        result = await self._bridge.create_window(profile=profile, command=command)
        new_id = result.get("new_session_id", "?") if isinstance(result, dict) else result
        return f"New window created. Session: {new_id}"

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        result = await self._bridge.create_tab(profile=profile, command=command)
        new_id = result.get("new_session_id", "?") if isinstance(result, dict) else result
        return f"New tab created. Session: {new_id}"

    async def create_session(self, profile: str | None = None) -> str:
        # In VSCode, creating a new terminal is the same as creating a tab
        return await self.create_tab(profile=profile)

    async def focus_session(self, session_id: str) -> str:
        return await self._bridge.focus_session(session_id)

    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        return await self._bridge.close_session(session_id)

    async def set_appearance(
        self,
        session_id: str | None = None,
        title: str | None = None,
        color: str | None = None,
        badge: str | None = None,
    ) -> str:
        return await self._bridge.set_appearance(
            session_id=session_id, title=title, color=color, badge=badge
        )
