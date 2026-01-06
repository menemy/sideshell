"""Ghostty backend — transparent tmux bridge.

Ghostty has no terminal control API on macOS.
On Linux it has minimal D-Bus IPC (new-window only).
This backend wraps TmuxBackend so sideshell works seamlessly in Ghostty.
"""

from __future__ import annotations

from .tmux_backend import TmuxBackend


class GhosttyBackend(TmuxBackend):
    """Ghostty backend using tmux as transport.

    Inherits all functionality from TmuxBackend including
    auto-creation of 'sideshell' tmux session on first connect.
    """

    @property
    def name(self) -> str:
        return "ghostty"
