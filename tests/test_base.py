"""Unit tests for base classes: ControlKey, SplitDirection, annotate_screen, get_backend."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sideshell_mcp.backends.base import (
    AnnotationResult,
    AnnotationType,
    BackendType,
    ControlKey,
    SplitDirection,
    TerminalBackend,
)

# =============================================================================
# Enums
# =============================================================================


class TestControlKey:
    def test_ctrl_keys(self):
        assert ControlKey.C.value == "c"
        assert ControlKey.D.value == "d"
        assert ControlKey.Z.value == "z"
        assert ControlKey.A.value == "a"
        assert ControlKey.E.value == "e"
        assert ControlKey.K.value == "k"
        assert ControlKey.L.value == "l"
        assert ControlKey.U.value == "u"
        assert ControlKey.W.value == "w"

    def test_special_keys(self):
        assert ControlKey.ENTER.value == "enter"
        assert ControlKey.ESC.value == "esc"
        assert ControlKey.TAB.value == "tab"
        assert ControlKey.BACKSPACE.value == "backspace"

    def test_arrow_keys(self):
        assert ControlKey.UP.value == "up"
        assert ControlKey.DOWN.value == "down"
        assert ControlKey.LEFT.value == "left"
        assert ControlKey.RIGHT.value == "right"

    def test_navigation_keys(self):
        assert ControlKey.HOME.value == "home"
        assert ControlKey.END.value == "end"
        assert ControlKey.PAGE_UP.value == "pageup"
        assert ControlKey.PAGE_DOWN.value == "pagedown"
        assert ControlKey.INSERT.value == "insert"
        assert ControlKey.DELETE.value == "delete"

    def test_function_keys(self):
        for i in range(1, 13):
            key = ControlKey(f"f{i}")
            assert key.value == f"f{i}"

    def test_all_keys_have_char_mapping(self):
        """Every ControlKey must have a CONTROL_CHARS mapping."""
        for key in ControlKey:
            assert key in TerminalBackend.CONTROL_CHARS, f"{key} missing from CONTROL_CHARS"

    def test_control_chars_are_strings(self):
        for key, char in TerminalBackend.CONTROL_CHARS.items():
            assert isinstance(char, str), f"{key}: expected str, got {type(char)}"
            assert len(char) >= 1, f"{key}: empty char"

    def test_ctrl_c_is_0x03(self):
        assert TerminalBackend.CONTROL_CHARS[ControlKey.C] == "\x03"

    def test_ctrl_d_is_0x04(self):
        assert TerminalBackend.CONTROL_CHARS[ControlKey.D] == "\x04"

    def test_enter_is_newline(self):
        assert TerminalBackend.CONTROL_CHARS[ControlKey.ENTER] == "\n"

    def test_tab_is_tab(self):
        assert TerminalBackend.CONTROL_CHARS[ControlKey.TAB] == "\t"

    def test_arrow_escape_sequences(self):
        assert TerminalBackend.CONTROL_CHARS[ControlKey.UP] == "\x1b[A"
        assert TerminalBackend.CONTROL_CHARS[ControlKey.DOWN] == "\x1b[B"
        assert TerminalBackend.CONTROL_CHARS[ControlKey.RIGHT] == "\x1b[C"
        assert TerminalBackend.CONTROL_CHARS[ControlKey.LEFT] == "\x1b[D"

    def test_from_string(self):
        assert ControlKey("c") == ControlKey.C
        assert ControlKey("enter") == ControlKey.ENTER
        assert ControlKey("f1") == ControlKey.F1


class TestRealOutputLines:
    """_real_output_lines must strip the echoed command from new output."""

    def test_drops_command_echo_line(self):
        new_lines = ["user@host:~$ sleep 1; echo done"]
        assert TerminalBackend._real_output_lines(new_lines, "sleep 1; echo done") == []

    def test_keeps_real_output(self):
        new_lines = ["user@host:~$ echo hi", "hi"]
        assert TerminalBackend._real_output_lines(new_lines, "echo hi") == ["hi"]

    def test_ignores_blank_lines(self):
        assert TerminalBackend._real_output_lines(["", "   "], "ls") == []

    def test_empty_command_keeps_all_nonblank(self):
        assert TerminalBackend._real_output_lines(["a", "", "b"], "") == ["a", "b"]

    def test_invalid_key(self):
        with pytest.raises(ValueError):
            ControlKey("invalid")


class TestSplitDirection:
    def test_values(self):
        assert SplitDirection.HORIZONTAL.value == "h"
        assert SplitDirection.VERTICAL.value == "v"

    def test_from_string(self):
        assert SplitDirection("h") == SplitDirection.HORIZONTAL
        assert SplitDirection("v") == SplitDirection.VERTICAL

    def test_invalid(self):
        with pytest.raises(ValueError):
            SplitDirection("x")


class TestBackendType:
    def test_all_backends(self):
        expected = {"iterm2", "tmux", "wezterm", "kitty", "ghostty", "maquake", "vscode", "intellij", "auto"}
        values = {bt.value for bt in BackendType}
        assert values == expected

    def test_is_string_enum(self):
        assert isinstance(BackendType.TMUX, str)
        assert BackendType.TMUX == "tmux"


class TestAnnotationType:
    def test_values(self):
        assert AnnotationType.ERROR.value == "error"
        assert AnnotationType.WARNING.value == "warning"
        assert AnnotationType.INFO.value == "info"
        assert AnnotationType.SUCCESS.value == "success"


# =============================================================================
# annotate_screen
# =============================================================================


class ConcreteBackend(TerminalBackend):
    """Concrete backend for testing base class methods."""

    def __init__(self, screen_content=""):
        self._screen = screen_content

    @property
    def name(self):
        return "test"

    @property
    def is_available(self):
        return True

    async def connect(self):
        return True

    async def ensure_connection(self):
        pass

    async def disconnect(self):
        pass

    async def get_session(self, sid=None):
        return None

    async def list_sessions(self):
        return ""

    async def get_terminal_state(self, sid=None):
        return "{}"

    async def is_ai_session(self, sid):
        return False

    async def get_current_active_session_id(self):
        return None

    async def execute_command(self, cmd, sid=None, **kw):
        return ""

    async def send_text(self, text, sid=None):
        return ""

    async def send_control(self, key, sid=None):
        return ""

    async def read_terminal(self, lines=20, session_id=None):
        return self._screen

    async def clear_terminal(self, sid=None):
        return ""

    async def split_pane(self, direction, sid=None):
        return ""

    async def create_window(self, **kw):
        return ""

    async def create_tab(self, **kw):
        return ""

    async def create_session(self, profile=None):
        return ""

    async def focus_session(self, sid):
        return ""

    async def close_session(self, sid=None, force=False):
        return ""


class TestAnnotateScreen:
    @pytest.mark.asyncio
    async def test_detects_errors(self):
        backend = ConcreteBackend("line1\n[ERROR] Something failed\nline3")
        result = await backend.annotate_screen()

        assert isinstance(result, AnnotationResult)
        assert result.backend == "test"
        assert result.native_annotations is False
        assert result.total_lines_scanned == 3
        assert len(result.annotations) >= 1
        error_ann = [a for a in result.annotations if a.type == AnnotationType.ERROR]
        assert len(error_ann) >= 1

    @pytest.mark.asyncio
    async def test_detects_warnings(self):
        backend = ConcreteBackend("Warning: deprecated function used")
        result = await backend.annotate_screen()

        warnings = [a for a in result.annotations if a.type == AnnotationType.WARNING]
        assert len(warnings) >= 1

    @pytest.mark.asyncio
    async def test_detects_success(self):
        backend = ConcreteBackend("Tests PASSED\n✓ All checks complete")
        result = await backend.annotate_screen()

        success = [a for a in result.annotations if a.type == AnnotationType.SUCCESS]
        assert len(success) >= 1

    @pytest.mark.asyncio
    async def test_no_annotations_for_clean_output(self):
        backend = ConcreteBackend("$ ls\nfile1.txt\nfile2.txt")
        result = await backend.annotate_screen()
        assert len(result.annotations) == 0

    @pytest.mark.asyncio
    async def test_custom_patterns(self):
        backend = ConcreteBackend("CUSTOM_MARKER: something happened")
        custom = {AnnotationType.INFO: [r"CUSTOM_MARKER"]}
        result = await backend.annotate_screen(patterns=custom)

        info = [a for a in result.annotations if a.type == AnnotationType.INFO]
        assert len(info) == 1

    @pytest.mark.asyncio
    async def test_custom_notes(self):
        backend = ConcreteBackend("[ERROR] disk full")
        custom_notes = {r"\[ERROR\]": "Check disk space immediately"}
        result = await backend.annotate_screen(custom_notes=custom_notes)

        assert len(result.annotations) >= 1
        assert result.annotations[0].note == "Check disk space immediately"

    @pytest.mark.asyncio
    async def test_annotation_position(self):
        backend = ConcreteBackend("some prefix [ERROR] the error")
        result = await backend.annotate_screen()

        ann = result.annotations[0]
        assert ann.line == 0
        assert ann.column > 0  # Not at start
        assert ann.length == len("[ERROR]")

    @pytest.mark.asyncio
    async def test_multiple_errors_different_lines(self):
        backend = ConcreteBackend("Error: first\nok line\nFAILED: second")
        result = await backend.annotate_screen()

        errors = [a for a in result.annotations if a.type == AnnotationType.ERROR]
        assert len(errors) >= 2
        lines = {a.line for a in errors}
        assert 0 in lines
        assert 2 in lines

    @pytest.mark.asyncio
    async def test_empty_screen(self):
        backend = ConcreteBackend("")
        result = await backend.annotate_screen()
        assert result.total_lines_scanned == 1  # Empty string splits to [""]
        assert len(result.annotations) == 0


# =============================================================================
# Default Backend Methods
# =============================================================================


class TestDefaultBackendMethods:
    @pytest.mark.asyncio
    async def test_set_appearance_default(self):
        backend = ConcreteBackend()
        result = await backend.set_appearance()
        assert "not supported" in result.lower()

    @pytest.mark.asyncio
    async def test_set_color_preset_default(self):
        backend = ConcreteBackend()
        result = await backend.set_color_preset("red")
        assert "not supported" in result.lower()

    @pytest.mark.asyncio
    async def test_list_color_presets_default(self):
        backend = ConcreteBackend()
        result = await backend.list_color_presets()
        assert "not supported" in result.lower()

    @pytest.mark.asyncio
    async def test_show_alert_default(self):
        backend = ConcreteBackend()
        result = await backend.show_alert("Hi", "Test")
        assert "not supported" in result.lower()


# =============================================================================
# get_backend factory
# =============================================================================


class TestGetBackend:
    def test_tmux_backend(self):
        from sideshell_mcp.backends.detection import get_backend

        with patch("shutil.which", return_value="/usr/bin/tmux"):
            backend = get_backend(BackendType.TMUX)
            assert backend.name == "tmux"

    def test_tmux_not_available(self):
        from sideshell_mcp.backends.detection import get_backend

        with patch("shutil.which", return_value=None):
            with pytest.raises(ValueError, match="not available"):
                get_backend(BackendType.TMUX)

    def test_unknown_backend(self):
        from sideshell_mcp.backends.detection import get_backend

        with pytest.raises(ValueError, match="Unknown"):
            get_backend("nonexistent")

    def test_auto_calls_detect(self):
        from sideshell_mcp.backends.detection import get_backend

        with patch("sideshell_mcp.backends.detection.detect_backend", return_value=BackendType.TMUX):
            with patch("shutil.which", return_value="/usr/bin/tmux"):
                backend = get_backend(BackendType.AUTO)
                assert backend.name == "tmux"

    def test_vscode_backend(self):
        from sideshell_mcp.backends.detection import get_backend

        backend = get_backend(BackendType.VSCODE)
        assert backend.name == "vscode"

    def test_intellij_backend(self):
        from sideshell_mcp.backends.detection import get_backend

        backend = get_backend(BackendType.INTELLIJ)
        assert backend.name == "intellij"

    def test_ghostty_needs_tmux(self):
        from sideshell_mcp.backends.detection import get_backend

        with patch("shutil.which", return_value=None):
            with pytest.raises(ValueError, match="tmux"):
                get_backend(BackendType.GHOSTTY)

    def test_ghostty_with_tmux(self):
        from sideshell_mcp.backends.detection import get_backend

        with patch("shutil.which", return_value="/usr/bin/tmux"):
            backend = get_backend(BackendType.GHOSTTY)
            assert backend.name == "ghostty_tmux"

    def test_maquake_not_available(self):
        from sideshell_mcp.backends.detection import get_backend

        with patch("os.path.exists", return_value=False):
            with pytest.raises(ValueError, match="not available"):
                get_backend(BackendType.MAQUAKE)


# =============================================================================
# list_available_backends / get_system_info
# =============================================================================


class TestSystemInfo:
    def test_list_available_backends(self):
        from sideshell_mcp.backends.detection import list_available_backends

        # Should return a list (may be empty depending on system)
        result = list_available_backends()
        assert isinstance(result, list)

    def test_get_system_info(self):
        from sideshell_mcp.backends.detection import get_system_info

        info = get_system_info()
        assert "platform" in info
        assert "available_terminals" in info
        assert "all_terminals" in info

    def test_print_startup_info(self):
        from sideshell_mcp.backends.detection import print_startup_info

        info = print_startup_info()
        assert "Platform" in info


# =============================================================================
# CLI parse_args
# =============================================================================


class TestParseArgs:
    def test_default_args(self):
        import sys

        from sideshell_mcp.server import parse_args

        with patch.object(sys, "argv", ["sideshell"]):
            args = parse_args()
            assert args.backend == "auto"
            assert args.verbose is False

    def test_backend_arg(self):
        import sys

        from sideshell_mcp.server import parse_args

        with patch.object(sys, "argv", ["sideshell", "--backend", "tmux"]):
            args = parse_args()
            assert args.backend == "tmux"

    def test_verbose_arg(self):
        import sys

        from sideshell_mcp.server import parse_args

        with patch.object(sys, "argv", ["sideshell", "-v"]):
            args = parse_args()
            assert args.verbose is True

    def test_invalid_backend(self):
        import sys

        from sideshell_mcp.server import parse_args

        with patch.object(sys, "argv", ["sideshell", "--backend", "invalid"]):
            with pytest.raises(SystemExit):
                parse_args()
