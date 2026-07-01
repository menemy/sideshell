# Changelog

## 1.0.0

Initial marketplace release.

- Local bridge for the sideshell MCP server: Unix domain socket on
  macOS/Linux, named pipe (`\\.\pipe\sideshell-vscode`) on Windows. No TCP.
- Token-authenticated, newline-delimited JSON-RPC 2.0; explicit in-IDE
  approval required before any terminal access.
- Terminal control: create/split/focus/close tabs, send text and control
  characters, paste, clear.
- `execute` with `wait` + output capture and exit codes via VS Code shell
  integration; captured output is stripped of ANSI/OSC control sequences.
- Output buffering for `read` of user-typed commands (shell integration).
- Auto-start on IDE launch; `sideshell.start` / `sideshell.stop` /
  `sideshell.status` commands.
