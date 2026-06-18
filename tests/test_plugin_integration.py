"""Integration tests against REAL running IDE plugins.

These tests connect to actually running VSCode/IntelliJ plugins via Unix socket
and exercise every JSON-RPC method with assertions.

Prerequisites:
  - VSCode/Cursor with sideshell extension running
  - IntelliJ with sideshell plugin running
  - At least one terminal open in each IDE
  - User must click "Allow" on first run (consent dialog)

Run:
  uv run python -m pytest tests/test_plugin_integration.py -v -s
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

SIDESHELL_DIR = Path.home() / ".sideshell"


def read_port_file(ide: str) -> tuple[str, str] | None:
    """Read socket path and token from port file."""
    port_file = SIDESHELL_DIR / f"{ide}-port"
    if not port_file.exists():
        return None
    data = json.loads(port_file.read_text())
    sock = data.get("socket", str(SIDESHELL_DIR / f"{ide}.sock"))
    token = data.get("token", "")
    return sock, token


class IDEClient:
    """Minimal Unix socket JSON-RPC client for integration tests."""

    def __init__(self, socket_path: str, token: str) -> None:
        self.socket_path = socket_path
        self.token = token
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._req_id = 0

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_unix_connection(self.socket_path),
            timeout=5.0,
        )
        # Send auth handshake
        handshake = {"type": "auth", "token": self.token}
        self._writer.write(json.dumps(handshake).encode() + b"\n")
        await self._writer.drain()
        # Read auth response
        line = await asyncio.wait_for(self._reader.readline(), timeout=5.0)
        resp = json.loads(line.decode())
        if not resp.get("ok"):
            raise ConnectionError(f"Auth failed: {resp.get('error')}")

    async def disconnect(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def call(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        self._req_id += 1
        msg = {"jsonrpc": "2.0", "id": self._req_id, "method": method}
        if params:
            msg["params"] = params
        self._writer.write(json.dumps(msg).encode() + b"\n")
        await self._writer.drain()
        raw = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
        resp = json.loads(raw.decode())
        # Retry once if waiting for approval
        if "error" in resp and resp["error"].get("code") == -32001:
            print("\n>>> Waiting for approval — click Allow in IDE <<<")
            await asyncio.sleep(15)
            self._req_id += 1
            msg["id"] = self._req_id
            self._writer.write(json.dumps(msg).encode() + b"\n")
            await self._writer.drain()
            raw = await asyncio.wait_for(self._reader.readline(), timeout=timeout)
            resp = json.loads(raw.decode())
        return resp


# ── Fixtures ─────────────────────────────────────────────────────────────────


vscode_info = read_port_file("vscode")
intellij_info = read_port_file("intellij")

skip_vscode = pytest.mark.skipif(
    vscode_info is None,
    reason="VSCode plugin not running",
)
skip_intellij = pytest.mark.skipif(
    intellij_info is None,
    reason="IntelliJ plugin not running",
)


@pytest.fixture
async def vscode() -> IDEClient:
    assert vscode_info is not None
    client = IDEClient(*vscode_info)
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def intellij() -> IDEClient:
    assert intellij_info is not None
    client = IDEClient(*intellij_info)
    await client.connect()
    yield client
    await client.disconnect()


# ── Security Tests ───────────────────────────────────────────────────────────


@skip_vscode
class TestVSCodeSecurity:
    @pytest.mark.asyncio
    async def test_rejects_wrong_token(self) -> None:
        assert vscode_info is not None
        sock_path = vscode_info[0]
        reader, writer = await asyncio.open_unix_connection(sock_path)
        # Send wrong token
        writer.write(json.dumps({"type": "auth", "token": "wrong"}).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        resp = json.loads(line.decode())
        assert not resp.get("ok"), f"Should reject wrong token, got: {resp}"
        writer.close()

    @pytest.mark.asyncio
    async def test_accepts_valid_token(self, vscode: IDEClient) -> None:
        resp = await vscode.call("list_sessions")
        assert "result" in resp, f"Expected result, got: {resp}"


@skip_intellij
class TestIntelliJSecurity:
    @pytest.mark.asyncio
    async def test_rejects_wrong_token(self) -> None:
        assert intellij_info is not None
        sock_path = intellij_info[0]
        reader, writer = await asyncio.open_unix_connection(sock_path)
        writer.write(json.dumps({"type": "auth", "token": "wrong"}).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        resp = json.loads(line.decode())
        assert not resp.get("ok"), f"Should reject wrong token, got: {resp}"
        writer.close()

    @pytest.mark.asyncio
    async def test_accepts_valid_token(self, intellij: IDEClient) -> None:
        resp = await intellij.call("list_sessions")
        assert "result" in resp, f"Expected result, got: {resp}"


# ── VSCode Functional Tests ─────────────────────────────────────────────────


@skip_vscode
class TestVSCodeSessions:
    @pytest.mark.asyncio
    async def test_list_sessions_returns_list(self, vscode: IDEClient) -> None:
        resp = await vscode.call("list_sessions")
        sessions = resp["result"]
        assert isinstance(sessions, list)
        assert len(sessions) >= 1, "Expected at least one terminal"

    @pytest.mark.asyncio
    async def test_session_has_required_fields(self, vscode: IDEClient) -> None:
        resp = await vscode.call("list_sessions")
        session = resp["result"][0]
        assert "id" in session
        assert "name" in session
        assert "active" in session
        assert isinstance(session["id"], str)
        assert len(session["id"]) > 0
        assert "Promise" not in session["id"]
        assert "object" not in session["id"]

    @pytest.mark.asyncio
    async def test_get_active_session(self, vscode: IDEClient) -> None:
        resp = await vscode.call("get_active_session")
        result = resp["result"]
        assert "session_id" in result
        if result["session_id"] is not None:
            assert isinstance(result["session_id"], str)
            assert result["session_id"].startswith("term-")

    @pytest.mark.asyncio
    async def test_is_ai_session_returns_bool(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("is_ai_session", {"session_id": sid})
        assert isinstance(resp["result"], bool)

    @pytest.mark.asyncio
    async def test_get_terminal_state_all(self, vscode: IDEClient) -> None:
        resp = await vscode.call("get_terminal_state", {})
        state = resp["result"]
        assert "terminals" in state
        assert "total" in state
        assert isinstance(state["total"], int)
        assert state["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_terminal_state_specific(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("get_terminal_state", {"session_id": sid})
        state = resp["result"]
        assert state["id"] == sid
        assert "name" in state


@skip_vscode
class TestVSCodeCommands:
    @pytest.mark.asyncio
    async def test_execute_command(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call(
            "execute_command",
            {
                "session_id": sid,
                "command": "echo sideshell_integration_test_ok",
                "wait": False,
            },
        )
        assert "result" in resp
        assert "Executed" in resp["result"] or "sent" in resp["result"].lower()

    @pytest.mark.asyncio
    async def test_send_text(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("send_text", {"session_id": sid, "text": ""})
        assert "result" in resp
        assert "Sent" in resp["result"]

    @pytest.mark.asyncio
    async def test_send_control(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        for key in ["c", "l", "a", "e"]:
            resp = await vscode.call("send_control", {"session_id": sid, "key": key})
            assert "result" in resp, f"send_control({key}) failed: {resp}"
            assert "control key" in resp["result"].lower()

    @pytest.mark.asyncio
    async def test_send_control_unknown_key(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("send_control", {"session_id": sid, "key": "nonexistent"})
        assert "Unknown" in resp["result"]

    @pytest.mark.asyncio
    async def test_read_terminal(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("read_terminal", {"session_id": sid, "lines": 10})
        assert "result" in resp
        assert isinstance(resp["result"], str)

    @pytest.mark.asyncio
    async def test_clear_terminal(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("clear_terminal", {"session_id": sid})
        assert "result" in resp
        assert "Cleared" in resp["result"]


@skip_vscode
class TestVSCodeCreateClose:
    @pytest.mark.asyncio
    async def test_create_tab_and_close(self, vscode: IDEClient) -> None:
        before = (await vscode.call("list_sessions"))["result"]
        count_before = len(before)

        # Create
        resp = await vscode.call("create_tab", {})
        assert "result" in resp
        new_id = resp["result"]["new_session_id"]
        assert isinstance(new_id, str)
        assert new_id.startswith("term-")

        await asyncio.sleep(0.5)

        after = (await vscode.call("list_sessions"))["result"]
        assert len(after) == count_before + 1

        # Close
        resp = await vscode.call("close_session", {"session_id": new_id})
        assert "result" in resp
        assert "Closed" in resp["result"]

        await asyncio.sleep(0.5)

        final = (await vscode.call("list_sessions"))["result"]
        assert len(final) == count_before

    @pytest.mark.asyncio
    async def test_split_pane(self, vscode: IDEClient) -> None:
        resp = await vscode.call("split_pane", {"direction": "v"})
        assert "result" in resp
        new_id = resp["result"]["new_session_id"]
        assert new_id.startswith("term-")

        await asyncio.sleep(0.5)

        # Cleanup
        await vscode.call("close_session", {"session_id": new_id})

    @pytest.mark.asyncio
    async def test_create_window(self, vscode: IDEClient) -> None:
        resp = await vscode.call("create_window", {})
        assert "result" in resp
        new_id = resp["result"]["new_session_id"]
        assert new_id.startswith("term-")

        await asyncio.sleep(0.5)

        await vscode.call("close_session", {"session_id": new_id})

    @pytest.mark.asyncio
    async def test_focus_session(self, vscode: IDEClient) -> None:
        sessions = (await vscode.call("list_sessions"))["result"]
        sid = sessions[0]["id"]
        resp = await vscode.call("focus_session", {"session_id": sid})
        assert "result" in resp
        assert "Focused" in resp["result"]


@skip_vscode
class TestVSCodeAppearance:
    @pytest.mark.asyncio
    async def test_set_appearance(self, vscode: IDEClient) -> None:
        resp = await vscode.call("set_appearance", {"title": "test-title"})
        assert "result" in resp
        assert isinstance(resp["result"], str)


@skip_vscode
class TestVSCodeErrors:
    @pytest.mark.asyncio
    async def test_unknown_method(self, vscode: IDEClient) -> None:
        resp = await vscode.call("nonexistent_method")
        assert "error" in resp
        assert resp["error"]["code"] == -32603
        assert "Unknown" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_nonexistent_session(self, vscode: IDEClient) -> None:
        resp = await vscode.call(
            "send_text",
            {
                "session_id": "term-99999",
                "text": "hello",
            },
        )
        assert "result" in resp
        assert "not found" in resp["result"].lower()


# ── IntelliJ Functional Tests ───────────────────────────────────────────────


@skip_intellij
class TestIntelliJSessions:
    @pytest.mark.asyncio
    async def test_list_sessions_returns_list(self, intellij: IDEClient) -> None:
        resp = await intellij.call("list_sessions")
        sessions = resp["result"]
        assert isinstance(sessions, list)

    @pytest.mark.asyncio
    async def test_session_has_required_fields(self, intellij: IDEClient) -> None:
        resp = await intellij.call("list_sessions")
        if not resp["result"]:
            pytest.skip("No terminals open in IntelliJ")
        session = resp["result"][0]
        assert "id" in session
        assert "name" in session
        assert "active" in session
        assert "project" in session
        assert session["id"].startswith("term-")

    @pytest.mark.asyncio
    async def test_get_active_session(self, intellij: IDEClient) -> None:
        resp = await intellij.call("get_active_session")
        result = resp["result"]
        assert "session_id" in result

    @pytest.mark.asyncio
    async def test_is_ai_session_returns_bool(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("is_ai_session", {"session_id": sid})
        assert isinstance(resp["result"], bool)

    @pytest.mark.asyncio
    async def test_get_terminal_state_all(self, intellij: IDEClient) -> None:
        resp = await intellij.call("get_terminal_state", {})
        state = resp["result"]
        assert "terminals" in state
        assert "total" in state
        assert isinstance(state["total"], int)

    @pytest.mark.asyncio
    async def test_get_terminal_state_specific(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("get_terminal_state", {"session_id": sid})
        state = resp["result"]
        assert state["id"] == sid
        assert "name" in state


@skip_intellij
class TestIntelliJCommands:
    @pytest.mark.asyncio
    async def test_execute_command(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call(
            "execute_command",
            {
                "session_id": sid,
                "command": "echo ij_integration_test_ok",
                "wait": False,
            },
        )
        assert "result" in resp
        assert "Executed" in resp["result"]

    @pytest.mark.asyncio
    async def test_send_text(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("send_text", {"session_id": sid, "text": ""})
        assert "result" in resp
        assert "Sent" in resp["result"]

    @pytest.mark.asyncio
    async def test_send_control_keys(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        for key in ["c", "l", "a", "e", "d", "z", "k", "u", "w"]:
            resp = await intellij.call("send_control", {"session_id": sid, "key": key})
            assert "result" in resp, f"send_control({key}) failed: {resp}"
            assert "Sent control key" in resp["result"], f"Unexpected result for key '{key}': {resp['result']}"

    @pytest.mark.asyncio
    async def test_send_control_navigation(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        for key in ["enter", "esc", "tab", "up", "down", "left", "right"]:
            resp = await intellij.call("send_control", {"session_id": sid, "key": key})
            assert "result" in resp, f"send_control({key}) failed: {resp}"

    @pytest.mark.asyncio
    async def test_read_terminal(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("read_terminal", {"session_id": sid, "lines": 10})
        assert "result" in resp
        assert isinstance(resp["result"], str)

    @pytest.mark.asyncio
    async def test_clear_terminal(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("clear_terminal", {"session_id": sid})
        assert "result" in resp
        assert "Cleared" in resp["result"]


@skip_intellij
class TestIntelliJCreateClose:
    @pytest.mark.asyncio
    async def test_create_tab_and_list(self, intellij: IDEClient) -> None:
        before = (await intellij.call("list_sessions"))["result"]
        count_before = len(before)

        resp = await intellij.call("create_tab", {})
        assert "result" in resp
        new_id = resp["result"]["new_session_id"]
        assert isinstance(new_id, str)

        await asyncio.sleep(1)

        after = (await intellij.call("list_sessions"))["result"]
        assert len(after) >= count_before + 1, f"Expected {count_before + 1}+ terminals, got {len(after)}"

    @pytest.mark.asyncio
    async def test_focus_session(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("focus_session", {"session_id": sid})
        assert "result" in resp
        assert "Focused" in resp["result"]


@skip_intellij
class TestIntelliJAppearance:
    @pytest.mark.asyncio
    async def test_set_appearance_title(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        resp = await intellij.call(
            "set_appearance",
            {
                "session_id": sessions[0]["id"],
                "title": "test-rename",
            },
        )
        assert "result" in resp
        assert isinstance(resp["result"], str)


@skip_intellij
class TestIntelliJFocus:
    @pytest.mark.asyncio
    async def test_focus_session(self, intellij: IDEClient) -> None:
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("focus_session", {"session_id": sid})
        assert "result" in resp
        assert "Focused" in resp["result"]

    @pytest.mark.asyncio
    async def test_return_focus(self, intellij: IDEClient) -> None:
        resp = await intellij.call("return_focus", {})
        assert "result" in resp
        assert "Focus returned" in resp["result"]

    @pytest.mark.asyncio
    async def test_focus_then_return(self, intellij: IDEClient) -> None:
        """Focus terminal, then return focus to editor."""
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]

        # Focus terminal
        resp = await intellij.call("focus_session", {"session_id": sid})
        assert "Focused" in resp["result"]
        await asyncio.sleep(0.3)

        # Return focus to editor
        resp = await intellij.call("return_focus", {"session_id": sid})
        assert "Focus returned" in resp["result"]


@skip_intellij
class TestIntelliJTerminalType:
    @pytest.mark.asyncio
    async def test_session_has_type_field(self, intellij: IDEClient) -> None:
        """Sessions should report terminal type (classic/new)."""
        resp = await intellij.call("list_sessions")
        sessions = resp["result"]
        if not sessions:
            pytest.skip("No terminals open")
        for session in sessions:
            assert "type" in session, f"Session missing type field: {session}"
            assert session["type"] in ("classic", "new", "unknown"), f"Unexpected type: {session['type']}"

    @pytest.mark.asyncio
    async def test_terminal_state_has_type(self, intellij: IDEClient) -> None:
        """Terminal state should report type."""
        sessions = (await intellij.call("list_sessions"))["result"]
        if not sessions:
            pytest.skip("No terminals open")
        sid = sessions[0]["id"]
        resp = await intellij.call("get_terminal_state", {"session_id": sid})
        state = resp["result"]
        assert "type" in state
        assert state["type"] in ("classic", "new", "unknown")


@skip_intellij
class TestIntelliJErrors:
    @pytest.mark.asyncio
    async def test_unknown_method(self, intellij: IDEClient) -> None:
        resp = await intellij.call("nonexistent_method")
        assert "error" in resp
        assert "Unknown" in resp["error"]["message"]
