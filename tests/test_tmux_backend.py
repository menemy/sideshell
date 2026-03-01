#!/usr/bin/env python3
"""Tests for tmux backend.

Run with: python tests/test_tmux_backend.py

Requirements:
- tmux must be installed and running
- Tests create/close their own sessions
"""

import asyncio
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.tmux_backend import TmuxBackend
from sideshell_mcp.backends.base import SplitDirection, ControlKey
from tests.conftest import TEST_DELAY, BaseTestSuite


class TestTmuxBackend(BaseTestSuite):
    """Test suite for tmux backend."""

    def __init__(self):
        super().__init__()
        self.backend = TmuxBackend()
        self.created_panes: list[str] = []
        self.terminal_opened = False

    def _extract_pane_id(self, result: str) -> str | None:
        """Extract pane ID from result string."""
        # tmux pane IDs are like %0, %1, %2
        match = re.search(r'(%\d+)', result)
        return match.group(1) if match else None

    async def setup(self):
        """Set up test environment."""
        print("Setting up tmux test environment...")

        if not self.backend.is_available:
            raise RuntimeError("tmux is not available")

        # Open a terminal window with tmux so user can see the tests
        print("Opening terminal window with tmux...")
        subprocess.Popen([
            'osascript', '-e',
            '''
            tell application "Terminal"
                activate
                do script "tmux attach || tmux new-session"
            end tell
            '''
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.terminal_opened = True
        await asyncio.sleep(1.5)  # Wait for terminal to open and tmux to attach

        connected = await self.backend.connect()
        if not connected:
            raise RuntimeError("Failed to connect to tmux")

        await self._delay()
        result = await self.backend.create_window()
        pane_id = self._extract_pane_id(result)
        if pane_id:
            self.created_panes.append(pane_id)
            print(f"Created test pane: {pane_id}")
        else:
            raise RuntimeError(f"Failed to create test pane: {result}")

        await asyncio.sleep(0.5)

    async def cleanup(self):
        """Clean up test panes."""
        print("\nCleaning up test panes...")
        for pane_id in self.created_panes:
            try:
                await self._delay()
                await self.backend.close_session(pane_id, force=True)
                print(f"  Closed pane: {pane_id}")
            except Exception as e:
                print(f"  Failed to close pane {pane_id}: {e}")

        # Close the Terminal window we opened for the test
        if self.terminal_opened:
            print("Closing test terminal window...")
            subprocess.run([
                'osascript', '-e',
                '''
                tell application "Terminal"
                    close (every window whose name contains "tmux")
                end tell
                '''
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- Test Methods ---

    async def test_connection(self):
        """Test connection to tmux."""
        print("\n▶ test_connection")
        await self.backend.ensure_connection()
        self._assert(self.backend._connected, "Backend should be connected")

    async def test_list_sessions(self):
        """Test listing sessions."""
        print("\n▶ test_list_sessions")
        result = await self.backend.list_sessions()
        self._assert("panes" in result.lower() or "%" in result, "Should list panes")

    async def test_get_session(self):
        """Test getting session info."""
        print("\n▶ test_get_session")
        pane_id = self.created_panes[0]
        info = await self.backend.get_session(pane_id)
        self._assert(info is not None, "Should get session info")
        if info:
            self._assert(info.session_id == pane_id, "Session ID should match")

    async def test_get_terminal_state(self):
        """Test getting terminal state."""
        print("\n▶ test_get_terminal_state")
        result = await self.backend.get_terminal_state()
        self._assert("panes" in result.lower() or "sessions" in result.lower(), "Should return state")

    async def test_execute_command(self):
        """Test executing command."""
        print("\n▶ test_execute_command")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.execute_command("echo 'hello tmux'", pane_id)
        await self._delay()
        self._assert("Sent" in result or "sent" in result.lower(), "Should confirm command sent")

    async def test_execute_with_wait(self):
        """Test executing command with wait."""
        print("\n▶ test_execute_with_wait")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.execute_command(
            "echo 'wait test'",
            pane_id,
            wait=True,
            timeout=10,
            watch_for="silence"
        )
        self._assert("Completed" in result or "wait test" in result, "Should complete with output")

    async def test_read_terminal(self):
        """Test reading terminal output."""
        print("\n▶ test_read_terminal")
        pane_id = self.created_panes[0]
        await self._delay()
        await self.backend.execute_command("echo 'read test marker'", pane_id)
        await asyncio.sleep(0.5)
        result = await self.backend.read_terminal(lines=20, session_id=pane_id)
        self._assert("read test marker" in result or "lines" in result.lower(), "Should read terminal content")

    async def test_send_text(self):
        """Test sending text."""
        print("\n▶ test_send_text")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.send_text("test text", pane_id)
        self._assert("Pasted" in result or "characters" in result, "Should paste text")

    async def test_send_control(self):
        """Test sending control characters."""
        print("\n▶ test_send_control")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.L, pane_id)
        self._assert("Ctrl+" in result or "Sent" in result, "Should send control character")

    async def test_arrow_keys(self):
        """Test sending arrow keys."""
        print("\n▶ test_arrow_keys")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.UP, pane_id)
        self._assert("Up arrow" in result or "Sent" in result, "Should send Up arrow")
        result = await self.backend.send_control(ControlKey.DOWN, pane_id)
        self._assert("Down arrow" in result or "Sent" in result, "Should send Down arrow")

    async def test_function_keys(self):
        """Test sending function keys."""
        print("\n▶ test_function_keys")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.F1, pane_id)
        self._assert("F1" in result or "Sent" in result, "Should send F1 key")

    async def test_navigation_keys(self):
        """Test sending navigation keys."""
        print("\n▶ test_navigation_keys")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.HOME, pane_id)
        self._assert("Home" in result or "Sent" in result, "Should send Home key")
        result = await self.backend.send_control(ControlKey.END, pane_id)
        self._assert("End" in result or "Sent" in result, "Should send End key")

    async def test_clear_terminal(self):
        """Test clearing terminal."""
        print("\n▶ test_clear_terminal")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.clear_terminal(pane_id)
        self._assert("cleared" in result.lower(), "Should clear terminal")

    async def test_split_pane(self):
        """Test splitting pane."""
        print("\n▶ test_split_pane")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.split_pane(SplitDirection.HORIZONTAL, pane_id)
        await self._delay()
        self._assert("Split" in result, "Should split pane")

        new_pane_id = self._extract_pane_id(result)
        if new_pane_id:
            self.created_panes.append(new_pane_id)
            self._assert(True, f"Created new pane: {new_pane_id}")
        else:
            self._assert(False, "Should return new pane ID")

    async def test_create_tab(self):
        """Test creating new tab (window in tmux)."""
        print("\n▶ test_create_tab")
        await self._delay()
        result = await self.backend.create_tab()
        await self._delay()
        self._assert("created" in result.lower() or "pane_id" in result.lower(), "Should create tab")

        new_pane_id = self._extract_pane_id(result)
        if new_pane_id:
            self.created_panes.append(new_pane_id)
            self._assert(True, f"Created new pane: {new_pane_id}")

    async def test_focus_session(self):
        """Test focusing session."""
        print("\n▶ test_focus_session")
        if len(self.created_panes) > 1:
            pane_id = self.created_panes[0]
            await self._delay()
            result = await self.backend.focus_session(pane_id)
            await self._delay()
            self._assert("Focused" in result or "focus" in result.lower(), "Should focus pane")
        else:
            self._assert(True, "Skipped (only one pane)")

    async def test_set_appearance(self):
        """Test setting appearance."""
        print("\n▶ test_set_appearance")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.set_appearance(session_id=pane_id, title="Test Pane")
        await self._delay()
        self._assert("title" in result.lower() or "appearance" in result.lower(), "Should set title")

    async def test_rename_window(self):
        """Test renaming window."""
        print("\n▶ test_rename_window")
        await self._delay()
        result = await self.backend.rename_window("Test Window")
        await self._delay()
        self._assert("renamed" in result.lower() or "window" in result.lower(), "Should rename window")

    async def test_list_color_presets(self):
        """Test listing color options."""
        print("\n▶ test_list_color_presets")
        result = await self.backend.list_color_presets()
        self._assert("color" in result.lower() or "style" in result.lower(), "Should return color options")

    async def test_show_alert(self):
        """Test showing message in status line."""
        print("\n▶ test_show_alert")
        await self._delay()
        result = await self.backend.show_alert("Test", "Message")
        await self._delay()
        self._assert("message" in result.lower() or "display" in result.lower(), "Should display message")

    async def test_close_session(self):
        """Test closing session."""
        print("\n▶ test_close_session")
        await self._delay()
        result = await self.backend.split_pane(SplitDirection.VERTICAL, self.created_panes[0])
        new_pane_id = self._extract_pane_id(result)

        if new_pane_id:
            await self._delay()
            close_result = await self.backend.close_session(new_pane_id, force=True)
            await self._delay()
            self._assert("Closed" in close_result or "close" in close_result.lower(), "Should close pane")
        else:
            self._assert(False, "Could not create pane to close")

    async def test_invalid_session(self):
        """Test operations on invalid session."""
        print("\n▶ test_invalid_session")
        result = await self.backend.execute_command("echo test", "%99999")
        self._assert("Error" in result or "not found" in result.lower() or "Sent" in result, "Should handle invalid pane")

    async def run_all(self):
        """Run all tests."""
        tests = [
            self.test_connection,
            self.test_list_sessions,
            self.test_get_session,
            self.test_get_terminal_state,
            self.test_execute_command,
            self.test_execute_with_wait,
            self.test_read_terminal,
            self.test_send_text,
            self.test_send_control,
            self.test_arrow_keys,
            self.test_function_keys,
            self.test_navigation_keys,
            self.test_clear_terminal,
            self.test_split_pane,
            self.test_create_tab,
            self.test_focus_session,
            self.test_set_appearance,
            self.test_rename_window,
            self.test_list_color_presets,
            self.test_show_alert,
            self.test_close_session,
            self.test_invalid_session,
        ]

        return await self.run_tests(tests)


async def main():
    """Main test runner."""
    print("=" * 60)
    print("tmux Backend Test Suite")
    print(f"(delay: {TEST_DELAY}s between operations)")
    print("=" * 60)

    backend = TmuxBackend()
    if not backend.is_available:
        print("\nERROR: tmux is not installed or not in PATH")
        print("Install with: brew install tmux (macOS) or apt install tmux (Linux)")
        sys.exit(1)

    suite = TestTmuxBackend()

    try:
        await suite.setup()
        passed, failed = await suite.run_all()
    finally:
        await suite.cleanup()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
