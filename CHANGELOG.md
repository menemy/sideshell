# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-06

### Added
- Initial public release of **vibe-sideshell**
- AI sidecar terminal concept - commands run in visible, persistent terminal
- 16 MCP tools for iTerm2 automation:
  - `execute` - Execute commands with optional wait, timeout, and broadcast support
  - `read` - Read terminal output
  - `control-char` - Send control characters (Ctrl+C, Ctrl+D, etc.)
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
  - `show-alert` - Show iTerm2 alert dialog
  - `clear` - Clear terminal screen
  - `paste` - Paste text to terminal
- Claude Code session protection (prevents affecting Claude's terminal)
- Focus return feature (returns focus after operations)
- Persistent connection to iTerm2 for better performance
- Comprehensive test suite (36 tests)

### Security
- Automatic detection and protection of Claude Code sessions
- Session isolation for safe multi-terminal operations

## [Unreleased]

### Planned
- Docker support for easier deployment
- Additional shell integration features
- Performance optimizations for large outputs
