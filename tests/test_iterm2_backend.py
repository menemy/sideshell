#!/usr/bin/env python3
"""Tests for iTerm2 backend.

Run with: python tests/test_iterm2_backend.py

Requirements:
- iTerm2 running with Python API enabled
- Tests create/close their own windows
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.iterm2_backend import ITermBackend
from sideshell_mcp.backends.base import SplitDirection, ControlKey
from tests.conftest import TEST_DELAY, BaseTestSuite


class TestITermBackend(BaseTestSuite):
    """Test suite for iTerm2 backend."""

    def __init__(self):
        super().__init__()
        self.backend = ITermBackend()
        self.created_sessions: list[str] = []

    def _extract_session_id(self, result: str) -> str | None:
        """Extract session ID from result string."""
        # iTerm2 session IDs are UUIDs
        match = re.search(
            r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
            result
        )
        return match.group(1) if match else None

    async def setup(self):
        """Set up test environment."""
        print("Setting up iTerm2 test environment...")

        if not self.backend.is_available:
            raise RuntimeError("iTerm2 is not available")

        connected = await self.backend.connect()
        if not connected:
            raise RuntimeError("Failed to connect to iTerm2")

        await self._delay()
        result = await self.backend.create_window()
        session_id = self._extract_session_id(result)
        if session_id:
            self.created_sessions.append(session_id)
            print(f"Created test session: {session_id}")
        else:
            raise RuntimeError(f"Failed to create test window: {result}")

        await asyncio.sleep(0.5)

    async def cleanup(self):
        """Clean up test sessions."""
        print("\nCleaning up test sessions...")
        for session_id in self.created_sessions:
            try:
                await self._delay()
                await self.backend.close_session(session_id, force=True)
                print(f"  Closed session: {session_id}")
            except Exception as e:
                print(f"  Failed to close session {session_id}: {e}")

    # --- Test Methods ---

    async def test_connection(self):
        """Test connection to iTerm2."""
        print("\n▶ test_connection")
        await self.backend.ensure_connection()
        self._assert(self.backend.app is not None, "App should be connected")

    async def test_list_sessions(self):
        """Test listing sessions."""
        print("\n▶ test_list_sessions")
        result = await self.backend.list_sessions()
        self._assert("panes" in result.lower() or "Window" in result, "Should list sessions")

    async def test_get_session(self):
        """Test getting session info."""
        print("\n▶ test_get_session")
        session_id = self.created_sessions[0]
        info = await self.backend.get_session(session_id)
        self._assert(info is not None, "Should get session info")
        if info:
            self._assert(info.session_id == session_id, "Session ID should match")

    async def test_get_terminal_state(self):
        """Test getting terminal state."""
        print("\n▶ test_get_terminal_state")
        result = await self.backend.get_terminal_state()
        self._assert("windows" in result.lower() or "sessions" in result.lower(), "Should return state")

    async def test_execute_command(self):
        """Test executing command."""
        print("\n▶ test_execute_command")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.execute_command("echo 'hello iterm'", session_id)
        await self._delay()
        self._assert("Sent" in result or "sent" in result.lower(), "Should confirm command sent")

    async def test_execute_with_wait(self):
        """Test executing command with wait."""
        print("\n▶ test_execute_with_wait")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.execute_command(
            "echo 'wait test'",
            session_id,
            wait=True,
            timeout=10,
            watch_for="silence"
        )
        self._assert("Completed" in result or "wait test" in result, "Should complete with output")

    async def test_read_terminal(self):
        """Test reading terminal output."""
        print("\n▶ test_read_terminal")
        session_id = self.created_sessions[0]
        await self._delay()
        await self.backend.execute_command("echo 'read test marker'", session_id)
        await asyncio.sleep(0.5)
        result = await self.backend.read_terminal(lines=20, session_id=session_id)
        self._assert("read test marker" in result or "lines" in result.lower(), "Should read terminal content")

    async def test_cursor_position(self):
        """Test that cursor position is returned."""
        print("\n▶ test_cursor_position")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.read_terminal(lines=10, session_id=session_id)
        self._assert("Cursor:" in result, "Should include cursor position")

    async def test_send_text(self):
        """Test sending text."""
        print("\n▶ test_send_text")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.send_text("test text", session_id)
        self._assert("Pasted" in result or "characters" in result, "Should paste text")

    async def test_send_control(self):
        """Test sending control characters."""
        print("\n▶ test_send_control")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.L, session_id)
        self._assert("Ctrl+" in result or "Sent" in result, "Should send control character")

    async def test_arrow_keys(self):
        """Test sending arrow keys."""
        print("\n▶ test_arrow_keys")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.UP, session_id)
        self._assert("Up arrow" in result, "Should send Up arrow")
        result = await self.backend.send_control(ControlKey.DOWN, session_id)
        self._assert("Down arrow" in result, "Should send Down arrow")

    async def test_function_keys(self):
        """Test sending function keys."""
        print("\n▶ test_function_keys")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.F1, session_id)
        self._assert("F1" in result, "Should send F1 key")

    async def test_navigation_keys(self):
        """Test sending navigation keys."""
        print("\n▶ test_navigation_keys")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.HOME, session_id)
        self._assert("Home" in result, "Should send Home key")
        result = await self.backend.send_control(ControlKey.END, session_id)
        self._assert("End" in result, "Should send End key")

    async def test_clear_terminal(self):
        """Test clearing terminal."""
        print("\n▶ test_clear_terminal")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.clear_terminal(session_id)
        self._assert("cleared" in result.lower(), "Should clear terminal")

    async def test_split_pane(self):
        """Test splitting pane."""
        print("\n▶ test_split_pane")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.split_pane(SplitDirection.HORIZONTAL, session_id)
        await self._delay()
        self._assert("Split" in result, "Should split pane")

        new_session_id = self._extract_session_id(result)
        if new_session_id:
            self.created_sessions.append(new_session_id)
            self._assert(True, f"Created new session: {new_session_id}")
        else:
            self._assert(False, "Should return new session ID")

    async def test_create_tab(self):
        """Test creating new tab."""
        print("\n▶ test_create_tab")
        await self._delay()
        result = await self.backend.create_tab()
        await self._delay()
        self._assert("created" in result.lower() or "session_id" in result.lower(), "Should create tab")

        new_session_id = self._extract_session_id(result)
        if new_session_id:
            self.created_sessions.append(new_session_id)
            self._assert(True, f"Created new session: {new_session_id}")

    async def test_focus_session(self):
        """Test focusing session."""
        print("\n▶ test_focus_session")
        if len(self.created_sessions) > 1:
            session_id = self.created_sessions[0]
            await self._delay()
            result = await self.backend.focus_session(session_id)
            await self._delay()
            self._assert("Focused" in result or "focus" in result.lower(), "Should focus session")
        else:
            self._assert(True, "Skipped (only one session)")

    async def test_set_appearance(self):
        """Test setting appearance."""
        print("\n▶ test_set_appearance")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.set_appearance(
            session_id=session_id,
            title="Test Title",
            badge="TEST",
            color="blue"
        )
        await self._delay()
        self._assert("Appearance" in result or "title" in result.lower(), "Should set appearance")

    async def test_list_color_presets(self):
        """Test listing color presets."""
        print("\n▶ test_list_color_presets")
        result = await self.backend.list_color_presets()
        self._assert("presets" in result.lower() or "Solarized" in result, "Should list presets")

    async def test_set_color_preset(self):
        """Test setting color preset."""
        print("\n▶ test_set_color_preset")
        session_id = self.created_sessions[0]
        await self._delay()
        result = await self.backend.set_color_preset("Solarized Dark", session_id)
        await self._delay()
        self._assert("set" in result.lower() or "color" in result.lower(), "Should set color preset")

    async def test_show_alert(self):
        """Test showing alert. Requires manual OK click or accessibility permissions."""
        print("\n▶ test_show_alert")
        print("  ⚠️  Click OK on the alert dialog (or grant Automation permissions)")
        await self._delay()

        import subprocess

        # Try auto-dismiss - requires:
        # System Settings > Privacy > Automation > iTerm2 > System Events ✓
        dismiss_proc = subprocess.Popen([
            'osascript', '-e',
            '''
            repeat 20 times
                delay 0.15
                tell application "System Events"
                    tell process "iTerm2"
                        try
                            click button "OK" of sheet 1 of window 1
                            exit repeat
                        end try
                        try
                            click button "OK" of front window
                            exit repeat
                        end try
                    end tell
                end tell
            end repeat
            '''
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # show_alert blocks until user clicks OK
        result = await self.backend.show_alert("Test Alert", "Click OK or wait for auto-dismiss")
        dismiss_proc.terminate()
        await self._delay()
        self._assert("alert" in result.lower() or "shown" in result.lower(), "Should show alert")

    async def test_close_session(self):
        """Test closing session."""
        print("\n▶ test_close_session")
        await self._delay()
        result = await self.backend.split_pane(SplitDirection.VERTICAL, self.created_sessions[0])
        new_session_id = self._extract_session_id(result)

        if new_session_id:
            await self._delay()
            close_result = await self.backend.close_session(new_session_id, force=True)
            await self._delay()
            self._assert("Closed" in close_result or "close" in close_result.lower(), "Should close session")
        else:
            self._assert(False, "Could not create session to close")

    async def test_invalid_session(self):
        """Test operations on invalid session."""
        print("\n▶ test_invalid_session")
        result = await self.backend.execute_command("echo test", "invalid-uuid-here")
        self._assert("not found" in result.lower() or "Error" in result, "Should handle invalid session")

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
            self.test_cursor_position,
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
            self.test_list_color_presets,
            self.test_set_color_preset,
            self.test_show_alert,
            self.test_close_session,
            self.test_invalid_session,
        ]

        return await self.run_tests(tests)


async def main():
    """Main test runner."""
    print("=" * 60)
    print("iTerm2 Backend Test Suite")
    print(f"(delay: {TEST_DELAY}s between operations)")
    print("=" * 60)

    backend = ITermBackend()
    if not backend.is_available:
        print("\nERROR: iTerm2 Python API not available")
        print("Make sure iTerm2 is running with Python API enabled")
        sys.exit(1)

    suite = TestITermBackend()

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
