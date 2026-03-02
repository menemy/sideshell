# Installation Guide

sideshell has 3 components. Install only what you need.

## Quick Start

```bash
make build     # build everything
make install   # install everything locally
make test      # run all tests
make help      # show all targets
```

---

## 1. Python MCP Server

The core. Talks to terminal backends and IDE plugins via Unix sockets.

### From source (development)

```bash
uv pip install -e ".[dev]"
python -m sideshell_mcp.server
```

### From PyPI (end users)

```bash
pip install sideshell-mcp
sideshell-mcp
# or
uvx sideshell-mcp
```

### Claude Code / Cursor MCP config

Add to `~/.claude/claude_desktop_config.json` or Cursor MCP settings:

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

---

## 2. VSCode / Cursor Extension

Required only if you want to control VSCode/Cursor terminals via MCP.

### From .vsix (recommended for now)

```bash
# Build
cd extensions/vscode
npm install
npm run compile
npx @vscode/vsce package --no-dependencies

# Install
code --install-extension sideshell-terminal-*.vsix     # VSCode
cursor --install-extension sideshell-terminal-*.vsix   # Cursor (if CLI available)
```

### Manual deploy to Cursor

Cursor doesn't always pick up `--install-extension`. Manual copy works reliably:

```bash
make install-cursor
# Then in Cursor: Cmd+Shift+P → "Developer: Reload Window"
```

### Verify it's running

```bash
cat ~/.sideshell/vscode-port
# Should show: {"socket":".../.sideshell/vscode.sock","pid":...,"token":"...","ide":"vscode"}
```

---

## 3. IntelliJ Plugin

Required only if you want to control JetBrains IDE terminals via MCP.
Works with: IntelliJ IDEA, PyCharm, WebStorm, GoLand, RustRover, PhpStorm, Android Studio.

### From .zip (recommended for now)

```bash
# Build (uses IntelliJ's bundled JDK)
cd extensions/intellij
JAVA_HOME="$HOME/Applications/IntelliJ IDEA.app/Contents/jbr/Contents/Home" \
  ./gradlew buildPlugin

# Install
make install-intellij
# Then restart IntelliJ
```

### Verify it's running

```bash
cat ~/.sideshell/intellij-port
# Should show: {"socket":".../.sideshell/intellij.sock","pid":...,"token":"...","ide":"intellij"}
```

---

## Terminal Backend Requirements

The Python MCP server auto-detects available backends. No extra setup needed for most.

| Backend | Requirements | Notes |
|---------|-------------|-------|
| Ghostty | `brew install tmux` | Auto-creates `sideshell` tmux session. Watch: `tmux attach -t sideshell` |
| tmux | `brew install tmux` | Auto-creates `sideshell` session if none exist |
| iTerm2 | iTerm2 + `pip install sideshell-mcp[iterm2]` | Preferences → General → Magic → Enable Python API |
| Kitty | `brew install --cask kitty` | Auto-detected if running |
| WezTerm | `brew install --cask wezterm` | Auto-detected if running |
| maquake | maquake running | Auto-detected via `/tmp/maquake.sock` |
| VSCode/Cursor | Extension installed (see above) | Unix socket at `~/.sideshell/vscode.sock` |
| IntelliJ | Plugin installed (see above) | Unix socket at `~/.sideshell/intellij.sock` |

### Dependencies

- **Base install** (`pip install sideshell-mcp`): only `mcp` package. Zero extra deps for tmux, Ghostty, Kitty, WezTerm, maquake, VSCode, IntelliJ.
- **iTerm2**: `pip install sideshell-mcp[iterm2]` adds the `iterm2` package.

---

## Troubleshooting

### Extension not loading in Cursor
Cursor loads from `~/.cursor/extensions/`, not from the project. Use `make install-cursor` and reload.

### IntelliJ plugin not found
Check the plugin directory path matches your IDE version:
```bash
ls ~/Library/Application\ Support/JetBrains/*/plugins/
```

### Socket file missing
The IDE plugin/extension writes `~/.sideshell/<ide>.sock` on startup. If missing:
- Check the extension/plugin is installed and active
- Check IDE developer console for errors
- Try `Cmd+Shift+P → "sideshell: Start Terminal Bridge"` in VSCode/Cursor

### Permission denied on first connect
On first connection, the IDE shows an approval dialog. Click "Allow".
The setting persists — check IDE settings to revoke/grant access.
