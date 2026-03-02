"""tmux backend implementation."""

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


class TmuxBackend(TerminalBackend):
    """tmux backend using CLI commands.

    Note: tmux terminology differs from iTerm2:
    - iTerm2 Window = tmux Window (but tmux session is different)
    - iTerm2 Tab = tmux Window
    - iTerm2 Pane/Session = tmux Pane

    This backend maps:
    - session_id -> tmux pane_id (e.g., %0, %1)
    - window -> tmux session:window
    - tab -> tmux window
    """

    def __init__(self) -> None:
        """Initialize tmux backend."""
        self._connected = False
        self._tmux_path: str | None = None

    @property
    def name(self) -> str:
        """Return backend name."""
        return "tmux"

    @property
    def is_available(self) -> bool:
        """Check if tmux is available."""
        return shutil.which("tmux") is not None

    def _get_tmux_path(self) -> str:
        """Get tmux binary path."""
        if self._tmux_path is None:
            self._tmux_path = shutil.which("tmux") or "tmux"
        return self._tmux_path

    async def _run_tmux(self, *args: str) -> tuple[int, str, str]:
        """Run tmux command and return (returncode, stdout, stderr)."""
        cmd = [self._get_tmux_path()] + list(args)
        logger.debug(f"Running tmux: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode().strip(), stderr.decode().strip()

    async def _tmux(self, *args: str) -> str:
        """Run tmux command and return stdout (raises on error)."""
        code, stdout, stderr = await self._run_tmux(*args)
        if code != 0:
            raise RuntimeError(f"tmux error: {stderr or stdout}")
        return stdout

    async def connect(self) -> bool:
        """Connect to tmux, auto-creating a 'sideshell' session if none exist."""
        try:
            code, stdout, _ = await self._run_tmux("list-sessions")
            if code == 0 and stdout.strip():
                self._connected = True
                logger.info("Connected to existing tmux session")
                return True

            # No sessions — create one so sideshell has something to work with
            code, _, stderr = await self._run_tmux(
                "new-session", "-d", "-s", "sideshell",
            )
            if code != 0:
                logger.error(f"Failed to create tmux session: {stderr}")
                return False

            self._connected = True
            logger.info(
                "Created tmux session 'sideshell'. "
                "Watch in a new tab: tmux attach -t sideshell"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to connect to tmux: {e}")
            return False

    async def ensure_connection(self) -> None:
        """Ensure tmux server is running."""
        if not self._connected:
            await self.connect()

    async def disconnect(self) -> None:
        """No persistent connection to close."""
        self._connected = False

    async def _get_active_pane(self) -> str | None:
        """Get the active pane ID."""
        try:
            output = await self._tmux("display-message", "-p", "#{pane_id}")
            return output
        except Exception:
            # Not in tmux session, try to get first pane
            try:
                output = await self._tmux("list-panes", "-a", "-F", "#{pane_id}")
                panes = output.strip().split("\n")
                return panes[0] if panes else None
            except Exception:
                return None

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        """Get session info by pane ID or current active pane."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if not pane_id:
                return None

            # Get pane info: pane_id, pane_current_command, pane_current_path, pane_width, pane_height
            output = await self._tmux(
                "display-message",
                "-t", pane_id,
                "-p",
                "#{pane_id}|#{pane_current_command}|#{pane_current_path}|#{pane_width}|#{pane_height}|#{pane_tty}"
            )

            parts = output.split("|")
            if len(parts) >= 6:
                return SessionInfo(
                    session_id=parts[0],
                    job=parts[1] or "shell",
                    path=parts[2] or "~",
                    name=parts[1] or "Unnamed",
                    at_prompt=parts[1] in ("bash", "zsh", "fish", "sh", "-bash", "-zsh"),
                    columns=int(parts[3]) if parts[3].isdigit() else 0,
                    rows=int(parts[4]) if parts[4].isdigit() else 0,
                    tty=parts[5] if len(parts) > 5 else None,
                )
            return None
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None

    async def list_sessions(self) -> str:
        """List all panes."""
        try:
            # Format: session:window.pane pane_id width x height command path
            output = await self._tmux(
                "list-panes",
                "-a",
                "-F",
                "#{session_name}:#{window_index}.#{pane_index}|#{pane_id}|#{pane_width}x#{pane_height}|#{pane_current_command}|#{pane_current_path}"
            )

            lines = output.strip().split("\n")
            result = [f"Total: {len(lines)} panes\n"]

            current_session = ""
            current_window = ""

            for line in lines:
                parts = line.split("|")
                if len(parts) >= 5:
                    location, pane_id, size, cmd, path = parts[:5]
                    session_window = location.rsplit(".", 1)[0]  # session:window
                    session_name = session_window.split(":")[0]

                    # Add session header if changed
                    if session_name != current_session:
                        current_session = session_name
                        result.append(f"\nSession: {session_name}")

                    # Add window header if changed
                    if session_window != current_window:
                        current_window = session_window
                        result.append(f"  Window: {session_window}")

                    # Determine prompt status
                    at_prompt = cmd in ("bash", "zsh", "fish", "sh", "-bash", "-zsh")
                    indicator = "●" if at_prompt else "○"

                    result.append(f"    {indicator} {cmd} @ {path} [{pane_id}] {size}")

            return "\n".join(result)
        except Exception as e:
            return f"Error listing sessions: {e!s}"

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        """Get detailed terminal state."""
        try:
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
                    "columns": info.columns,
                    "rows": info.rows,
                    "tty": info.tty,
                }, indent=2)

            # Get all sessions
            output = await self._tmux(
                "list-panes",
                "-a",
                "-F",
                "#{session_name}|#{window_index}|#{window_name}|#{pane_index}|#{pane_id}|#{pane_current_command}|#{pane_current_path}|#{pane_width}|#{pane_height}"
            )

            state = {
                "sessions": [],
                "total_panes": 0,
                "active_session": None,
                "active_window": None,
                "active_pane": await self._get_active_pane(),
            }

            lines = output.strip().split("\n")
            sessions_dict: dict = {}

            for line in lines:
                parts = line.split("|")
                if len(parts) >= 9:
                    sess_name, win_idx, win_name, pane_idx, pane_id, cmd, path, width, height = parts[:9]

                    if sess_name not in sessions_dict:
                        sessions_dict[sess_name] = {"session_name": sess_name, "windows": {}}

                    win_key = f"{win_idx}"
                    if win_key not in sessions_dict[sess_name]["windows"]:
                        sessions_dict[sess_name]["windows"][win_key] = {
                            "window_index": win_idx,
                            "window_name": win_name,
                            "panes": [],
                        }

                    sessions_dict[sess_name]["windows"][win_key]["panes"].append({
                        "pane_id": pane_id,
                        "pane_index": pane_idx,
                        "command": cmd,
                        "path": path,
                        "columns": int(width) if width.isdigit() else 0,
                        "rows": int(height) if height.isdigit() else 0,
                    })
                    state["total_panes"] += 1

            # Convert to list format
            for sess_name, sess_data in sessions_dict.items():
                session_info = {
                    "session_name": sess_name,
                    "windows": list(sess_data["windows"].values()),
                }
                state["sessions"].append(session_info)

            return json.dumps(state, indent=2)
        except Exception as e:
            return f"Error getting terminal state: {e!s}"

    async def is_ai_session(self, session_id: str) -> bool:
        """Check if pane is running Claude or other AI tool."""
        try:
            output = await self._tmux("display-message", "-t", session_id, "-p", "#{pane_current_command}")
            cmd = output.lower()
            return "claude" in cmd or "mcp" in cmd or "cursor" in cmd
        except Exception:
            return False

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
        """Execute command in tmux pane.

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

            if wait:
                return await self._execute_with_wait(pane_id, command, timeout, watch_for)

            # Send keys to pane
            await self._tmux("send-keys", "-t", pane_id, command, "Enter")
            return f"Sent: {command}"
        except Exception as e:
            return f"Error: {e!s}"

    async def _execute_with_wait(
        self,
        pane_id: str,
        command: str,
        timeout: int,
        watch_for: str,
    ) -> str:
        """Execute command and wait for completion.

        Args:
            pane_id: Target pane ID.
            command: Command to execute.
            timeout: Timeout in seconds.
            watch_for: What to wait for ('prompt', 'output', 'silence').
        """
        start_time = asyncio.get_running_loop().time()

        initial_output = await self._capture_pane(pane_id)
        await self._tmux("send-keys", "-t", pane_id, command, "Enter")

        last_output = initial_output
        last_change_time = start_time
        poll_interval = 0.1

        while True:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= timeout:
                return f"Timed out after {timeout}s"

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 1.0)

            current_output = await self._capture_pane(pane_id)

            if watch_for == "output":
                if current_output != initial_output:
                    return f"Output detected in {elapsed:.1f}s"

            elif watch_for == "silence":
                if current_output != last_output:
                    last_output = current_output
                    last_change_time = asyncio.get_running_loop().time()
                    poll_interval = 0.1
                elif asyncio.get_running_loop().time() - last_change_time >= 2.0:
                    return f"Completed (silence) in {elapsed:.1f}s:\n{current_output[-2000:]}"

            else:  # prompt - wait for stability
                if current_output != last_output:
                    last_output = current_output
                    last_change_time = asyncio.get_running_loop().time()
                    poll_interval = 0.1
                elif asyncio.get_running_loop().time() - last_change_time >= 2.0:
                    return f"Completed (stability) in {elapsed:.1f}s:\n{current_output[-2000:]}"

    async def _capture_pane(self, pane_id: str, lines: int = 50) -> str:
        """Capture pane content."""
        try:
            output = await self._tmux("capture-pane", "-p", "-t", pane_id, "-S", f"-{lines}")
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

            # Use send-keys with -l for literal text
            await self._tmux("send-keys", "-t", pane_id, "-l", text)
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

        # tmux key mappings
        tmux_keys = {
            ControlKey.C: "C-c",
            ControlKey.D: "C-d",
            ControlKey.Z: "C-z",
            ControlKey.A: "C-a",
            ControlKey.E: "C-e",
            ControlKey.K: "C-k",
            ControlKey.L: "C-l",
            ControlKey.U: "C-u",
            ControlKey.W: "C-w",
            ControlKey.ENTER: "Enter",
            ControlKey.ESC: "Escape",
        }

        tmux_key = tmux_keys.get(key, f"C-{key.value}")
        await self._tmux("send-keys", "-t", pane_id, tmux_key)

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

            output = await self._capture_pane(pane_id, lines)

            # Check if at prompt
            info = await self.get_session(pane_id)
            at_prompt = info.at_prompt if info else False

            return f"Last {lines} lines:\n{output}\n\nAt prompt: {at_prompt}"
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

            await self._tmux("send-keys", "-t", pane_id, "C-l")
            return "Terminal cleared"
        except Exception as e:
            return f"Error: {e!s}"

    async def split_pane(
        self,
        direction: SplitDirection,
        session_id: str | None = None,
    ) -> str:
        """Split pane."""
        pane_id = session_id or await self._get_active_pane()
        if not pane_id:
            return "No active pane found"

        # -h for horizontal split (side by side), -v for vertical (stacked)
        split_flag = "-h" if direction == SplitDirection.HORIZONTAL else "-v"

        # Split and get new pane ID
        output = await self._tmux("split-window", split_flag, "-t", pane_id, "-P", "-F", "#{pane_id}")
        new_pane_id = output.strip()

        direction_text = "horizontally" if direction == SplitDirection.HORIZONTAL else "vertically"
        return f"Split {direction_text}. New session: {new_pane_id}"

    async def create_window(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new tmux session (equivalent to new window)."""
        try:
            # Generate session name
            session_name = f"vibe-{os.getpid()}"

            args = ["new-session", "-d", "-s", session_name, "-P", "-F", "#{pane_id}"]
            if command:
                args.extend([command])

            output = await self._tmux(*args)
            pane_id = output.strip()

            return f"New session created with pane_id: {pane_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_tab(
        self,
        profile: str | None = None,
        command: str | None = None,
    ) -> str:
        """Create new tmux window (equivalent to new tab)."""
        try:
            args = ["new-window", "-P", "-F", "#{pane_id}"]
            if command:
                args.extend([command])

            output = await self._tmux(*args)
            pane_id = output.strip()

            return f"New window created with pane_id: {pane_id}"
        except Exception as e:
            return f"Error: {e!s}"

    async def create_session(self, profile: str | None = None) -> str:
        """Smart session creation: split if in tmux, else new window."""
        try:
            active_pane = await self._get_active_pane()
            if active_pane:
                # Already in tmux, split
                return await self.split_pane(SplitDirection.HORIZONTAL)
            else:
                # Create new session
                return await self.create_window()
        except Exception as e:
            return f"Error: {e!s}"

    async def focus_session(self, session_id: str) -> str:
        """Focus specific pane."""
        try:
            await self._tmux("select-pane", "-t", session_id)
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

            await self._tmux("kill-pane", "-t", pane_id)
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
        """Set pane/window appearance.

        tmux supports:
        - Window (tab) rename
        - Pane title
        - Pane border styles (color)
        Badge is not supported.
        """
        results = []

        try:
            pane_id = session_id or await self._get_active_pane()

            if title:
                if pane_id:
                    # Set pane title
                    await self._tmux("select-pane", "-t", pane_id, "-T", title)
                    results.append(f"Pane title set to '{title}'")
                else:
                    # Rename current window
                    await self._tmux("rename-window", title)
                    results.append(f"Window renamed to '{title}'")

            if color:
                # Set pane border color
                # tmux uses style format like "fg=red" or "bg=blue"
                style = f"fg={color}"
                if pane_id:
                    await self._tmux("select-pane", "-t", pane_id, "-P", style)
                else:
                    await self._tmux("set-option", "pane-active-border-style", style)
                results.append(f"Pane style set to '{style}'")

            if badge:
                results.append("Badge not supported in tmux")

            if not results:
                return "No appearance changes requested"

            return "Appearance updated: " + "; ".join(results)
        except Exception as e:
            return f"Error setting appearance: {e!s}"

    async def rename_window(self, name: str) -> str:
        """Rename current tmux window."""
        try:
            await self._tmux("rename-window", name)
            return f"Window renamed to '{name}'"
        except Exception as e:
            return f"Error: {e!s}"

    async def set_pane_title(self, title: str, session_id: str | None = None) -> str:
        """Set pane title."""
        try:
            pane_id = session_id or await self._get_active_pane()
            if pane_id:
                await self._tmux("select-pane", "-t", pane_id, "-T", title)
                return f"Pane title set to '{title}'"
            return "No active pane found"
        except Exception as e:
            return f"Error: {e!s}"

    async def set_color_preset(self, preset: str, session_id: str | None = None) -> str:
        """Set tmux color style.

        Accepts tmux style format like 'fg=red,bg=black,bold'.
        Common presets: default, green, blue, red, yellow, cyan, magenta.
        """
        try:
            # Map simple color names to pane border style
            simple_colors = {"default", "green", "blue", "red", "yellow", "cyan", "magenta", "white", "black"}

            if preset.lower() in simple_colors:
                style = f"fg={preset}"
            else:
                # Assume it's already a valid tmux style string
                style = preset

            await self._tmux("set-option", "-g", "pane-active-border-style", style)
            await self._tmux("set-option", "-g", "pane-border-style", "fg=colour240")
            return f"Color preset '{preset}' applied"
        except Exception as e:
            return f"Error setting color preset: {e!s}"

    async def list_color_presets(self) -> str:
        """List available color options for tmux."""
        return """tmux color options:
- Simple colors: default, black, red, green, yellow, blue, magenta, cyan, white
- Extended: colour0-colour255
- Hex: #RRGGBB
- Styles: fg=COLOR,bg=COLOR,bold,underscore,blink,reverse,hidden

Example: set_color_preset('fg=green,bold')"""

    async def show_alert(self, title: str, message: str) -> str:
        """Display message in tmux status line."""
        try:
            # tmux display-message shows in status line
            await self._tmux("display-message", f"{title}: {message}")
            return f"Message displayed: {title}"
        except Exception as e:
            return f"Error: {e!s}"
