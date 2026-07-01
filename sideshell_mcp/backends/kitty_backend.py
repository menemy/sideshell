"""Kitty terminal backend implementation.

Uses `kitten @` commands for terminal automation.
Docs: https://sw.kovidgoyal.net/kitty/remote-control/

Requirements:
- kitty must be started with: kitty -o allow_remote_control=yes
  or have allow_remote_control=yes in kitty.conf
- For remote: kitty --listen-on unix:/path/to/socket
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil

from .base import (
    ControlKey,
    SessionInfo,
    SplitDirection,
    TerminalBackend,
)

logger = logging.getLogger(__name__)


class KittyBackend(TerminalBackend):
    """Kitty terminal backend using kitten @ commands.

    Kitty uses window IDs within tabs within OS windows.
    Match specs: id:N, title:pattern, pid:N, cwd:pattern, etc.
    """

    def __init__(self, listen_on: str | None = None) -> None:
        """Initialize Kitty backend.

        Args:
            listen_on: Socket path for remote control (e.g., unix:/tmp/kitty.sock)
        """
        self._connected = False
        self._kitten_path: str | None = None
        self._listen_on = listen_on or os.environ.get("KITTY_LISTEN_ON")

    @property
    def name(self) -> str:
        """Return backend name."""
        return "kitty"

    @property
    def is_available(self) -> bool:
        """Check if Kitty is available."""
        return shutil.which("kitten") is not None or shutil.which("kitty") is not None

    def _get_kitten_path(self) -> str:
        """Get kitten binary path."""
        if self._kitten_path is None:
            self._kitten_path = shutil.which("kitten") or shutil.which("kitty")
            if self._kitten_path and "kitty" in self._kitten_path and "kitten" not in self._kitten_path:
                # Use kitty +kitten syntax if kitten not found
                self._kitten_path = f"{self._kitten_path} +kitten"
        return self._kitten_path or "kitten"

    async def _run_kitten(self, *args: str) -> tuple[int, str, str]:
        """Run kitten @ command and return (returncode, stdout, stderr)."""
        base_cmd = self._get_kitten_path().split()
        cmd = [*base_cmd, "@"]

        if self._listen_on:
            cmd.extend(["--to", self._listen_on])

        cmd.extend(list(args))
        logger.debug(f"Running kitten: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    async def _kitten(self, *args: str) -> str:
        """Run kitten @ command and return stdout (raises on error)."""
        code, stdout, stderr = await self._run_kitten(*args)
        if code != 0:
            raise RuntimeError(f"kitten error: {stderr or stdout}")
        return stdout

    async def _send_text_literal(self, window_id: str, text: str) -> None:
        """Send text to a window verbatim via `send-text --stdin`.

        The positional TEXT argument of `kitten @ send-text` is interpreted with
        Python escape rules (e.g. ``\\d``, ``\\t``, ``\\e``), which corrupts any
        command containing backslashes. Content piped via ``--stdin`` is sent as
        is, so all user text/commands go through this path.
        """
        base_cmd = self._get_kitten_path().split()
        cmd = [*base_cmd, "@"]
        if self._listen_on:
            cmd.extend(["--to", self._listen_on])
        cmd.extend(["send-text", "--match", f"id:{window_id}", "--stdin"])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(text.encode())
        if proc.returncode:
            raise RuntimeError(f"kitten error: {stderr.decode().strip()}")

    async def connect(self) -> bool:
        """Check kitty remote control is available."""
        try:
            code, _, stderr = await self._run_kitten("ls")
            if code == 0:
                self._connected = True
                logger.info("Successfully connected to Kitty")
                return True

            if "allow_remote_control" in stderr.lower():
                logger.error("Kitty remote control not enabled. Start with: kitty -o allow_remote_control=yes")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Kitty: {e}")
            return False

    async def ensure_connection(self) -> None:
        """Ensure kitty is accessible."""
        if not self._connected:
            await self.connect()

    async def disconnect(self) -> None:
        """No persistent connection to close."""
        self._connected = False

    async def _get_windows_json(self) -> list:
        """Get all windows as JSON."""
        output = await self._kitten("ls")
        windows: list = json.loads(output)
        return windows

    async def _get_active_window_id(self) -> int | None:
        """Get the active window ID."""
        # Check KITTY_WINDOW_ID env var first
        window_id = os.environ.get("KITTY_WINDOW_ID")
        if window_id:
            return int(window_id)

        try:
            windows = await self._get_windows_json()
            for os_window in windows:
                for tab in os_window.get("tabs", []):
                    if tab.get("is_focused"):
                        for window in tab.get("windows", []):
                            if window.get("is_focused"):
                                focused_id: int | None = window.get("id")
                                return focused_id
        except Exception:
            pass
        return None

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        """Get session info by window ID."""
        try:
            window_id = int(session_id) if session_id else await self._get_active_window_id()
            if not window_id:
                return None

            windows = await self._get_windows_json()
            for os_window in windows:
                for tab in os_window.get("tabs", []):
                    for window in tab.get("windows", []):
                        if window.get("id") == window_id:
                            fg_procs = window.get("foreground_processes", [])
                            cmdline = fg_procs[0].get("cmdline", ["shell"]) if fg_procs else ["shell"]
                            return SessionInfo(
                                session_id=str(window.get("id")),
                                name=window.get("title", "Unnamed"),
                                path=window.get("cwd", "~"),
                                job=cmdline[-1] if cmdline else "shell",
                                at_prompt=window.get("at_prompt", False),
                                columns=window.get("columns", 0),
                                rows=window.get("lines", 0),
                                tty=None,
                            )
            return None
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None

    async def list_sessions(self) -> str:
        """List all windows."""
        try:
            windows = await self._get_windows_json()

            total = sum(len(tab.get("windows", [])) for os_win in windows for tab in os_win.get("tabs", []))
            result = [f"Total: {total} windows\n"]

            for os_window in windows:
                result.append(f"\nOS Window: {os_window.get('id')}")

                for tab in os_window.get("tabs", []):
                    tab_title = tab.get("title", f"Tab {tab.get('id')}")
                    result.append(f"  Tab: {tab_title} (id: {tab.get('id')})")

                    for window in tab.get("windows", []):
                        fg_procs = window.get("foreground_processes", [])
                        cmdline = fg_procs[0].get("cmdline", []) if fg_procs else []
                        job = cmdline[-1] if cmdline else "shell"
                        cwd = window.get("cwd", "~")
                        window_id = window.get("id")
                        is_focused = window.get("is_focused", False)

                        indicator = "●" if is_focused else "○"
                        result.append(f"    {indicator} {job} @ {cwd} [{window_id}]")

            return "\n".join(result)
        except Exception as e:
            return f"Error listing sessions: {e!s}"

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        """Get detailed terminal state."""
        try:
            windows = await self._get_windows_json()

            if session_id:
                window_id = int(session_id)
                for os_window in windows:
                    for tab in os_window.get("tabs", []):
                        for window in tab.get("windows", []):
                            if window.get("id") == window_id:
                                return json.dumps(window, indent=2)
                return "Session not found"

            return json.dumps(windows, indent=2)
        except Exception as e:
            return f"Error getting terminal state: {e!s}"

    async def is_ai_session(self, session_id: str) -> bool:
        """Check if window is running AI tool."""
        info = await self.get_session(session_id)
        if not info:
            return False
        job_lower = info.job.lower()
        return "claude" in job_lower or "mcp" in job_lower or "cursor" in job_lower

    async def get_current_active_session_id(self) -> str | None:
        """Get the currently active window ID."""
        window_id = await self._get_active_window_id()
        return str(window_id) if window_id else None

    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,
        watch_for: str = "prompt",
    ) -> str:
        """Execute command in Kitty window.

        Args:
            command: Command to execute.
            session_id: Target window ID.
            wait: Wait for completion.
            timeout: Timeout in seconds.
            watch_for: What to wait for ('prompt', 'output', 'silence').
        """
        try:
            window_id = session_id or await self.get_current_active_session_id()
            if not window_id:
                return "No active window found"

            if await self.is_ai_session(window_id):
                return "Cannot execute in AI window. Use 'split' to create a new window."

            await self._send_text_literal(window_id, f"{command}\n")

            if wait:
                return await self._wait_for_completion(window_id, timeout, watch_for)

            return f"Sent: {command}"
        except Exception as e:
            return f"Error: {e!s}"

    async def _wait_for_completion(
        self,
        window_id: str,
        timeout: int,
        watch_for: str,
    ) -> str:
        """Wait for command completion."""
        start_time = asyncio.get_running_loop().time()
        initial_content = await self._capture_window(window_id)
        last_content = initial_content
        last_change_time = start_time
        poll_interval = 0.1

        while True:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= timeout:
                return f"Timed out after {timeout}s"

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 1.0)

            current_content = await self._capture_window(window_id)

            if watch_for == "output":
                if current_content != initial_content:
                    return f"Output detected in {elapsed:.1f}s"

            elif watch_for == "silence":
                if current_content != last_content:
                    last_content = current_content
                    last_change_time = asyncio.get_running_loop().time()
                    poll_interval = 0.1
                elif asyncio.get_running_loop().time() - last_change_time >= 2.0:
                    return f"Completed (silence) in {elapsed:.1f}s:\n{current_content[-2000:]}"

            else:  # prompt - wait for stability
                if current_content != last_content:
                    last_content = current_content
                    last_change_time = asyncio.get_running_loop().time()
                    poll_interval = 0.1
                elif asyncio.get_running_loop().time() - last_change_time >= 2.0:
                    return f"Completed (stability) in {elapsed:.1f}s:\n{current_content[-2000:]}"

    async def _capture_window(self, window_id: str) -> str:
        """Capture window content, including scrollback.

        Without ``--extent all`` kitty only returns the visible screen, so
        ``read_terminal`` could never reach scrollback.
        """
        try:
            output = await self._kitten("get-text", "--match", f"id:{window_id}", "--extent", "all")
            return output
        except Exception:
            return ""

    async def send_text(self, text: str, session_id: str | None = None) -> str:
        """Send text to window."""
        try:
            window_id = session_id or await self.get_current_active_session_id()
            if not window_id:
                return "No active window found"

            if await self.is_ai_session(window_id):
                return "Cannot paste to AI window. Use 'split' to create a new window."

            await self._send_text_literal(window_id, text)
            return f"Pasted {len(text)} characters"
        except Exception as e:
            return f"Error: {e!s}"

    async def send_control(self, key: ControlKey, session_id: str | None = None) -> str:
        """Send control character."""
        window_id = session_id or await self.get_current_active_session_id()
        if not window_id:
            return "No active window found"

        if await self.is_ai_session(window_id):
            return "Cannot send control to AI window. Use 'split' to create a new window."

        char_to_send = self.CONTROL_CHARS[key]
        await self._kitten("send-text", "--match", f"id:{window_id}", char_to_send)

        if key == ControlKey.ENTER:
            return "Sent Enter key"
        elif key == ControlKey.ESC:
            return "Sent Escape key"
        else:
            return f"Sent Ctrl+{key.value.upper()}"

    async def read_terminal(self, lines: int = 20, session_id: str | None = None) -> str:
        """Read window content."""
        try:
            window_id = session_id or await self.get_current_active_session_id()
            if not window_id:
                return "No active window found"

            output = await self._capture_window(window_id)
            output_lines = output.split("\n")
            result = "\n".join(output_lines[-lines:])

            return f"Last {lines} lines:\n{result}"
        except Exception as e:
            return f"Error: {e!s}"

    async def clear_terminal(self, session_id: str | None = None) -> str:
        """Clear window."""
        try:
            window_id = session_id or await self.get_current_active_session_id()
            if not window_id:
                return "No active window found"

            if await self.is_ai_session(window_id):
                return "Cannot clear AI window. Use 'split' to create a new window."

            # Send Ctrl+L
            await self._kitten("send-text", "--match", f"id:{window_id}", "\x0c")
            return "Terminal cleared"
        except Exception as e:
            return f"Error: {e!s}"

    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        """Split window."""
        try:
            window_id = session_id or await self.get_current_active_session_id()

            args = ["launch", "--type=window"]
            if window_id:
                args.extend(["--match", f"id:{window_id}"])

            if direction == SplitDirection.HORIZONTAL:
                args.append("--location=hsplit")
            else:
                args.append("--location=vsplit")

            output = await self._kitten(*args)
            # Output should be new window ID

            direction_text = "horizontally" if direction == SplitDirection.HORIZONTAL else "vertically"
            return f"Split {direction_text}. New window: {output.strip()}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new OS window."""
        try:
            args = ["launch", "--type=os-window"]
            if command:
                args.append(command)

            output = await self._kitten(*args)
            return f"New OS window created: {output.strip()}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new tab."""
        try:
            args = ["launch", "--type=tab"]
            if command:
                args.append(command)

            output = await self._kitten(*args)
            return f"New tab created: {output.strip()}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_session(self, profile: str | None = None) -> str:
        """Smart session creation: split if window exists, else new tab."""
        try:
            active = await self._get_active_window_id()
            if active:
                return await self.split_pane(SplitDirection.HORIZONTAL)
            else:
                return await self.create_tab()
        except Exception as e:
            return f"Error: {e!s}"

    async def focus_session(self, session_id: str) -> str:
        """Focus specific window."""
        try:
            await self._kitten("focus-window", "--match", f"id:{session_id}")
            return f"Focused window {session_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        """Close window."""
        try:
            window_id = session_id or await self.get_current_active_session_id()
            if not window_id:
                return "No active window found"

            if not force and await self.is_ai_session(window_id):
                return "Cannot close AI window. Specify a different window_id."

            await self._kitten("close-window", "--match", f"id:{window_id}")
            return f"Closed window {window_id}"
        except Exception as e:
            return f"Error: {e!s}"

    # Appearance support

    async def set_appearance(
        self,
        session_id: str | None = None,
        title: str | None = None,
        color: str | None = None,
        badge: str | None = None,
    ) -> str:
        """Set tab/window appearance.

        Kitty supports tab title, window title, and tab color.
        Badge is not supported.
        """
        results = []

        try:
            window_id = session_id or await self.get_current_active_session_id()

            if title:
                # Set tab title
                if window_id:
                    await self._kitten("set-tab-title", "--match", f"id:{window_id}", title)
                else:
                    await self._kitten("set-tab-title", title)
                results.append(f"Tab title set to '{title}'")

            if color:
                # Set tab color (Kitty supports this)
                # Color format: foreground, background, or both
                if window_id:
                    await self._kitten("set-tab-color", "--match", f"id:{window_id}", f"active_bg={color}")
                else:
                    await self._kitten("set-tab-color", f"active_bg={color}")
                results.append(f"Tab color set to '{color}'")

            if badge:
                results.append("Badge not supported in Kitty")

            if not results:
                return "No appearance changes requested"

            return "Appearance updated: " + "; ".join(results)
        except Exception as e:
            return f"Error setting appearance: {e!s}"

    async def set_window_title(self, title: str, session_id: str | None = None) -> str:
        """Set the window title."""
        try:
            window_id = session_id or await self.get_current_active_session_id()
            if window_id:
                await self._kitten("set-window-title", "--match", f"id:{window_id}", title)
            else:
                await self._kitten("set-window-title", title)
            return f"Window title set to '{title}'"
        except Exception as e:
            return f"Error: {e!s}"

    async def set_color_preset(self, preset: str, session_id: str | None = None) -> str:
        """Set color theme/preset.

        Kitty supports setting colors via kitten @ set-colors.
        Use theme names or path to .conf file.
        """
        try:
            window_id = session_id or await self.get_current_active_session_id()
            # Try to load theme using kitten themes
            # First check if it's a theme name or a file path
            if window_id:
                await self._kitten("set-colors", "--match", f"id:{window_id}", preset)
            else:
                await self._kitten("set-colors", preset)
            return f"Color preset '{preset}' applied"
        except Exception as e:
            return f"Error setting color preset: {e!s}"

    async def list_color_presets(self) -> str:
        """List available color themes.

        Returns list of built-in Kitty themes.
        """
        try:
            # Get colors info
            code, stdout, _stderr = await self._run_kitten("get-colors")
            if code == 0:
                return f"Current colors:\n{stdout}\n\nTo set colors, use a .conf file path or color definitions."
            return "Use 'kitten themes' command to browse themes interactively"
        except Exception as e:
            return f"Error: {e!s}"

    async def show_alert(self, title: str, message: str) -> str:
        """Show notification.

        Kitty can send desktop notifications via escape sequences.
        """
        try:
            # Use OSC 99 for desktop notifications
            notification = f"\x1b]99;i=1:d=0;{title}\x1b\\\x1b]99;i=1:d=1:p=body;{message}\x1b\\"
            window_id = await self.get_current_active_session_id()
            if window_id:
                await self._kitten("send-text", "--match", f"id:{window_id}", notification)
            return f"Notification sent: {title}"
        except Exception as e:
            return f"Error showing alert: {e!s}"
