"""Unit tests for the Kitty backend (mocked — no live kitty required)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sideshell_mcp.backends.kitty_backend import KittyBackend


@pytest.fixture
def backend() -> KittyBackend:
    b = KittyBackend()
    b.is_ai_session = AsyncMock(return_value=False)
    b.get_current_active_session_id = AsyncMock(return_value="1")
    b._send_text_literal = AsyncMock()
    b._wait_for_completion = AsyncMock(return_value="done")
    return b


class TestLiteralSendRouting:
    """User text/commands must go through the literal (--stdin) path."""

    @pytest.mark.asyncio
    async def test_execute_command_uses_literal_send(self, backend: KittyBackend) -> None:
        # A command with backslashes would be corrupted by send-text's positional arg.
        await backend.execute_command(r"grep '\d+' file", session_id="1", wait=False)
        backend._send_text_literal.assert_awaited_once_with("1", "grep '\\d+' file\n")

    @pytest.mark.asyncio
    async def test_send_text_uses_literal_send(self, backend: KittyBackend) -> None:
        await backend.send_text(r"C:\Users\me", session_id="1")
        backend._send_text_literal.assert_awaited_once_with("1", r"C:\Users\me")


class TestSendTextLiteralArgv:
    """_send_text_literal must invoke `send-text --stdin` and pipe the bytes verbatim."""

    @pytest.mark.asyncio
    async def test_uses_stdin_and_pipes_bytes(self) -> None:
        b = KittyBackend()
        b._get_kitten_path = lambda: "kitten"  # type: ignore[method-assign]
        b._listen_on = None
        captured: dict = {}

        class FakeProc:
            returncode = 0

            async def communicate(self, data: bytes | None = None) -> tuple[bytes, bytes]:
                captured["data"] = data
                return (b"", b"")

        def fake_exec(*cmd: str, **kwargs: object) -> FakeProc:
            captured["cmd"] = cmd
            captured["stdin"] = kwargs.get("stdin")
            # create_subprocess_exec is patched as an AsyncMock (it's a coroutine
            # function), so the side_effect's return value IS the await result.
            return FakeProc()

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            await b._send_text_literal("7", r"echo \t")

        assert "--stdin" in captured["cmd"]
        assert "id:7" in " ".join(captured["cmd"])
        # Bytes are piped through stdin unchanged (no escape interpretation here).
        assert captured["data"] == b"echo \\t"
