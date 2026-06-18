# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-06

### Added
- Initial public release of **sideshell** (distributed as `sideshell-mcp`)
- AI sidecar terminal concept - commands run in visible, persistent terminal
- 17 MCP tools for terminal automation:
  - `execute` - Execute commands with optional wait, timeout, and broadcast support
  - `read` - Read terminal output
  - `control-char` - Send control characters and special keys (Ctrl+C/D/Z, arrows, F1-F12, etc.)
  - `list` - List all windows/tabs/sessions
  - `split` - Split pane horizontally or vertically
  - `new-window` - Create new window
  - `new-tab` - Create new tab
  - `new-session` - Smart session creation (splits if window exists)
  - `focus` - Focus specific session
  - `close-session` - Close terminal session
  - `set-appearance` - Set title, badge, and tab color
  - `get-terminal-state` - Get detailed terminal state
  - `list-color-presets` - List available color presets
  - `set-color-preset` - Apply color preset to session
  - `show-alert` - Show alert dialog
  - `clear` - Clear terminal screen
  - `paste` - Paste text to terminal
- MCP resources: `sideshell://sessions`, `sideshell://capabilities`,
  `sideshell://sessions/{id}`, `sideshell://sessions/{id}/screen`
- Pluggable backends (8): iTerm2, tmux, WezTerm, Kitty, Ghostty
  (`ghostty_tmux` hybrid: native AppleScript splits + per-surface tmux engine),
  maquake (drop-down terminal), VS Code/Cursor, and JetBrains IDEs
- IDE bridge over a local Unix domain socket (`~/.sideshell/<ide>.sock`,
  newline-delimited JSON-RPC 2.0 with a token handshake) for the VS Code/Cursor
  extension and JetBrains plugin backends
- Auto-detection of the active terminal/IDE backend
- Claude Code session protection (prevents affecting Claude's terminal)
- Focus return feature (returns focus after operations)

### Security
- Automatic detection and protection of Claude Code sessions
- Session isolation for safe multi-terminal operations

## [Unreleased]

### Planned
- Docker support for easier deployment
- Additional shell integration features
- Performance optimizations for large outputs
