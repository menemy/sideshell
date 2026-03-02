# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**sideshell** is an AI sidecar terminal - an MCP server that lets Claude/Cursor run commands in a visible, persistent terminal. Cross-platform with pluggable backends (iTerm2, tmux, Ghostty, WezTerm, Kitty, maquake).

## Commands

### Development
- `uv pip install -e .` - Install in development mode (minimal: tmux/ghostty/kitty/wezterm/maquake)
- `uv pip install -e ".[all]"` - Install with all optional deps (iTerm2 + IDE backends)
- `python -m sideshell_mcp.server` - Run the MCP server directly
- `uvx sideshell-mcp` - Run via uvx (after publishing)

### Testing
- `python tests/test_iterm2_backend.py` - Run iTerm2 backend tests
- `python tests/test_tmux_backend.py` - Run tmux backend tests
- `uv run python tests/test_maquake_backend.py` - Run maquake backend tests (requires maquake running)
- `pytest` - Run all pytest-based tests

### Linting & Formatting
- `ruff format .` - Format code
- `ruff check . --fix` - Lint and fix issues
- `mypy sideshell_mcp` - Type check

## Architecture

### Directory Structure
```
sideshell_mcp/
├── server.py           # MCP server with 17 tools
├── backends/
│   ├── base.py             # Abstract base class, ControlKey enum
│   ├── iterm2_backend.py   # iTerm2 Python API backend
│   ├── tmux_backend.py     # tmux subprocess backend
│   ├── ghostty_backend.py  # Ghostty (via tmux)
│   ├── maquake_backend.py  # maquake Unix socket backend
│   ├── wezterm_backend.py  # WezTerm
│   └── kitty_backend.py    # Kitty
```

### Backend Pattern
Each backend implements `TerminalBackend` abstract class:
- `connect()`, `ensure_connection()`
- `execute_command()`, `read_terminal()`, `send_control()`
- `split_pane()`, `create_tab()`, `create_window()`
- `focus_session()`, `close_session()`
- `set_appearance()`, `list_color_presets()`, `set_color_preset()`

### ControlKey Enum
Special keys in `base.py`:
- Ctrl keys: c, d, z, a, e, k, l, u, w
- Navigation: up, down, left, right, home, end, pageup, pagedown
- Function keys: f1-f12
- Other: enter, esc, tab, backspace, insert, delete

### Dependencies
- Core: only `mcp>=1.14.0` — zero extra deps for tmux/ghostty/kitty/wezterm/maquake/vscode/intellij
- Optional `[iterm2]`: `iterm2>=2.7` — for iTerm2 backend
- IDE backends use Unix sockets (stdlib) — no extra packages needed

### Development Notes
- Python 3.11+ required
- tmux, kitty, wezterm backends use subprocess calls (stdlib only)
- Ghostty backend wraps TmuxBackend (Ghostty has no terminal API on macOS)
- maquake backend uses Unix domain socket at `/tmp/maquake.sock` (JSON request/response)
- iTerm2 backend requires `iterm2` package (`pip install sideshell-mcp[iterm2]`)
- IDE backends use Unix sockets at `~/.sideshell/<ide>.sock` (stdlib, no extra packages)
- All backends support wait/timeout for command completion