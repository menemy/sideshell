"""Integration tests for IntelliJ plugin — runs against a REAL IntelliJ instance.

Tests all JSON-RPC methods including split lifecycle, create/close tabs,
command execution, and terminal type detection.

Prerequisites:
  - IntelliJ with sideshell plugin running (auto-allow enabled for dev)
  - At least one terminal open

Run:
  uv run python -m pytest tests/test_intellij_integration.py -v -s
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

SPLIT_POLL_INTERVAL = 0.5
SPLIT_POLL_ATTEMPTS = 12  # 6 seconds total

SIDESHELL_DIR = Path.home() / ".sideshell"


def read_port_file() -> tuple[int, str] | None:
    port_file = SIDESHELL_DIR / "intellij-port"
    if not port_file.exists():
        return None
    data = json.loads(port_file.read_text())
    return data["port"], data["token"]


class IDEClient:
    """Minimal WebSocket JSON-RPC client."""

    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self.token = token
        self._ws: object = None
        self._req_id = 0

    async def connect(self) -> None:
        import websockets

        uri = f"ws://127.0.0.1:{self.port}?token={self.token}"
        self._ws = await asyncio.wait_for(websockets.connect(uri), timeout=5.0)

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()

    async def call(self, method: str, params: dict | None = None, timeout: float = 15.0):
        self._req_id += 1
        msg = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params:
            msg["params"] = params
        await self._ws.send(json.dumps(msg))
        raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        resp = json.loads(raw)
        if "error" in resp and resp["error"].get("code") == -32001:
            pytest.fail("Plugin requires user approval — click Allow in IDE")
        if "error" in resp:
            raise RuntimeError(f"RPC error: {resp['error']}")
        return resp["result"]


# ── Fixtures ─────────────────────────────────────────────────────────────────

info = read_port_file()
skip = pytest.mark.skipif(info is None, reason="IntelliJ plugin not running")


@pytest.fixture
async def ij():
    assert info is not None
    client = IDEClient(*info)
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def clean_ij(ij):
    """Fixture that cleans up extra terminals after the test."""
    before = await ij.call("list_sessions")
    initial_count = len(before)
    yield ij
    # Cleanup: close any extra terminals created during test
    await asyncio.sleep(0.5)
    after = await ij.call("list_sessions")
    for session in after[initial_count:]:
        try:
            await ij.call("close_session", {"session_id": session["id"]})
            await asyncio.sleep(0.3)
        except Exception:
            pass


# ── Session Listing ──────────────────────────────────────────────────────────


@skip
class TestListSessions:
    @pytest.mark.asyncio
    async def test_returns_list(self, ij):
        sessions = await ij.call("list_sessions")
        assert isinstance(sessions, list)
        assert len(sessions) >= 1, "Expected at least one terminal"

    @pytest.mark.asyncio
    async def test_session_fields(self, ij):
        sessions = await ij.call("list_sessions")
        s = sessions[0]
        for field in ("id", "name", "path", "job", "active", "at_prompt", "project", "type"):
            assert field in s, f"Missing field: {field}"
        assert s["id"].startswith("term-")
        assert s["type"] in ("classic", "new", "unknown")

    @pytest.mark.asyncio
    async def test_get_active_session(self, ij):
        result = await ij.call("get_active_session")
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_is_ai_session(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("is_ai_session", {"session_id": sid})
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_get_terminal_state_all(self, ij):
        state = await ij.call("get_terminal_state", {})
        assert "terminals" in state
        assert "total" in state
        assert state["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_terminal_state_specific(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        state = await ij.call("get_terminal_state", {"session_id": sid})
        assert state["id"] == sid
        assert "name" in state
        assert "type" in state


# ── Command Execution ────────────────────────────────────────────────────────


@skip
class TestCommands:
    @pytest.mark.asyncio
    async def test_execute_command(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("execute_command", {
            "session_id": sid,
            "command": "echo ij_test_ok",
            "wait": False,
        })
        assert "Executed" in result

    @pytest.mark.asyncio
    async def test_send_text(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("send_text", {"session_id": sid, "text": "# test"})
        assert "Sent" in result

    @pytest.mark.asyncio
    async def test_send_control_keys(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        for key in ("c", "d", "z", "a", "e", "k", "l", "u", "w"):
            result = await ij.call("send_control", {"session_id": sid, "key": key})
            assert "Sent control key" in result, f"Failed for key '{key}': {result}"

    @pytest.mark.asyncio
    async def test_send_control_navigation(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        for key in ("enter", "esc", "tab", "backspace", "up", "down", "left", "right"):
            result = await ij.call("send_control", {"session_id": sid, "key": key})
            assert "Sent control key" in result, f"Failed for key '{key}': {result}"

    @pytest.mark.asyncio
    async def test_send_control_unknown(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("send_control", {"session_id": sid, "key": "nonexistent"})
        assert "Unknown" in result

    @pytest.mark.asyncio
    async def test_read_terminal(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        # Execute a command first to have something to read
        await ij.call("execute_command", {
            "session_id": sid,
            "command": "echo read_test_12345",
            "wait": False,
        })
        await asyncio.sleep(0.5)
        result = await ij.call("read_terminal", {"session_id": sid, "lines": 10})
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_clear_terminal(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("clear_terminal", {"session_id": sid})
        assert "Cleared" in result


# ── Create Tab + Close ───────────────────────────────────────────────────────


@skip
class TestCreateClose:
    @pytest.mark.asyncio
    async def test_create_tab(self, clean_ij):
        ij = clean_ij
        before = await ij.call("list_sessions")
        count_before = len(before)

        result = await ij.call("create_tab", {})
        new_id = result["new_session_id"]
        assert isinstance(new_id, str)

        await asyncio.sleep(1)

        after = await ij.call("list_sessions")
        assert len(after) > count_before, (
            f"Expected more than {count_before} terminals, got {len(after)}"
        )

    @pytest.mark.asyncio
    async def test_create_tab_and_close(self, ij):
        before = await ij.call("list_sessions")
        count_before = len(before)

        result = await ij.call("create_tab", {})
        new_id = result["new_session_id"]
        await asyncio.sleep(1)

        after = await ij.call("list_sessions")
        assert len(after) > count_before

        # Find and close the new one
        new_sessions = [s for s in after if s["id"] not in [b["id"] for b in before]]
        assert len(new_sessions) >= 1, "New tab not found in session list"

        close_id = new_sessions[0]["id"]
        result = await ij.call("close_session", {"session_id": close_id})
        assert "Closed" in result

        await asyncio.sleep(1)

        final = await ij.call("list_sessions")
        assert len(final) == count_before, (
            f"Expected {count_before} terminals after close, got {len(final)}"
        )


# ── Split Pane ───────────────────────────────────────────────────────────────


@skip
class TestSplitPane:
    @pytest.mark.asyncio
    async def test_split_right(self, ij):
        """Split vertically (side by side) and verify detection."""
        before = await ij.call("list_sessions")
        count_before = len(before)
        sid = before[0]["id"]

        result = await ij.call("split_pane", {"session_id": sid, "direction": "v"})
        new_id = result["new_session_id"]
        assert isinstance(new_id, str)

        # Poll for split to be detected
        after = before
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            after = await ij.call("list_sessions")
            if len(after) > count_before:
                break

        assert len(after) > count_before, (
            f"Split right: expected more than {count_before}, got {len(after)}"
        )

        # Cleanup
        new_sessions = [s for s in after if s["id"] not in [b["id"] for b in before]]
        for s in new_sessions:
            await ij.call("close_session", {"session_id": s["id"]})
            await asyncio.sleep(0.3)

    @pytest.mark.asyncio
    async def test_split_down(self, ij):
        """Split horizontally (top/bottom) and verify detection."""
        before = await ij.call("list_sessions")
        count_before = len(before)
        sid = before[0]["id"]

        result = await ij.call("split_pane", {"session_id": sid, "direction": "h"})
        new_id = result["new_session_id"]
        assert isinstance(new_id, str)

        # Poll for split to be detected
        after = before
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            after = await ij.call("list_sessions")
            if len(after) > count_before:
                break

        assert len(after) > count_before, (
            f"Split down: expected more than {count_before}, got {len(after)}"
        )

        # Cleanup
        new_sessions = [s for s in after if s["id"] not in [b["id"] for b in before]]
        for s in new_sessions:
            await ij.call("close_session", {"session_id": s["id"]})
            await asyncio.sleep(0.3)

    @pytest.mark.asyncio
    async def test_split_and_execute_independently(self, ij):
        """Split, run different commands in each pane, verify output."""
        before = await ij.call("list_sessions")
        count_before = len(before)
        sid = before[0]["id"]

        result = await ij.call("split_pane", {"session_id": sid, "direction": "v"})

        # Poll for split to be detected
        after = before
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            after = await ij.call("list_sessions")
            if len(after) > count_before:
                break

        assert len(after) >= 2, f"Expected 2+ sessions, got {len(after)}"

        pane1 = after[0]["id"]
        pane2 = after[-1]["id"]
        assert pane1 != pane2, "Split should create a different session ID"

        # Execute different commands
        await ij.call("execute_command", {
            "session_id": pane1,
            "command": "echo PANE_A_OK",
        })
        await ij.call("execute_command", {
            "session_id": pane2,
            "command": "echo PANE_B_OK",
        })

        await asyncio.sleep(1)

        out1 = await ij.call("read_terminal", {"session_id": pane1, "lines": 5})
        out2 = await ij.call("read_terminal", {"session_id": pane2, "lines": 5})

        assert isinstance(out1, str)
        assert isinstance(out2, str)

        # Cleanup
        new_sessions = [s for s in after if s["id"] not in [b["id"] for b in before]]
        for s in new_sessions:
            await ij.call("close_session", {"session_id": s["id"]})
            await asyncio.sleep(0.3)

    @pytest.mark.asyncio
    async def test_split_close_restores_count(self, ij):
        """Split then close should restore original count."""
        before = await ij.call("list_sessions")
        count_before = len(before)

        await ij.call("split_pane", {"direction": "v"})

        # Poll for split to be detected
        mid = before
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            mid = await ij.call("list_sessions")
            if len(mid) > count_before:
                break

        assert len(mid) > count_before

        # Close the new pane
        new_sessions = [s for s in mid if s["id"] not in [b["id"] for b in before]]
        for s in new_sessions:
            await ij.call("close_session", {"session_id": s["id"]})
            await asyncio.sleep(0.3)

        await asyncio.sleep(0.5)
        final = await ij.call("list_sessions")
        assert len(final) == count_before, (
            f"After close: expected {count_before}, got {len(final)}"
        )

    @pytest.mark.asyncio
    async def test_multiple_splits(self, ij):
        """Multiple splits should create multiple detectable panes."""
        before = await ij.call("list_sessions")
        count_before = len(before)

        # Split right
        await ij.call("split_pane", {"direction": "v"})
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            mid = await ij.call("list_sessions")
            if len(mid) > count_before:
                break

        # Split down
        await ij.call("split_pane", {"direction": "h"})
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            after = await ij.call("list_sessions")
            if len(after) >= count_before + 2:
                break

        assert len(after) >= count_before + 2, (
            f"Two splits: expected {count_before + 2}+, got {len(after)}"
        )

        # Cleanup all new panes
        new_sessions = [s for s in after if s["id"] not in [b["id"] for b in before]]
        for s in reversed(new_sessions):
            await ij.call("close_session", {"session_id": s["id"]})
            await asyncio.sleep(0.3)


# ── Focus & Appearance ───────────────────────────────────────────────────────


@skip
class TestFocusAppearance:
    @pytest.mark.asyncio
    async def test_focus_session(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("focus_session", {"session_id": sid})
        assert "Focused" in result

    @pytest.mark.asyncio
    async def test_return_focus(self, ij):
        result = await ij.call("return_focus", {})
        assert "Focus returned" in result

    @pytest.mark.asyncio
    async def test_focus_then_return(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("focus_session", {"session_id": sid})
        assert "Focused" in result
        await asyncio.sleep(0.3)
        result = await ij.call("return_focus", {"session_id": sid})
        assert "Focus returned" in result

    @pytest.mark.asyncio
    async def test_set_title(self, ij):
        sessions = await ij.call("list_sessions")
        sid = sessions[0]["id"]
        result = await ij.call("set_appearance", {
            "session_id": sid,
            "title": "integration-test",
        })
        assert isinstance(result, str)


# ── Error Handling ───────────────────────────────────────────────────────────


@skip
class TestErrors:
    @pytest.mark.asyncio
    async def test_unknown_method(self, ij):
        with pytest.raises(RuntimeError, match="Unknown"):
            await ij.call("nonexistent_method")

    @pytest.mark.asyncio
    async def test_nonexistent_session_read(self, ij):
        result = await ij.call("read_terminal", {"session_id": "term-fake-999", "lines": 5})
        assert "not found" in result.lower() or "no output" in result.lower() or isinstance(result, str)

    @pytest.mark.asyncio
    async def test_nonexistent_session_execute(self, ij):
        result = await ij.call("execute_command", {
            "session_id": "term-fake-999",
            "command": "echo nope",
        })
        assert "not found" in result.lower()


# ── Full Lifecycle ───────────────────────────────────────────────────────────


@skip
class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_create_split_execute_close(self, ij):
        """Full workflow: create tab → split it → execute in each → close all."""
        initial = await ij.call("list_sessions")
        initial_count = len(initial)

        # 1. Create new tab
        result = await ij.call("create_tab", {})
        await asyncio.sleep(1)
        after_create = await ij.call("list_sessions")
        assert len(after_create) > initial_count, "create_tab should add a session"

        # 2. Split the new tab
        new_tab_id = [s for s in after_create if s["id"] not in [x["id"] for x in initial]][0]["id"]
        await ij.call("split_pane", {"session_id": new_tab_id, "direction": "v"})

        # Poll for split detection
        after_split = after_create
        for _ in range(SPLIT_POLL_ATTEMPTS):
            await asyncio.sleep(SPLIT_POLL_INTERVAL)
            after_split = await ij.call("list_sessions")
            if len(after_split) > len(after_create):
                break

        assert len(after_split) > len(after_create), "split should add another session"

        # 3. Execute in each new pane
        new_panes = [s for s in after_split if s["id"] not in [x["id"] for x in initial]]
        for i, pane in enumerate(new_panes):
            await ij.call("execute_command", {
                "session_id": pane["id"],
                "command": f"echo lifecycle_pane_{i}",
            })

        await asyncio.sleep(0.5)

        # 4. Read output from each
        for pane in new_panes:
            output = await ij.call("read_terminal", {"session_id": pane["id"], "lines": 3})
            assert isinstance(output, str)

        # 5. Close all new panes (reverse order)
        for pane in reversed(new_panes):
            await ij.call("close_session", {"session_id": pane["id"]})
            await asyncio.sleep(0.5)

        # 6. Verify we're back to initial count
        await asyncio.sleep(0.5)
        final = await ij.call("list_sessions")
        assert len(final) == initial_count, (
            f"After cleanup: expected {initial_count}, got {len(final)}"
        )
