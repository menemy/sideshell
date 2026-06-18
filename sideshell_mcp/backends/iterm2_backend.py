"""iTerm2 backend implementation."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .base import (
    DEFAULT_ANNOTATION_PATTERNS,
    Annotation,
    AnnotationResult,
    AnnotationType,
    ControlKey,
    SessionInfo,
    SplitDirection,
    TerminalBackend,
)

logger = logging.getLogger(__name__)

# Polling constants
SILENCE_THRESHOLD_DEFAULT = 2.0
POLL_INTERVAL_MIN = 0.1
POLL_INTERVAL_MAX = 1.0
POLL_INTERVAL_GROWTH = 1.2

# Color map for appearance
COLOR_MAP = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (255, 0, 255),
    "cyan": (0, 255, 255),
    "orange": (255, 128, 0),
    "pink": (255, 128, 128),
    "gray": (128, 128, 128),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
}


def _get_screen_lines(contents: Any) -> list[str]:
    """Extract all text lines from screen contents."""
    lines = []
    for i in range(contents.number_of_lines):
        line = contents.line(i)
        lines.append(line.string if line else "")
    return lines


class ITermBackend(TerminalBackend):
    """iTerm2 backend using native Python API."""

    def __init__(self) -> None:
        """Initialize iTerm2 backend."""
        self.connection: Any | None = None
        self.app: Any | None = None
        self._iterm2: Any | None = None

    @property
    def name(self) -> str:
        """Return backend name."""
        return "iterm2"

    @property
    def is_available(self) -> bool:
        """Check if iTerm2 is available."""
        try:
            import iterm2  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_iterm2(self) -> Any:
        """Get iterm2 module (lazy import)."""
        if self._iterm2 is None:
            import iterm2

            self._iterm2 = iterm2
        return self._iterm2

    async def connect(self) -> bool:
        """Establish connection to iTerm2."""
        try:
            iterm2 = self._get_iterm2()
            self.connection = await iterm2.Connection.async_create()
            self.app = await iterm2.async_get_app(self.connection)
            logger.info("Successfully connected to iTerm2")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to iTerm2: {e}")
            return False

    async def ensure_connection(self) -> None:
        """Ensure we have an active connection to iTerm2."""
        if not self.connection or not self.app:
            await self.connect()
            return

        try:
            iterm2 = self._get_iterm2()
            self.app = await iterm2.async_get_app(self.connection)
        except Exception:
            await self.connect()

    async def disconnect(self) -> None:
        """Close connection to iTerm2."""
        self.connection = None
        self.app = None

    async def _get_session_object(self, session_id: str | None = None) -> Any | None:
        """Get iTerm2 session object by ID or current active session."""
        if not self.app:
            raise ValueError("Not connected to iTerm2")

        if session_id:
            return await self._find_session_object(session_id)

        window = self.app.current_terminal_window
        if not window:
            if self.app.windows and len(self.app.windows) > 0:
                window = self.app.windows[0]
            else:
                raise ValueError("No iTerm2 windows found")

        tab = window.current_tab
        if not tab:
            if window.tabs and len(window.tabs) > 0:
                tab = window.tabs[0]
            else:
                raise ValueError("No tabs found in window")

        session = tab.current_session
        if not session:
            if tab.sessions and len(tab.sessions) > 0:
                session = tab.sessions[0]
            else:
                raise ValueError("No sessions found in tab")

        return session

    async def _find_session_object(self, session_id: str) -> Any | None:
        """Find session object by ID."""
        if not self.app:
            return None

        for window in self.app.windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id == session_id:
                        return session
        return None

    async def _find_tab_for_session(self, session_id: str) -> Any | None:
        """Find tab containing session."""
        if not self.app:
            return None

        for window in self.app.windows:
            for tab in window.tabs:
                for session in tab.sessions:
                    if session.session_id == session_id:
                        return tab
        return None

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        """Get session info by ID or current active session."""
        session = await self._get_session_object(session_id)
        if not session:
            return None

        return SessionInfo(
            session_id=session.session_id,
            name=await session.async_get_variable("session.name") or "Unnamed",
            path=await session.async_get_variable("session.path") or "~",
            job=await session.async_get_variable("session.foregroundJob") or "shell",
            at_prompt=await session.async_get_variable("session.isAtShellPrompt") or False,
            columns=session.preferred_size.width if session.preferred_size else 0,
            rows=session.preferred_size.height if session.preferred_size else 0,
            tty=await session.async_get_variable("session.tty"),
        )

    async def list_sessions(self) -> str:
        """List all sessions with pane info."""
        if not self.app:
            return "Not connected to iTerm2"

        result: list[str] = []
        total_panes = 0

        for window in self.app.windows:
            result.append(f"Window: {window.window_id}")

            for tab in window.tabs:
                tab_title = await tab.async_get_variable("titleOverride") or f"Tab {tab.tab_id}"
                pane_count = len(tab.sessions)
                total_panes += pane_count
                pane_info = f" ({pane_count} panes)" if pane_count > 1 else ""
                result.append(f"  Tab: {tab_title} ({tab.tab_id}){pane_info}")

                for session in tab.sessions:
                    info = await self.get_session(session.session_id)
                    if info:
                        indicator = "●" if info.at_prompt else "○"
                        size = ""
                        if pane_count > 1 and session.preferred_size:
                            size = f" {session.preferred_size.width}x{session.preferred_size.height}"
                        result.append(
                            f"    {indicator} {info.name}: {info.job} @ {info.path} [{info.session_id}]{size}"
                        )

        result.insert(0, f"Total: {total_panes} panes\n")
        return "\n".join(result)

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        """Get detailed terminal state."""
        if not self.app:
            return "Not connected to iTerm2"

        try:
            if session_id:
                session = await self._get_session_object(session_id)
                if not session:
                    return "Session not found"

                info = {
                    "session_id": session.session_id,
                    "name": await session.async_get_variable("session.name") or "Unnamed",
                    "path": await session.async_get_variable("session.path") or "~",
                    "job": await session.async_get_variable("session.foregroundJob") or "shell",
                    "at_prompt": await session.async_get_variable("session.isAtShellPrompt") or False,
                    "tty": await session.async_get_variable("session.tty"),
                    "columns": session.preferred_size.width if session.preferred_size else 0,
                    "rows": session.preferred_size.height if session.preferred_size else 0,
                }
                return json.dumps(info, indent=2)

            state = {
                "windows": [],
                "total_sessions": 0,
                "active_window": None,
                "active_tab": None,
                "active_session": None,
            }

            current_window = self.app.current_terminal_window
            if current_window:
                state["active_window"] = current_window.window_id
                if current_window.current_tab:
                    state["active_tab"] = current_window.current_tab.tab_id
                    if current_window.current_tab.current_session:
                        state["active_session"] = current_window.current_tab.current_session.session_id

            for window in self.app.windows:
                window_info = {"window_id": window.window_id, "tabs": []}

                for tab in window.tabs:
                    tab_info = {
                        "tab_id": tab.tab_id,
                        "title": await tab.async_get_variable("titleOverride") or f"Tab {tab.tab_id}",
                        "sessions": [],
                    }

                    for session in tab.sessions:
                        session_info = {
                            "session_id": session.session_id,
                            "name": await session.async_get_variable("session.name") or "Unnamed",
                            "path": await session.async_get_variable("session.path") or "~",
                            "job": await session.async_get_variable("session.foregroundJob") or "shell",
                            "at_prompt": await session.async_get_variable("session.isAtShellPrompt") or False,
                            "columns": session.preferred_size.width if session.preferred_size else 0,
                            "rows": session.preferred_size.height if session.preferred_size else 0,
                        }
                        tab_info["sessions"].append(session_info)
                        state["total_sessions"] += 1

                    window_info["tabs"].append(tab_info)
                state["windows"].append(window_info)

            return json.dumps(state, indent=2)
        except Exception as e:
            return f"Error getting terminal state: {e!s}"

    # Processes that are never AI sessions (shells, multiplexers, etc.)
    _NON_AI_PROCESSES = frozenset(
        {
            "zsh",
            "bash",
            "sh",
            "fish",
            "csh",
            "tcsh",
            "dash",
            "tmux",
            "screen",
            "login",
            "sshd",
            "ssh",
        }
    )

    async def is_ai_session(self, session_id: str) -> bool:
        """Check if session is running Claude Code or other AI tool."""
        session = await self._find_session_object(session_id)
        if not session:
            return False

        try:
            # Check foreground process first — shells and multiplexers
            # are never AI sessions, even if names/titles contain "claude"
            job_name = await session.async_get_variable("session.jobName")
            if job_name and job_name.lower().strip() in self._NON_AI_PROCESSES:
                return False

            last_command = await session.async_get_variable("session.lastCommand")
            if last_command and "claude" in last_command.lower():
                return True

            session_name = await session.async_get_variable("session.name")
            if session_name and "claude" in session_name.lower():
                return True

            command_line = await session.async_get_variable("session.commandLine")
            if command_line and ("mcp" in command_line.lower() or "claude" in command_line.lower()):
                return True

            if job_name and ("node" in job_name.lower() or "npx" in job_name.lower()):
                if last_command and ("claude" in last_command.lower() or "@anthropic" in last_command.lower()):
                    return True

            tab = await self._find_tab_for_session(session.session_id)
            if tab:
                tab_title = await tab.async_get_variable("titleOverride")
                if tab_title and "claude" in tab_title.lower():
                    return True

            return False
        except Exception as e:
            logger.warning(f"Error checking if session is AI: {e}")
            return False

    async def get_current_active_session_id(self) -> str | None:
        """Get the currently active/focused session ID."""
        if not self.app:
            return None

        window = self.app.current_terminal_window
        if not window:
            return None

        tab = window.current_tab
        if not tab:
            return None

        session = tab.current_session
        return session.session_id if session else None

    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,
        watch_for: str = "prompt",
    ) -> str:
        """Execute command in terminal.

        Args:
            command: Command to execute.
            session_id: Target session ID.
            wait: Wait for completion.
            timeout: Timeout in seconds.
            watch_for: What to wait for ('prompt', 'output', 'silence').
        """
        try:
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            if await self.is_ai_session(session.session_id):
                return "Cannot execute commands in AI terminal. Use 'split' to create a new pane."

            if wait:
                return await self._execute_with_wait(session, command, timeout, watch_for)

            await session.async_send_text(f"{command}\n")
            return f"Sent: {command}"
        except Exception as e:
            return f"Error: {e!s}"

    async def _execute_with_wait(
        self,
        session: Any,
        command: str,
        timeout: int,
        watch_for: str,
    ) -> str:
        """Execute command and wait for completion.

        Args:
            session: iTerm2 session object.
            command: Command to execute.
            timeout: Timeout in seconds.
            watch_for: What to wait for ('prompt', 'output', 'silence').
        """
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        initial_contents = await session.async_get_screen_contents()
        initial_lines = _get_screen_lines(initial_contents)
        initial_hash = hash(tuple(initial_lines))
        last_change_time = start_time
        poll_interval = POLL_INTERVAL_MIN

        await session.async_send_text(f"{command}\n")

        def _get_output(contents: Any) -> str:
            """Get last 25 lines of output."""
            lines = _get_screen_lines(contents)
            return "\n".join(lines[-25:])[-2000:]

        while True:
            elapsed = loop.time() - start_time
            if elapsed >= timeout:
                return f"Timed out after {timeout}s"

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * POLL_INTERVAL_GROWTH, POLL_INTERVAL_MAX)

            current_contents = await session.async_get_screen_contents()
            current_lines = _get_screen_lines(current_contents)
            current_hash = hash(tuple(current_lines))

            if watch_for == "output":
                if current_hash != initial_hash:
                    new_lines = [line for line in current_lines if line.strip() and line not in initial_lines]
                    # Ignore the echoed command line; wait for real output.
                    real_lines = self._real_output_lines(new_lines, command)
                    if real_lines:
                        return f"Output detected in {elapsed:.1f}s:\n" + "\n".join(real_lines[-20:])

            elif watch_for == "silence":
                if current_hash != initial_hash:
                    initial_hash = current_hash
                    last_change_time = loop.time()
                    poll_interval = POLL_INTERVAL_MIN
                elif (loop.time() - last_change_time) >= SILENCE_THRESHOLD_DEFAULT:
                    output = _get_output(current_contents)
                    return f"Completed (silence) in {elapsed:.1f}s:\n{output}"

            else:  # prompt
                at_prompt = await session.async_get_variable("session.isAtShellPrompt")
                if at_prompt:
                    output = _get_output(current_contents)
                    return f"Completed in {elapsed:.1f}s:\n{output}"
                if current_hash != initial_hash:
                    initial_hash = current_hash
                    last_change_time = loop.time()
                    poll_interval = POLL_INTERVAL_MIN
                elif (loop.time() - last_change_time) >= SILENCE_THRESHOLD_DEFAULT:
                    output = _get_output(current_contents)
                    return f"Completed (stability) in {elapsed:.1f}s:\n{output}"

    async def send_text(self, text: str, session_id: str | None = None) -> str:
        """Send text to terminal (paste)."""
        try:
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            if await self.is_ai_session(session.session_id):
                return "Cannot paste to AI terminal. Use 'split' to create a new pane."

            await session.async_send_text(text)
            return f"Pasted {len(text)} characters"
        except Exception as e:
            return f"Error: {e!s}"

    async def send_control(self, key: ControlKey, session_id: str | None = None) -> str:
        """Send control character."""
        session = await self._get_session_object(session_id)
        if not session:
            return "Session not found"

        if await self.is_ai_session(session.session_id):
            return "Cannot send control to AI terminal. Use 'split' to create a new pane."

        char_to_send = self.CONTROL_CHARS[key]
        await session.async_send_text(char_to_send)

        # Format response based on key type
        key_names = {
            ControlKey.ENTER: "Enter",
            ControlKey.ESC: "Escape",
            ControlKey.TAB: "Tab",
            ControlKey.BACKSPACE: "Backspace",
            ControlKey.UP: "Up arrow",
            ControlKey.DOWN: "Down arrow",
            ControlKey.LEFT: "Left arrow",
            ControlKey.RIGHT: "Right arrow",
            ControlKey.HOME: "Home",
            ControlKey.END: "End",
            ControlKey.PAGE_UP: "Page Up",
            ControlKey.PAGE_DOWN: "Page Down",
            ControlKey.INSERT: "Insert",
            ControlKey.DELETE: "Delete",
        }

        if key in key_names:
            return f"Sent {key_names[key]} key"
        elif key.value.startswith("f") and key.value[1:].isdigit():
            return f"Sent {key.value.upper()} key"
        else:
            return f"Sent Ctrl+{key.value.upper()}"

    async def read_terminal(self, lines: int = 20, session_id: str | None = None) -> str:
        """Read terminal output."""
        try:
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            contents = await session.async_get_screen_contents()
            number_of_lines = contents.number_of_lines
            start_line = max(0, number_of_lines - lines)

            output_lines: list[str] = []
            for line_num in range(start_line, number_of_lines):
                line = contents.line(line_num)
                if line:
                    output_lines.append(line.string)

            output = "\n".join(output_lines)
            at_prompt = await session.async_get_variable("session.isAtShellPrompt")

            # Get cursor position
            cursor = contents.cursor_coord
            cursor_info = f"Cursor: ({cursor.x}, {cursor.y})" if cursor else "Cursor: unknown"

            return f"Last {lines} lines:\n{output}\n\n{cursor_info}\nAt prompt: {at_prompt}"
        except Exception as e:
            return f"Error: {e!s}"

    async def clear_terminal(self, session_id: str | None = None) -> str:
        """Clear terminal screen."""
        try:
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            if await self.is_ai_session(session.session_id):
                return "Cannot clear AI terminal. Use 'split' to create a new pane."

            await session.async_send_text("\x0c")
            return "Terminal cleared"
        except Exception as e:
            return f"Error: {e!s}"

    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        """Split pane to create new terminal."""
        session = await self._get_session_object(session_id)
        if not session:
            return "Session not found"

        vertical = direction == SplitDirection.VERTICAL
        new_session = await session.async_split_pane(vertical=vertical)

        direction_text = "vertically" if vertical else "horizontally"
        return f"Split {direction_text}. New session: {new_session.session_id}"

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new window."""
        if not self.connection:
            return "Not connected to iTerm2"

        iterm2 = self._get_iterm2()
        if profile:
            window = await iterm2.Window.async_create(self.connection, profile=profile)
        else:
            window = await iterm2.Window.async_create(self.connection)

        session = window.current_tab.current_session

        if command:
            await session.async_send_text(f"{command}\n")

        return f"New window created with session_id: {session.session_id}"

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new tab."""
        if not self.app:
            return "Not connected to iTerm2"

        window = self.app.current_terminal_window
        if not window:
            if self.app.windows and len(self.app.windows) > 0:
                window = self.app.windows[0]
            else:
                return "No iTerm2 windows found"

        if profile:
            tab = await window.async_create_tab(profile=profile)
        else:
            tab = await window.async_create_tab()

        session = tab.current_session

        if command:
            await session.async_send_text(f"{command}\n")

        return f"New tab created with session_id: {session.session_id}"

    async def create_session(self, profile: str | None = None) -> str:
        """Smart session creation: split if window exists, else new tab."""
        if not self.app:
            return "Not connected to iTerm2"

        try:
            window = self.app.current_terminal_window
            if window and window.current_tab and window.current_tab.current_session:
                current_session = window.current_tab.current_session
                new_session = await current_session.async_split_pane(vertical=False, profile=profile)
                return f"Created new session (split): {new_session.session_id}"
            elif window:
                tab = await window.async_create_tab(profile=profile)
                new_session = tab.current_session
                return f"Created new session (tab): {new_session.session_id}"
            else:
                if not self.connection:
                    return "Not connected to iTerm2"
                iterm2 = self._get_iterm2()
                window = await iterm2.Window.async_create(self.connection, profile=profile)
                new_session = window.current_tab.current_session
                return f"Created new session (window): {new_session.session_id}"
        except Exception as e:
            return f"Error creating session: {e!s}"

    async def focus_session(self, session_id: str) -> str:
        """Focus specific session."""
        session = await self._find_session_object(session_id)
        if not session:
            return f"Session {session_id} not found"

        await session.async_activate()
        return f"Focused session {session_id}"

    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        """Close session."""
        try:
            if not session_id:
                session = await self._get_session_object()
                if not session:
                    return "No active session found"
                session_id = session.session_id
            else:
                session = await self._find_session_object(session_id)
                if not session:
                    return f"Session {session_id} not found"

            if not force and await self.is_ai_session(session.session_id):
                return "Cannot close AI terminal session. Specify a different session_id."

            session_name = await session.async_get_variable("session.name") or "Unnamed"

            tab = await self._find_tab_for_session(session.session_id)
            if tab and len(tab.sessions) == 1:
                window = None
                for w in self.app.windows:
                    if tab in w.tabs:
                        window = w
                        break

                if window and len(window.tabs) == 1:
                    await window.async_close(force=True)
                    return f"Closed window containing session '{session_name}' [{session.session_id}]"
                else:
                    await tab.async_close(force=True)
                    return f"Closed tab containing session '{session_name}' [{session.session_id}]"
            else:
                await session.async_close(force=True)
                return f"Closed pane '{session_name}' [{session.session_id}]"
        except Exception as e:
            return f"Error closing session: {e!s}"

    # Appearance methods

    def _parse_color(self, color: str) -> Any:
        """Parse color string to iterm2.Color object."""
        iterm2 = self._get_iterm2()

        if color.startswith("#"):
            hex_color = color[1:]
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return iterm2.Color(r, g, b)

        color_tuple = COLOR_MAP.get(color.lower(), (128, 128, 128))
        return iterm2.Color(*color_tuple)

    async def set_appearance(
        self,
        session_id: str | None = None,
        title: str | None = None,
        color: str | None = None,
        badge: str | None = None,
    ) -> str:
        """Set tab/session appearance."""
        if not title and not color and not badge:
            return "No appearance options specified"

        try:
            iterm2 = self._get_iterm2()
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            results = []

            if badge is not None or color is not None:
                change = iterm2.LocalWriteOnlyProfile()
                if badge is not None:
                    change.set_badge_text(badge)
                    results.append(f"badge='{badge}'")
                if color is not None:
                    color_obj = self._parse_color(color)
                    change.set_tab_color(color_obj)
                    change.set_use_tab_color(True)
                    results.append(f"color={color}")
                await session.async_set_profile_properties(change)

            if title is not None:
                tab = await self._find_tab_for_session(session.session_id)
                if tab:
                    await tab.async_set_title(title)
                    results.append(f"title='{title}'")
                else:
                    results.append("title failed (tab not found)")

            return f"Appearance set: {', '.join(results)}"
        except Exception as e:
            return f"Error: {e!s}"

    async def set_color_preset(self, preset: str, session_id: str | None = None) -> str:
        """Set color preset."""
        try:
            iterm2 = self._get_iterm2()
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            # async_get_list returns list of preset names (strings)
            preset_names = await iterm2.ColorPreset.async_get_list(self.connection)

            # Find matching preset name (case-insensitive)
            selected_name = None
            for name in preset_names:
                if name.lower() == preset.lower():
                    selected_name = name
                    break

            if not selected_name:
                available = ", ".join(preset_names[:10])
                if len(preset_names) > 10:
                    available += f"... ({len(preset_names)} total)"
                return f"Preset '{preset}' not found. Available: {available}"

            # Load the actual ColorPreset object
            color_preset = await iterm2.ColorPreset.async_get(self.connection, selected_name)

            profile = await session.async_get_profile()
            await profile.async_set_color_preset(color_preset)

            return f"Color scheme changed to: {selected_name}"
        except Exception as e:
            return f"Error: {e!s}"

    async def list_color_presets(self) -> str:
        """List available color presets."""
        if not self.connection:
            return "Not connected to iTerm2"

        try:
            iterm2 = self._get_iterm2()
            presets = await iterm2.ColorPreset.async_get_list(self.connection)

            if not presets:
                return "No color presets available"

            result = ["Available color presets:"]
            for preset in presets:
                result.append(f"  - {preset}")

            return "\n".join(result)
        except Exception as e:
            return f"Error: {e!s}"

    async def show_alert(self, title: str, message: str) -> str:
        """Show iTerm2 alert dialog."""
        try:
            if not self.connection:
                return "Not connected to iTerm2"

            iterm2 = self._get_iterm2()
            alert = iterm2.Alert(title=title, subtitle=message)
            await alert.async_run(self.connection)

            return f"Alert shown: {title}"
        except Exception as e:
            return f"Error: {e!s}"

    # Window positioning methods

    async def move_tab_to_window(self, session_id: str | None = None) -> str:
        """Move tab to its own window."""
        try:
            await self.ensure_connection()
            session = await self._get_session_object(session_id)
            if not session:
                return "Session not found"

            tab = await self._find_tab_for_session(session.session_id)
            if not tab:
                return "Tab not found for session"

            # Check if tab is already alone in window
            for window in self.app.windows:
                if tab in window.tabs:
                    if len(window.tabs) == 1:
                        return "Tab is already in its own window"
                    break

            new_window = await tab.async_move_to_window()
            return f"Moved tab to new window. Window ID: {new_window.window_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def set_window_frame(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        session_id: str | None = None,
    ) -> str:
        """Set window position and size.

        Note: Origin (0,0) is bottom-left of main screen.
        """
        try:
            await self.ensure_connection()
            iterm2 = self._get_iterm2()

            # Find window for session
            if session_id:
                session = await self._get_session_object(session_id)
                if not session:
                    return "Session not found"
                tab = await self._find_tab_for_session(session.session_id)
                if not tab:
                    return "Tab not found"
                window = None
                for w in self.app.windows:
                    if tab in w.tabs:
                        window = w
                        break
            else:
                # Use current window
                window = self.app.current_window

            if not window:
                return "Window not found"

            frame = iterm2.Frame(iterm2.Point(x, y), iterm2.Size(width, height))
            await window.async_set_frame(frame)
            return f"Window positioned at ({x}, {y}) with size {width}x{height}"
        except Exception as e:
            return f"Error: {e!s}"

    async def get_window_frame(self, session_id: str | None = None) -> str:
        """Get current window position and size."""
        try:
            await self.ensure_connection()

            if session_id:
                session = await self._get_session_object(session_id)
                if not session:
                    return "Session not found"
                tab = await self._find_tab_for_session(session.session_id)
                if not tab:
                    return "Tab not found"
                window = None
                for w in self.app.windows:
                    if tab in w.tabs:
                        window = w
                        break
            else:
                window = self.app.current_window

            if not window:
                return "Window not found"

            frame = await window.async_get_frame()
            return f"Window at ({frame.origin.x}, {frame.origin.y}), size {frame.size.width}x{frame.size.height}"
        except Exception as e:
            return f"Error: {e!s}"

    async def arrange_windows(self, arrangement: str = "tiled") -> str:
        """Arrange all windows.

        Arrangements: tiled, horizontal, vertical
        Uses AppleScript since Python API doesn't have direct arrange method.
        """
        import subprocess

        valid = {"tiled", "horizontal", "vertical"}
        if arrangement.lower() not in valid:
            return f"Invalid arrangement. Use: {', '.join(valid)}"

        # Map to AppleScript arrangement names
        arrange_map = {
            "tiled": "Tile All Windows",
            "horizontal": "Arrange Windows Horizontally",
            "vertical": "Arrange Windows Vertically",
        }

        script = f'''
        tell application "iTerm2"
            activate
            tell application "System Events"
                tell process "iTerm2"
                    click menu item "{arrange_map[arrangement.lower()]}" of menu "Window" of menu bar 1
                end tell
            end tell
        end tell
        '''

        try:
            subprocess.run(  # noqa: ASYNC221 - one-shot osascript, runs faster than offloading to a thread
                ["osascript", "-e", script],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return f"Windows arranged: {arrangement}"
        except subprocess.CalledProcessError as e:
            return f"Error arranging windows: {e.stderr.decode()}"
        except Exception as e:
            return f"Error: {e!s}"

    async def broadcast_input(
        self,
        session_ids: list[str],
        enable: bool = True,
    ) -> str:
        """Enable/disable broadcast input to multiple sessions.

        When enabled, keystrokes sent to any session in the group
        will be sent to all sessions in the group.
        """
        try:
            await self.ensure_connection()
            iterm2 = self._get_iterm2()

            sessions = []
            for sid in session_ids:
                session = await self._get_session_object(sid)
                if session:
                    sessions.append(session)

            if len(sessions) < 2:
                return "Need at least 2 valid sessions for broadcast"

            if enable:
                domain = iterm2.BroadcastDomain()
                for session in sessions:
                    domain.add_session(session)
                await iterm2.async_set_broadcast_domains(self.connection, [domain])
                return f"Broadcast enabled for {len(sessions)} sessions"
            else:
                # Clear all broadcast domains
                await iterm2.async_set_broadcast_domains(self.connection, [])
                return "Broadcast disabled"
        except Exception as e:
            return f"Error: {e!s}"

    async def window_command(self, command: str, session_id: str | None = None) -> str:
        """Execute simplified window command.

        Commands:
        - arrange: tile all windows
        - fullscreen: toggle fullscreen mode
        - windowed: convert current tab to new window
        - tabbed: merge all windows into one (tabs)
        """
        import subprocess

        command = command.lower().strip()

        if command == "arrange":
            return await self.arrange_windows("tiled")

        elif command == "fullscreen":
            try:
                await self.ensure_connection()
                if session_id:
                    session = await self._get_session_object(session_id)
                    if not session:
                        return "Session not found"
                    tab = await self._find_tab_for_session(session.session_id)
                    window = None
                    for w in self.app.windows:
                        if tab in w.tabs:
                            window = w
                            break
                else:
                    window = self.app.current_window

                if not window:
                    return "Window not found"

                is_fullscreen = await window.async_get_fullscreen()
                await window.async_set_fullscreen(not is_fullscreen)
                return f"Fullscreen: {'off' if is_fullscreen else 'on'}"
            except Exception as e:
                return f"Error: {e!s}"

        elif command == "windowed":
            return await self.move_tab_to_window(session_id)

        elif command == "tabbed":
            # Merge all windows into tabs via AppleScript
            script = """
            tell application "iTerm2"
                activate
                tell application "System Events"
                    tell process "iTerm2"
                        click menu item "Merge All Windows" of menu "Window" of menu bar 1
                    end tell
                end tell
            end tell
            """
            try:
                subprocess.run(  # noqa: ASYNC221 - one-shot osascript, runs faster than offloading to a thread
                    ["osascript", "-e", script],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return "All windows merged into tabs"
            except Exception as e:
                return f"Error: {e!s}"

        else:
            return f"Unknown command: {command}. Use: arrange, fullscreen, windowed, tabbed"

    async def annotate_screen(
        self,
        session_id: str | None = None,
        patterns: dict[AnnotationType, list[str]] | None = None,
        custom_notes: dict[str, str] | None = None,
        lines: int = 50,
    ) -> AnnotationResult:
        """Analyze screen and add native iTerm2 annotations.

        iTerm2 supports clickable annotation markers that appear
        in the terminal margin.
        """
        import re

        try:
            await self.ensure_connection()
            iterm2 = self._get_iterm2()

            session = await self._get_session_object(session_id)
            if not session:
                return AnnotationResult(
                    annotations=[],
                    backend=self.name,
                    native_annotations=False,
                    total_lines_scanned=0,
                )

            # Get screen contents
            contents = await session.async_get_screen_contents()

            # Get patterns to use
            active_patterns = patterns or DEFAULT_ANNOTATION_PATTERNS

            # Emoji/icon prefixes for annotation notes
            type_icons = {
                AnnotationType.ERROR: "🔴",
                AnnotationType.WARNING: "⚠️",
                AnnotationType.SUCCESS: "✅",
                AnnotationType.INFO: "ℹ️",  # noqa: RUF001 - deliberate info glyph in the badge map
            }

            # Default notes
            default_notes = {
                AnnotationType.ERROR: "Error detected - needs attention",
                AnnotationType.WARNING: "Warning - review recommended",
                AnnotationType.SUCCESS: "Success indicator",
                AnnotationType.INFO: "Information",
            }

            annotations: list[Annotation] = []
            native_added = 0
            annotated_lines: set[int] = set()  # Track annotated lines to avoid duplicates

            # Scan each line
            for line_num in range(min(lines, contents.number_of_lines)):
                if line_num in annotated_lines:
                    continue  # Skip already annotated lines

                line = contents.line(line_num)
                if not line:
                    continue

                line_text = line.string
                line_annotated = False

                # Priority order: ERROR > WARNING > SUCCESS > INFO
                for ann_type in [
                    AnnotationType.ERROR,
                    AnnotationType.WARNING,
                    AnnotationType.SUCCESS,
                    AnnotationType.INFO,
                ]:
                    if line_annotated:
                        break

                    type_patterns = active_patterns.get(ann_type, [])
                    for pattern in type_patterns:
                        match = re.search(pattern, line_text, re.IGNORECASE)
                        if match:
                            # Determine note
                            if custom_notes and pattern in custom_notes:
                                note = custom_notes[pattern]
                            else:
                                note = default_notes.get(ann_type, "")

                            icon = type_icons.get(ann_type, "📝")
                            full_note = f"{icon} {note}"

                            # Create annotation object
                            ann = Annotation(
                                line=line_num,
                                column=match.start(),
                                length=match.end() - match.start(),
                                type=ann_type,
                                text=line_text[max(0, match.start() - 10) : match.end() + 30].strip(),
                                note=full_note,
                            )
                            annotations.append(ann)

                            # Add native iTerm2 annotation
                            try:
                                start = iterm2.Point(match.start(), line_num)
                                end = iterm2.Point(min(match.end() + 20, len(line_text)), line_num)
                                coord_range = iterm2.CoordRange(start, end)
                                await session.async_add_annotation(coord_range, full_note)
                                native_added += 1
                            except Exception as e:
                                logger.warning(f"Failed to add annotation: {e}")

                            annotated_lines.add(line_num)
                            line_annotated = True
                            break  # One annotation per line

            return AnnotationResult(
                annotations=annotations,
                backend=self.name,
                native_annotations=native_added > 0,
                total_lines_scanned=min(lines, contents.number_of_lines),
            )

        except Exception as e:
            logger.error(f"annotate_screen error: {e}")
            # Graceful degradation: fall back to base implementation
            return await super().annotate_screen(
                session_id=session_id,
                patterns=patterns,
                custom_notes=custom_notes,
                lines=lines,
            )
