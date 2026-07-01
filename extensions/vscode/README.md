# sideshell Terminal Control

Let AI agents (Claude Code, Cursor, any MCP client) run commands in **real,
visible VS Code terminals** — instead of a hidden shell you can't see or stop.

This extension is the VS Code side of [sideshell](https://github.com/menemy/sideshell):
it exposes terminal control over a local bridge that the `sideshell-mcp` server
connects to. You watch every command execute live, in your own terminal panel,
and can intervene at any time.

## How it works

1. Install this extension — it starts a local bridge automatically
   (Unix socket on macOS/Linux, named pipe on Windows; never TCP).
2. Add the MCP server to your AI tool:

   ```bash
   claude mcp add sideshell -- uvx sideshell-mcp --backend vscode
   ```

3. The first time an agent connects, VS Code asks you to **Allow** terminal
   access. Until you do, every request is rejected.

## What agents can do

- Open, split, focus and close terminal tabs
- Run commands and (with shell integration) wait for completion and read output
- Send keystrokes and control characters (Ctrl+C, arrows, …)
- Read back recent terminal output

## Security

- Local-only transport: Unix domain socket / Windows named pipe, `0600` perms — no TCP port.
- Random per-session token; the first message must authenticate.
- Nothing works until you approve access in the IDE (persisted in `sideshell.allowAccess`).
- Commands are never executed in the AI's own terminal.

## Requirements

- Waiting for command completion and reading output use VS Code
  [shell integration](https://code.visualstudio.com/docs/terminal/shell-integration)
  (enabled by default for bash, zsh, fish and PowerShell). Without it, commands
  are still sent — output capture is unavailable.
- The `sideshell-mcp` server (Python 3.11+): `uvx sideshell-mcp`.

## Links

- [sideshell on GitHub](https://github.com/menemy/sideshell)
- [Report an issue](https://github.com/menemy/sideshell/issues)
