"""Unit tests for GhosttyTmuxBackend with mocked AppleScript + tmux.

No real Ghostty/tmux required — _osascript and tmux calls are mocked. Live
end-to-end verification lives in tests/live_ghostty_check.py.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.base import ControlKey, SplitDirection
from sideshell_mcp.backends.ghostty_tmux_backend import GhosttyTmuxBackend


@pytest.fixture
def backend():
    b = GhosttyTmuxBackend()
    b._connected = True
    b._tmux_path = "/opt/homebrew/bin/tmux"
    # Default mocks: surfaces "launch" instantly and tmux calls succeed.
    b._wait_for_session = AsyncMock(return_value=True)
    b._tmux = AsyncMock(return_value="")
    b._run_tmux = AsyncMock(return_value=(0, "", ""))
    # Neutralize filesystem persistence + reconciliation by default; the
    # dedicated TestPersistence/TestReconcile classes exercise them explicitly.
    b._save_state = lambda: None
    b._load_state = lambda: None
    b._reconcile = AsyncMock(return_value=None)
    return b


def _sid(text: str) -> str | None:
    m = re.search(r"session_id:\s*(\S+)", text)
    return m.group(1) if m else None


# =============================================================================
# Identity / availability
# =============================================================================


class TestIdentity:
    def test_name(self, backend):
        assert backend.name == "ghostty_tmux"

    def test_available_needs_tmux(self, backend):
        with patch("shutil.which", return_value=None):
            assert backend.is_available is False

    def test_available_when_all_present(self, backend):
        with patch("shutil.which", return_value="/usr/bin/x"):
            with patch("os.path.exists", return_value=True):
                assert backend.is_available is True

    def test_session_name_format(self, backend):
        n1 = backend._new_session_name()
        n2 = backend._new_session_name()
        assert n1.startswith("sideshell_")
        assert n1 != n2
        assert re.fullmatch(r"sideshell_\d+_\d+_[0-9a-f]+", n1)

    def test_launch_cmd(self, backend):
        cmd = backend._tmux_launch_cmd("sideshell_1_1")
        assert "new-session -A -s sideshell_1_1" in cmd
        assert cmd.startswith("/opt/homebrew/bin/tmux")


# =============================================================================
# Connection
# =============================================================================


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_starts_server_no_hidden_session(self, backend):
        backend._connected = False
        backend._run_tmux = AsyncMock(return_value=(0, "", ""))
        ok = await backend.connect()
        assert ok is True
        assert backend._connected is True
        # Only start-server, never new-session (no hidden detached session).
        calls = [c.args for c in backend._run_tmux.await_args_list]
        assert ("start-server",) in calls
        assert not any("new-session" in args for args in calls)


# =============================================================================
# Creation via AppleScript
# =============================================================================


class TestCreateWindow:
    @pytest.mark.asyncio
    async def test_create_window_stores_mapping(self, backend):
        backend._osascript = AsyncMock(return_value="TERM-UUID-1")
        out = await backend.create_window()
        name = _sid(out)
        assert name is not None
        assert backend._ghostty_terminals[name] == "TERM-UUID-1"

    @pytest.mark.asyncio
    async def test_create_window_script_runs_tmux(self, backend):
        backend._osascript = AsyncMock(return_value="TERM-UUID-1")
        await backend.create_window()
        script = backend._osascript.await_args.args[0]
        assert "new window with configuration cfg" in script
        assert "new-session -A -s" in script

    @pytest.mark.asyncio
    async def test_create_window_with_command_sends_keys(self, backend):
        backend._osascript = AsyncMock(return_value="TERM-UUID-1")
        out = await backend.create_window(command="htop")
        name = _sid(out)
        backend._tmux.assert_awaited_with("send-keys", "-t", name, "--", "htop", "Enter")

    @pytest.mark.asyncio
    async def test_create_window_osascript_error(self, backend):
        backend._osascript = AsyncMock(side_effect=RuntimeError("denied"))
        out = await backend.create_window()
        assert "Error creating Ghostty window" in out


class TestCreateTab:
    @pytest.mark.asyncio
    async def test_create_tab_targets_front_window(self, backend):
        backend._osascript = AsyncMock(return_value="TAB-UUID-1")
        out = await backend.create_tab()
        name = _sid(out)
        assert name is not None
        script = backend._osascript.await_args.args[0]
        assert "new tab in front window with configuration cfg" in script
        assert backend._ghostty_terminals[name] == "TAB-UUID-1"

    @pytest.mark.asyncio
    async def test_create_tab_falls_back_to_window(self, backend):
        # First osascript (new tab) fails, second (create_window) succeeds.
        backend._osascript = AsyncMock(side_effect=[RuntimeError("no window"), "WIN-UUID"])
        out = await backend.create_tab()
        assert "Created Ghostty window" in out


class TestSplit:
    @pytest.mark.asyncio
    async def test_split_horizontal_maps_right(self, backend):
        backend._osascript = AsyncMock(return_value="SPLIT-UUID")
        out = await backend.split_pane(SplitDirection.HORIZONTAL)
        assert "horizontally" in out
        script = backend._osascript.await_args.args[0]
        assert "direction right" in script

    @pytest.mark.asyncio
    async def test_split_vertical_maps_down(self, backend):
        backend._osascript = AsyncMock(return_value="SPLIT-UUID")
        out = await backend.split_pane(SplitDirection.VERTICAL)
        assert "vertically" in out
        script = backend._osascript.await_args.args[0]
        assert "direction down" in script

    @pytest.mark.asyncio
    async def test_split_uses_focused_when_no_session(self, backend):
        backend._osascript = AsyncMock(return_value="SPLIT-UUID")
        await backend.split_pane(SplitDirection.HORIZONTAL)
        script = backend._osascript.await_args.args[0]
        assert "focused terminal of selected tab of front window" in script

    @pytest.mark.asyncio
    async def test_split_resolves_known_session_to_terminal_id(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "SRC-TERM-ID"
        backend._osascript = AsyncMock(return_value="NEW-SPLIT")
        await backend.split_pane(SplitDirection.HORIZONTAL, "sideshell_1_1")
        script = backend._osascript.await_args.args[0]
        assert 'whose id is "SRC-TERM-ID"' in script

    @pytest.mark.asyncio
    async def test_split_fallback_to_window_on_error(self, backend):
        backend._osascript = AsyncMock(side_effect=[RuntimeError("no window"), "WIN-UUID"])
        out = await backend.split_pane(SplitDirection.HORIZONTAL)
        assert "Created Ghostty window" in out


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_session_splits_when_existing(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "T1"
        backend._osascript = AsyncMock(return_value="NEW")
        out = await backend.create_session()
        assert "Split" in out

    @pytest.mark.asyncio
    async def test_create_session_new_window_when_empty(self, backend):
        backend._osascript = AsyncMock(return_value="NEW")
        out = await backend.create_session()
        assert "Created Ghostty window" in out


# =============================================================================
# Focus / current / close
# =============================================================================


class TestFocusCurrentClose:
    @pytest.mark.asyncio
    async def test_focus_maps_name_to_terminal(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "TERM-X"
        backend._osascript = AsyncMock(return_value="")
        out = await backend.focus_session("sideshell_1_1")
        assert "Focused sideshell_1_1" in out
        script = backend._osascript.await_args.args[0]
        assert 'whose id is "TERM-X"' in script
        assert "focus" in script

    @pytest.mark.asyncio
    async def test_focus_raw_terminal_id_passthrough(self, backend):
        backend._osascript = AsyncMock(return_value="")
        await backend.focus_session("RAW-TERM-ID")
        script = backend._osascript.await_args.args[0]
        assert 'whose id is "RAW-TERM-ID"' in script

    @pytest.mark.asyncio
    async def test_current_session_reverse_maps(self, backend):
        backend._ghostty_terminals["sideshell_1_2"] = "TERM-Y"
        backend._osascript = AsyncMock(return_value="TERM-Y")
        sid = await backend.get_current_active_session_id()
        assert sid == "sideshell_1_2"

    @pytest.mark.asyncio
    async def test_current_session_unmanaged_returns_term_id(self, backend):
        backend._osascript = AsyncMock(return_value="SOME-OTHER-TERM")
        sid = await backend.get_current_active_session_id()
        assert sid == "SOME-OTHER-TERM"

    @pytest.mark.asyncio
    async def test_current_session_none_when_no_window(self, backend):
        backend._osascript = AsyncMock(side_effect=RuntimeError("no front window"))
        sid = await backend.get_current_active_session_id()
        assert sid is None

    @pytest.mark.asyncio
    async def test_active_pane_prefers_focused_managed(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "T1"
        backend.get_current_active_session_id = AsyncMock(return_value="sideshell_1_1")
        assert await backend._get_active_pane() == "sideshell_1_1"

    @pytest.mark.asyncio
    async def test_active_pane_falls_back_to_last(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "T1"
        backend._ghostty_terminals["sideshell_1_2"] = "T2"
        backend.get_current_active_session_id = AsyncMock(return_value="UNMANAGED")
        assert await backend._get_active_pane() == "sideshell_1_2"

    @pytest.mark.asyncio
    async def test_active_pane_none_when_empty(self, backend):
        backend.get_current_active_session_id = AsyncMock(return_value=None)
        assert await backend._get_active_pane() is None

    @pytest.mark.asyncio
    async def test_close_closes_surface_then_kills_tmux(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "TERM-Z"
        backend._osascript = AsyncMock(return_value="")
        backend.is_ai_session = AsyncMock(return_value=False)
        out = await backend.close_session("sideshell_1_1")
        assert "Closed sideshell_1_1" in out
        # surface closed via AppleScript
        assert 'whose id is "TERM-Z"' in backend._osascript.await_args.args[0]
        # tmux session killed
        backend._run_tmux.assert_any_await("kill-session", "-t", "sideshell_1_1")
        # mapping removed
        assert "sideshell_1_1" not in backend._ghostty_terminals

    @pytest.mark.asyncio
    async def test_close_blocks_ai_without_force(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "TERM-Z"
        backend.is_ai_session = AsyncMock(return_value=True)
        out = await backend.close_session("sideshell_1_1")
        assert "Cannot close AI session" in out
        assert "sideshell_1_1" in backend._ghostty_terminals

    @pytest.mark.asyncio
    async def test_close_force_overrides_ai(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "TERM-Z"
        backend._osascript = AsyncMock(return_value="")
        backend.is_ai_session = AsyncMock(return_value=True)
        out = await backend.close_session("sideshell_1_1", force=True)
        assert "Closed" in out


# =============================================================================
# Control keys (full tmux key map)
# =============================================================================


class TestControlKeys:
    @pytest.mark.asyncio
    async def test_ctrl_c(self, backend):
        backend.is_ai_session = AsyncMock(return_value=False)
        out = await backend.send_control(ControlKey.C, "sideshell_1_1")
        assert "Ctrl+C" in out
        backend._tmux.assert_awaited_with("send-keys", "-t", "sideshell_1_1", "C-c")

    @pytest.mark.asyncio
    async def test_arrow_up_uses_named_key(self, backend):
        backend.is_ai_session = AsyncMock(return_value=False)
        out = await backend.send_control(ControlKey.UP, "sideshell_1_1")
        assert "Up" in out
        backend._tmux.assert_awaited_with("send-keys", "-t", "sideshell_1_1", "Up")

    @pytest.mark.asyncio
    async def test_function_key(self, backend):
        backend.is_ai_session = AsyncMock(return_value=False)
        out = await backend.send_control(ControlKey.F5, "sideshell_1_1")
        assert "F5" in out
        backend._tmux.assert_awaited_with("send-keys", "-t", "sideshell_1_1", "F5")

    @pytest.mark.asyncio
    async def test_pageup_and_delete(self, backend):
        backend.is_ai_session = AsyncMock(return_value=False)
        await backend.send_control(ControlKey.PAGE_UP, "sideshell_1_1")
        backend._tmux.assert_awaited_with("send-keys", "-t", "sideshell_1_1", "PageUp")
        await backend.send_control(ControlKey.DELETE, "sideshell_1_1")
        backend._tmux.assert_awaited_with("send-keys", "-t", "sideshell_1_1", "DC")

    @pytest.mark.asyncio
    async def test_enter_and_escape(self, backend):
        backend.is_ai_session = AsyncMock(return_value=False)
        assert "Enter" in await backend.send_control(ControlKey.ENTER, "sideshell_1_1")
        assert "Escape" in await backend.send_control(ControlKey.ESC, "sideshell_1_1")

    @pytest.mark.asyncio
    async def test_blocks_ai(self, backend):
        backend.is_ai_session = AsyncMock(return_value=True)
        out = await backend.send_control(ControlKey.C, "sideshell_1_1")
        assert "Cannot send control" in out

    @pytest.mark.asyncio
    async def test_no_pane(self, backend):
        backend.get_current_active_session_id = AsyncMock(return_value=None)
        out = await backend.send_control(ControlKey.C)
        assert "No active" in out

    def test_key_map_covers_all_control_keys(self, backend):
        for key in ControlKey:
            assert key in backend._TMUX_KEYS, f"{key} missing from _TMUX_KEYS"


# =============================================================================
# Listing
# =============================================================================


class TestListing:
    @pytest.mark.asyncio
    async def test_list_empty(self, backend):
        out = await backend.list_sessions()
        assert "No sideshell sessions" in out

    @pytest.mark.asyncio
    async def test_list_with_sessions(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "TERM-A"
        backend._osascript = AsyncMock(return_value="TERM-A||my-title||/home/user/code\nOTHER||x||/tmp")
        out = await backend.list_sessions()
        assert "Total: 1 sideshell session(s)" in out
        assert "sideshell_1_1" in out
        assert "my-title" in out
        assert "/home/user/code" in out

    @pytest.mark.asyncio
    async def test_list_marks_closed_surface(self, backend):
        backend._ghostty_terminals["sideshell_1_1"] = "TERM-GONE"
        backend._osascript = AsyncMock(return_value="OTHER-TERM||x||/tmp")
        out = await backend.list_sessions()
        assert "surface closed?" in out

    @pytest.mark.asyncio
    async def test_get_session_preserves_session_id(self, backend):
        from sideshell_mcp.backends.base import SessionInfo

        async def fake_super(session_id=None):
            return SessionInfo(session_id="%5", name="zsh", path="/tmp", job="zsh", at_prompt=True)

        with patch.object(GhosttyTmuxBackend.__bases__[0], "get_session", side_effect=fake_super):
            info = await backend.get_session("sideshell_1_1")
        assert info is not None
        assert info.session_id == "sideshell_1_1"


# =============================================================================
# Safety: AppleScript-injection guard
# =============================================================================


class TestInjectionGuard:
    def test_safe_id_accepts_real_ids(self, backend):
        assert backend._safe_id("sideshell_4711_2_ab12")
        assert backend._safe_id("DBC0F5C5-2D26-4FD0-A4BB-5531F810EB9E")
        assert backend._safe_id("tab-group-b23b706e0")

    def test_safe_id_rejects_injection(self, backend):
        assert not backend._safe_id('x" \n do shell script "id" \n "')
        assert not backend._safe_id("a b")
        assert not backend._safe_id('a"b')
        assert not backend._safe_id("")
        assert not backend._safe_id(None)

    @pytest.mark.asyncio
    async def test_split_rejects_unsafe_session_id(self, backend):
        backend._osascript = AsyncMock(return_value="X")
        out = await backend.split_pane(SplitDirection.HORIZONTAL, '"; do shell script "id"')
        assert "invalid session_id" in out
        backend._osascript.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_focus_rejects_unsafe_id(self, backend):
        backend._osascript = AsyncMock(return_value="")
        out = await backend.focus_session('bad" id')
        assert "invalid session id" in out
        backend._osascript.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_rejects_unsafe_id(self, backend):
        backend._osascript = AsyncMock(return_value="")
        backend.is_ai_session = AsyncMock(return_value=False)
        out = await backend.close_session('bad" id', force=True)
        assert "invalid session id" in out
        backend._osascript.assert_not_awaited()


# =============================================================================
# Safety: no silent half-creation
# =============================================================================


class TestHalfCreation:
    @pytest.mark.asyncio
    async def test_create_window_cleans_up_when_tmux_never_starts(self, backend):
        backend._osascript = AsyncMock(return_value="TERM-DEAD")
        backend._wait_for_session = AsyncMock(return_value=False)
        closed = []
        backend._close_surface = AsyncMock(side_effect=lambda tid: closed.append(tid))

        out = await backend.create_window()
        assert "did not start" in out
        assert "TERM-DEAD" in closed  # dead surface was closed
        assert backend._ghostty_terminals == {}  # no phantom mapping
        # orphan tmux session kill attempted
        backend._run_tmux.assert_any_await("kill-session", "-t", out.split("'")[1])


# =============================================================================
# Reconciliation + persistence
# =============================================================================


class TestReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_prunes_dead_surface_and_kills_tmux(self):
        b = GhosttyTmuxBackend()
        b._tmux_path = "/usr/bin/tmux"
        b._ghostty_terminals = {"s1": "T1", "s2": "T2"}
        b._save_state = lambda: None
        b._run_tmux = AsyncMock(return_value=(0, "", ""))  # both tmux sessions alive
        b._live_terminal_ids = AsyncMock(return_value={"T1"})  # s2's surface gone

        await b._reconcile()

        assert "s1" in b._ghostty_terminals
        assert "s2" not in b._ghostty_terminals
        b._run_tmux.assert_any_await("kill-session", "-t", "s2")

    @pytest.mark.asyncio
    async def test_reconcile_prunes_dead_tmux(self):
        b = GhosttyTmuxBackend()
        b._tmux_path = "/usr/bin/tmux"
        b._ghostty_terminals = {"s1": "T1"}
        b._save_state = lambda: None
        b._run_tmux = AsyncMock(return_value=(1, "", "no session"))  # tmux gone
        b._live_terminal_ids = AsyncMock(return_value={"T1"})

        await b._reconcile()
        assert b._ghostty_terminals == {}


class TestPersistence:
    def test_save_then_load_roundtrip(self, tmp_path):
        state = tmp_path / "ghostty-sessions.json"
        with patch("sideshell_mcp.backends.ghostty_tmux_backend._STATE_DIR", tmp_path):
            with patch("sideshell_mcp.backends.ghostty_tmux_backend._STATE_FILE", state):
                b1 = GhosttyTmuxBackend()
                b1._ghostty_terminals = {"sideshell_1_1_aa": "TERM-X"}
                b1._save_state()
                assert state.exists()

                b2 = GhosttyTmuxBackend()
                b2._load_state()
                assert b2._ghostty_terminals.get("sideshell_1_1_aa") == "TERM-X"

    def test_load_ignores_unsafe_entries(self, tmp_path):
        state = tmp_path / "ghostty-sessions.json"
        state.write_text('{"good_1": "T1", "bad id": "T2", "k": "v\\" x"}')
        with patch("sideshell_mcp.backends.ghostty_tmux_backend._STATE_DIR", tmp_path):
            with patch("sideshell_mcp.backends.ghostty_tmux_backend._STATE_FILE", state):
                b = GhosttyTmuxBackend()
                b._load_state()
                assert b._ghostty_terminals == {"good_1": "T1"}
