# sideshell

**AI sidecar terminal** — let Claude/Cursor run commands in a visible, persistent terminal you control.

[![PyPI version](https://badge.fury.io/py/sideshell-mcp.svg)](https://badge.fury.io/py/sideshell-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Why?

When AI assistants run shell commands, they execute in a hidden terminal:
- ❌ No visible history
- ❌ Can't intervene (enter password, confirm prompts)
- ❌ Output mixed with AI conversation

**sideshell** runs commands in a **separate visible terminal**:
- ✅ Full command history visible
- ✅ Persistent session (survives AI restarts)
- ✅ Intervene anytime (passwords, confirmations)
- ✅ Clean separation from AI conversation

## Supported Terminals

| Terminal | Platform | Status |
|----------|----------|--------|
| **iTerm2** | macOS | ✅ Full support (native Python API) |
| **tmux** | macOS, Linux, WSL | ✅ Full support |
| **WezTerm** | macOS, Linux, Windows | ✅ Full support |
| **Kitty** | macOS, Linux | ✅ Full support |
| **Ghostty** | macOS | ✅ Full support (`ghostty_tmux` hybrid: native AppleScript splits + per-surface tmux engine, Ghostty 1.3+) |
| **maquake** | macOS | ✅ Full support (drop-down terminal via Unix socket) |
| **VS Code / Cursor** | macOS, Linux, Windows | ✅ Full support (via extension, Unix-socket bridge) |
| **JetBrains IDEs** | macOS, Linux, Windows | ✅ Full support (via plugin, Unix-socket bridge) |

## Features

- **Multi-Backend** - Works with iTerm2, tmux, WezTerm, Kitty, Ghostty, maquake, VS Code/Cursor, or JetBrains IDEs
- **Sidecar Terminal** - AI commands run in a visible terminal pane
- **You Stay in Control** - See everything, intervene anytime
- **Session Persistence** - Terminal survives AI session restarts
- **TUI Support** - Arrow keys, F1-F12, Ctrl+C/D/Z for interactive apps
- **Focus Management** - Optionally returns focus after operations

## Installation

### Using uvx (Recommended)

```bash
# Install uv first
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run sideshell
uvx sideshell-mcp
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "sideshell": {
      "command": "uvx",
      "args": ["sideshell-mcp"]
    }
  }
}
```

### Using pipx

```bash
pipx install sideshell-mcp
sideshell-mcp
```

### Backend Selection

```bash
# Auto-detect (default)
uvx sideshell-mcp

# Force specific backend
uvx sideshell-mcp --backend=tmux
uvx sideshell-mcp --backend=iterm2
```

## Available Tools (17)

| Tool | Description |
|------|-------------|
| `execute` | Execute commands (supports `wait`, `timeout`, `targets` for broadcast) |
| `read` | Read terminal output |
| `control-char` | Send special keys: Ctrl+C/D/Z, arrows, F1-F12, Home/End, PageUp/Down |
| `list` | List all windows/tabs/sessions |
| `split` | Split pane horizontally or vertically |
| `new-window` | Create new window |
| `new-tab` | Create new tab |
| `new-session` | Smart session creation (splits if window exists) |
| `focus` | Focus specific session |
| `close-session` | Close terminal session |
| `set-appearance` | Set tab title, badge, and color |
| `get-terminal-state` | Get detailed terminal state |
| `list-color-presets` | List available color presets |
| `set-color-preset` | Apply color preset |
| `show-alert` | Show alert dialog |
| `clear` | Clear terminal screen |
| `paste` | Paste text to terminal |

## MCP Resources

| Resource | Description |
|----------|-------------|
| `sideshell://sessions` | List all terminal sessions |
| `sideshell://capabilities` | Backend features and system info |
| `sideshell://sessions/{id}` | Session details |
| `sideshell://sessions/{id}/screen` | Screen content |

## Prerequisites

### iTerm2 (macOS)
1. Open iTerm2 → Preferences → General → Magic
2. Enable "Enable Python API"
3. Restart iTerm2

### tmux
```bash
# macOS
brew install tmux

# Ubuntu/Debian
sudo apt install tmux
```

### WezTerm
Download from [wezfurlong.org/wezterm](https://wezfurlong.org/wezterm/)

### Kitty
```bash
# macOS
brew install --cask kitty

# Linux
curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ MCP Client  │────▶│  sideshell   │────▶│  Terminal   │
│   (Claude)  │     │  MCP Server  │     │   Backend   │
└─────────────┘     └──────────────┘     └─────────────┘
                            │
                    ┌───────┴────────────┐
                    │      Backends      │
                    ├────────────────────┤
                    │ • iTerm2           │
                    │ • tmux             │
                    │ • WezTerm          │
                    │ • Kitty            │
                    │ • Ghostty          │
                    │ • maquake          │
                    │ • VS Code / Cursor │
                    │ • JetBrains IDEs   │
                    └────────────────────┘
```

VS Code/Cursor and JetBrains backends talk to their IDE extension/plugin over a
local Unix domain socket (`~/.sideshell/<ide>.sock`) using newline-delimited
JSON-RPC 2.0 with a token handshake.

## Development

```bash
git clone https://github.com/menemy/sideshell
cd sideshell
uv pip install -e ".[dev]"

# Run tests
python tests/test_iterm2_backend.py   # iTerm2
python tests/test_tmux_backend.py     # tmux
python tests/test_wezterm_backend.py  # WezTerm
python tests/test_kitty_backend.py    # Kitty

# Lint & format
ruff format .
ruff check . --fix
```

## Requirements

- Python 3.11+
- One of: iTerm2, tmux, WezTerm, Kitty, Ghostty, maquake, VS Code/Cursor, or a JetBrains IDE

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request
