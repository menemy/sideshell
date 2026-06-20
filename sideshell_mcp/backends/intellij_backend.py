"""IntelliJ IDEA terminal backend via Unix socket bridge.

This backend connects to the sideshell IntelliJ plugin which runs
a Unix domain socket server inside the IDE, exposing terminal control APIs.

Compatible with all JetBrains IDEs: IntelliJ IDEA, PyCharm, WebStorm,
GoLand, RustRover, Android Studio, PhpStorm, etc.

Install the plugin:
  - From JetBrains Marketplace: search for "sideshell"
  - Or: Settings -> Plugins -> Install from disk -> sideshell-terminal.zip
"""

from __future__ import annotations

import json
import logging

from .base import ControlKey, SessionInfo, SplitDirection, TerminalBackend
from .ide_bridge import DEFAULT_INTELLIJ_PORT, IDEBridgeClient, IDEBridgeError

logger = logging.getLogger(__name__)

INSTALL_INSTRUCTIONS = """
The sideshell JetBrains plugin isn't running, so this backend can't connect.

Note: only the JetBrains and VS Code backends need an extension. If you just need
a visible terminal, switch to a backend that needs none -- tmux, iTerm2, Ghostty,
WezTerm, Kitty, or maquake -- e.g. start the server with --backend tmux.

To use the JetBrains backend, install the plugin:
  - JetBrains Marketplace (once published): Settings -> Plugins -> Marketplace ->
    search "sideshell" -> Install.
  - Install now from disk: download sideshell-intellij-<version>.zip from
      https://github.com/menemy/sideshell/releases
    then Settings -> Plugins -> (gear icon) -> "Install Plugin from Disk..." and pick it.

Restart the IDE afterwards. The plugin auto-starts and listens on a Unix socket at
~/.sideshell/intellij.sock.
Works with: IntelliJ IDEA, PyCharm, WebStorm, GoLand, RustRover, PhpStorm, Android Studio.
""".strip()


class IntelliJBackend(TerminalBackend):
    """IntelliJ terminal backend using Unix socket bridge to the plugin."""

    def __init__(self) -> None:
        self._bridge = IDEBridgeClient("intellij", DEFAULT_INTELLIJ_PORT)

    @property
    def name(self) -> str:
        return "intellij"

    @property
    def is_available(self) -> bool:
        """Check if an IntelliJ-based IDE is likely available."""
        # Check port file
        if self._bridge.port_file.exists():
            return True
        # Check common IDE process indicators
        import os

        # JetBrains Toolbox or IDE sets these
        if os.environ.get("JETBRAINS_IDE"):
            return True
        # IntelliJ terminal sets TERMINAL_EMULATOR
        if "JetBrains" in os.environ.get("TERMINAL_EMULATOR", ""):
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
            raise IDEBridgeError(INSTALL_INSTRUCTIONS) from None

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
            return "No terminal sessions found in IntelliJ IDE"

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
        return (
            f"Split {'vertically' if direction == SplitDirection.VERTICAL else 'horizontally'}. New session: {new_id}"
        )

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
        return await self._bridge.set_appearance(session_id=session_id, title=title, color=color, badge=badge)
