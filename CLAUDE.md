# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**sideshell** is an AI sidecar terminal - an MCP server that lets Claude/Cursor run commands in a visible, persistent terminal. Cross-platform with pluggable backends (iTerm2, tmux, WezTerm, Kitty).

## Commands

### Development
- `uv pip install -e .` - Install in development mode
- `python -m sideshell_mcp.server` - Run the MCP server directly
- `uvx sideshell-mcp` - Run via uvx (after publishing)

### Testing
- `python tests/test_iterm2_backend.py` - Run iTerm2 backend tests
- `python tests/test_tmux_backend.py` - Run tmux backend tests
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
│   ├── base.py         # Abstract base class, ControlKey enum
│   ├── iterm2_backend.py   # iTerm2 Python API backend
│   ├── tmux_backend.py     # tmux subprocess backend
│   ├── wezterm_backend.py  # WezTerm (planned)
│   └── kitty_backend.py    # Kitty (planned)
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

### Development Notes
- Python 3.11+ required
- Uses `iterm2` package for iTerm2 Python API
- tmux backend uses subprocess calls
- All backends support wait/timeout for command completion