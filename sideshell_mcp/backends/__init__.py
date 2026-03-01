"""Terminal backends for sideshell."""

from .base import BackendType, ControlKey, SessionInfo, SplitDirection, TerminalBackend
from .detection import (
    detect_backend,
    detect_ghostty,
    detect_intellij,
    detect_iterm2,
    detect_kitty,
    detect_parent_process,
    detect_tmux,
    detect_vscode,
    detect_wezterm,
    detect_windows_terminal,
    get_backend,
    get_system_info,
    list_available_backends,
    print_startup_info,
)

__all__ = [
    # Base classes
    "BackendType",
    "ControlKey",
    "SessionInfo",
    "SplitDirection",
    "TerminalBackend",
    # Detection
    "detect_backend",
    "detect_ghostty",
    "detect_intellij",
    "detect_iterm2",
    "detect_kitty",
    "detect_parent_process",
    "detect_tmux",
    "detect_vscode",
    "detect_wezterm",
    "detect_windows_terminal",
    "get_backend",
    "get_system_info",
    "list_available_backends",
    "print_startup_info",
]
