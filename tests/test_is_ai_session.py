"""Unit tests for is_ai_session detection logic.

Tests that shells and terminal multiplexers (tmux, zsh, bash) are never
detected as AI sessions, even when session/tab names contain 'claude'.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.iterm2_backend import ITermBackend


def _make_session(variables: dict[str, Any], session_id: str = "test-session-id") -> AsyncMock:
    """Create a mock iTerm2 session with given variables."""
    session = AsyncMock()
    session.session_id = session_id

    async def get_variable(name: str) -> Any:
        return variables.get(name)

    session.async_get_variable = AsyncMock(side_effect=get_variable)
    return session


def _make_tab(title_override: str | None = None) -> AsyncMock:
    """Create a mock tab with optional title override."""
    tab = AsyncMock()

    async def get_variable(name: str) -> Any:
        if name == "titleOverride":
            return title_override
        return None

    tab.async_get_variable = AsyncMock(side_effect=get_variable)
    return tab


class TestIsAiSession:
    """Tests for is_ai_session method."""

    @pytest.fixture
    def backend(self) -> ITermBackend:
        backend = ITermBackend()
        backend.app = MagicMock()
        backend.app.windows = []
        return backend

    @pytest.mark.asyncio
    async def test_tmux_not_ai_even_with_claude_in_name(self, backend: ITermBackend) -> None:
        """tmux session named 'claude-island' should NOT be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "tmux",
                "session.lastCommand": "tmux new-session -s claude-island",
                "session.name": "claude-island",
                "session.commandLine": "tmux new-session -s claude-island",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is False, "tmux should not be detected as AI session"

    @pytest.mark.asyncio
    async def test_zsh_not_ai_in_claude_tab(self, backend: ITermBackend) -> None:
        """zsh shell in a tab titled 'Claude Code' should NOT be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "zsh",
                "session.lastCommand": "cd /projects/claude-island",
                "session.name": "",
                "session.commandLine": "zsh",
            }
        )
        tab = _make_tab(title_override="Claude Code")
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=tab)

        result = await backend.is_ai_session("test-session-id")
        assert result is False, "zsh should not be detected as AI even in Claude tab"

    @pytest.mark.asyncio
    async def test_bash_not_ai(self, backend: ITermBackend) -> None:
        """bash shell should NOT be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "bash",
                "session.lastCommand": "claude --help",
                "session.name": "claude-dev",
                "session.commandLine": "bash",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is False, "bash should not be detected as AI session"

    @pytest.mark.asyncio
    async def test_ssh_not_ai(self, backend: ITermBackend) -> None:
        """ssh session should NOT be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "ssh",
                "session.lastCommand": "ssh claude-server",
                "session.name": "claude-server",
                "session.commandLine": "ssh claude-server",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is False, "ssh should not be detected as AI session"

    @pytest.mark.asyncio
    async def test_node_claude_is_ai(self, backend: ITermBackend) -> None:
        """Node process running Claude Code SHOULD be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "node",
                "session.lastCommand": "claude",
                "session.name": "Claude Code",
                "session.commandLine": "node /usr/local/bin/claude",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is True, "node running claude should be detected as AI"

    @pytest.mark.asyncio
    async def test_python_claude_is_ai(self, backend: ITermBackend) -> None:
        """Python process with claude in command SHOULD be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "python3",
                "session.lastCommand": "claude -c",
                "session.name": "Claude Code",
                "session.commandLine": "python3 -m claude",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is True, "python running claude should be detected as AI"

    @pytest.mark.asyncio
    async def test_npx_anthropic_is_ai(self, backend: ITermBackend) -> None:
        """npx running @anthropic package SHOULD be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "npx",
                "session.lastCommand": "npx @anthropic/claude-code",
                "session.name": "",
                "session.commandLine": "npx @anthropic/claude-code",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is True, "npx @anthropic should be detected as AI"

    @pytest.mark.asyncio
    async def test_session_not_found(self, backend: ITermBackend) -> None:
        """Non-existent session should return False."""
        backend._find_session_object = AsyncMock(return_value=None)

        result = await backend.is_ai_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_tab_title_claude_with_node_job(self, backend: ITermBackend) -> None:
        """Tab titled 'Claude Code' with node job SHOULD be AI."""
        session = _make_session(
            {
                "session.jobName": "node",
                "session.lastCommand": "",
                "session.name": "",
                "session.commandLine": "",
            }
        )
        tab = _make_tab(title_override="Claude Code")
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=tab)

        result = await backend.is_ai_session("test-session-id")
        assert result is True, "node in Claude tab should be detected as AI"

    @pytest.mark.asyncio
    async def test_fish_shell_not_ai(self, backend: ITermBackend) -> None:
        """fish shell should NOT be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "fish",
                "session.lastCommand": "claude",
                "session.name": "claude-project",
                "session.commandLine": "fish",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is False, "fish should not be detected as AI session"

    @pytest.mark.asyncio
    async def test_screen_not_ai(self, backend: ITermBackend) -> None:
        """GNU screen should NOT be detected as AI."""
        session = _make_session(
            {
                "session.jobName": "screen",
                "session.lastCommand": "screen -S claude",
                "session.name": "claude",
                "session.commandLine": "screen -S claude",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is False, "screen should not be detected as AI session"

    @pytest.mark.asyncio
    async def test_none_job_name_falls_through(self, backend: ITermBackend) -> None:
        """When jobName is None, should fall through to other checks."""
        session = _make_session(
            {
                "session.jobName": None,
                "session.lastCommand": "claude",
                "session.name": "",
                "session.commandLine": "",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is True, "should fall through to lastCommand check"

    @pytest.mark.asyncio
    async def test_mcp_in_command_line_is_ai(self, backend: ITermBackend) -> None:
        """Process with 'mcp' in commandLine SHOULD be AI (when not a shell)."""
        session = _make_session(
            {
                "session.jobName": "node",
                "session.lastCommand": "",
                "session.name": "",
                "session.commandLine": "node /path/to/mcp-server",
            }
        )
        backend._find_session_object = AsyncMock(return_value=session)
        backend._find_tab_for_session = AsyncMock(return_value=None)

        result = await backend.is_ai_session("test-session-id")
        assert result is True, "node running mcp server should be detected as AI"
