# Contributing to sideshell

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Git

For IDE plugins:
- **VSCode extension**: Node.js 18+, npm
- **IntelliJ plugin**: JDK 21 (`brew install openjdk@21`)

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/menemy/sideshell.git
cd sideshell

# Install with uv
uv pip install -e .

# Install dev dependencies
uv pip install pytest pytest-asyncio ruff mypy
```

### Running Tests

```bash
# Run all tests (skip legacy test files)
uv run python -m pytest tests/test_ide_bridge.py tests/test_vscode_backend.py \
  tests/test_intellij_backend.py tests/test_detection.py -v

# Run specific test file
uv run python -m pytest tests/test_ide_bridge.py -v

# Run with coverage
uv run python -m pytest tests/ --cov=sideshell_mcp -v
```

### Code Quality

```bash
# Format code
ruff format .

# Lint code
ruff check . --fix

# Type check
mypy sideshell_mcp
```

## Building IDE Plugins

### VSCode Extension

The VSCode extension provides terminal control via a Unix-socket bridge. It works in both VSCode and Cursor.

```bash
cd extensions/vscode

# Install dependencies
npm install

# Compile TypeScript
npm run compile

# Package as VSIX
npx @vscode/vsce package --allow-missing-repository
# Output: sideshell-terminal-0.1.0.vsix
```

**Install in VSCode:**
```bash
code --install-extension sideshell-terminal-0.1.0.vsix --force
```

**Install in Cursor:**
```bash
cursor --install-extension sideshell-terminal-0.1.0.vsix --force
```

**Key files:**
- `src/extension.ts` - Extension activation, command registration
- `src/terminal-manager.ts` - Terminal session management, output buffering
- `src/bridge.ts` - Unix socket server (JSON-RPC 2.0)
- `package.json` - Extension manifest, commands, configuration

### IntelliJ Plugin

The IntelliJ plugin works with all JetBrains IDEs (IntelliJ IDEA, PyCharm, WebStorm, GoLand, etc.).

**Prerequisites:**
```bash
# Install JDK 21
brew install openjdk@21

# Verify
/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java -version
```

**Build:**
```bash
cd extensions/intellij

# Build plugin (set JAVA_HOME to JDK 21)
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home \
  ./gradlew buildPlugin

# Output: build/distributions/sideshell-terminal-0.1.0.zip
```

**Install:**
```bash
# Find your IDE plugins directory (example for IntelliJ IDEA 2025.3):
PLUGIN_DIR="$HOME/Library/Application Support/JetBrains/IntelliJIdea2025.3/plugins/sideshell-terminal"

# For PyCharm:
# PLUGIN_DIR="$HOME/Library/Application Support/JetBrains/PyCharm2025.3/plugins/sideshell-terminal"

# For WebStorm:
# PLUGIN_DIR="$HOME/Library/Application Support/JetBrains/WebStorm2025.3/plugins/sideshell-terminal"

# Install
rm -rf "$PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR"
cd "$PLUGIN_DIR"
unzip /path/to/sideshell-terminal-0.1.0.zip
mv sideshell-terminal/* .
rmdir sideshell-terminal

# Restart IDE to load the plugin
```

**Key files:**
- `src/main/kotlin/com/sideshell/terminal/SideshellBridgeService.kt` - Unix socket server, JSON-RPC dispatch
- `src/main/kotlin/com/sideshell/terminal/TerminalManagerService.kt` - Terminal session management
- `src/main/kotlin/com/sideshell/terminal/SideshellSettings.kt` - Plugin settings (socket path, buffer size)
- `src/main/kotlin/com/sideshell/terminal/SideshellStartupActivity.kt` - Auto-start on IDE launch
- `build.gradle.kts` - Build configuration (Kotlin 2.1.0, IntelliJ Platform 2.11.0)

### How IDE Plugins Work

Both plugins follow the same architecture:

1. **Unix Socket Server** - Plugin starts a Unix domain socket server at
   `~/.sideshell/<ide>.sock`
   - VSCode: `~/.sideshell/vscode.sock`
   - IntelliJ: `~/.sideshell/intellij.sock`

2. **Discovery File** - Plugin writes socket info (path + auth token) to
   `~/.sideshell/<ide>-port`
   ```json
   {"socket": "/Users/you/.sideshell/intellij.sock", "token": "...", "pid": 12345, "ide": "intellij"}
   ```

3. **Auth Handshake** - The Python MCP backend connects to the socket and sends
   the token as the first message:
   ```json
   {"type": "auth", "token": "..."}
   ```

4. **JSON-RPC 2.0** - The backend then sends newline-delimited JSON-RPC requests:
   ```json
   {"jsonrpc": "2.0", "id": 1, "method": "list_sessions"}
   ```

5. **Terminal Control** - Plugin translates JSON-RPC methods to IDE terminal API calls

### Socket Discovery

The Python backend (`sideshell_mcp/backends/ide_bridge.py`) discovers plugins via:
1. Read `~/.sideshell/<ide>-port` for the socket path and auth token
2. Fall back to the well-known socket path (`~/.sideshell/<ide>.sock`)
3. Connect to the Unix socket, send the token handshake, then JSON-RPC requests

## Project Structure

```
sideshell/
├── sideshell_mcp/
│   ├── server.py              # MCP server with tools
│   └── backends/
│       ├── base.py            # Abstract base class, ControlKey enum
│       ├── detection.py       # Auto-detect terminal/IDE backend
│       ├── ide_bridge.py      # Unix socket client for IDE backends
│       ├── vscode_backend.py  # VSCode/Cursor backend
│       ├── intellij_backend.py # IntelliJ/JetBrains backend
│       ├── iterm2_backend.py  # iTerm2 backend
│       ├── tmux_backend.py    # tmux backend
│       ├── wezterm_backend.py # WezTerm backend
│       └── kitty_backend.py   # Kitty backend
├── extensions/
│   ├── vscode/                # VSCode/Cursor extension (TypeScript)
│   └── intellij/              # IntelliJ plugin (Kotlin)
├── tests/
│   ├── test_ide_bridge.py     # IDE bridge protocol tests
│   ├── test_vscode_backend.py # VSCode backend tests
│   ├── test_intellij_backend.py # IntelliJ backend tests
│   └── test_detection.py     # Backend detection tests
├── pyproject.toml
├── CLAUDE.md
└── CONTRIBUTING.md            # This file
```

## How to Contribute

### Reporting Bugs

1. Check existing issues to avoid duplicates
2. Create a new issue with:
   - Clear title describing the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, IDE version, Python version)

### Submitting Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Run linting and formatting
7. Commit with clear messages
8. Push and open a Pull Request

## Code Style

- Python: PEP 8, type hints, line length 100
- TypeScript: Standard TSConfig strict mode
- Kotlin: Kotlin coding conventions, JDK 21
