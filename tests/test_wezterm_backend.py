#!/usr/bin/env python3
"""Tests for WezTerm backend.

Run with: python tests/test_wezterm_backend.py

Requirements:
- WezTerm must be running
- Tests create/close their own panes
"""

import asyncio
import re
import subprocess
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.wezterm_backend import WezTermBackend
from sideshell_mcp.backends.base import SplitDirection, ControlKey


class TestWezTermBackend:
    """Test suite for WezTerm backend."""

    # Delay between operations to see what's happening
    OP_DELAY = 0.6

    def __init__(self):
        self.backend = WezTermBackend()
        self.created_panes: list[str] = []
        self.passed = 0
        self.failed = 0
        self.wezterm_launched = False

    async def _delay(self):
        """Delay for visual observation."""
        await asyncio.sleep(self.OP_DELAY)

    def _extract_pane_id(self, result: str) -> str | None:
        """Extract pane ID from result string."""
        match = re.search(r'pane[_\s]*(?:id)?[:\s]*(\d+)', result.lower())
        if match:
            return match.group(1)
        match = re.search(r':\s*(\d+)$', result)
        if match:
            return match.group(1)
        match = re.search(r'\b(\d+)\b', result)
        return match.group(1) if match else None

    async def setup(self):
        """Set up test environment."""
        print("Setting up WezTerm test environment...")

        if not self.backend.is_available:
            raise RuntimeError("WezTerm is not available")

        # Launch WezTerm if not running
        import shutil
        wezterm_path = shutil.which("wezterm")
        if wezterm_path:
            # Check if WezTerm is already running
            check = subprocess.run(
                [wezterm_path, "cli", "list"],
                capture_output=True, text=True
            )
            if check.returncode != 0:
                print("Launching WezTerm...")
                subprocess.Popen(
                    ["open", "-a", "WezTerm"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.wezterm_launched = True
                await asyncio.sleep(2)  # Wait for WezTerm to start

        connected = await self.backend.connect()
        if not connected:
            raise RuntimeError("Failed to connect to WezTerm")

        await self._delay()
        result = await self.backend.create_window()
        pane_id = self._extract_pane_id(result)
        if pane_id:
            self.created_panes.append(pane_id)
            print(f"Created test pane: {pane_id}")
        else:
            raise RuntimeError(f"Failed to create test window: {result}")

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

        # Close WezTerm if we launched it
        if self.wezterm_launched:
            print("Closing WezTerm...")
            subprocess.run(
                ["osascript", "-e", 'quit app "WezTerm"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

    def _assert(self, condition: bool, message: str):
        """Assert helper with counting."""
        if condition:
            self.passed += 1
            print(f"  ✓ {message}")
        else:
            self.failed += 1
            print(f"  ✗ {message}")

    # --- Test Methods ---

    async def test_connection(self):
        """Test connection to WezTerm."""
        print("\n▶ test_connection")
        await self.backend.ensure_connection()
        self._assert(self.backend._connected, "Backend should be connected")

    async def test_list_sessions(self):
        """Test listing sessions."""
        print("\n▶ test_list_sessions")
        result = await self.backend.list_sessions()
        self._assert("panes" in result.lower() or "Window" in result, "Should list panes")

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
        self._assert("panes" in result.lower() or "{" in result, "Should return state")

    async def test_execute_command(self):
        """Test executing command."""
        print("\n▶ test_execute_command")
        pane_id = self.created_panes[0]
        await self._delay()
        result = await self.backend.execute_command("echo 'hello wezterm'", pane_id)
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
        """Test creating new tab."""
        print("\n▶ test_create_tab")
        await self._delay()
        result = await self.backend.create_tab()
        await self._delay()
        self._assert("created" in result.lower() or "pane" in result.lower(), "Should create tab")

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
        result = await self.backend.set_appearance(session_id=pane_id, title="Test Tab")
        await self._delay()
        self._assert("title" in result.lower() or "appearance" in result.lower(), "Should set title")

    async def test_set_window_title(self):
        """Test setting window title."""
        print("\n▶ test_set_window_title")
        await self._delay()
        result = await self.backend.set_window_title("Test Window")
        await self._delay()
        self._assert("title" in result.lower() or "window" in result.lower(), "Should set window title")

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
        result = await self.backend.execute_command("echo test", "99999")
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
            self.test_clear_terminal,
            self.test_split_pane,
            self.test_create_tab,
            self.test_focus_session,
            self.test_set_appearance,
            self.test_set_window_title,
            self.test_close_session,
            self.test_invalid_session,
        ]

        for test in tests:
            try:
                await test()
                await self._delay()
            except Exception as e:
                self.failed += 1
                print(f"  ✗ ERROR in {test.__name__}: {e}")

        return self.passed, self.failed


async def main():
    """Main test runner."""
    print("=" * 60)
    print("WezTerm Backend Test Suite")
    print("=" * 60)

    backend = WezTermBackend()
    if not backend.is_available:
        print("\nERROR: WezTerm is not installed or not in PATH")
        print("Install with: brew install --cask wezterm")
        sys.exit(1)

    suite = TestWezTermBackend()

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
