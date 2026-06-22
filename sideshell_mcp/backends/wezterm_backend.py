"""WezTerm backend implementation.

Uses `wezterm cli` commands for terminal automation.
Docs: https://wezterm.org/cli/cli/index.html
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from urllib.parse import unquote, urlparse

from .base import (
    ControlKey,
    SessionInfo,
    SplitDirection,
    TerminalBackend,
)

logger = logging.getLogger(__name__)


class WezTermBackend(TerminalBackend):
    """WezTerm backend using CLI commands.

    WezTerm uses pane IDs similar to tmux. The WEZTERM_PANE env var
    identifies the current pane.
    """

    def __init__(self) -> None:
        """Initialize WezTerm backend."""
        self._connected = False
        self._wezterm_path: str | None = None

    @property
    def name(self) -> str:
        """Return backend name."""
        return "wezterm"

    @property
    def is_available(self) -> bool:
        """Check if WezTerm is available."""
        return shutil.which("wezterm") is not None

    def _get_wezterm_path(self) -> str:
        """Get wezterm binary path."""
        if self._wezterm_path is None:
            self._wezterm_path = shutil.which("wezterm") or "wezterm"
        return self._wezterm_path

    async def _run_wezterm(self, *args: str) -> tuple[int, str, str]:
        """Run wezterm cli command and return (returncode, stdout, stderr)."""
        cmd = [self._get_wezterm_path(), "cli", *args]
        logger.debug(f"Running wezterm: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    async def _wezterm(self, *args: str) -> str:
        """Run wezterm cli command and return stdout (raises on error)."""
        code, stdout, stderr = await self._run_wezterm(*args)
        if code != 0:
            raise RuntimeError(f"wezterm error: {stderr or stdout}")
        return stdout

    async def connect(self) -> bool:
        """Check wezterm is running."""
        try:
            code, _, _ = await self._run_wezterm("list")
            if code == 0:
                self._connected = True
                logger.info("Successfully connected to WezTerm")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to connect to WezTerm: {e}")
            return False

    async def ensure_connection(self) -> None:
        """Ensure wezterm is accessible."""
        if not self._connected:
            await self.connect()

    async def disconnect(self) -> None:
        """No persistent connection to close."""
        self._connected = False

    async def _get_active_pane(self) -> str | None:
        """Get the active pane ID."""
        # Check WEZTERM_PANE env var first
        pane_id = os.environ.get("WEZTERM_PANE")
        if pane_id:
            return pane_id

        # Try to get from list
        try:
            output = await self._wezterm("list", "--format=json")
            panes = json.loads(output)
            if panes:
                # Return first pane or focused pane
                for pane in panes:
                    if pane.get("is_active"):
                        return str(pane.get("pane_id"))
                return str(panes[0].get("pane_id"))
        except Exception:
            pass
        return None

    @staticmethod
    def _clean_cwd(raw: str | None) -> str:
        """Normalize wezterm's `file://host/path` cwd URL to a plain path."""
        if not raw:
            return "~"
        if raw.startswith("file://"):
            return unquote(urlparse(raw).path) or "~"
        return raw

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        """Get session info by pane ID."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return None

            output = await self._wezterm("list", "--format=json")
            panes = json.loads(output)

            for pane in panes:
                if str(pane.get("pane_id")) == str(pane_id):
                    return SessionInfo(
                        session_id=str(pane.get("pane_id")),
                        name=pane.get("title", "Unnamed"),
                        path=self._clean_cwd(pane.get("cwd")),
                        job=pane.get("foreground_process_name", "shell"),
                        at_prompt=False,  # WezTerm doesn't expose this
                        columns=pane.get("size", {}).get("cols", 0),
                        rows=pane.get("size", {}).get("rows", 0),
                        tty=pane.get("tty_name"),
                    )
            return None
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None

    async def list_sessions(self) -> str:
        """List all panes."""
        try:
            output = await self._wezterm("list", "--format=json")
            panes = json.loads(output)

            result = [f"Total: {len(panes)} panes\n"]

            current_window = None
            current_tab = None

            for pane in panes:
                window_id = pane.get("window_id")
                tab_id = pane.get("tab_id")
                pane_id = pane.get("pane_id")
                title = pane.get("title", "Unnamed")
                cwd = self._clean_cwd(pane.get("cwd"))
                process = pane.get("foreground_process_name", "shell")

                if window_id != current_window:
                    current_window = window_id
                    result.append(f"\nWindow: {window_id}")

                if tab_id != current_tab:
                    current_tab = tab_id
                    result.append(f"  Tab: {tab_id}")

                is_active = pane.get("is_active", False)
                indicator = "●" if is_active else "○"
                result.append(f"    {indicator} {process} @ {cwd} [{pane_id}] {title}")

            return "\n".join(result)
        except Exception as e:
            return f"Error listing sessions: {e!s}"

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        """Get detailed terminal state."""
        try:
            output = await self._wezterm("list", "--format=json")
            panes = json.loads(output)

            if session_id:
                for pane in panes:
                    if str(pane.get("pane_id")) == str(session_id):
                        return json.dumps(pane, indent=2)
                return "Session not found"

            return json.dumps({"panes": panes, "total": len(panes)}, indent=2)
        except Exception as e:
            return f"Error getting terminal state: {e!s}"

    async def is_ai_session(self, session_id: str) -> bool:
        """Check if pane is running AI tool."""
        info = await self.get_session(session_id)
        if not info:
            return False
        job_lower = info.job.lower()
        return "claude" in job_lower or "mcp" in job_lower or "cursor" in job_lower

    async def get_current_active_session_id(self) -> str | None:
        """Get the currently active pane ID."""
        return await self._get_active_pane()

    async def execute_command(
        self,
        command: str,
        session_id: str | None = None,
        wait: bool = False,
        timeout: int = 30,
        watch_for: str = "prompt",
    ) -> str:
        """Execute command in WezTerm pane.

        Args:
            command: Command to execute.
            session_id: Target pane ID.
            wait: Wait for completion.
            timeout: Timeout in seconds.
            watch_for: What to wait for ('prompt', 'output', 'silence').
        """
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return "No active pane found"

            if await self.is_ai_session(pane_id):
                return "Cannot execute in AI pane. Use 'split' to create a new pane."

            args = ["send-text", "--pane-id", str(pane_id), "--no-paste"]
            await self._wezterm(*args, f"{command}\n")

            if wait:
                return await self._wait_for_completion(pane_id, timeout, watch_for)

            return f"Sent: {command}"
        except Exception as e:
            return f"Error: {e!s}"

    async def _wait_for_completion(
        self,
        pane_id: str,
        timeout: int,
        watch_for: str,
    ) -> str:
        """Wait for command completion by monitoring pane content."""
        start_time = asyncio.get_running_loop().time()
        initial_content = await self._capture_pane(pane_id)
        last_content = initial_content
        last_change_time = start_time
        poll_interval = 0.1

        while True:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= timeout:
                return f"Timed out after {timeout}s"

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 1.0)

            current_content = await self._capture_pane(pane_id)

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

    async def _capture_pane(self, pane_id: str, lines: int = 200) -> str:
        """Capture pane content, including scrollback.

        ``wezterm cli get-text`` returns only the visible viewport by default;
        ``--start-line=-N`` reaches back N lines into the scrollback so
        ``read_terminal`` isn't limited to what's currently on screen.
        """
        try:
            output = await self._wezterm("get-text", "--pane-id", str(pane_id), f"--start-line=-{lines}")
            return output
        except Exception:
            return ""

    async def send_text(self, text: str, session_id: str | None = None) -> str:
        """Send text to pane."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return "No active pane found"

            if await self.is_ai_session(pane_id):
                return "Cannot paste to AI pane. Use 'split' to create a new pane."

            await self._wezterm("send-text", "--pane-id", str(pane_id), text)
            return f"Pasted {len(text)} characters"
        except Exception as e:
            return f"Error: {e!s}"

    async def send_control(self, key: ControlKey, session_id: str | None = None) -> str:
        """Send control character."""
        pane_id = session_id or await self._get_active_pane()
        if not pane_id:
            return "No active pane found"

        if await self.is_ai_session(pane_id):
            return "Cannot send control to AI pane. Use 'split' to create a new pane."

        char_to_send = self.CONTROL_CHARS[key]
        await self._wezterm("send-text", "--pane-id", str(pane_id), "--no-paste", char_to_send)

        if key == ControlKey.ENTER:
            return "Sent Enter key"
        elif key == ControlKey.ESC:
            return "Sent Escape key"
        else:
            return f"Sent Ctrl+{key.value.upper()}"

    async def read_terminal(self, lines: int = 20, session_id: str | None = None) -> str:
        """Read pane content."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return "No active pane found"

            output = await self._capture_pane(pane_id)
            output_lines = output.split("\n")
            result = "\n".join(output_lines[-lines:])

            return f"Last {lines} lines:\n{result}"
        except Exception as e:
            return f"Error: {e!s}"

    async def clear_terminal(self, session_id: str | None = None) -> str:
        """Clear pane."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return "No active pane found"

            if await self.is_ai_session(pane_id):
                return "Cannot clear AI pane. Use 'split' to create a new pane."

            # Send Ctrl+L
            await self._wezterm("send-text", "--pane-id", str(pane_id), "--no-paste", "\x0c")
            return "Terminal cleared"
        except Exception as e:
            return f"Error: {e!s}"

    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        """Split pane."""
        try:
            pane_id = session_id or await self._get_active_pane()
            args = ["split-pane"]

            if pane_id:
                args.extend(["--pane-id", str(pane_id)])

            if direction == SplitDirection.HORIZONTAL:
                args.append("--horizontal")
            else:
                args.append("--bottom")

            output = await self._wezterm(*args)
            new_pane_id = output.strip()

            direction_text = "horizontally" if direction == SplitDirection.HORIZONTAL else "vertically"
            return f"Split {direction_text}. New session: {new_pane_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new window."""
        try:
            args = ["spawn", "--new-window"]
            if command:
                # Run via a shell so multi-word commands work; passing the raw
                # string as PROG would make wezterm spawn a program named after
                # the whole command line and fail.
                args.extend(["--", "/bin/sh", "-lc", command])

            output = await self._wezterm(*args)
            pane_id = output.strip()

            return f"New window created with pane_id: {pane_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new tab."""
        try:
            args = ["spawn"]
            # Anchor to an existing pane's window: without --pane-id (and with no
            # $WEZTERM_PANE), wezterm can't determine the target window when it
            # isn't the focused app (the sidecar case) and errors out.
            anchor = await self._get_active_pane()
            if anchor:
                args.extend(["--pane-id", str(anchor)])
            if command:
                args.extend(["--", "/bin/sh", "-lc", command])

            output = await self._wezterm(*args)
            pane_id = output.strip()

            return f"New tab created with pane_id: {pane_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_session(self, profile: str | None = None) -> str:
        """Smart session creation: split if pane exists, else new tab."""
        try:
            active_pane = await self._get_active_pane()
            if active_pane:
                return await self.split_pane(SplitDirection.HORIZONTAL)
            else:
                return await self.create_tab()
        except Exception as e:
            return f"Error: {e!s}"

    async def focus_session(self, session_id: str) -> str:
        """Focus specific pane."""
        try:
            await self._wezterm("activate-pane", "--pane-id", str(session_id))
            return f"Focused pane {session_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        """Close pane."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return "No active pane found"

            if not force and await self.is_ai_session(pane_id):
                return "Cannot close AI pane. Specify a different pane_id."

            await self._wezterm("kill-pane", "--pane-id", str(pane_id))
            return f"Closed pane {pane_id}"
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

        WezTerm supports tab and window titles.
        Badge and color are not directly supported via CLI.
        """
        results = []

        try:
            if title:
                # Set tab title (target an explicit pane so it works when wezterm
                # isn't the focused app — otherwise wezterm can't resolve a tab).
                args = ["set-tab-title"]
                pane_id = session_id or await self._get_active_pane()
                if pane_id:
                    args.extend(["--pane-id", str(pane_id)])
                args.append(title)
                await self._wezterm(*args)
                results.append(f"Tab title set to '{title}'")

            if color:
                results.append("Tab color not supported via WezTerm CLI")

            if badge:
                results.append("Badge not supported in WezTerm")

            if not results:
                return "No appearance changes requested"

            return "Appearance updated: " + "; ".join(results)
        except Exception as e:
            return f"Error setting appearance: {e!s}"

    async def set_window_title(self, title: str) -> str:
        """Set the window title."""
        try:
            # Target an explicit pane's window; without --pane-id (and no
            # $WEZTERM_PANE) wezterm can't resolve the window when unfocused.
            args = ["set-window-title"]
            pane_id = await self._get_active_pane()
            if pane_id:
                args.extend(["--pane-id", str(pane_id)])
            args.append(title)
            await self._wezterm(*args)
            return f"Window title set to '{title}'"
        except Exception as e:
            return f"Error: {e!s}"
