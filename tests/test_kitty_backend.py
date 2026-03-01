#!/usr/bin/env python3
"""Tests for Kitty backend.

Run with: python tests/test_kitty_backend.py

Requirements:
- Kitty must be running with remote control enabled:
  kitty -o allow_remote_control=yes --listen-on unix:/tmp/kitty.sock
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.kitty_backend import KittyBackend
from sideshell_mcp.backends.base import SplitDirection, ControlKey
from tests.conftest import TEST_DELAY, BaseTestSuite


class TestKittyBackend(BaseTestSuite):
    """Test suite for Kitty backend."""

    def __init__(self, listen_on: str | None = None):
        super().__init__()
        self.backend = KittyBackend(listen_on=listen_on or "unix:/tmp/kitty.sock")
        self.created_windows: list[str] = []
        self.kitty_launched = False
        self.kitty_process = None

    def _extract_window_id(self, result: str) -> str | None:
        """Extract window ID from result string."""
        match = re.search(r'window[:\s]*(\d+)', result.lower())
        if match:
            return match.group(1)
        match = re.search(r':\s*(\d+)$', result)
        if match:
            return match.group(1)
        match = re.search(r'\b(\d+)\b', result)
        return match.group(1) if match else None

    async def setup(self):
        """Set up test environment."""
        print("Setting up Kitty test environment...")

        if not self.backend.is_available:
            raise RuntimeError("Kitty is not available")

        # Try to connect, launch Kitty if needed
        connected = await self.backend.connect()
        if not connected:
            print("Launching Kitty with remote control...")
            import shutil
            kitty_path = shutil.which("kitty")
            if kitty_path:
                self.kitty_process = subprocess.Popen(
                    [kitty_path, "-o", "allow_remote_control=yes",
                     "--listen-on", "unix:/tmp/kitty.sock"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.kitty_launched = True
                await asyncio.sleep(2)  # Wait for Kitty to start
                connected = await self.backend.connect()

        if not connected:
            raise RuntimeError(
                "Failed to connect to Kitty. "
                "Make sure Kitty is installed."
            )

        await self._delay()
        result = await self.backend.create_tab()
        window_id = self._extract_window_id(result)
        if window_id:
            self.created_windows.append(window_id)
            print(f"Created test window: {window_id}")
        else:
            raise RuntimeError(f"Failed to create test window: {result}")

        await asyncio.sleep(0.5)

    async def cleanup(self):
        """Clean up test windows."""
        print("\nCleaning up test windows...")
        for window_id in self.created_windows:
            try:
                await self._delay()
                await self.backend.close_session(window_id, force=True)
                print(f"  Closed window: {window_id}")
            except Exception as e:
                print(f"  Failed to close window {window_id}: {e}")

        # Close Kitty if we launched it
        if self.kitty_launched and self.kitty_process:
            print("Closing Kitty...")
            self.kitty_process.terminate()
            try:
                self.kitty_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.kitty_process.kill()

    # --- Test Methods ---

    async def test_connection(self):
        """Test connection to Kitty."""
        print("\n▶ test_connection")
        await self.backend.ensure_connection()
        self._assert(self.backend._connected, "Backend should be connected")

    async def test_list_sessions(self):
        """Test listing sessions."""
        print("\n▶ test_list_sessions")
        result = await self.backend.list_sessions()
        self._assert("windows" in result.lower() or "Tab" in result or "OS Window" in result, "Should list windows")

    async def test_get_session(self):
        """Test getting session info."""
        print("\n▶ test_get_session")
        window_id = self.created_windows[0]
        info = await self.backend.get_session(window_id)
        self._assert(info is not None, "Should get session info")
        if info:
            self._assert(info.session_id == window_id, "Session ID should match")

    async def test_get_terminal_state(self):
        """Test getting terminal state."""
        print("\n▶ test_get_terminal_state")
        result = await self.backend.get_terminal_state()
        self._assert("[" in result or "{" in result, "Should return state as JSON")

    async def test_execute_command(self):
        """Test executing command."""
        print("\n▶ test_execute_command")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.execute_command("echo 'hello kitty'", window_id)
        await self._delay()
        self._assert("Sent" in result or "sent" in result.lower(), "Should confirm command sent")

    async def test_execute_with_wait(self):
        """Test executing command with wait."""
        print("\n▶ test_execute_with_wait")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.execute_command(
            "echo 'wait test'",
            window_id,
            wait=True,
            timeout=10,
            watch_for="silence"
        )
        self._assert("Completed" in result or "wait test" in result, "Should complete with output")

    async def test_read_terminal(self):
        """Test reading terminal output."""
        print("\n▶ test_read_terminal")
        window_id = self.created_windows[0]
        await self._delay()
        await self.backend.execute_command("echo 'read test marker'", window_id)
        await asyncio.sleep(0.5)
        result = await self.backend.read_terminal(lines=20, session_id=window_id)
        self._assert("read test marker" in result or "lines" in result.lower(), "Should read terminal content")

    async def test_send_text(self):
        """Test sending text."""
        print("\n▶ test_send_text")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.send_text("test text", window_id)
        self._assert("Pasted" in result or "characters" in result, "Should paste text")

    async def test_send_control(self):
        """Test sending control characters."""
        print("\n▶ test_send_control")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.send_control(ControlKey.L, window_id)
        self._assert("Ctrl+" in result or "Sent" in result, "Should send control character")

    async def test_clear_terminal(self):
        """Test clearing terminal."""
        print("\n▶ test_clear_terminal")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.clear_terminal(window_id)
        self._assert("cleared" in result.lower(), "Should clear terminal")

    async def test_split_pane(self):
        """Test splitting pane."""
        print("\n▶ test_split_pane")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.split_pane(SplitDirection.HORIZONTAL, window_id)
        await self._delay()
        self._assert("Split" in result, "Should split window")

        new_window_id = self._extract_window_id(result)
        if new_window_id:
            self.created_windows.append(new_window_id)
            self._assert(True, f"Created new window: {new_window_id}")
        else:
            self._assert(False, "Should return new window ID")

    async def test_create_tab(self):
        """Test creating new tab."""
        print("\n▶ test_create_tab")
        await self._delay()
        result = await self.backend.create_tab()
        await self._delay()
        self._assert("created" in result.lower() or "tab" in result.lower(), "Should create tab")

        new_window_id = self._extract_window_id(result)
        if new_window_id:
            self.created_windows.append(new_window_id)
            self._assert(True, f"Created new window: {new_window_id}")

    async def test_focus_session(self):
        """Test focusing session."""
        print("\n▶ test_focus_session")
        if len(self.created_windows) > 1:
            window_id = self.created_windows[0]
            await self._delay()
            result = await self.backend.focus_session(window_id)
            await self._delay()
            self._assert("Focused" in result or "focus" in result.lower(), "Should focus window")
        else:
            self._assert(True, "Skipped (only one window)")

    async def test_set_appearance(self):
        """Test setting appearance."""
        print("\n▶ test_set_appearance")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.set_appearance(session_id=window_id, title="Test Tab")
        await self._delay()
        self._assert("title" in result.lower() or "appearance" in result.lower(), "Should set title")

    async def test_set_window_title(self):
        """Test setting window title."""
        print("\n▶ test_set_window_title")
        window_id = self.created_windows[0]
        await self._delay()
        result = await self.backend.set_window_title("Test Window", session_id=window_id)
        await self._delay()
        self._assert("title" in result.lower() or "window" in result.lower(), "Should set window title")

    async def test_list_color_presets(self):
        """Test listing color presets."""
        print("\n▶ test_list_color_presets")
        result = await self.backend.list_color_presets()
        self._assert("color" in result.lower() or "theme" in result.lower(), "Should return color info")

    async def test_show_alert(self):
        """Test showing alert/notification."""
        print("\n▶ test_show_alert")
        await self._delay()
        result = await self.backend.show_alert("Test Title", "Test message")
        await self._delay()
        self._assert("notification" in result.lower() or "sent" in result.lower(), "Should send notification")

    async def test_close_session(self):
        """Test closing session."""
        print("\n▶ test_close_session")
        await self._delay()
        result = await self.backend.split_pane(SplitDirection.VERTICAL, self.created_windows[0])
        new_window_id = self._extract_window_id(result)

        if new_window_id:
            await self._delay()
            close_result = await self.backend.close_session(new_window_id, force=True)
            await self._delay()
            self._assert("Closed" in close_result or "close" in close_result.lower(), "Should close window")
        else:
            self._assert(False, "Could not create window to close")

    async def test_invalid_session(self):
        """Test operations on invalid session."""
        print("\n▶ test_invalid_session")
        result = await self.backend.execute_command("echo test", "99999")
        self._assert("Error" in result or "not found" in result.lower() or "Sent" in result, "Should handle invalid window")

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
            self.test_clear_terminal,
            self.test_split_pane,
            self.test_create_tab,
            self.test_focus_session,
            self.test_set_appearance,
            self.test_set_window_title,
            self.test_list_color_presets,
            self.test_show_alert,
            self.test_close_session,
            self.test_invalid_session,
        ]

        return await self.run_tests(tests)


async def main():
    """Main test runner."""
    print("=" * 60)
    print("Kitty Backend Test Suite")
    print(f"(delay: {TEST_DELAY}s between operations)")
    print("=" * 60)

    backend = KittyBackend()
    if not backend.is_available:
        print("\nERROR: Kitty is not installed or not in PATH")
        print("Install with: brew install --cask kitty")
        sys.exit(1)

    suite = TestKittyBackend()

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
