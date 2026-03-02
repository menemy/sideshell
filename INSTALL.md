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

The core. Talks to terminal backends (iTerm2, tmux, Kitty, WezTerm) and IDE plugins.

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

### From VSCode Marketplace (when published)

Search "sideshell" in Extensions panel, or:

```bash
code --install-extension sideshell.sideshell-terminal
```

### Verify it's running

Check that `~/.sideshell/vscode-port` exists after starting the IDE:

```bash
cat ~/.sideshell/vscode-port
# Should show: {"port":46117,"pid":...,"token":"...","ide":"vscode","version":"0.2.0"}
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

### From JetBrains Marketplace (when published)

Settings → Plugins → Marketplace → search "sideshell"

### Verify it's running

```bash
cat ~/.sideshell/intellij-port
# Should show: {"port":46118,"pid":...,"token":"...","ide":"intellij","version":"0.1.0"}
```

---

## Terminal Backend Requirements

The Python MCP server auto-detects available backends. No extra setup needed for most.

| Backend | Requirements | Notes |
|---------|-------------|-------|
| iTerm2 | iTerm2 running, Python API enabled | Preferences → General → Magic → Enable Python API |
| tmux | `brew install tmux` | Works headless |
| Kitty | `brew install --cask kitty` | Auto-detected if running |
| WezTerm | `brew install --cask wezterm` | Auto-detected if running |
| VSCode/Cursor | Extension installed (see above) | Communicates via WebSocket |
| IntelliJ | Plugin installed (see above) | Communicates via WebSocket |
| Ghostty | Not supported yet | No remote control API available |

---

## Troubleshooting

### Extension not loading in Cursor
Cursor loads from `~/.cursor/extensions/`, not from the project. Use `make install-cursor` and reload.

### IntelliJ plugin not found
Check the plugin directory path matches your IDE version:
```bash
ls ~/Library/Application\ Support/JetBrains/*/plugins/
```

### Port file missing
The IDE plugin/extension writes `~/.sideshell/<ide>-port` on startup. If missing:
- Check the extension/plugin is installed and active
- Check IDE developer console for errors (Help → Toggle Developer Tools)
- Try `Cmd+Shift+P → "sideshell: Start Terminal Bridge"` in VSCode/Cursor

### Permission denied on first connect
On first connection, the IDE shows an approval dialog. Click "Allow".
For development, auto-allow is enabled (`_approved = true` in bridge source).
