"""Unit tests for TmuxBackend with mocked subprocess calls.

No real tmux required — all tmux CLI calls are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.base import ControlKey, SplitDirection
from sideshell_mcp.backends.tmux_backend import TmuxBackend


@pytest.fixture
def backend():
    b = TmuxBackend()
    b._connected = True
    b._tmux_path = "/usr/bin/tmux"
    return b


def mock_run_tmux(stdout="", returncode=0, stderr=""):
    """Create a mock for _run_tmux that returns (returncode, stdout, stderr)."""
    return AsyncMock(return_value=(returncode, stdout, stderr))


# =============================================================================
# Connection
# =============================================================================


class TestConnection:
    @pytest.mark.asyncio
    async def test_connect_existing_session(self, backend):
        backend._connected = False
        backend._run_tmux = mock_run_tmux(stdout="0: 1 windows (created ...)")

        result = await backend.connect()
        assert result is True
        assert backend._connected is True

    @pytest.mark.asyncio
    async def test_connect_no_sessions_creates_one(self, backend):
        backend._connected = False
        call_count = 0

        async def multi_response(*args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # list-sessions returns empty
                return (1, "", "no server running")
            else:
                # new-session succeeds
                return (0, "", "")

        backend._run_tmux = multi_response

        result = await backend.connect()
        assert result is True
        assert backend._connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, backend):
        backend._connected = False
        call_count = 0

        async def fail_response(*args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (1, "", "no server")
            else:
                return (1, "", "failed to create")

        backend._run_tmux = fail_response

        result = await backend.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_exception(self, backend):
        backend._connected = False
        backend._run_tmux = AsyncMock(side_effect=Exception("tmux not found"))

        result = await backend.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_connection_when_connected(self, backend):
        backend._connected = True
        backend.connect = AsyncMock()
        await backend.ensure_connection()
        backend.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_connection_when_disconnected(self, backend):
        backend._connected = False
        backend.connect = AsyncMock(return_value=True)
        await backend.ensure_connection()
        backend.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, backend):
        await backend.disconnect()
        assert backend._connected is False

    def test_name(self, backend):
        assert backend.name == "tmux"

    def test_is_available(self, backend):
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            assert backend.is_available is True

    def test_is_not_available(self, backend):
        with patch("shutil.which", return_value=None):
            assert backend.is_available is False


# =============================================================================
# Session Info
# =============================================================================


class TestSessionInfo:
    @pytest.mark.asyncio
    async def test_get_session(self, backend):
        backend._run_tmux = mock_run_tmux(stdout="%0|zsh|/home/user|80|24|/dev/ttys001")

        # _tmux calls _run_tmux internally; mock at _tmux level
        backend._tmux = AsyncMock(return_value="%0|zsh|/home/user|80|24|/dev/ttys001")
        info = await backend.get_session("%0")

        assert info is not None
        assert info.session_id == "%0"
        assert info.job == "zsh"
        assert info.path == "/home/user"
        assert info.at_prompt is True
        assert info.columns == 80
        assert info.rows == 24
        assert info.tty == "/dev/ttys001"

    @pytest.mark.asyncio
    async def test_get_session_not_at_prompt(self, backend):
        backend._tmux = AsyncMock(return_value="%1|python3|/home/user|120|40|/dev/ttys002")
        info = await backend.get_session("%1")

        assert info is not None
        assert info.at_prompt is False
        assert info.job == "python3"

    @pytest.mark.asyncio
    async def test_get_session_error(self, backend):
        backend._tmux = AsyncMock(side_effect=RuntimeError("pane not found"))
        info = await backend.get_session("%999")
        assert info is None

    @pytest.mark.asyncio
    async def test_get_session_uses_active_pane_when_no_id(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="%0|bash|/tmp|100|30|/dev/ttys003")
        info = await backend.get_session()

        assert info is not None
        assert info.session_id == "%0"

    @pytest.mark.asyncio
    async def test_list_sessions(self, backend):
        backend._tmux = AsyncMock(
            return_value=("main:0.0|%0|80x24|zsh|/home/user\nmain:0.1|%1|80x24|vim|/home/user/code")
        )
        result = await backend.list_sessions()

        assert "Total: 2 panes" in result
        assert "Session: main" in result
        assert "zsh" in result
        assert "vim" in result

    @pytest.mark.asyncio
    async def test_list_sessions_error(self, backend):
        backend._tmux = AsyncMock(side_effect=RuntimeError("no server"))
        result = await backend.list_sessions()
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_get_terminal_state_all(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value=("main|0|bash|0|%0|zsh|/home|80|24\nmain|0|bash|1|%1|vim|/code|80|24"))
        result = await backend.get_terminal_state()
        data = json.loads(result)

        assert data["total_panes"] == 2
        assert data["active_pane"] == "%0"
        assert len(data["sessions"]) == 1

    @pytest.mark.asyncio
    async def test_get_terminal_state_single(self, backend):
        backend._tmux = AsyncMock(return_value="%5|python|/tmp|120|40|/dev/ttys005")
        result = await backend.get_terminal_state("%5")
        data = json.loads(result)

        assert data["session_id"] == "%5"
        assert data["job"] == "python"

    @pytest.mark.asyncio
    async def test_get_terminal_state_not_found(self, backend):
        backend._tmux = AsyncMock(side_effect=RuntimeError("not found"))
        backend.get_session = AsyncMock(return_value=None)
        result = await backend.get_terminal_state("%999")
        assert "not found" in result.lower()


# =============================================================================
# AI Session Detection
# =============================================================================


class TestAISession:
    @pytest.mark.asyncio
    async def test_claude_is_ai(self, backend):
        backend._tmux = AsyncMock(return_value="claude")
        assert await backend.is_ai_session("%0") is True

    @pytest.mark.asyncio
    async def test_mcp_is_ai(self, backend):
        backend._tmux = AsyncMock(return_value="python3 -m sideshell_mcp")
        assert await backend.is_ai_session("%0") is True

    @pytest.mark.asyncio
    async def test_cursor_is_ai(self, backend):
        backend._tmux = AsyncMock(return_value="cursor")
        assert await backend.is_ai_session("%0") is True

    @pytest.mark.asyncio
    async def test_zsh_is_not_ai(self, backend):
        backend._tmux = AsyncMock(return_value="zsh")
        assert await backend.is_ai_session("%0") is False

    @pytest.mark.asyncio
    async def test_python_is_not_ai(self, backend):
        backend._tmux = AsyncMock(return_value="python3")
        assert await backend.is_ai_session("%0") is False

    @pytest.mark.asyncio
    async def test_error_returns_false(self, backend):
        backend._tmux = AsyncMock(side_effect=RuntimeError("pane gone"))
        assert await backend.is_ai_session("%0") is False


# =============================================================================
# Command Execution
# =============================================================================


class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_execute_fire_and_forget(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="")
        backend.is_ai_session = AsyncMock(return_value=False)

        result = await backend.execute_command("echo hello", "%0")
        assert "Sent: echo hello" in result

    @pytest.mark.asyncio
    async def test_execute_blocks_ai_session(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=True)

        result = await backend.execute_command("echo hello", "%0")
        assert "Cannot execute in AI pane" in result

    @pytest.mark.asyncio
    async def test_execute_no_active_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value=None)
        result = await backend.execute_command("echo hello")
        assert "No active pane" in result

    @pytest.mark.asyncio
    async def test_execute_with_wait_delegated(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._execute_with_wait = AsyncMock(return_value="Completed (silence)")
        backend._tmux = AsyncMock(return_value="")

        result = await backend.execute_command("ls", "%0", wait=True, timeout=10, watch_for="silence")
        backend._execute_with_wait.assert_called_once_with("%0", "ls", 10, "silence")

    @pytest.mark.asyncio
    async def test_execute_error_handling(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(side_effect=RuntimeError("pane dead"))

        result = await backend.execute_command("echo hello", "%0")
        assert "Error" in result


# =============================================================================
# Send Text & Control
# =============================================================================


class TestSendTextAndControl:
    @pytest.mark.asyncio
    async def test_send_text(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.send_text("hello world", "%0")
        assert "Pasted 11 characters" in result

    @pytest.mark.asyncio
    async def test_send_text_blocks_ai(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=True)

        result = await backend.send_text("hello", "%0")
        assert "Cannot paste to AI pane" in result

    @pytest.mark.asyncio
    async def test_send_text_no_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value=None)
        result = await backend.send_text("hello")
        assert "No active pane" in result

    @pytest.mark.asyncio
    async def test_send_control_ctrl_c(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.send_control(ControlKey.C, "%0")
        assert "Ctrl+C" in result

    @pytest.mark.asyncio
    async def test_send_control_enter(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.send_control(ControlKey.ENTER, "%0")
        assert "Enter" in result

    @pytest.mark.asyncio
    async def test_send_control_escape(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.send_control(ControlKey.ESC, "%0")
        assert "Escape" in result

    @pytest.mark.asyncio
    async def test_send_control_blocks_ai(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=True)

        result = await backend.send_control(ControlKey.C, "%0")
        assert "Cannot send control to AI pane" in result


# =============================================================================
# Read & Clear
# =============================================================================


class TestReadAndClear:
    @pytest.mark.asyncio
    async def test_read_terminal(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._capture_pane = AsyncMock(return_value="$ echo hi\nhi\n$")
        backend.get_session = AsyncMock(return_value=None)

        result = await backend.read_terminal(20, "%0")
        assert "Last 20 lines" in result
        assert "echo hi" in result

    @pytest.mark.asyncio
    async def test_read_terminal_no_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value=None)
        result = await backend.read_terminal()
        assert "No active pane" in result

    @pytest.mark.asyncio
    async def test_clear_terminal(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.clear_terminal("%0")
        assert "cleared" in result.lower()

    @pytest.mark.asyncio
    async def test_clear_blocks_ai(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=True)

        result = await backend.clear_terminal("%0")
        assert "Cannot clear AI pane" in result


# =============================================================================
# Split / Create
# =============================================================================


class TestSplitAndCreate:
    @pytest.mark.asyncio
    async def test_split_horizontal(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="%5")

        result = await backend.split_pane(SplitDirection.HORIZONTAL, "%0")
        assert "horizontally" in result
        assert "%5" in result

    @pytest.mark.asyncio
    async def test_split_vertical(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="%6")

        result = await backend.split_pane(SplitDirection.VERTICAL, "%0")
        assert "vertically" in result
        assert "%6" in result

    @pytest.mark.asyncio
    async def test_split_no_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value=None)
        result = await backend.split_pane(SplitDirection.HORIZONTAL)
        assert "No active pane" in result

    @pytest.mark.asyncio
    async def test_create_window(self, backend):
        backend._tmux = AsyncMock(return_value="%10")
        result = await backend.create_window()
        assert "pane_id: %10" in result

    @pytest.mark.asyncio
    async def test_create_window_with_command(self, backend):
        backend._tmux = AsyncMock(return_value="%11")
        result = await backend.create_window(command="echo hello world")
        assert "pane_id: %11" in result
        # Multi-word command is typed via send-keys (with "--" guard), NOT passed
        # to new-session (which would exec it literally and kill the pane).
        backend._tmux.assert_any_await("send-keys", "-t", "%11", "--", "echo hello world", "Enter")
        new_session_call = backend._tmux.await_args_list[0]
        assert new_session_call.args[0] == "new-session"
        assert "echo hello world" not in new_session_call.args

    @pytest.mark.asyncio
    async def test_create_window_uses_unique_names(self, backend):
        backend._tmux = AsyncMock(return_value="%1")
        await backend.create_window()
        await backend.create_window()
        names = [c.args[3] for c in backend._tmux.await_args_list if c.args[0] == "new-session"]
        assert len(names) == 2
        assert names[0] != names[1]

    @pytest.mark.asyncio
    async def test_create_tab(self, backend):
        backend._tmux = AsyncMock(return_value="%12")
        result = await backend.create_tab()
        assert "pane_id: %12" in result

    @pytest.mark.asyncio
    async def test_create_tab_with_command_uses_send_keys(self, backend):
        backend._tmux = AsyncMock(return_value="%12")
        await backend.create_tab(command="ls -la /tmp")
        backend._tmux.assert_any_await("send-keys", "-t", "%12", "--", "ls -la /tmp", "Enter")

    @pytest.mark.asyncio
    async def test_create_session_with_active_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="%13")

        result = await backend.create_session()
        # Should split (has active pane)
        assert "Split" in result or "session" in result.lower()

    @pytest.mark.asyncio
    async def test_create_session_no_active_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value=None)
        backend._tmux = AsyncMock(return_value="%14")

        result = await backend.create_session()
        # Should create window
        assert "pane_id" in result or "session" in result.lower()


# =============================================================================
# Focus & Close
# =============================================================================


class TestFocusAndClose:
    @pytest.mark.asyncio
    async def test_focus_session(self, backend):
        backend._tmux = AsyncMock(return_value="")
        result = await backend.focus_session("%3")
        assert "Focused pane %3" in result

    @pytest.mark.asyncio
    async def test_focus_error(self, backend):
        backend._tmux = AsyncMock(side_effect=RuntimeError("pane not found"))
        result = await backend.focus_session("%999")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_close_session(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=False)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.close_session("%0", force=True)
        assert "Closed pane %0" in result

    @pytest.mark.asyncio
    async def test_close_blocks_ai_without_force(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=True)

        result = await backend.close_session("%0", force=False)
        assert "Cannot close AI pane" in result

    @pytest.mark.asyncio
    async def test_close_force_overrides_ai_check(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend.is_ai_session = AsyncMock(return_value=True)
        backend._tmux = AsyncMock(return_value="")

        result = await backend.close_session("%0", force=True)
        assert "Closed" in result

    @pytest.mark.asyncio
    async def test_close_no_pane(self, backend):
        backend._get_active_pane = AsyncMock(return_value=None)
        result = await backend.close_session()
        assert "No active pane" in result


# =============================================================================
# Appearance
# =============================================================================


class TestAppearance:
    @pytest.mark.asyncio
    async def test_set_title(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="")

        result = await backend.set_appearance(session_id="%0", title="Dev")
        assert "title" in result.lower()
        assert "Dev" in result

    @pytest.mark.asyncio
    async def test_set_color(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="")

        result = await backend.set_appearance(session_id="%0", color="red")
        assert "style" in result.lower()

    @pytest.mark.asyncio
    async def test_set_badge_not_supported(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        backend._tmux = AsyncMock(return_value="")

        result = await backend.set_appearance(session_id="%0", badge="B1")
        assert "not supported" in result.lower()

    @pytest.mark.asyncio
    async def test_set_appearance_nothing(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        result = await backend.set_appearance(session_id="%0")
        assert "No appearance changes" in result

    @pytest.mark.asyncio
    async def test_rename_window(self, backend):
        backend._tmux = AsyncMock(return_value="")
        result = await backend.rename_window("MyWindow")
        assert "renamed" in result.lower()

    @pytest.mark.asyncio
    async def test_list_color_presets(self, backend):
        result = await backend.list_color_presets()
        assert "color" in result.lower()
        assert "hex" in result.lower()

    @pytest.mark.asyncio
    async def test_set_color_preset_simple(self, backend):
        backend._tmux = AsyncMock(return_value="")
        result = await backend.set_color_preset("green")
        assert "green" in result

    @pytest.mark.asyncio
    async def test_set_color_preset_custom_style(self, backend):
        backend._tmux = AsyncMock(return_value="")
        result = await backend.set_color_preset("fg=red,bold")
        assert "fg=red,bold" in result

    @pytest.mark.asyncio
    async def test_show_alert(self, backend):
        backend._tmux = AsyncMock(return_value="")
        result = await backend.show_alert("Warning", "Disk full")
        assert "Message displayed" in result

    @pytest.mark.asyncio
    async def test_get_active_session_id(self, backend):
        backend._get_active_pane = AsyncMock(return_value="%0")
        result = await backend.get_current_active_session_id()
        assert result == "%0"
