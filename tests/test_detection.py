"""Tests for backend detection including parent process and IDE detection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from sideshell_mcp.backends.base import BackendType
from sideshell_mcp.backends.detection import (
    detect_backend,
    detect_ghostty,
    detect_intellij,
    detect_parent_process,
    detect_vscode,
)


class TestDetectParentProcess:
    """Tests for parent process tree detection."""

    @patch("subprocess.run")
    def test_detects_vscode_parent(self, mock_run: MagicMock) -> None:
        """Should detect VSCode when 'code' is in parent process tree."""
        mock_run.side_effect = [
            # First call: get ppid and comm for current process
            MagicMock(returncode=0, stdout="  1234 zsh"),
            # First call: get cmdline for parent
            MagicMock(returncode=0, stdout="/usr/bin/code --ms-enable-electron"),
            # Second call: get ppid and comm for parent
            MagicMock(returncode=0, stdout="  5678 code"),
            # Second call: get cmdline for grandparent
            MagicMock(returncode=0, stdout="/Applications/Visual Studio Code.app"),
        ]

        result = detect_parent_process()
        assert result == BackendType.VSCODE

    @patch("subprocess.run")
    def test_detects_cursor_parent(self, mock_run: MagicMock) -> None:
        """Should detect Cursor as VSCode backend."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/usr/bin/cursor"),
            MagicMock(returncode=0, stdout="  5678 cursor"),
            MagicMock(returncode=0, stdout="/Applications/Cursor.app"),
        ]

        result = detect_parent_process()
        assert result == BackendType.VSCODE

    @patch("subprocess.run")
    def test_detects_intellij_parent(self, mock_run: MagicMock) -> None:
        """Should detect IntelliJ IDEA via java process with idea marker."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="java -Didea.home=/opt/idea"),
            MagicMock(returncode=0, stdout="  5678 java"),
            MagicMock(returncode=0, stdout="java -Didea.home=/opt/idea -cp ..."),
        ]

        result = detect_parent_process()
        assert result == BackendType.INTELLIJ

    @patch("subprocess.run")
    def test_detects_pycharm_parent(self, mock_run: MagicMock) -> None:
        """Should detect PyCharm as IntelliJ backend."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/opt/pycharm/bin/pycharm"),
            MagicMock(returncode=0, stdout="  5678 pycharm"),
            MagicMock(returncode=0, stdout="/opt/pycharm/bin/pycharm"),
        ]

        result = detect_parent_process()
        assert result == BackendType.INTELLIJ

    @patch("subprocess.run")
    def test_detects_iterm2_parent(self, mock_run: MagicMock) -> None:
        """Should detect iTerm2."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/Applications/iTerm.app"),
            MagicMock(returncode=0, stdout="  5678 iterm2"),
            MagicMock(returncode=0, stdout="/Applications/iTerm.app/Contents/MacOS/iTerm2"),
        ]

        result = detect_parent_process()
        assert result == BackendType.ITERM2

    @patch("subprocess.run")
    def test_detects_ghostty_parent(self, mock_run: MagicMock) -> None:
        """Should detect Ghostty."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/usr/local/bin/ghostty"),
            MagicMock(returncode=0, stdout="  5678 ghostty"),
            MagicMock(returncode=0, stdout="/usr/local/bin/ghostty"),
        ]

        result = detect_parent_process()
        assert result == BackendType.GHOSTTY

    @patch("subprocess.run")
    def test_detects_tmux_parent(self, mock_run: MagicMock) -> None:
        """Should detect tmux."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/usr/bin/tmux"),
            MagicMock(returncode=0, stdout="  5678 tmux"),
            MagicMock(returncode=0, stdout="tmux new-session -s main"),
        ]

        result = detect_parent_process()
        assert result == BackendType.TMUX

    @patch("subprocess.run")
    def test_detects_wezterm_parent(self, mock_run: MagicMock) -> None:
        """Should detect WezTerm."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/usr/local/bin/wezterm"),
            MagicMock(returncode=0, stdout="  5678 wezterm"),
            MagicMock(returncode=0, stdout="/usr/local/bin/wezterm"),
        ]

        result = detect_parent_process()
        assert result == BackendType.WEZTERM

    @patch("subprocess.run")
    def test_detects_kitty_parent(self, mock_run: MagicMock) -> None:
        """Should detect Kitty."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="  1234 zsh"),
            MagicMock(returncode=0, stdout="/usr/local/bin/kitty"),
            MagicMock(returncode=0, stdout="  5678 kitty"),
            MagicMock(returncode=0, stdout="/usr/local/bin/kitty"),
        ]

        result = detect_parent_process()
        assert result == BackendType.KITTY

    @patch("subprocess.run")
    def test_returns_none_when_no_known_parent(self, mock_run: MagicMock) -> None:
        """Should return None when no recognized terminal in process tree."""
        mock_run.side_effect = [
            # First iteration: PID is current, ppid=1 (launchd)
            MagicMock(returncode=0, stdout="  1 launchd"),
            MagicMock(returncode=0, stdout="/sbin/launchd"),
        ]

        result = detect_parent_process()
        assert result is None

    @patch("subprocess.run")
    def test_handles_subprocess_failure(self, mock_run: MagicMock) -> None:
        """Should return None on subprocess errors."""
        mock_run.side_effect = Exception("Command not found")

        result = detect_parent_process()
        assert result is None

    @patch("subprocess.run")
    def test_handles_ps_nonzero_return(self, mock_run: MagicMock) -> None:
        """Should stop walking when ps returns non-zero."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        result = detect_parent_process()
        assert result is None

    @patch("subprocess.run")
    def test_handles_empty_ps_output(self, mock_run: MagicMock) -> None:
        """Should stop walking when ps output is empty."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        result = detect_parent_process()
        assert result is None


class TestDetectVSCode:
    """Tests for VSCode detection."""

    def test_detects_via_term_program(self) -> None:
        with patch.dict(os.environ, {"TERM_PROGRAM": "vscode"}, clear=False):
            assert detect_vscode() is True

    def test_detects_via_cursor_term_program(self) -> None:
        with patch.dict(os.environ, {"TERM_PROGRAM": "cursor"}, clear=False):
            assert detect_vscode() is True

    def test_detects_via_vscode_pid(self) -> None:
        with patch.dict(os.environ, {"VSCODE_PID": "12345"}, clear=False):
            assert detect_vscode() is True

    def test_detects_via_port_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "vscode-port"
        port_file.write_text(json.dumps({"port": 46117}))

        # detection.py does `from .ide_bridge import SIDESHELL_DIR` locally
        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            assert detect_vscode() is True

    def test_detects_via_code_binary(self) -> None:
        # Clear env vars that might trigger early return
        env = {k: v for k, v in os.environ.items()
               if k not in ("TERM_PROGRAM", "VSCODE_PID", "VSCODE_CWD")}
        with patch.dict(os.environ, env, clear=True):
            with patch("shutil.which", return_value="/usr/bin/code"):
                assert detect_vscode() is True

    def test_not_detected_when_nothing_available(self) -> None:
        env = {k: v for k, v in os.environ.items()
               if k not in ("TERM_PROGRAM", "VSCODE_PID", "VSCODE_CWD")}
        with patch.dict(os.environ, env, clear=True):
            with patch("shutil.which", return_value=None):
                with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                    assert detect_vscode() is False


class TestDetectIntelliJ:
    """Tests for IntelliJ/JetBrains IDE detection."""

    def test_detects_via_terminal_emulator(self) -> None:
        with patch.dict(os.environ, {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}, clear=False):
            assert detect_intellij() is True

    def test_detects_via_jetbrains_ide(self) -> None:
        with patch.dict(os.environ, {"JETBRAINS_IDE": "PyCharm"}, clear=False):
            assert detect_intellij() is True

    def test_detects_via_port_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "intellij-port"
        port_file.write_text(json.dumps({"port": 46118}))

        with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
            assert detect_intellij() is True

    def test_not_detected_without_indicators(self) -> None:
        env = {k: v for k, v in os.environ.items()
               if k not in ("TERMINAL_EMULATOR", "JETBRAINS_IDE")}
        with patch.dict(os.environ, env, clear=True):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                assert detect_intellij() is False


class TestDetectGhostty:
    """Tests for Ghostty terminal detection."""

    def test_detects_via_term_program(self) -> None:
        with patch.dict(os.environ, {"TERM_PROGRAM": "ghostty"}, clear=False):
            assert detect_ghostty() is True

    def test_detects_via_resources_dir(self) -> None:
        with patch.dict(os.environ, {"GHOSTTY_RESOURCES_DIR": "/opt/ghostty"}, clear=False):
            assert detect_ghostty() is True

    def test_detects_via_binary(self) -> None:
        env = {k: v for k, v in os.environ.items()
               if k not in ("TERM_PROGRAM", "GHOSTTY_RESOURCES_DIR")}
        with patch.dict(os.environ, env, clear=True):
            with patch("shutil.which", return_value="/usr/local/bin/ghostty"):
                assert detect_ghostty() is True

    def test_not_detected_when_nothing_available(self) -> None:
        env = {k: v for k, v in os.environ.items()
               if k not in ("TERM_PROGRAM", "GHOSTTY_RESOURCES_DIR")}
        with patch.dict(os.environ, env, clear=True):
            with patch("shutil.which", return_value=None):
                assert detect_ghostty() is False


class TestDetectBackend:
    """Tests for the full detect_backend() flow."""

    @patch("sideshell_mcp.backends.detection.detect_parent_process")
    def test_parent_process_takes_priority(self, mock_parent: MagicMock) -> None:
        """Parent process detection should be highest priority."""
        mock_parent.return_value = BackendType.VSCODE
        result = detect_backend()
        assert result == BackendType.VSCODE

    @patch("sideshell_mcp.backends.detection.detect_parent_process")
    def test_env_vars_when_no_parent(self, mock_parent: MagicMock) -> None:
        """Env var detection used when parent process detection fails."""
        mock_parent.return_value = None
        with patch.dict(os.environ, {"VSCODE_PID": "12345"}, clear=False):
            result = detect_backend()
            assert result == BackendType.VSCODE

    @patch("sideshell_mcp.backends.detection.detect_parent_process")
    def test_jetbrains_env_detection(self, mock_parent: MagicMock) -> None:
        mock_parent.return_value = None
        with patch.dict(os.environ, {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}, clear=False):
            result = detect_backend()
            assert result == BackendType.INTELLIJ

    @patch("sideshell_mcp.backends.detection.detect_parent_process")
    def test_ghostty_env_detection(self, mock_parent: MagicMock) -> None:
        mock_parent.return_value = None
        env = {k: v for k, v in os.environ.items()
               if k not in ("VSCODE_PID", "TERMINAL_EMULATOR", "ITERM_SESSION_ID",
                            "TERM_PROGRAM", "WEZTERM_PANE", "KITTY_WINDOW_ID",
                            "GHOSTTY_RESOURCES_DIR", "TMUX", "VSCODE_CWD",
                            "LC_TERMINAL", "TERM", "WT_SESSION")}
        env["TERM_PROGRAM"] = "ghostty"
        with patch.dict(os.environ, env, clear=True):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                result = detect_backend()
                assert result == BackendType.GHOSTTY

    @patch("sideshell_mcp.backends.detection.detect_parent_process")
    def test_tmux_env_detection(self, mock_parent: MagicMock) -> None:
        mock_parent.return_value = None
        env = {k: v for k, v in os.environ.items()
               if k not in ("VSCODE_PID", "TERMINAL_EMULATOR", "ITERM_SESSION_ID",
                            "TERM_PROGRAM", "WEZTERM_PANE", "KITTY_WINDOW_ID",
                            "GHOSTTY_RESOURCES_DIR", "VSCODE_CWD",
                            "LC_TERMINAL", "TERM", "WT_SESSION")}
        env["TMUX"] = "/tmp/tmux-501/default,12345,0"
        with patch.dict(os.environ, env, clear=True):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", Path("/nonexistent")):
                result = detect_backend()
                assert result == BackendType.TMUX

    @patch("sideshell_mcp.backends.detection.detect_parent_process")
    def test_port_file_detection(self, mock_parent: MagicMock, tmp_path: Path) -> None:
        """Port files should be checked when env vars don't match."""
        mock_parent.return_value = None
        env = {k: v for k, v in os.environ.items()
               if k not in ("VSCODE_PID", "TERMINAL_EMULATOR", "ITERM_SESSION_ID",
                            "TERM_PROGRAM", "WEZTERM_PANE", "KITTY_WINDOW_ID",
                            "GHOSTTY_RESOURCES_DIR", "TMUX", "VSCODE_CWD",
                            "LC_TERMINAL", "TERM", "WT_SESSION")}
        # Create vscode port file
        (tmp_path / "vscode-port").write_text(json.dumps({"port": 46117}))

        with patch.dict(os.environ, env, clear=True):
            with patch("sideshell_mcp.backends.ide_bridge.SIDESHELL_DIR", tmp_path):
                result = detect_backend()
                assert result == BackendType.VSCODE
